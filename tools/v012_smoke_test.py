"""Offline VEDA v0.1.2 smoke test.

Exercises the new multi-source intake, deduplication, pasted WhatsApp parsing,
schedule revision deltas, and structural proposal guards without requiring
Horizun or a reasoning provider.

Usage:
    .venv\\Scripts\\python.exe tools\\v012_smoke_test.py
"""
from __future__ import annotations

import asyncio
import os
import tempfile
import sys
from io import BytesIO
from pathlib import Path

# Must be set before importing VEDA configuration.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
_TMP = tempfile.TemporaryDirectory(prefix="veda_v012_smoke_")
os.environ["VEDA_DATA_DIR"] = str(Path(_TMP.name) / "data")
os.environ["VEDA_OCR"] = "0"

from starlette.datastructures import UploadFile  # noqa: E402
from veda import db  # noqa: E402
from veda.api.routes import _store_ingestion_batch  # noqa: E402
from veda.mcpc import schedule_ops  # noqa: E402
from veda.pipeline import extract, ingest, validators  # noqa: E402


def ok(label: str) -> None:
    print("[PASS] " + label)


def main() -> None:
    db.init_db()
    pid = db.insert("projects", {
        "name": "v0.1.2 smoke", "status": "active", "updated_at": db.now()
    })

    first = ingest.store_upload(
        pid, "daily.csv", b"Date,Description\n2026-08-26,Spool erected\n", "text/csv")
    duplicate = ingest.store_upload(
        pid, "daily-copy.csv", b"Date,Description\n2026-08-26,Spool erected\n", "text/csv")
    assert not first["skipped"] and duplicate["skipped"]
    assert duplicate["duplicate_of"] == first["id"]
    ok("exact duplicate sources are skipped by SHA-256")

    note = ingest.store_text_input(
        pid,
        "26/08/2026, 10:14 - Ravi: Spool 24-P-101 erection completed",
        "whatsapp", "Piping chat")
    f = db.q1("SELECT * FROM files WHERE id=?", [note["id"]])
    rows = extract.extract_evidence(pid, f, None)
    assert len(rows) == 1 and rows[0]["author"] == "Ravi"
    assert rows[0]["provenance"] == "HUMAN_INPUT"
    ok("single-message WhatsApp paste becomes HUMAN_INPUT evidence")

    async def batch():
        files = [
            UploadFile(filename="a.txt", file=BytesIO(b"civil work started")),
            UploadFile(filename="b.txt", file=BytesIO(b"electrical work complete")),
        ]
        return await _store_ingestion_batch(
            pid, files, "Instrument loop check done", "field_note", "Supervisor note")

    result = asyncio.run(batch())
    assert result["stored_count"] == 3 and result["evidence_count"] == 3
    ok("one ingestion batch accepts many files plus pasted text")

    base = {
        "wbs": "1", "parent_uid": None, "is_summary": 0, "is_milestone": 0,
        "status": "not_started", "start": "2026-08-01", "finish": "2026-08-02",
        "actual_start": None, "actual_finish": None, "duration_days": 1,
        "remaining_days": 1, "percent_complete": 0, "constraint_type": None,
        "constraint_date": None, "deadline": None, "baseline_start": None,
        "baseline_finish": None,
    }
    before = [
        {**base, "uid": 1, "display_id": "A1", "name": "Task A"},
        {**base, "uid": 2, "display_id": "A2", "name": "Remove me"},
    ]
    after = [
        {**before[0], "percent_complete": 50},
        {**base, "uid": 3, "display_id": "A3", "name": "New task"},
    ]
    sid = db.insert("schedule_snapshots", {
        "project_id": pid, "revision": 2, "is_current": 1
    })
    counts = schedule_ops._record_revision_changes(pid, sid, 2, before, after)
    assert counts == {"added": 1, "removed": 1, "updated": 1}
    ok("schedule revisions persist added/removed/updated activity deltas")

    db.insert("activities", {
        "project_id": pid, "uid": 100, "name": "Parent", "is_summary": 1
    })
    db.insert("activities", {
        "project_id": pid, "uid": 101, "name": "Child", "parent_uid": 100,
        "is_summary": 0
    })
    caps = {"dry_run_simulation": True}
    create_prop = {
        "operation": "create",
        "payload_json": db.jdumps({
            "parent_uid": 100,
            "task_fields": {"name": "New child", "duration": "2d"},
        }),
        "evidence_ids_json": "[]",
    }
    create_result = validators.validate_proposal(
        create_prop, None, project_id=pid, capabilities=caps)
    assert create_result["result"] != validators.FAIL

    leaf = db.q1("SELECT * FROM activities WHERE project_id=? AND uid=?", [pid, 101])
    leaf_result = validators.validate_proposal({
        "operation": "delete", "target_uid": 101,
        "payload_json": "{}", "evidence_ids_json": "[]",
    }, leaf, project_id=pid, capabilities=caps)
    assert leaf_result["result"] != validators.FAIL

    parent = db.q1("SELECT * FROM activities WHERE project_id=? AND uid=?", [pid, 100])
    parent_result = validators.validate_proposal({
        "operation": "delete", "target_uid": 100,
        "payload_json": "{}", "evidence_ids_json": "[]",
    }, parent, project_id=pid, capabilities=caps)
    assert parent_result["result"] == validators.FAIL
    ok("create + leaf delete validate; cascading parent delete is blocked")

    print("\nVEDA v0.1.2 offline smoke test passed.")


if __name__ == "__main__":
    main()
