"""Horizun MCP stdio client.

VEDA does not reimplement schedule machinery (spec 10). Every schedule fact
comes from this client and is stamped MCP_FACT. The client is synchronous and
serialised behind a lock; the job runner calls it from a worker thread.
"""
from __future__ import annotations

import json
import subprocess
import threading
import time
from typing import Any, Callable

from .. import config, db


class McpError(RuntimeError):
    def __init__(self, message: str, tool: str = "", data: Any = None):
        super().__init__(message)
        self.tool = tool
        self.data = data


# Tools that mutate. VEDA gates these behind validation + dry-run + approval.
WRITE_TOOLS = {
    "tasks_write", "links_write", "resources_write", "calendars_write",
    "schedule_update", "project_save", "project_import", "schedule_sequence",
}
# Tools that write files to disk but never touch the open document.
EXPORT_TOOLS = {"project_export", "bim_sync", "schedule_learn", "schedule_generate"}


class HorizunClient:
    """One long-lived MCP server process, shared by all projects.

    The server supports multiple concurrently open documents, each addressed by
    its own handle, so a single process is enough.
    """

    def __init__(self, cmd: str | None = None):
        self.cmd = cmd or config.HORIZUN_CMD
        self._proc: subprocess.Popen | None = None
        self._lock = threading.RLock()
        self._id = 0
        self._pending: dict = {}
        self._reader: threading.Thread | None = None
        self._tools: list | None = None
        self._capabilities: dict | None = None
        self._server_info: dict = {}
        self._last_error: str | None = None
        self._alive = False

    # ------------------------------------------------------------ lifecycle
    def _spawn(self) -> None:
        creation = 0
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            creation = subprocess.CREATE_NO_WINDOW
        self._proc = subprocess.Popen(
            [self.cmd],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=creation,
        )
        self._pending = {}
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

        init = self._rpc(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "veda", "version": "1.0.0"},
            },
            timeout=60,
        )
        self._server_info = init.get("serverInfo", {})
        self._notify("notifications/initialized", {})
        self._alive = True

    def _read_loop(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except Exception:
                continue
            mid = msg.get("id")
            if mid is not None:
                self._pending[mid] = msg
        self._alive = False

    def ensure(self) -> None:
        with self._lock:
            if self._proc is None or self._proc.poll() is not None:
                self._spawn()

    def restart(self) -> None:
        with self._lock:
            self.close()
            self._spawn()

    def close(self) -> None:
        if self._proc is not None:
            try:
                self._proc.kill()
            except Exception:
                pass
        self._proc = None
        self._alive = False
        self._tools = None

    # --------------------------------------------------------------- jsonrpc
    def _notify(self, method: str, params: dict) -> None:
        assert self._proc and self._proc.stdin
        self._proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method,
                                           "params": params}) + "\n")
        self._proc.stdin.flush()

    def _rpc(self, method: str, params: dict, timeout: int | None = None) -> dict:
        timeout = timeout or config.HORIZUN_TIMEOUT
        assert self._proc and self._proc.stdin
        self._id += 1
        rid = self._id
        payload = {"jsonrpc": "2.0", "id": rid, "method": method, "params": params}
        try:
            self._proc.stdin.write(json.dumps(payload) + "\n")
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise McpError("Horizun MCP pipe closed: " + str(exc))

        deadline = time.time() + timeout
        while time.time() < deadline:
            if rid in self._pending:
                msg = self._pending.pop(rid)
                if "error" in msg:
                    err = msg["error"]
                    raise McpError(str(err.get("message", err)), data=err)
                return msg.get("result", {})
            if self._proc.poll() is not None:
                raise McpError("Horizun MCP process exited unexpectedly")
            time.sleep(0.03)
        raise McpError("Horizun MCP timed out after " + str(timeout) + "s: " + method)

    # ----------------------------------------------------------------- tools
    def list_tools(self, refresh: bool = False) -> list:
        with self._lock:
            self.ensure()
            if self._tools is None or refresh:
                res = self._rpc("tools/list", {})
                self._tools = res.get("tools", [])
        return self._tools or []

    def tool_names(self) -> set:
        return {t.get("name") for t in self.list_tools()}

    def has_tool(self, name: str) -> bool:
        return name in self.tool_names()

    def call(
        self,
        name: str,
        args: dict,
        *,
        project_id: str | None = None,
        job_id: str | None = None,
        timeout: int | None = None,
        log: bool = True,
    ) -> Any:
        """Call a Horizun tool. Records an mcp_calls row (spec 51)."""
        started = time.time()
        rec_id = db.new_id("mcp_")
        state, err, summary = "success", None, None
        result: Any = None
        try:
            with self._lock:
                self.ensure()
                if not self.has_tool(name):
                    raise McpError("Horizun does not expose tool " + name, tool=name)
                res = self._rpc("tools/call", {"name": name, "arguments": args},
                                timeout=timeout)
            result = _unwrap(res)
            if isinstance(res, dict) and res.get("isError"):
                state = "failed"
                err = _text_of(result)[:2000]
                raise McpError(err or "tool reported an error", tool=name, data=result)
            summary = _summarise(name, result)
        except McpError as exc:
            state, err = "failed", str(exc)[:2000]
            self._last_error = err
            raise
        except Exception as exc:  # noqa: BLE001
            state, err = "failed", (type(exc).__name__ + ": " + str(exc))[:2000]
            self._last_error = err
            raise McpError(err, tool=name) from exc
        finally:
            if log:
                try:
                    db.insert("mcp_calls", {
                        "id": rec_id, "project_id": project_id, "job_id": job_id,
                        "server": "Horizun", "tool": name,
                        "args_json": db.jdumps(_redact(args)),
                        "state": state, "error": err,
                        "duration_ms": round((time.time() - started) * 1000, 1),
                        "summary": summary,
                    })
                except Exception:
                    pass
        return result

    def try_call(self, name: str, args: dict, **kw) -> tuple:
        """Call and never raise. Returns (ok, result_or_error)."""
        try:
            return True, self.call(name, args, **kw)
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)

    # ------------------------------------------------------------ capability
    def health(self, deep: bool = False, project_id: str | None = None,
               job_id: str | None = None) -> dict:
        """spec 8: call project_health at initialisation, honour the matrix."""
        res = self.call("project_health", {"deep": deep},
                        project_id=project_id, job_id=job_id, timeout=120)
        if isinstance(res, dict):
            self._capabilities = res.get("capabilities", {}) or {}
        return res if isinstance(res, dict) else {"raw": res}

    def capabilities(self) -> dict:
        if self._capabilities is None:
            try:
                self.health()
            except Exception:
                return {}
        return self._capabilities or {}

    def supports(self, capability: str) -> bool:
        return bool(self.capabilities().get(capability))

    def status(self) -> dict:
        running = self._proc is not None and self._proc.poll() is None
        return {
            "command": self.cmd,
            "running": running,
            "server": self._server_info,
            "tool_count": len(self._tools or []),
            "tools": sorted(self.tool_names()) if self._tools else [],
            "capabilities": self._capabilities or {},
            "last_error": self._last_error,
        }


def _unwrap(res: Any) -> Any:
    """MCP content blocks -> python. Prefers structured JSON when present."""
    if not isinstance(res, dict):
        return res
    if "structuredContent" in res and res["structuredContent"] is not None:
        sc = res["structuredContent"]
        if isinstance(sc, dict) and set(sc.keys()) == {"result"}:
            return sc["result"]
        return sc
    content = res.get("content")
    if isinstance(content, list):
        texts = [c.get("text", "") for c in content
                 if isinstance(c, dict) and c.get("type") == "text"]
        blob = "".join(texts).strip()
        if not blob:
            return res
        try:
            return json.loads(blob)
        except Exception:
            return blob
    return res


def _text_of(v: Any) -> str:
    if isinstance(v, str):
        return v
    return db.jdumps(v)


def _redact(args: dict) -> dict:
    out = {}
    for k, v in (args or {}).items():
        if isinstance(v, list) and len(v) > 40:
            out[k] = "[" + str(len(v)) + " items]"
        elif isinstance(v, str) and len(v) > 400:
            out[k] = v[:400] + "..."
        else:
            out[k] = v
    return out


def _summarise(name: str, result: Any) -> str:
    """Short, safe, human-readable line for the MCP activity feed (spec 51)."""
    if not isinstance(result, dict):
        return name + " ok"
    try:
        if name == "project_open":
            return "opened " + str(result.get("name") or result.get("handle", ""))
        if name == "project_info":
            return str(result.get("taskCount", result.get("tasks", "?"))) + " tasks"
        if name in ("tasks_query", "links_query", "resources_query"):
            noun = {"tasks_query": "tasks", "links_query": "links",
                    "resources_query": "resources"}[name]
            rows = (result.get("items") or result.get(noun) or
                    result.get("rows") or [])
            total = result.get("total")
            got = str(len(rows)) + " " + noun
            return got + (" of " + str(total) if total is not None else "") + \
                " returned"
        if name == "schedule_qa":
            checks = result.get("checks") or result.get("results") or []
            failed = sum(1 for c in checks
                         if isinstance(c, dict)
                         and str(c.get("status", "")).lower() in ("fail", "failed"))
            return str(len(checks)) + " checks, " + str(failed) + " failed"
        if name == "schedule_analyze":
            return ", ".join(k for k in result if not k.startswith("_"))[:160]
        if name == "project_health":
            caps = result.get("capabilities", {})
            on = sum(1 for v in caps.values() if v)
            return "backend " + str(result.get("backend", "?")) + \
                   ", " + str(on) + "/" + str(len(caps)) + " capabilities"
    except Exception:
        pass
    keys = [k for k in result if not k.startswith("_")][:6]
    return ", ".join(keys)[:160] or (name + " ok")


horizun = HorizunClient()
