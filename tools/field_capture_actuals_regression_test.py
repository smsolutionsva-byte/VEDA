"""Focused regression coverage for capture idempotency and actuals policy."""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

tmp = tempfile.TemporaryDirectory(prefix="veda_field_capture_")
os.environ["VEDA_DATA_DIR"] = tmp.name
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from veda import db  # noqa: E402
from veda.integrations import primavera  # noqa: E402
from veda.pipeline import field_capture  # noqa: E402

db.init_db()
project_id = db.insert("projects", {"name": "Field capture regression"})
day = (date.today() - timedelta(days=1)).isoformat()


def activity(uid: int, name: str, **patch):
    row = {
        "project_id": project_id, "uid": uid, "display_id": f"A-{uid}",
        "name": name, "is_summary": 0, "status": "In Progress",
        "start": (date.today() - timedelta(days=20)).isoformat(),
        "finish": (date.today() + timedelta(days=20)).isoformat(),
        "duration_days": 20, "remaining_days": 10, "percent_complete": 25,
    }
    row.update(patch)
    db.insert("activities", row)


def payload(client_id: str, uid: int | None, state: str, **patch):
    row = {
        "client_capture_id": client_id, "activity_uid": uid,
        "event_state": state, "occurred_at": day + "T08:30:00",
        "language": "hi-IN", "reporter": "Field engineer",
        "original_text": "काम की पुष्टि की गई",
        "confirmed_text": "Confirmed field observation",
        "location_label": "Unit 04",
    }
    row.update(patch)
    return row


activity(101, "Install pipe rack steel", actual_start=None, percent_complete=0)
start = field_capture.store(project_id, payload("capture-start-001", 101, "start"), [])
assert start["status"] == "proposal_ready"
assert len(start["proposal_ids"]) == 1
assert db.q1("SELECT field FROM proposals WHERE id=?", [start["proposal_ids"][0]])["field"] == "actualStart"

replay = field_capture.store(project_id, payload("capture-start-001", 101, "start"), [])
assert replay["id"] == start["id"] and replay["idempotent_replay"] is True
assert (db.q1("SELECT COUNT(*) c FROM proposals WHERE project_id=?", [project_id]) or {})["c"] == 1

activity(102, "Weld process piping", percent_complete=20, remaining_days=12)
progress = field_capture.store(project_id, payload(
    "capture-progress-001", 102, "progress", observed_progress=62.5,
    remaining_days=4.5), [])
assert progress["status"] == "proposal_ready"
assert {row["field"] for row in db.q(
    "SELECT field FROM proposals WHERE source_event_id=?", [progress["execution_event_id"]])} == {
        "percentComplete", "remainingDuration"}

activity(103, "Hydrotest system", percent_complete=80, remaining_days=3)
finish = field_capture.store(project_id, payload("capture-finish-001", 103, "finish"), [])
assert finish["status"] == "proposal_ready"
assert {row["field"] for row in db.q(
    "SELECT field FROM proposals WHERE source_event_id=?", [finish["execution_event_id"]])} == {
        "actualFinish", "percentComplete", "remainingDuration"}

activity(104, "Cable tray installation", actual_start=(date.today() - timedelta(days=8)).isoformat())
conflict = field_capture.store(project_id, payload("capture-conflict-001", 104, "start"), [])
assert conflict["status"] == "conflict" and conflict["conflicts"]
assert not conflict["proposal_ids"]

unmatched = field_capture.store(project_id, payload("capture-unmatched-001", None, "progress",
                                                     observed_progress=10), [])
assert unmatched["status"] == "needs_activity" and not unmatched["proposal_ids"]

preview = primavera.preview_proposal(finish["proposal_ids"][0])
assert preview["ready"] is False
assert "activity has no verified P6 ObjectId mapping" in preview["blockers"]

print("field capture / actuals / P6 guard regression: ok")
db.connect().close()
db._local.conn = None
tmp.cleanup()
