"""End-to-end verification of the VEDA vertical slice (spec 59, 60).

Runs the real path: create project -> upload files -> dataset_uploaded ->
agent wakes -> Horizun analyses -> structured result -> VEDA database.

Run:  .venv\\Scripts\\python.exe tools\\verify_slice.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from veda import db, events, jobs  # noqa: E402
from veda.pipeline import ingest  # noqa: E402

SAMPLES = ROOT / "sample_data"


def line(title: str) -> None:
    print("\n" + "=" * 66)
    print(title)
    print("=" * 66)


def main() -> None:
    db.init_db()

    line("1. CREATE PROJECT")
    db.ex("DELETE FROM projects")
    pid = db.insert("projects", {
        "name": "Trans-Ridge 24in Pipeline - Section 4",
        "client": "Ridgeline Energy", "location": "Section 4, CH 0+000 to 24+000",
        "description": "24 inch cross-country pipeline, two spreads, one HDD "
                       "river crossing and a pump station.",
        "status": "active", "created_at": db.now(), "updated_at": db.now()})
    print("  project", pid)

    line("2. UPLOAD SCHEDULE + PROJECT FILES")
    uploaded = []
    for p in sorted(SAMPLES.iterdir()):
        if p.name.startswith("_") or p.is_dir():
            continue
        rec = ingest.store_upload(pid, p.name, p.read_bytes())
        uploaded.append(rec)
        flag = "" if rec["security_state"] == "clean" else \
            "  <-- " + rec["security_state"].upper()
        print("  " + rec["kind"].ljust(9) + rec["filename"].ljust(42) +
              str(rec["size_bytes"]).rjust(8) + " B" + flag)

    line("3. EVENT: dataset_uploaded  (the agent wakes on this)")
    ev = events.emit(events.DATASET_UPLOADED, pid,
                     {"file_ids": [u["id"] for u in uploaded]}, source="test")
    job_id = jobs.create_job(pid, "analysis", ev["id"], {})
    print("  event", ev["id"], "-> job", job_id)

    line("4. RUN THE JOB (Horizun + agent + validators)")
    t0 = time.time()
    jobs._run(job_id)
    print("  completed in", round(time.time() - t0, 1), "s")

    job = db.q1("SELECT * FROM jobs WHERE id=?", [job_id])
    print("  status:", job["status"], "| provider:", job["provider"])
    if job.get("error"):
        print("  ERROR:", job["error"][:1500])

    line("5. AGENT ACTIVITY (spec 50)")
    for a in db.q("SELECT step,label,state FROM agent_activity WHERE job_id=? "
                  "ORDER BY created_at", [job_id]):
        mark = "ok  " if a["state"] == "success" else "FAIL"
        print("  [" + mark + "] " + str(a["label"])[:88])

    line("6. MCP ACTIVITY (spec 51)")
    for c in db.q("SELECT tool,state,summary,duration_ms FROM mcp_calls "
                  "WHERE project_id=? ORDER BY created_at", [pid])[:18]:
        print("  Horizun/" + str(c["tool"]).ljust(20) + str(c["state"]).ljust(9) +
              str(c["summary"] or "")[:52].ljust(54) +
              str(round(c["duration_ms"])) + "ms")

    line("7. VEDA DATABASE POPULATED")
    for t in ("activities", "relationships", "resources", "assignments",
              "milestones", "wbs_nodes", "qa_findings", "earned_value",
              "timephased", "evidence", "evidence_links", "observed_progress",
              "issues", "risks", "reviews", "proposals", "artifacts", "audit"):
        n = db.q1("SELECT COUNT(*) c FROM " + t + " WHERE project_id=?",
                  [pid])["c"] if t != "audit" else \
            db.q1("SELECT COUNT(*) c FROM audit WHERE project_id=?", [pid])["c"]
        print("  " + t.ljust(20) + str(n).rjust(6))

    line("8. SCHEDULE SNAPSHOT (spec 15, 16)")
    s = db.q1("SELECT * FROM schedule_snapshots WHERE project_id=? "
              "AND is_current=1", [pid])
    if s:
        for k in ("project_name", "data_date", "planned_start", "planned_finish",
                  "forecast_finish", "baseline_finish", "task_count",
                  "critical_count", "late_count", "percent_complete",
                  "health_score"):
            print("  " + k.ljust(18) + str(s.get(k)))

    line("9. EVIDENCE STATES (spec 36, 37)")
    for r in db.q("SELECT state, COUNT(*) c FROM evidence WHERE project_id=? "
                  "GROUP BY state ORDER BY c DESC", [pid]):
        print("  " + str(r["state"]).ljust(16) + str(r["c"]).rjust(5))

    line("10. HUMAN REVIEW REQUIRED (spec 40, 41)")
    for r in db.q("SELECT kind,title,affected_count,cluster_key,priority "
                  "FROM reviews WHERE project_id=? AND status='open'", [pid]):
        print("  [" + str(r["kind"]) + "] " + str(r["title"])[:60])
        print("      covers " + str(r["affected_count"]) +
              " record(s)   cluster=" + str(r["cluster_key"]))

    line("11. PROPOSED CHANGES (spec 46, 47)")
    for p in db.q("SELECT * FROM proposals WHERE project_id=?", [pid]):
        print("  uid " + str(p["target_uid"]) + " " + str(p["field"]) + ": " +
              str(p["current_value"]) + " -> " + str(p["proposed_value"]))
        print("      validation=" + str(p["validation_state"]) +
              " dryrun=" + str(p["dryrun_state"]) +
              " tasksMoved=" + str(p["impact_tasks_moved"]) +
              " finish " + str(p["impact_finish_before"]) + " -> " +
              str(p["impact_finish_after"]) +
              " criticalChanged=" + str(p["impact_critical_change"]))

    line("12. ISSUES / RISKS (spec 30-32)")
    for i in db.q("SELECT title,severity,provenance FROM issues WHERE project_id=? "
                  "LIMIT 8", [pid]):
        print("  ISSUE [" + str(i["severity"]) + "] " + str(i["title"])[:66] +
              "  <" + str(i["provenance"]) + ">")
    for r in db.q("SELECT title,rating,provenance FROM risks WHERE project_id=? "
                  "LIMIT 8", [pid]):
        print("  RISK  [" + str(r["rating"]) + "] " + str(r["title"])[:66] +
              "  <" + str(r["provenance"]) + ">")

    line("13. SECURITY (spec 56)")
    for f in db.q("SELECT filename, security_state, security_notes FROM files "
                  "WHERE project_id=? AND security_state!='clean'", [pid]):
        print("  " + str(f["filename"]) + " -> " + str(f["security_state"]))
        print("      " + str(f["security_notes"])[:150])

    line("SUMMARY")
    art = db.q1("SELECT description FROM artifacts WHERE project_id=? "
                "AND kind='summary' ORDER BY created_at DESC LIMIT 1", [pid])
    if art:
        print(str(art["description"])[:1400])
    print("\nproject_id =", pid)


if __name__ == "__main__":
    main()
