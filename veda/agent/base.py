"""Provider-neutral agent bridge (spec 3).

VEDA owns the workflow; a provider only supplies reasoning. Every provider
implements the same surface, so swapping Claude Code for Antigravity/Gemini
changes nothing above this line.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any, AsyncIterator


@dataclass
class AgentEvent:
    """A safe, high-level progress record (spec 50).

    Chain-of-thought never travels in here. `kind` is one of:
      status | tool_call | tool_result | output | result | error
    """
    kind: str
    step: str = ""
    label: str = ""
    data: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"kind": self.kind, "step": self.step, "label": self.label,
                "data": self.data}


@dataclass
class AgentSession:
    session_id: str            # VEDA's id
    external_id: str | None    # the provider's own conversation id
    provider: str
    model: str | None = None
    meta: dict = field(default_factory=dict)


@dataclass
class AgentRunResult:
    ok: bool
    text: str = ""
    structured: Any = None
    external_id: str | None = None
    error: str | None = None
    turns: int = 0
    cost_usd: float = 0.0
    events: list = field(default_factory=list)


class AgentProvider(abc.ABC):
    """The interface every reasoning provider must satisfy."""

    name: str = "base"

    @abc.abstractmethod
    async def health(self) -> dict:
        """Is this provider usable right now? Never raises."""

    @abc.abstractmethod
    async def start_session(self, *, project_id: str, job_id: str, prompt: str,
                            system: str = "", schema: dict | None = None,
                            mcp_config: dict | None = None,
                            allowed_tools: list | None = None,
                            workspace: str | None = None) -> AgentSession:
        """Begin a new reasoning session and return its handle."""

    @abc.abstractmethod
    async def resume_session(self, session: AgentSession, prompt: str, *,
                             schema: dict | None = None) -> AgentSession:
        """Continue an existing session (spec 42) with new information."""

    @abc.abstractmethod
    async def submit_event(self, session: AgentSession, event: dict) -> None:
        """Hand a backend event to a live session."""

    @abc.abstractmethod
    def stream_events(self, session: AgentSession) -> AsyncIterator[AgentEvent]:
        """Yield high-level progress for the running turn."""

    @abc.abstractmethod
    async def cancel(self, session: AgentSession) -> None:
        """Stop the session. Must be safe to call twice."""

    async def run(self, *, project_id: str, job_id: str, prompt: str,
                  system: str = "", schema: dict | None = None,
                  mcp_config: dict | None = None, allowed_tools: list | None = None,
                  workspace: str | None = None, resume: AgentSession | None = None,
                  on_event=None) -> AgentRunResult:
        """Convenience: start (or resume), drain the stream, return the result."""
        if resume is not None:
            session = await self.resume_session(resume, prompt, schema=schema)
        else:
            session = await self.start_session(
                project_id=project_id, job_id=job_id, prompt=prompt, system=system,
                schema=schema, mcp_config=mcp_config, allowed_tools=allowed_tools,
                workspace=workspace)
        collected: list = []
        result = AgentRunResult(ok=False, external_id=session.external_id)
        async for ev in self.stream_events(session):
            collected.append(ev)
            if on_event is not None:
                try:
                    on_event(ev)
                except Exception:
                    pass
            if ev.kind == "result":
                result.ok = not ev.data.get("is_error", False)
                result.text = ev.data.get("text", "")
                result.structured = ev.data.get("structured")
                result.turns = ev.data.get("turns", 0)
                result.cost_usd = ev.data.get("cost_usd", 0.0)
                result.external_id = ev.data.get("external_id") or session.external_id
            elif ev.kind == "error":
                result.error = ev.label or ev.data.get("error")
        result.events = collected
        if result.error and not result.text:
            result.ok = False
        return result
