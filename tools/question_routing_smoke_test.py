"""Offline checks for Ask VEDA's adaptive reasoning lanes."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from veda.agent.prompts import question_prompt
from veda.agent.question_router import instant_reply, route_question


def main() -> None:
    project = {"name": "Bridge Test"}

    assert route_question("hi").mode == "instant"
    assert instant_reply("hi", project["name"], []).startswith("Hey!")
    assert route_question("tell me a joke").mode == "fast"
    assert route_question("What is the forecast finish?").mode == "deep"
    assert route_question("Check activity A-100").mode == "deep"
    assert route_question("why?", previous_mode="deep").mode == "deep"
    assert route_question("what caused that?", previous_mode="deep").mode == "deep"
    assert route_question("why?", previous_mode="fast").mode == "fast"
    assert route_question("say hello", force_deep=True).mode == "deep"

    fast = question_prompt("tell me a joke", project, None, "fast")
    assert "[VEDA_REASONING_MODE:FAST]" in fast
    assert "veda_activities" not in fast
    deep = question_prompt("Which task is late?", project, None, "deep")
    assert "[VEDA_REASONING_MODE:DEEP]" in deep
    assert "veda_activities" in deep

    print("Ask VEDA adaptive question routing smoke test: PASS")


if __name__ == "__main__":
    main()
