"""Reasoning provider registry and automatic fallback policy."""
from __future__ import annotations

import asyncio

from .. import config, db
from .antigravity import AntigravityProvider
from .antigravity_cli import AntigravityCLIProvider
from .base import AgentProvider
from .claude_code import ClaudeCodeProvider
from .codex_cli import CodexCLIProvider
from .local_antigravity import LocalAntigravityProvider

_INSTANCES: dict[str, AgentProvider] = {}

# The normal user-facing providers.  The old Gemini API and inbox bridge remain
# available as explicit/manual compatibility choices, but are never silently
# inserted into AUTO_PROVIDER_ORDER.
PROVIDERS = {
    "antigravity_cli": AntigravityCLIProvider,
    "claude_code": ClaudeCodeProvider,
    "codex": CodexCLIProvider,
    "gemini_api": AntigravityProvider,
    "local_antigravity": LocalAntigravityProvider,
}

AUTO_PROVIDER_ORDER = ["antigravity_cli", "claude_code", "codex"]

LABELS = {
    "auto": "Auto · Antigravity → Claude Code → Codex",
    "antigravity_cli": "Antigravity",
    "claude_code": "Claude Code",
    "codex": "Codex",
    "gemini_api": "Gemini API (manual)",
    "local_antigravity": "Antigravity inbox bridge (manual)",
}

# Backward compatibility: old databases used "antigravity" for the direct API.
_ALIASES = {"antigravity": "gemini_api"}


def _normalise(name: str | None) -> str:
    name = (name or "").strip()
    return _ALIASES.get(name, name)


def get_provider(name: str) -> AgentProvider:
    name = _normalise(name)
    if name not in PROVIDERS:
        raise ValueError("unknown provider: " + name)
    if name not in _INSTANCES:
        _INSTANCES[name] = PROVIDERS[name]()
    return _INSTANCES[name]


def active_provider_name() -> str:
    row = db.q1("SELECT v FROM kv WHERE k='agent_provider'")
    if row:
        name = _normalise(row.get("v"))
        if name == "auto" or name in PROVIDERS:
            return name
    name = _normalise(config.AGENT_PROVIDER)
    return name if (name == "auto" or name in PROVIDERS) else "auto"


def set_active_provider(name: str) -> str:
    name = _normalise(name)
    if name != "auto" and name not in PROVIDERS:
        raise ValueError("unknown provider: " + name)
    db.ex("INSERT OR REPLACE INTO kv (k,v,updated_at) VALUES ('agent_provider',?,?)",
          [name, db.now()])
    return name


def candidate_names() -> list[str]:
    """Providers to try for the next reasoning turn, in exact priority order."""
    active = active_provider_name()
    if active == "auto":
        return list(AUTO_PROVIDER_ORDER)
    return [active]


async def _health(name: str) -> dict:
    try:
        h = await asyncio.wait_for(get_provider(name).health(), timeout=45)
    except Exception as exc:  # noqa: BLE001
        h = {"ok": False, "provider": name, "error": str(exc)}
    h["label"] = LABELS.get(name, name)
    return h


async def health_all() -> dict:
    out = {}
    for name in PROVIDERS:
        out[name] = await _health(name)
        out[name]["active"] = (name == active_provider_name())

    chain = []
    selected = None
    for name in AUTO_PROVIDER_ORDER:
        ok = bool(out.get(name, {}).get("ok"))
        chain.append({"provider": name, "label": LABELS.get(name, name), "ok": ok})
        if selected is None and ok:
            selected = name
    out["auto"] = {
        "ok": selected is not None,
        "provider": "auto",
        "label": LABELS["auto"],
        "active": active_provider_name() == "auto",
        "selected": selected,
        "selected_label": LABELS.get(selected, selected) if selected else None,
        "chain": chain,
        "note": "Each job tries Antigravity, then Claude Code, then Codex. Runtime failures also fall through.",
    }
    return out


async def health_active() -> dict:
    active = active_provider_name()
    if active == "auto":
        all_h = await health_all()
        return all_h["auto"]
    return await _health(active)
