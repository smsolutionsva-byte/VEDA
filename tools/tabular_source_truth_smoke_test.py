"""Regression: adapter defaults must never override tabular source truth."""
from __future__ import annotations
import os, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
_TMP = tempfile.TemporaryDirectory(prefix="veda_tab_truth_")
os.environ["VEDA_DATA_DIR"] = str(Path(_TMP.name) / "data")
os.environ["VEDA_OCR"] = "0"

from veda import db
from veda.mcpc import tabular_schedule
from veda.mcpc.qa_guard import guard_schedule_qa
from veda.mcpc.reference_semantics import inspect_project_references
from veda.mcpc.schedule_ops import _health_score


def _write(p: Path, text: str) -> None:
    p.write_text(text.strip() + "\n", encoding="utf-8")


def main() -> None:
    db.init_db()
    td = Path(_TMP.name)
    sched = td / "baseline_schedule.csv"
    _write(sched, """
Activity_ID,WBS_Path,Activity_Name,Planned_Start,Planned_Finish,Planned_Duration_Days,Baseline_Start,Baseline_Finish,Activity_Type,Calendar,Predecessor_IDs,Resource_Assigned,Status
A1,P/CIV,Excavate,2026-09-01,2026-09-05,5,2026-09-01,2026-09-05,Task Dependent,6-Day,,Crew A,Not Started
A2,P/CIV,Excavate,2026-09-06,2026-09-10,5,2026-09-06,2026-09-10,Task Dependent,6-Day,A1,Crew B,Not Started
M1,P/COM,Handover,2026-09-11,2026-09-13,3,2026-09-11,2026-09-13,Finish Milestone,6-Day,A2,Project Manager,Not Started
""")
    sem = tabular_schedule.inspect_semantics(str(sched))
    assert sem["activity_count"] == 3
    assert sem["baseline_values_available"] and sem["baseline_coverage_count"] == 3
    assert sem["criticality_available"] is False
    assert sem["data_date"] is None
    assert sem["source_progress_pct"] == 0.0
    assert len(sem["resource_labels"]) == 3 and sem["resource_assignment_count"] == 3
    assert len(sem["milestone_duration_uids"]) == 1
    assert len(sem["milestone_resource_uids"]) == 1
    assert len(sem["duplicate_sibling_affected_ids"]) == 2

    # Transport XML must preserve source baseline/resources without inventing WBS summary tasks.
    xml, meta = tabular_schedule.prepare_mspdi(str(sched), str(td / "adapted"))
    txt = Path(xml).read_text(encoding="utf-8")
    assert txt.count("<Summary>0</Summary>") == 3
    assert txt.count("<Baseline>") == 3
    assert "<Resources>" in txt and "<Assignments>" in txt

    rules = [
        "dcma_01_logic", "dcma_02_leads", "dcma_03_lags", "dcma_04_relationship_types",
        "dcma_05_hard_constraints", "dcma_06_high_float", "dcma_07_negative_float",
        "dcma_08_high_duration", "dcma_09_invalid_dates", "dcma_10_resources",
        "dcma_11_missed_tasks", "dcma_12_critical_path_test", "dcma_13_cpli", "dcma_14_bei",
        "horizun_duplicate_names", "horizun_milestone_duration",
        "horizun_progress_recorded", "horizun_unnamed_tasks",
    ]
    raw = {"findings": [{"rule": r, "evaluated": True, "passed": True,
                           "summary": r, "uids": []} for r in rules]}
    out = guard_schedule_qa(raw, schedule_path=str(sched))
    assert out["passed"] == 3 and out["failed"] == 3 and out["notEvaluated"] == 12, out
    assert _health_score(out) == 50.0

    # Supporting tables stay reference context; exact mismatches are reported, never guessed.
    refs = {
        "resource_allocation_master.csv": "Resource_ID,Resource_Name\nR1,Crew A\nR2,Crew C\n",
        "calendar_definitions.csv": "Calendar_Name,Hours_Per_Day\n6_Day_Standard,8\n",
        "milestone_register.csv": "Milestone_ID,Linked_Activity_IDs\nMS1,M1\nMS2,OLD-1\n",
        "WBS_dictionary.csv": "WBS_Code,WBS_Name\nP,Project\n",
        "activity_code_dictionary.csv": "Code_Type,Code_Value\nDiscipline,CIV\n",
    }
    pid = db.insert("projects", {"name": "P", "status": "active", "updated_at": db.now()})
    for name, content in refs.items():
        p = td / name; _write(p, content)
        db.insert("files", {"project_id": pid, "filename": name, "stored_path": str(p),
                             "security_state": "clean", "created_at": db.now()})
    ctx = inspect_project_references(pid, sem)
    assert ctx["reference_record_count"] == 7
    assert ctx["resource_exact_match_count"] == 1
    assert ctx["resource_unresolved_count"] == 2
    assert ctx["calendar_unresolved_count"] == 1
    assert ctx["milestone_links_resolved_count"] == 1
    assert ctx["milestone_links_unresolved_count"] == 1

    print("tabular source-truth smoke test: PASS")


if __name__ == "__main__":
    main()
