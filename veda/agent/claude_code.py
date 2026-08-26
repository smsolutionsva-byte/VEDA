"""ClaudeCodeProvider - drives the Claude Code CLI in headless mode.

The CLI already offers everything the bridge needs: --session-id and --resume
for durable sessions (spec 42), --mcp-config for Horizun plus VEDA's own tools
(spec 9), --json-schema for structured output (spec 43), and --allowedTools to
hold the agent inside a read-only tool scope (spec 45).

The user never opens Claude Code themselves (spec 7).
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

# Read-only scope. Horizun's write tools are deliberately absent: schedule
# changes travel through VEDA's proposal pipeline, never straight from the model.
HORIZUN_READ_TOOLS = [
    "project_health", "project_open", "project_info", "tasks_query",
    "links_query", "resources_query", "timephased_query", "schedule_analyze",
    "schedule_qa", "baseline_compare", "schedule_target", "schedule_recovery",
]
VEDA_TOOLS = [
    "veda_project_overview", "veda_activities", "veda_relationships",
    "veda_schedule_quality", "veda_files", "veda_read_file", "veda_evidence",
    "veda_human_answers",
]


def default_allowed_tools() -> list:
    return (["mcp__horizun__" + t for t in HORIZUN_READ_TOOLS] +
            ["mcp__veda__" + t for t in VEDA_TOOLS])


def build_mcp_config(project_id: str, job_id: str) -> dict:
    root = str(Path(__file__).resolve().parent.parent.parent)
    return {
        "mcpServers": {
            "horizun": {
                "type": "stdio",
                "command": config.HORIZUN_CMD,
                "args": [],
                "env": {},
            },
            "veda": {
                "type": "stdio",
                "command": sys.executable,
                "args": ["-m", "veda.mcpc.veda_server"],
                "env": {
                    "VEDA_PROJECT_ID": project_id,
                    "VEDA_JOB_ID": job_id,
                    "VEDA_DATA_DIR": str(config.DATA_DIR),
                    "PYTHONPATH": root,
                    "PYTHONIOENCODING": "utf-8",
                },
            },
        }
    }


class ClaudeCodeProvider(AgentProvider):
    name = "claude_code"

    def __init__(self, cmd: str | None = None, model: str | None = None):
        self.cmd = cmd or config.CLAUDE_CMD
        self.model = model or config.CLAUDE_MODEL
        self._procs: dict = {}
        self._queues: dict = {}
        self._tmpfiles: dict = {}

    # ----------------------------------------------------------------- health
    async def health(self) -> dict:
        exe = shutil.which(self.cmd) or (self.cmd if os.path.exists(self.cmd) else None)
        if not exe:
            return {"ok": False, "provider": self.name,
                    "error": "claude CLI not found on PATH",
                    "hint": "npm install -g @anthropic-ai/claude-code"}
        try:
            proc = await asyncio.create_subprocess_exec(
                exe, "--version",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            out, err = await asyncio.wait_for(proc.communicate(), timeout=30)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "provider": self.name, "error": str(exc)}
        version = (out or b"").decode("utf-8", "replace").strip()
        if proc.returncode != 0:
            return {"ok": False, "provider": self.name,
                    "error": (err or b"").decode("utf-8", "replace")[:400]}
        return {"ok": True, "provider": self.name, "version": version,
                "model": self.model, "path": exe}

    # --------------------------------------------------------------- sessions
    async def start_session(self, *, project_id: str, job_id: str, prompt: str,
                            system: str = "", schema: dict | None = None,
                            mcp_config: dict | None = None,
                            allowed_tools: list | None = None,
                            workspace: str | None = None) -> AgentSession:
        sid = str(uuid.uuid4())
        session = AgentSession(session_id=sid, external_id=sid, provider=self.name,
                               model=self.model,
                               meta={"project_id": project_id, "job_id": job_id,
                                     "workspace": workspace,
                                     "allowed_tools": allowed_tools,
                                     "mcp_config": mcp_config})
        await self._spawn(session, prompt, system=system, schema=schema,
                          mcp_config=mcp_config, allowed_tools=allowed_tools,
                          workspace=workspace, resume=False)
        return session

    async def resume_session(self, session: AgentSession, prompt: str, *,
                             schema: dict | None = None) -> AgentSession:
        meta = session.meta or {}
        await self._spawn(session, prompt, system="", schema=schema,
                          mcp_config=meta.get("mcp_config"),
                          allowed_tools=meta.get("allowed_tools"),
                          workspace=meta.get("workspace"), resume=True)
        return session

    async def submit_event(self, session: AgentSession, event: dict) -> None:
        """Claude Code turns are discrete; a backend event becomes a resume."""
        text = event.get("prompt") or json.dumps(event, default=str)
        await self.resume_session(session, text)

    async def cancel(self, session: AgentSession) -> None:
        proc = self._procs.pop(session.session_id, None)
        if proc is not None and proc.poll() is None:
            try:
                proc.kill()
            except Exception:
                pass
        self._cleanup_tmp(session.session_id)

    # ------------------------------------------------------------------ spawn
    async def _spawn(self, session: AgentSession, prompt: str, *, system: str,
                     schema: dict | None, mcp_config: dict | None,
                     allowed_tools: list | None, workspace: str | None,
                     resume: bool) -> None:
        meta = session.meta or {}
        mcp_config = mcp_config or build_mcp_config(meta.get("project_id", ""),
                                                    meta.get("job_id", ""))
        allowed_tools = allowed_tools or default_allowed_tools()

        tmpdir = Path(tempfile.mkdtemp(prefix="veda_agent_"))
        mcp_path = tmpdir / "mcp.json"
        mcp_path.write_text(json.dumps(mcp_config), encoding="utf-8")
        self._tmpfiles.setdefault(session.session_id, []).append(tmpdir)

        # The prompt goes over stdin, not argv: Windows caps a command line at
        # ~32k characters and an evidence-rich prompt can exceed that.
        argv = [
            self.cmd, "-p",
            "--output-format", "stream-json", "--verbose",
            "--mcp-config", str(mcp_path), "--strict-mcp-config",
            "--allowedTools", ",".join(allowed_tools),
            "--disallowedTools", "Bash,Edit,Write,NotebookEdit,WebFetch,WebSearch",
            "--permission-mode", "bypassPermissions",
            "--model", self.model,
            "--setting-sources", "",
        ]
        if resume:
            argv += ["--resume", session.external_id or session.session_id]
        else:
            argv += ["--session-id", session.session_id]
        if system:
            argv += ["--append-system-prompt", system]
        if schema:
            argv += ["--json-schema", json.dumps(schema)]

        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
        cwd = workspace or str(config.DATA_DIR)

        creation = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        proc = subprocess.Popen(
            argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            stdin=subprocess.PIPE, text=True, encoding="utf-8",
            errors="replace", bufsize=1, cwd=cwd, env=env,
            creationflags=creation)
        self._procs[session.session_id] = proc
        try:
            proc.stdin.write(prompt)  # type: ignore[union-attr]
            proc.stdin.close()        # type: ignore[union-attr]
        except Exception:
            pass

        q: queue.Queue = queue.Queue()
        self._queues[session.session_id] = q

        def reader():
            try:
                for line in proc.stdout:  # type: ignore[union-attr]
                    line = line.strip()
                    if line:
                        q.put(("line", line))
            except Exception as exc:  # noqa: BLE001
                q.put(("error", str(exc)))
            finally:
                err = ""
                try:
                    err = (proc.stderr.read() or "")[:4000]  # type: ignore
                except Exception:
                    pass
                proc.wait()
                q.put(("done", {"code": proc.returncode, "stderr": err}))

        threading.Thread(target=reader, daemon=True).start()

    def _cleanup_tmp(self, sid: str) -> None:
        for d in self._tmpfiles.pop(sid, []):
            try:
                shutil.rmtree(d, ignore_errors=True)
            except Exception:
                pass

    # ---------------------------------------------------------------- streaming
    async def stream_events(self, session: AgentSession) -> AsyncIterator[AgentEvent]:
        q = self._queues.get(session.session_id)
        if q is None:
            yield AgentEvent("error", label="session was never started")
            return

        text_parts: list = []
        finished = False
        timeout_at = asyncio.get_event_loop().time() + config.AGENT_TIMEOUT

        while not finished:
            if asyncio.get_event_loop().time() > timeout_at:
                await self.cancel(session)
                yield AgentEvent("error", label="agent timed out after " +
                                 str(config.AGENT_TIMEOUT) + "s")
                return
            try:
                kind, payload = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: q.get(timeout=1.0))
            except Exception:
                continue

            if kind == "error":
                yield AgentEvent("error", label=str(payload))
                continue

            if kind == "done":
                code = payload.get("code")
                if code not in (0, None):
                    stderr = (payload.get("stderr") or "").strip()
                    yield AgentEvent("error",
                                     label="claude exited with code " + str(code) +
                                     (": " + stderr[:600] if stderr else ""))
                finished = True
                self._cleanup_tmp(session.session_id)
                continue

            try:
                msg = json.loads(payload)
            except Exception:
                continue

            for ev in self._translate(msg, session, text_parts):
                yield ev

    def _translate(self, msg: dict, session: AgentSession, text_parts: list) -> list:
        """Map CLI stream-json to safe, high-level events (spec 50, 51).

        Assistant reasoning text is never surfaced; only tool activity, coarse
        status and the final result travel onward.
        """
        out: list = []
        mtype = msg.get("type")

        if mtype == "system" and msg.get("subtype") == "init":
            sid = msg.get("session_id")
            if sid:
                session.external_id = sid
            servers = msg.get("mcp_servers") or []
            names = ", ".join(
                str(s.get("name")) + "=" + str(s.get("status")) for s in servers)
            out.append(AgentEvent("status", step="agent_started",
                                  label="Agent session started",
                                  data={"session_id": sid, "mcp_servers": names,
                                        "model": msg.get("model")}))
            for s in servers:
                if str(s.get("status")).lower() not in ("connected", "ok"):
                    out.append(AgentEvent(
                        "error", step="mcp_connect",
                        label="MCP server " + str(s.get("name")) + " is " +
                              str(s.get("status"))))
            return out

        if mtype == "assistant":
            for block in (msg.get("message") or {}).get("content") or []:
                btype = block.get("type")
                if btype == "tool_use":
                    name = str(block.get("name", ""))
                    out.append(AgentEvent(
                        "tool_call", step="tool", label=_pretty_tool(name),
                        data={"tool": name,
                              "input_keys": sorted((block.get("input") or {}).keys())}))
                elif btype == "text":
                    txt = block.get("text") or ""
                    if txt.strip():
                        text_parts.append(txt)
            return out

        if mtype == "user":
            for block in (msg.get("message") or {}).get("content") or []:
                if block.get("type") == "tool_result":
                    is_err = bool(block.get("is_error"))
                    out.append(AgentEvent(
                        "tool_result", step="tool",
                        label="tool " + ("failed" if is_err else "returned"),
                        data={"is_error": is_err}))
            return out

        if mtype == "result":
            text = msg.get("result") or "".join(text_parts)
            structured = None
            for key in ("structured_result", "structured_output", "json"):
                if isinstance(msg.get(key), (dict, list)):
                    structured = msg[key]
                    break
            out.append(AgentEvent(
                "result", step="agent_finished", label="Agent finished",
                data={"text": text, "structured": structured,
                      "is_error": bool(msg.get("is_error")),
                      "turns": msg.get("num_turns", 0),
                      "cost_usd": msg.get("total_cost_usd", 0.0) or 0.0,
                      "external_id": msg.get("session_id"),
                      "subtype": msg.get("subtype")}))
            return out

        return out


def _pretty_tool(name: str) -> str:
    """'mcp__horizun__schedule_qa' -> 'Horizun/schedule_qa' (spec 51)."""
    if name.startswith("mcp__"):
        parts = name.split("__")
        if len(parts) >= 3:
            server = parts[1]
            tool = "__".join(parts[2:])
            label = {"horizun": "Horizun", "veda": "VEDA"}.get(server, server)
            return label + "/" + tool
    return name
