"""Regression: authoritative selection auto-queues analysis and field ingest changes overview."""
from __future__ import annotations
import os, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
_TMP = tempfile.TemporaryDirectory(prefix="veda_overview_flow_")
os.environ["VEDA_DATA_DIR"] = str(Path(_TMP.name) / "data")
os.environ["VEDA_OCR"] = "0"

from veda import db
from veda.api import routes


def main() -> None:
    db.init_db()
    pid = db.insert("projects", {"name": "Project 1", "status": "active", "updated_at": db.now()})
    batch = db.insert("ingestion_batches", {"project_id": pid, "status": "awaiting_schedule", "schedule_count": 2})
    td = Path(_TMP.name)
    f1p = td / "base.csv"; f1p.write_text("x\n", encoding="utf-8")
    f2p = td / "extended.csv"; f2p.write_text("x\n", encoding="utf-8")
    f1 = db.insert("files", {"project_id": pid, "batch_id": batch, "filename": "base.csv", "relative_path": "Schedule/base.csv", "stored_path": str(f1p), "kind": "schedule", "security_state": "clean"})
    db.insert("files", {"project_id": pid, "batch_id": batch, "filename": "extended.csv", "relative_path": "ScheduleExtended/extended.csv", "stored_path": str(f2p), "kind": "schedule", "security_state": "clean"})

    picked = routes.select_batch_schedule(pid, batch, {"file_id": f1})
    assert picked["analysis_started"] is True and picked["job_id"], picked
    jobs = db.q("SELECT * FROM jobs WHERE trigger_event_id=?", [picked["event"]])
    assert len(jobs) == 1 and jobs[0]["kind"] == "analysis" and jobs[0]["status"] == "queued", jobs
    assert (db.q1("SELECT schedule_file_id FROM projects WHERE id=?", [pid]) or {}).get("schedule_file_id") == f1

    snap = db.insert("schedule_snapshots", {
        "project_id": pid, "file_id": f1, "revision": 1, "project_name": "base.csv",
        "planned_start": "2026-09-01", "planned_finish": "2027-02-28",
        "baseline_start": "2026-09-01", "baseline_finish": "2027-02-28",
        "baseline_present": 1, "baseline_coverage_count": 2,
        "criticality_available": 0, "overdue_evaluable": 0,
        "completed_late_evaluable": 0, "progress_available": 1,
        "progress_basis": "activity status (exact 0/100 states)", "percent_complete": 0,
        "task_count": 2, "wbs_count": 1, "relationship_count": 1,
        "resource_count": 2, "resource_assignment_count": 2,
        "health_score": 50.0, "is_current": 1,
        "info_json": db.jdumps({"reference_context": {"reference_record_count": 165},
                                  "source": {"status_counts": {"not_started": 2}}}),
    })
    for status, n in (("pass", 3), ("fail", 3), ("not_evaluated", 12)):
        for i in range(n):
            db.insert("qa_findings", {"project_id": pid, "snapshot_id": snap,
                                       "code": status + str(i), "status": status,
                                       "title": status, "provenance": "DETERMINISTIC_CALCULATION"})
    db.insert("activities", {"project_id": pid, "snapshot_id": snap, "uid": 1,
                              "display_id": "A1", "name": "Work", "wbs": "P",
                              "status": "not_started", "percent_complete": 0})

    before = routes.overview(pid)
    assert before["field_context"]["record_count"] == 0
    assert before["quality"] == {"passed": 3, "failed": 3, "not_evaluated": 12}

    ef1 = db.insert("files", {"project_id": pid, "filename": "DPR_1.csv", "stored_path": str(td / "DPR_1.csv"), "kind": "evidence", "security_state": "clean"})
    ef2 = db.insert("files", {"project_id": pid, "filename": "DPR_2.csv", "stored_path": str(td / "DPR_2.csv"), "kind": "evidence", "security_state": "clean"})
    e1 = db.insert("evidence", {"project_id": pid, "file_id": ef1, "source_file": "DPR_1.csv",
                                 "date": "2026-09-10", "description": "Work 20%", "observed_progress": 20,
                                 "state": "linked", "provenance": "SOURCE_FILE"})
    db.insert("evidence", {"project_id": pid, "file_id": ef2, "source_file": "DPR_2.csv",
                            "date": "2026-09-11", "description": "Ambiguous work 30%", "observed_progress": 30,
                            "state": "needs_review", "provenance": "SOURCE_FILE"})
    db.insert("evidence_links", {"project_id": pid, "evidence_id": e1, "activity_uid": 1,
                                  "activity_name": "Work", "relation": "supporting", "is_candidate": 0,
                                  "provenance": "DETERMINISTIC_CALCULATION"})
    db.insert("observed_progress", {"project_id": pid, "activity_uid": 1,
                                     "official_percent": 0, "observed_percent": 20,
                                     "delta": 20, "evidence_count": 1, "as_of": "2026-09-10",
                                     "basis": "validated field evidence", "provenance": "DERIVED"})

    after = routes.overview(pid)
    fc = after["field_context"]
    assert fc["record_count"] == 2, fc
    assert fc["source_file_count"] == 2, fc
    assert fc["latest_date"] == "2026-09-11", fc
    assert fc["reported_progress_record_count"] == 2, fc
    assert fc["validated_link_record_count"] == 1 and fc["validated_activity_count"] == 1, fc
    assert fc["numeric_observed_activity_count"] == 1 and fc["unresolved_record_count"] == 1, fc
    assert "2 field-evidence record(s)" in after["state_summary"], after["state_summary"]
    assert "separately from the schedule-QA findings" in after["state_summary"], after["state_summary"]

    print("overview ingestion workflow smoke test: PASS")


if __name__ == "__main__":
    main()
