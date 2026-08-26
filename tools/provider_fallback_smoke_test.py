"""Offline smoke test for VEDA's provider fallback policy.

No external CLI or network is required. It simulates:
Antigravity offline -> Claude run failure -> Codex success.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Must be set before importing VEDA config/db.
os.environ["VEDA_DATA_DIR"] = tempfile.mkdtemp(prefix="veda_provider_test_")

from veda import db, jobs  # noqa: E402
from veda.agent import registry, schemas  # noqa: E402
from veda.agent.base import AgentRunResult  # noqa: E402


class FakeProvider:
    def __init__(self, name: str, healthy: bool = True,
                 result: AgentRunResult | None = None):
        self.name = name
        self.model = "fake"
        self.healthy = healthy
        self.result = result

    async def health(self) -> dict:
        return {"ok": self.healthy, "provider": self.name,
                "error": None if self.healthy else "offline"}

    async def run(self, **_kwargs) -> AgentRunResult:
        assert self.result is not None
        return self.result


def main() -> None:
    db.init_db()
    pid = db.insert("projects", {"name": "Fallback Test", "status": "active",
                                 "agent_provider": "auto"})
    jid = jobs.create_job(pid, "analysis")

    fake = {
        "antigravity_cli": FakeProvider("antigravity_cli", healthy=False),
        "claude_code": FakeProvider(
            "claude_code", result=AgentRunResult(ok=False, error="auth expired")),
        "codex": FakeProvider(
            "codex", result=AgentRunResult(
                ok=True,
                structured=schemas.AgentResult(summary="codex won").model_dump(),
                turns=1, external_id="cx1")),
    }
    original_get = registry.get_provider
    original_candidates = registry.candidate_names
    registry.get_provider = lambda name: fake[name]
    registry.candidate_names = lambda: ["antigravity_cli", "claude_code", "codex"]
    try:
        result, used = jobs._invoke_agent(jid, pid, "test prompt")
        assert used == "codex"
        assert result.summary == "codex won"
        assert db.q1("SELECT provider FROM jobs WHERE id=?", [jid])["provider"] == "codex"
    finally:
        registry.get_provider = original_get
        registry.candidate_names = original_candidates

    print("[PASS] Antigravity -> Claude Code -> Codex runtime fallback")


if __name__ == "__main__":
    main()
