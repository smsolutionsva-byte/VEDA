"""Offline checks for Ask VEDA's question-aware deterministic fallback."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["VEDA_DATA_DIR"] = tempfile.mkdtemp(prefix="veda_question_test_")

from veda import db  # noqa: E402
from veda.pipeline import deterministic  # noqa: E402


def main() -> None:
    db.init_db()
    pid = db.insert("projects", {"name": "Bridge Test", "status": "active"})

    greeting = deterministic.answer_question(pid, "hi")
    assert greeting.summary.startswith("Hey!")
    assert "Schedule '" not in greeting.summary

    unavailable = deterministic.answer_question(pid, "What caused yesterday's delay?")
    assert "couldn't reach the configured Antigravity agent" in unavailable.summary
    assert "Schedule '" not in unavailable.summary

    print("[PASS] Ask VEDA fallback respects the user's message")


if __name__ == "__main__":
    main()
