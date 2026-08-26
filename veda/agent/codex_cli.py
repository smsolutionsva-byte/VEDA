"""CodexCLIProvider - OpenAI Codex CLI fallback in read-only headless mode."""
from __future__ import annotations

import asyncio
import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import uuid
from pathlib import Path
from typing import AsyncIterator

from .. import config
from .base import AgentEvent, AgentProvider, AgentSession


class CodexCLIProvider(AgentProvider):
    name = "codex"

    def __init__(self, cmd: str | None = None, model: str | None = None):
        self.cmd = cmd or config.CODEX_CMD
        self.model = model or config.CODEX_MODEL
        self._procs: dict[str, subprocess.Popen] = {}
        self._queues: dict[str, queue.Queue] = {}

    async def health(self) -> dict:
        exe = shutil.which(self.cmd) or (self.cmd if os.path.exists(self.cmd) else None)
        if not exe:
            return {"ok": False, "provider": self.name, "error": "codex CLI not found on PATH",
                    "hint": "Install @openai/codex and sign in once."}
        try:
            proc = await asyncio.create_subprocess_exec(exe, "--version",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            out, err = await asyncio.wait_for(proc.communicate(), timeout=15)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "provider": self.name, "error": str(exc)}
        if proc.returncode != 0:
            return {"ok": False, "provider": self.name,
                    "error": (err or b"").decode("utf-8", "replace")[:400]}
        return {"ok": True, "provider": self.name,
                "version": (out or b"").decode("utf-8", "replace").strip(),
                "model": self.model or "Codex default", "path": exe}

    async def start_session(self, *, project_id: str, job_id: str, prompt: str,
                            system: str = "", schema: dict | None = None,
                            mcp_config: dict | None = None, allowed_tools: list | None = None,
                            workspace: str | None = None) -> AgentSession:
        sid = str(uuid.uuid4())
        s = AgentSession(sid, None, self.name, self.model,
                         {"project_id": project_id, "job_id": job_id})
        self._spawn(s, prompt, system, schema, resume=False)
        return s

    async def resume_session(self, session: AgentSession, prompt: str, *, schema: dict | None = None) -> AgentSession:
        self._spawn(session, prompt, "", schema, resume=True)
        return session

    async def submit_event(self, session: AgentSession, event: dict) -> None:
        await self.resume_session(session, event.get("prompt") or json.dumps(event))

    async def cancel(self, session: AgentSession) -> None:
        p = self._procs.get(session.session_id)
        if p and p.poll() is None:
            p.kill()

    def _mcp_overrides(self, project_id: str, job_id: str) -> list[str]:
        root = str(Path(__file__).resolve().parent.parent.parent)
        env = {"VEDA_PROJECT_ID": project_id, "VEDA_JOB_ID": job_id,
               "VEDA_DATA_DIR": str(config.DATA_DIR), "PYTHONPATH": root,
               "PYTHONIOENCODING": "utf-8"}
        vals = {
            "mcp_servers.horizun.command": sys.executable,
            "mcp_servers.horizun.args": ["-m", "veda.mcpc.horizun_read_server"],
            "mcp_servers.horizun.env": env,
            "mcp_servers.veda.command": sys.executable,
            "mcp_servers.veda.args": ["-m", "veda.mcpc.veda_server"],
            "mcp_servers.veda.env": env,
        }
        out: list[str] = []
        for k, v in vals.items():
            out += ["-c", k + "=" + json.dumps(v, ensure_ascii=False)]
        return out

    def _spawn(self, session: AgentSession, prompt: str, system: str,
               schema: dict | None, resume: bool) -> None:
        exe = shutil.which(self.cmd) or self.cmd
        tmp = Path(tempfile.mkdtemp(prefix="veda_codex_"))
        schema_path = tmp / "schema.json"
        if schema:
            schema_path.write_text(json.dumps(schema), encoding="utf-8")
        argv = [exe, "exec", "--json", "--skip-git-repo-check", "--sandbox", "read-only", "-C", str(tmp)]
        if self.model:
            argv += ["--model", self.model]
        if schema:
            argv += ["--output-schema", str(schema_path)]
        argv += self._mcp_overrides(session.meta["project_id"], session.meta["job_id"])
        if resume and session.external_id:
            argv += ["resume", session.external_id, "-"]
        else:
            argv += ["-"]
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        creation = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        proc = subprocess.Popen(argv, cwd=str(tmp), env=env, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, encoding="utf-8", errors="replace", bufsize=1,
                                creationflags=creation)
        self._procs[session.session_id] = proc
        q: queue.Queue = queue.Queue()
        self._queues[session.session_id] = q
        combined = (("SYSTEM / VEDA SAFETY RULES:\n" + system + "\n\n") if system else "") + prompt
        try:
            proc.stdin.write(combined)  # type: ignore[union-attr]
            proc.stdin.close()  # type: ignore[union-attr]
        except Exception:
            pass

        def reader() -> None:
            stderr_buf: list[str] = []
            def read_err():
                try:
                    for line in proc.stderr:  # type: ignore[union-attr]
                        if line.strip(): stderr_buf.append(line.strip())
                except Exception: pass
            threading.Thread(target=read_err, daemon=True).start()
            last_text = ""
            usage = {}
            failed = None
            try:
                for raw in proc.stdout:  # type: ignore[union-attr]
                    raw = raw.strip()
                    if not raw: continue
                    try: ev = json.loads(raw)
                    except Exception: continue
                    typ = ev.get("type")
                    if typ == "thread.started":
                        session.external_id = ev.get("thread_id") or session.external_id
                        q.put(AgentEvent("status", "agent_started", "Codex analysis started",
                                         {"external_id": session.external_id}))
                    elif typ == "item.started":
                        item = ev.get("item") or {}
                        if item.get("type") == "mcp_tool_call":
                            q.put(AgentEvent("tool_call", "tool_call", str(item.get("name") or "Codex MCP tool")))
                    elif typ == "item.completed":
                        item = ev.get("item") or {}
                        if item.get("type") == "agent_message":
                            last_text = item.get("text") or last_text
                    elif typ == "turn.completed":
                        usage = ev.get("usage") or {}
                    elif typ == "turn.failed":
                        failed = str(ev.get("error") or "Codex turn failed")
                code = proc.wait()
                if failed or code != 0 or not last_text:
                    err = failed or "\n".join(stderr_buf[-8:]) or ("Codex exited with code " + str(code))
                    q.put(AgentEvent("error", label=err[:800]))
                else:
                    structured = None
                    if schema:
                        try: structured = json.loads(last_text)
                        except Exception: structured = None
                    q.put(AgentEvent("result", "agent_finished", "Codex finished",
                                     {"text": last_text, "structured": structured,
                                      "is_error": False, "turns": 1, "cost_usd": 0.0,
                                      "usage": usage, "external_id": session.external_id}))
            except Exception as exc:  # noqa: BLE001
                q.put(AgentEvent("error", label=type(exc).__name__ + ": " + str(exc)))
            finally:
                q.put(None)
        threading.Thread(target=reader, daemon=True).start()

    async def stream_events(self, session: AgentSession) -> AsyncIterator[AgentEvent]:
        q = self._queues.get(session.session_id)
        if q is None:
            yield AgentEvent("error", label="session was never started")
            return
        loop = asyncio.get_running_loop()
        while True:
            item = await loop.run_in_executor(None, q.get)
            if item is None: return
            yield item
