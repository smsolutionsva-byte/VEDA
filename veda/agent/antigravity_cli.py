"""AntigravityCLIProvider - official Google Antigravity CLI in headless mode.

Uses the operator's existing Antigravity authentication.  No Gemini API key is
required.  VEDA gives the agent a temporary workspace containing only read-only
MCP definitions, so the reasoning provider cannot mutate the project schedule.
"""
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


class AntigravityCLIProvider(AgentProvider):
    name = "antigravity_cli"

    def __init__(self, cmd: str | None = None, model: str | None = None):
        self.cmd = cmd or config.ANTIGRAVITY_CMD
        self.model = model or config.ANTIGRAVITY_MODEL
        self._procs: dict[str, subprocess.Popen] = {}
        self._queues: dict[str, queue.Queue] = {}
        self._tmpdirs: dict[str, Path] = {}

    async def health(self) -> dict:
        exe = shutil.which(self.cmd) or (self.cmd if os.path.exists(self.cmd) else None)
        if not exe:
            return {"ok": False, "provider": self.name,
                    "error": "Antigravity CLI (agy) not found on PATH",
                    "hint": "Install Antigravity CLI once; it reuses your Antigravity sign-in."}
        try:
            proc = await asyncio.create_subprocess_exec(
                exe, "--version", stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE)
            out, err = await asyncio.wait_for(proc.communicate(), timeout=15)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "provider": self.name, "error": str(exc)}
        if proc.returncode != 0:
            return {"ok": False, "provider": self.name,
                    "error": (err or b"").decode("utf-8", "replace")[:400]}
        return {"ok": True, "provider": self.name,
                "version": (out or b"").decode("utf-8", "replace").strip(),
                "model": self.model or "Antigravity default", "path": exe}

    async def start_session(self, *, project_id: str, job_id: str, prompt: str,
                            system: str = "", schema: dict | None = None,
                            mcp_config: dict | None = None,
                            allowed_tools: list | None = None,
                            workspace: str | None = None) -> AgentSession:
        sid = str(uuid.uuid4())
        session = AgentSession(sid, None, self.name, self.model,
                               {"project_id": project_id, "job_id": job_id})
        self._spawn(session, prompt, system, schema, mcp_config, resume=False)
        return session

    async def resume_session(self, session: AgentSession, prompt: str, *,
                             schema: dict | None = None) -> AgentSession:
        self._spawn(session, prompt, "", schema, None, resume=True)
        return session

    async def submit_event(self, session: AgentSession, event: dict) -> None:
        await self.resume_session(session, event.get("prompt") or json.dumps(event))

    async def cancel(self, session: AgentSession) -> None:
        proc = self._procs.get(session.session_id)
        if proc and proc.poll() is None:
            proc.kill()

    def _safe_mcp(self, project_id: str, job_id: str) -> dict:
        root = str(Path(__file__).resolve().parent.parent.parent)
        return {"mcpServers": {
            "horizun": {
                "command": sys.executable,
                "args": ["-m", "veda.mcpc.horizun_read_server"],
                "env": {"VEDA_PROJECT_ID": project_id, "VEDA_JOB_ID": job_id,
                        "VEDA_DATA_DIR": str(config.DATA_DIR), "PYTHONPATH": root,
                        "PYTHONIOENCODING": "utf-8"},
            },
            "veda": {
                "command": sys.executable,
                "args": ["-m", "veda.mcpc.veda_server"],
                "env": {"VEDA_PROJECT_ID": project_id, "VEDA_JOB_ID": job_id,
                        "VEDA_DATA_DIR": str(config.DATA_DIR), "PYTHONPATH": root,
                        "PYTHONIOENCODING": "utf-8"},
            },
        }}

    def _spawn(self, session: AgentSession, prompt: str, system: str,
               schema: dict | None, mcp_config: dict | None, resume: bool) -> None:
        exe = shutil.which(self.cmd) or self.cmd
        tmp = Path(tempfile.mkdtemp(prefix="veda_agy_"))
        (tmp / ".agents").mkdir(parents=True, exist_ok=True)
        (tmp / ".agents" / "mcp_config.json").write_text(
            json.dumps(self._safe_mcp(session.meta["project_id"], session.meta["job_id"])),
            encoding="utf-8")
        schema_path = tmp / "schema.json"
        if schema:
            schema_path.write_text(json.dumps(schema), encoding="utf-8")
        self._tmpdirs[session.session_id] = tmp

        argv = [exe, "--input-format", "stream-json", "--output-format", "stream-json",
                "--print-timeout", str(max(1, config.AGENT_TIMEOUT)) + "s"]
        if schema:
            argv += ["--json-schema", str(schema_path)]
        if self.model:
            argv += ["--model", self.model]
        if resume and session.external_id:
            argv += ["--conversation", session.external_id]

        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        creation = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        proc = subprocess.Popen(argv, cwd=str(tmp), env=env,
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, encoding="utf-8",
                                errors="replace", bufsize=1, creationflags=creation)
        self._procs[session.session_id] = proc
        q: queue.Queue = queue.Queue()
        self._queues[session.session_id] = q

        combined = (("SYSTEM / VEDA SAFETY RULES:\n" + system + "\n\n") if system else "") + prompt
        try:
            proc.stdin.write(json.dumps({"event": "user", "message": {"content": combined}}) + "\n")  # type: ignore[union-attr]
            proc.stdin.close()  # type: ignore[union-attr]
        except Exception:
            pass

        def reader() -> None:
            stderr_buf: list[str] = []
            def read_err():
                try:
                    for line in proc.stderr:  # type: ignore[union-attr]
                        if line.strip():
                            stderr_buf.append(line.strip())
                except Exception:
                    pass
            threading.Thread(target=read_err, daemon=True).start()
            final_seen = False
            try:
                for raw in proc.stdout:  # type: ignore[union-attr]
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        ev = json.loads(raw)
                    except Exception:
                        continue
                    kind = ev.get("event")
                    if kind == "init":
                        cid = ev.get("conversation_id") or (ev.get("init") or {}).get("conversation_id")
                        if cid:
                            session.external_id = cid
                        q.put(AgentEvent("status", "agent_started", "Antigravity analysis started",
                                         {"external_id": cid}))
                    elif kind == "step_update":
                        s = ev.get("step_update") or {}
                        if s.get("step_type") == "tool" and s.get("state") == "ACTIVE":
                            q.put(AgentEvent("tool_call", "tool_call",
                                             str(s.get("tool_name") or "Antigravity tool")))
                    elif kind == "result":
                        r = ev.get("result") or {}
                        cid = r.get("conversation_id") or session.external_id
                        if cid:
                            session.external_id = cid
                        status = str(r.get("status") or "").upper()
                        ok = status == "SUCCESS"
                        q.put(AgentEvent("result", "agent_finished",
                                         "Antigravity finished" if ok else "Antigravity failed",
                                         {"text": r.get("response") or "",
                                          "structured": r.get("structured_output"),
                                          "is_error": not ok,
                                          "turns": int(r.get("num_turns") or 1),
                                          "cost_usd": 0.0,
                                          "external_id": cid}))
                        if not ok:
                            q.put(AgentEvent("error", label=str(r.get("error") or status or "Antigravity failed")[:500]))
                        final_seen = True
                code = proc.wait()
                if not final_seen:
                    err = "\n".join(stderr_buf[-8:])[:800]
                    q.put(AgentEvent("error", label=err or ("Antigravity exited with code " + str(code))))
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
            if item is None:
                return
            yield item
