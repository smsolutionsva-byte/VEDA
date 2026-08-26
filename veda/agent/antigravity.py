"""AntigravityProvider - Google Antigravity / Gemini as the reasoning provider.

Same contract as ClaudeCodeProvider (spec 3). VEDA drives a function-calling
loop and executes the tool calls itself, dispatching to the Horizun MCP client
and to VEDA's own tool handlers in-process. The model therefore sees exactly
the tool surface Claude Code sees, and the workflow above the bridge is
unchanged - which is what provider neutrality means here.

Needs GEMINI_API_KEY (or GOOGLE_API_KEY). Without one, health() reports the
provider unavailable and VEDA falls back rather than pretending.
"""
from __future__ import annotations

import asyncio
import json
import queue
import threading
from typing import Any, AsyncIterator

import httpx

from .. import config, db
from ..mcpc import horizun
from ..mcpc import veda_server as vtools
from .base import AgentEvent, AgentProvider, AgentSession
from .claude_code import HORIZUN_READ_TOOLS, VEDA_TOOLS

MAX_STEPS = 24


def _clean_schema(schema: dict) -> dict:
    """Gemini rejects several JSON Schema keywords; keep only what it accepts."""
    allowed = {"type", "description", "properties", "required", "items", "enum",
               "nullable", "format"}
    if not isinstance(schema, dict):
        return {"type": "string"}
    out = {}
    for k, v in schema.items():
        if k not in allowed:
            continue
        if k == "properties" and isinstance(v, dict):
            out[k] = {pk: _clean_schema(pv) for pk, pv in v.items()}
        elif k == "items" and isinstance(v, dict):
            out[k] = _clean_schema(v)
        elif k == "type" and isinstance(v, list):
            real = [t for t in v if t != "null"]
            out[k] = real[0] if real else "string"
            out["nullable"] = True
        else:
            out[k] = v
    out.setdefault("type", "object" if "properties" in out else "string")
    return out


def _tool_declarations() -> list:
    """Horizun read tools + VEDA tools, as Gemini function declarations."""
    decls = []
    try:
        for t in horizun.list_tools():
            if t.get("name") not in HORIZUN_READ_TOOLS:
                continue
            decls.append({
                "name": "horizun__" + t["name"],
                "description": (t.get("description") or "")[:1000],
                "parameters": _clean_schema(t.get("inputSchema") or
                                            {"type": "object", "properties": {}}),
            })
    except Exception:
        pass
    for t in vtools.TOOLS:
        if t["name"] not in VEDA_TOOLS:
            continue
        decls.append({
            "name": t["name"],
            "description": (t.get("description") or "")[:1000],
            "parameters": _clean_schema(t.get("inputSchema") or
                                        {"type": "object", "properties": {}}),
        })
    return decls


def _dispatch(name: str, args: dict, project_id: str, job_id: str) -> Any:
    """Execute one tool call locally - the same tools the MCP path exposes."""
    if name.startswith("horizun__"):
        tool = name[len("horizun__"):]
        if tool not in HORIZUN_READ_TOOLS:
            return {"error": "tool " + tool + " is outside the permitted read scope"}
        try:
            return horizun.call(tool, args, project_id=project_id, job_id=job_id)
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)}
    fn = vtools.HANDLERS.get(name)
    if fn is None:
        return {"error": "unknown tool " + name}
    try:
        res = fn(args, project_id)
    except Exception as exc:  # noqa: BLE001
        return {"error": type(exc).__name__ + ": " + str(exc)}
    text = "".join(c.get("text", "") for c in res.get("content", []))
    if res.get("isError"):
        return {"error": text}
    try:
        return json.loads(text)
    except Exception:
        return {"text": text}


class AntigravityProvider(AgentProvider):
    name = "antigravity"

    def __init__(self, api_key: str | None = None, model: str | None = None):
        self.api_key = api_key if api_key is not None else config.GEMINI_API_KEY
        self.model = model or config.GEMINI_MODEL
        self.base = config.GEMINI_BASE
        self._sessions: dict = {}
        self._queues: dict = {}
        self._cancel: dict = {}

    async def health(self) -> dict:
        if not self.api_key:
            return {"ok": False, "provider": self.name,
                    "error": "no GEMINI_API_KEY / GOOGLE_API_KEY in the environment",
                    "hint": "set GEMINI_API_KEY to use Antigravity/Gemini"}
        try:
            async with httpx.AsyncClient(timeout=20) as cl:
                r = await cl.get(self.base + "/models",
                                 params={"key": self.api_key})
            if r.status_code != 200:
                return {"ok": False, "provider": self.name,
                        "error": "models endpoint returned " + str(r.status_code),
                        "detail": r.text[:300]}
            names = [m.get("name", "") for m in r.json().get("models", [])]
            return {"ok": True, "provider": self.name, "model": self.model,
                    "models_available": len(names)}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "provider": self.name, "error": str(exc)}

    # ---------------------------------------------------------------- session
    async def start_session(self, *, project_id: str, job_id: str, prompt: str,
                            system: str = "", schema: dict | None = None,
                            mcp_config: dict | None = None,
                            allowed_tools: list | None = None,
                            workspace: str | None = None) -> AgentSession:
        sid = db.new_id("ag_")
        session = AgentSession(session_id=sid, external_id=sid, provider=self.name,
                               model=self.model,
                               meta={"project_id": project_id, "job_id": job_id,
                                     "system": system, "history": []})
        self._sessions[sid] = session
        self._start_turn(session, prompt, schema)
        return session

    async def resume_session(self, session: AgentSession, prompt: str, *,
                             schema: dict | None = None) -> AgentSession:
        self._sessions.setdefault(session.session_id, session)
        self._start_turn(session, prompt, schema)
        return session

    async def submit_event(self, session: AgentSession, event: dict) -> None:
        await self.resume_session(session,
                                  event.get("prompt") or json.dumps(event, default=str))

    async def cancel(self, session: AgentSession) -> None:
        self._cancel[session.session_id] = True

    def _start_turn(self, session: AgentSession, prompt: str,
                    schema: dict | None) -> None:
        q: queue.Queue = queue.Queue()
        self._queues[session.session_id] = q
        self._cancel[session.session_id] = False
        threading.Thread(target=self._run_turn, args=(session, prompt, schema, q),
                         daemon=True).start()

    # ------------------------------------------------------------------- loop
    def _run_turn(self, session: AgentSession, prompt: str, schema: dict | None,
                  q: queue.Queue) -> None:
        meta = session.meta
        project_id = meta.get("project_id", "")
        job_id = meta.get("job_id", "")
        history: list = meta.setdefault("history", [])
        history.append({"role": "user", "parts": [{"text": prompt}]})

        tools = [{"functionDeclarations": _tool_declarations()}]
        sys_instr = meta.get("system") or ""
        if schema:
            sys_instr += ("\n\nReturn a single JSON object matching this schema:\n" +
                          json.dumps(schema))

        url = (self.base + "/models/" + self.model + ":generateContent")
        turns = 0
        final_text = ""
        q.put(AgentEvent("status", step="agent_started",
                         label="Agent session started",
                         data={"session_id": session.session_id,
                               "model": self.model}))
        try:
            with httpx.Client(timeout=config.AGENT_TIMEOUT) as cl:
                for _ in range(MAX_STEPS):
                    if self._cancel.get(session.session_id):
                        q.put(AgentEvent("error", label="cancelled"))
                        break
                    body: dict = {
                        "contents": history,
                        "tools": tools,
                        "generationConfig": {"temperature": 0.2,
                                             "maxOutputTokens": 8192},
                    }
                    if sys_instr:
                        body["systemInstruction"] = {"parts": [{"text": sys_instr}]}
                    r = cl.post(url, params={"key": self.api_key}, json=body)
                    if r.status_code != 200:
                        q.put(AgentEvent("error",
                                         label="Gemini returned " +
                                               str(r.status_code) + ": " +
                                               r.text[:400]))
                        break
                    data = r.json()
                    cands = data.get("candidates") or []
                    if not cands:
                        q.put(AgentEvent("error", label="Gemini returned no candidate"))
                        break
                    parts = (cands[0].get("content") or {}).get("parts") or []
                    history.append({"role": "model", "parts": parts})
                    turns += 1

                    calls = [p["functionCall"] for p in parts if "functionCall" in p]
                    texts = [p["text"] for p in parts if "text" in p]
                    if texts:
                        final_text = "\n".join(texts)

                    if not calls:
                        break

                    responses = []
                    for c in calls:
                        name = c.get("name", "")
                        args = c.get("args") or {}
                        q.put(AgentEvent("tool_call", step="tool",
                                         label=_pretty(name),
                                         data={"tool": name,
                                               "input_keys": sorted(args.keys())}))
                        result = _dispatch(name, args, project_id, job_id)
                        is_err = isinstance(result, dict) and "error" in result
                        q.put(AgentEvent("tool_result", step="tool",
                                         label="tool " + ("failed" if is_err
                                                          else "returned"),
                                         data={"is_error": is_err}))
                        responses.append({"functionResponse": {
                            "name": name,
                            "response": {"result": _truncate(result)}}})
                    history.append({"role": "user", "parts": responses})

            q.put(AgentEvent("result", step="agent_finished", label="Agent finished",
                             data={"text": final_text, "structured": None,
                                   "is_error": not bool(final_text),
                                   "turns": turns, "cost_usd": 0.0,
                                   "external_id": session.session_id}))
        except Exception as exc:  # noqa: BLE001
            q.put(AgentEvent("error", label=type(exc).__name__ + ": " + str(exc)))
        finally:
            q.put(None)

    async def stream_events(self, session: AgentSession) -> AsyncIterator[AgentEvent]:
        q = self._queues.get(session.session_id)
        if q is None:
            yield AgentEvent("error", label="session was never started")
            return
        loop = asyncio.get_event_loop()
        while True:
            item = await loop.run_in_executor(None, lambda: _get(q))
            if item is None:
                return
            if item is _EMPTY:
                continue
            yield item


_EMPTY = object()


def _get(q: queue.Queue):
    try:
        return q.get(timeout=1.0)
    except queue.Empty:
        return _EMPTY


def _truncate(result: Any, limit: int = 60000) -> Any:
    blob = json.dumps(result, default=str)
    if len(blob) <= limit:
        return result
    return {"truncated": True,
            "note": "result was " + str(len(blob)) + " characters; narrow the query",
            "head": blob[:limit]}


def _pretty(name: str) -> str:
    if name.startswith("horizun__"):
        return "Horizun/" + name[len("horizun__"):]
    if name.startswith("veda_"):
        return "VEDA/" + name
    return name
