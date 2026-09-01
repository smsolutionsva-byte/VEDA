"""Opt-in live test for VEDA's official Antigravity CLI provider.

This uses the signed-in Antigravity account and therefore is intentionally not
part of the offline test suite.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["VEDA_DATA_DIR"] = tempfile.mkdtemp(prefix="veda_agy_live_")
os.environ["VEDA_AGENT_PROVIDER"] = "antigravity_cli"
os.environ["VEDA_AGENT_TIMEOUT"] = "180"

from veda import db, jobs  # noqa: E402
from veda.agent.prompts import question_prompt  # noqa: E402


def main() -> None:
    db.init_db()
    pid = db.insert("projects", {"name": "Antigravity Bridge Test",
                                 "status": "active"})
    jid = jobs.create_job(pid, "question")
    prompt = question_prompt("hi", {"name": "Antigravity Bridge Test"}, None)
    result, provider = jobs._invoke_agent(jid, pid, prompt)
    assert provider == "antigravity_cli", provider
    assert result.summary.strip(), "Antigravity returned an empty summary"
    print("[PASS] VEDA -> Antigravity -> structured VEDA response")
    print(result.summary)


if __name__ == "__main__":
    main()
