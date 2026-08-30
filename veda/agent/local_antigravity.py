"""LocalAntigravityProvider - bridge to the running Antigravity IDE agent.

Instead of calling any external API, this provider writes the job context to
an inbox table and waits for the Antigravity agent (already running in the IDE)
to pick it up, reason about it, and post the result back.

No API key needed. The agent is already authenticated and running.
"""
from __future__ import annotations

import asyncio
import json
import queue
import threading
import time
from typing import AsyncIterator

from .. import config, db
from .base import AgentEvent, AgentProvider, AgentSession

# How long to wait once the IDE agent has claimed a job (seconds).
INBOX_TIMEOUT = int(config.AGENT_TIMEOUT)
# How long an unclaimed inbox item may block the single VEDA worker.  The IDE
# bridge is useful only when something is actively polling /api/agent/inbox;
# without this guard one missing watcher stalls every project for 15 minutes.
CLAIM_TIMEOUT = max(1, min(INBOX_TIMEOUT, int(config.AGENT_CLAIM_TIMEOUT)))

# The bridge is now signal-driven: the HTTP handlers that claim a job and post a
# result wake this waiter directly, so a finished job is observed in roughly the
# time one SQLite read takes rather than up to a full poll interval.  Polling
# remains only as a safety net for a result written by another process, and it
# backs off from a fast first check to a quiet steady state.
POLL_MIN = 0.05
POLL_MAX = 1.0
POLL_GROWTH = 1.6

# inbox_id -> Event.  Set by notify() from the API layer.
_SIGNALS: dict = {}
_SIGNAL_LOCK = threading.Lock()


def _signal_for(inbox_id: str) -> threading.Event:
    with _SIGNAL_LOCK:
        ev = _SIGNALS.get(inbox_id)
        if ev is None:
            ev = _SIGNALS[inbox_id] = threading.Event()
        return ev


def _release_signal(inbox_id: str) -> None:
    with _SIGNAL_LOCK:
        _SIGNALS.pop(inbox_id, None)


def notify(inbox_id: str | None) -> None:
    """Wake the waiter for one inbox item.

    Called by the agent-bridge HTTP routes the moment an item is claimed or a
    result is posted.  Safe to call for an unknown id.
    """
    if not inbox_id:
        return
    with _SIGNAL_LOCK:
        ev = _SIGNALS.get(inbox_id)
    if ev is not None:
        ev.set()


class LocalAntigravityProvider(AgentProvider):
    """Bridges VEDA's job system to the running Antigravity IDE agent.

    The lifecycle is:
      1. start_session() writes the prompt + schema to agent_inbox
      2. stream_events() polls agent_outbox until a result appears
      3. The Antigravity agent (polling /api/agent/inbox) picks up
         the job, reasons, and POSTs to /api/agent/result
      4. stream_events() finds the result in the outbox and yields it
    """
    name = "local_antigravity"

    def __init__(self):
        self._sessions: dict = {}
        self._queues: dict = {}
        self._cancel: dict = {}

    async def health(self) -> dict:
        return {
            "ok": True,
            "provider": self.name,
            "model": "Antigravity IDE (local agent)",
            "note": "Local Antigravity inbox bridge is enabled. An IDE agent "
                    "must claim pending inbox work; otherwise VEDA falls back "
                    "without blocking the global queue.",
        }

    async def start_session(self, *, project_id: str, job_id: str, prompt: str,
                            system: str = "", schema: dict | None = None,
                            mcp_config: dict | None = None,
                            allowed_tools: list | None = None,
                            workspace: str | None = None) -> AgentSession:
        sid = db.new_id("la_")
        session = AgentSession(
            session_id=sid, external_id=sid, provider=self.name,
            model="local_antigravity",
            meta={"project_id": project_id, "job_id": job_id})

        # Write to inbox so the Antigravity agent can pick it up
        inbox_id = db.insert("agent_inbox", {
            "project_id": project_id,
            "job_id": job_id,
            "prompt": prompt,
            "system_prompt": system or "",
            "schema_json": db.jdumps(schema) if schema else None,
            "status": "pending",
        })
        session.meta["inbox_id"] = inbox_id
        self._sessions[sid] = session
        _signal_for(inbox_id)

        # Start a background thread that waits for the bridge to answer.
        q: queue.Queue = queue.Queue()
        self._queues[sid] = q
        self._cancel[sid] = False
        threading.Thread(target=self._wait_for_result,
                         args=(session, inbox_id, q), daemon=True).start()
        return session

    async def resume_session(self, session: AgentSession, prompt: str, *,
                             schema: dict | None = None) -> AgentSession:
        self._sessions.setdefault(session.session_id, session)
        meta = session.meta
        inbox_id = db.insert("agent_inbox", {
            "project_id": meta.get("project_id", ""),
            "job_id": meta.get("job_id", ""),
            "prompt": prompt,
            "system_prompt": "",
            "schema_json": db.jdumps(schema) if schema else None,
            "status": "pending",
        })
        meta["inbox_id"] = inbox_id
        _signal_for(inbox_id)
        q: queue.Queue = queue.Queue()
        self._queues[session.session_id] = q
        self._cancel[session.session_id] = False
        threading.Thread(target=self._wait_for_result,
                         args=(session, inbox_id, q), daemon=True).start()
        return session

    async def submit_event(self, session: AgentSession, event: dict) -> None:
        await self.resume_session(
            session, event.get("prompt") or json.dumps(event, default=str))

    async def cancel(self, session: AgentSession) -> None:
        self._cancel[session.session_id] = True
        inbox_id = session.meta.get("inbox_id")
        if inbox_id:
            db.update("agent_inbox", inbox_id, {
                "status": "cancelled", "finished_at": db.now()})
            notify(inbox_id)

    def _wait_for_result(self, session: AgentSession, inbox_id: str,
                         q: queue.Queue) -> None:
        """Poll the outbox until the Antigravity agent posts a result."""
        q.put(AgentEvent("status", step="agent_started",
                         label="Job queued for Antigravity IDE agent",
                         data={"session_id": session.session_id,
                               "inbox_id": inbox_id,
                               "model": "local_antigravity"}))
        started = time.time()
        claim_deadline = started + CLAIM_TIMEOUT
        result_deadline = started + INBOX_TIMEOUT
        claimed = False
        processing_announced = False
        wake = _signal_for(inbox_id)
        backoff = POLL_MIN
        try:
            while time.time() < result_deadline:
                if self._cancel.get(session.session_id):
                    q.put(AgentEvent("error", label="cancelled"))
                    break

                # Check first: a very fast agent can claim and post between polls.
                outbox = db.q1(
                    "SELECT * FROM agent_outbox WHERE inbox_id=? "
                    "ORDER BY created_at DESC LIMIT 1", [inbox_id])
                if outbox:
                    error = outbox.get("error")
                    if error:
                        q.put(AgentEvent("error", label=error[:400]))
                    else:
                        result_text = outbox.get("result_json") or ""
                        # Replay any events the agent recorded
                        events_raw = db.jloads(outbox.get("events_json"), [])
                        for ev_dict in (events_raw or []):
                            q.put(AgentEvent(
                                kind=ev_dict.get("kind", "status"),
                                step=ev_dict.get("step", ""),
                                label=ev_dict.get("label", ""),
                                data=ev_dict.get("data", {})))
                        q.put(AgentEvent(
                            "result", step="agent_finished",
                            label="Agent finished",
                            data={"text": result_text,
                                  "structured": None,
                                  "is_error": False, "turns": 1,
                                  "cost_usd": 0.0,
                                  "external_id": session.session_id}))
                    db.update("agent_inbox", inbox_id, {
                        "status": "done", "finished_at": db.now()})
                    break

                inbox = db.q1("SELECT status FROM agent_inbox WHERE id=?",
                              [inbox_id])
                state = (inbox or {}).get("status")
                if state == "claimed":
                    claimed = True
                    if not processing_announced:
                        q.put(AgentEvent("status", step="agent_processing",
                                         label="Agent is processing..."))
                        processing_announced = True
                elif state in ("cancelled", "timeout"):
                    q.put(AgentEvent("error",
                                     label="Antigravity inbox was " + str(state)))
                    break

                # The important guard: an IDE being open is not proof that an
                # agent is actually consuming VEDA's inbox. Fail fast so the
                # deterministic fallback can finish this job and release the
                # next queued project.
                if not claimed and time.time() >= claim_deadline:
                    q.put(AgentEvent(
                        "error",
                        label=("Antigravity IDE agent did not claim this job within "
                               + str(CLAIM_TIMEOUT) +
                               "s; releasing the VEDA worker.")))
                    db.update("agent_inbox", inbox_id, {
                        "status": "timeout", "finished_at": db.now()})
                    break

                # Sleep until the bridge signals, the backoff elapses, or the
                # relevant deadline arrives -- whichever comes first.
                deadline = claim_deadline if not claimed else result_deadline
                budget = max(0.0, min(deadline, result_deadline) - time.time())
                if wake.wait(timeout=min(backoff, budget) if budget else 0.0):
                    wake.clear()
                    backoff = POLL_MIN
                else:
                    backoff = min(POLL_MAX, backoff * POLL_GROWTH)
            else:
                q.put(AgentEvent(
                    "error",
                    label=("Timeout: Antigravity agent did not respond within " +
                           str(INBOX_TIMEOUT) + "s after the job was queued.")))
                db.update("agent_inbox", inbox_id, {
                    "status": "timeout", "finished_at": db.now()})
        except Exception as exc:  # noqa: BLE001
            q.put(AgentEvent("error",
                             label=type(exc).__name__ + ": " + str(exc)))
        finally:
            _release_signal(inbox_id)
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
