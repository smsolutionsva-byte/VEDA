"""Provider registry - VEDA stays provider-neutral (spec 3)."""
from __future__ import annotations

import asyncio

from .. import config, db
from .antigravity import AntigravityProvider
from .base import AgentProvider
from .claude_code import ClaudeCodeProvider
from .local_antigravity import LocalAntigravityProvider

_INSTANCES: dict = {}

PROVIDERS = {
    "claude_code": ClaudeCodeProvider,
    "antigravity": AntigravityProvider,
    "local_antigravity": LocalAntigravityProvider,
}

LABELS = {
    "claude_code": "Claude Code",
    "antigravity": "Google Antigravity / Gemini",
    "local_antigravity": "Antigravity IDE (Local Agent)",
}


def get_provider(name: str | None = None) -> AgentProvider:
    name = (name or active_provider_name()).strip()
    if name not in PROVIDERS:
        name = "claude_code"
    if name not in _INSTANCES:
        _INSTANCES[name] = PROVIDERS[name]()
    return _INSTANCES[name]


def active_provider_name() -> str:
    row = db.q1("SELECT v FROM kv WHERE k='agent_provider'")
    if row and row.get("v") in PROVIDERS:
        return row["v"]
    return config.AGENT_PROVIDER if config.AGENT_PROVIDER in PROVIDERS \
        else "claude_code"


def set_active_provider(name: str) -> str:
    if name not in PROVIDERS:
        raise ValueError("unknown provider: " + name)
    db.ex("INSERT OR REPLACE INTO kv (k,v,updated_at) VALUES ('agent_provider',?,?)",
          [name, db.now()])
    return name


async def health_all() -> dict:
    out = {}
    for name in PROVIDERS:
        try:
            out[name] = await asyncio.wait_for(get_provider(name).health(),
                                               timeout=45)
        except Exception as exc:  # noqa: BLE001
            out[name] = {"ok": False, "provider": name, "error": str(exc)}
        out[name]["label"] = LABELS.get(name, name)
        out[name]["active"] = (name == active_provider_name())
    return out


async def health_active() -> dict:
    name = active_provider_name()
    try:
        h = await asyncio.wait_for(get_provider(name).health(), timeout=45)
    except Exception as exc:  # noqa: BLE001
        h = {"ok": False, "provider": name, "error": str(exc)}
    h["label"] = LABELS.get(name, name)
    return h
