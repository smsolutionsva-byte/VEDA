"""Offline regression checks for the Antigravity desktop bridge."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from veda.agent import local_antigravity as bridge


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="veda_local_ag_") as raw:
        temp = Path(raw)
        home = temp / "home"
        workspace = temp / "VEDA-main"
        nested = workspace / "data"
        nested.mkdir(parents=True)
        descriptors = home / ".gemini" / "config" / "projects"
        descriptors.mkdir(parents=True)
        project_id = "11111111-2222-3333-4444-555555555555"
        (descriptors / (project_id + ".json")).write_text(json.dumps({
            "id": project_id,
            "projectResources": {
                "resources": [{"folderUri": workspace.as_uri()}],
            },
        }), encoding="utf-8")

        with mock.patch.object(bridge.Path, "home", return_value=home):
            actual = bridge._agentapi_project_id(str(nested))
        assert actual == project_id, (actual, project_id)

    with mock.patch.object(
            bridge.config, "LOCAL_ANTIGRAVITY_CALLBACK_URL",
            "http://127.0.0.1:8770"):
        prompt = bridge._callback_prompt("inbox_test")
    assert "GET http://127.0.0.1:8770/api/agent/inbox/item/inbox_test" in prompt
    assert '"inbox_id":"inbox_test"' in prompt
    assert "Do not only reply" in prompt

    with (mock.patch.object(bridge.config, "LOCAL_ANTIGRAVITY_FAST_MODEL",
                            "flash_lite"),
          mock.patch.object(bridge.config, "LOCAL_ANTIGRAVITY_DEEP_MODEL", "pro")):
        assert bridge._reasoning_mode("[VEDA_REASONING_MODE:FAST]\nhello") == "fast"
        assert bridge._reasoning_mode("analyse this schedule") == "deep"
        assert bridge._desktop_model("fast") == "flash_lite"
        assert bridge._desktop_model("deep") == "pro"

    print("local Antigravity desktop bridge smoke test: PASS")


if __name__ == "__main__":
    main()
