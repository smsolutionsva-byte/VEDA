"""Dev-only: seed synthetic job/activity/answer rows to preview the Execution
Intelligence and Ask VEDA UI without invoking the real agent pipeline.

Never enqueues a job (no jobs.enqueue call), so the background worker never
picks these rows up - they just sit there as realistic-looking persisted
state for the frontend to render. Safe to run against the live dev server's
sqlite file (WAL mode tolerates the extra writer).
"""
import sys
import time

sys.path.insert(0, ".")
from veda import db, config

config.ensure_dirs()
db.init_db()

PID = sys.argv[1] if len(sys.argv) > 1 else None
if not PID:
    row = db.q1("SELECT id FROM projects ORDER BY created_at DESC LIMIT 1")
    PID = row["id"] if row else None
if not PID:
    print("No project found. Create one first.")
    sys.exit(1)

now = time.time()


def mkjob(kind, status, phase, started_offset, finished_offset=None, error=None):
    jid = db.insert("jobs", {
        "project_id": PID, "kind": kind, "status": status, "phase": phase,
        "progress": 1.0 if status == "done" else 0.4,
        "provider": "claude_code",
        "started_at": now - started_offset,
        "finished_at": (now - finished_offset) if finished_offset is not None else None,
        "attempts": 1, "error": error,
        "result_json": db.jdumps({"input": {}}),
    })
    return jid


def step(jid, name, label, state, detail, off):
    db.insert("agent_activity", {
        "project_id": PID, "job_id": jid, "step": name, "label": label,
        "state": state, "detail": detail, "created_at": now - off,
    })


def call(jid, server, tool, state, summary, dur, off, error=None):
    db.insert("mcp_calls", {
        "project_id": PID, "job_id": jid, "server": server, "tool": tool,
        "state": state, "error": error, "duration_ms": dur, "summary": summary,
        "created_at": now - off,
    })


# ---- 1. A LIVE analysis run (Execution Intelligence "Thinking" panel: live) ----
live_job = mkjob("analysis", "running", "resolver_ranking", started_offset=14)
seq = [
    ("files_received", "Files received", "success", None, 13.6),
    ("mcp_health", "Horizun session confirmed healthy", "success", None, 13.1),
    ("schedule_parsed", "Parsed XER schedule snapshot", "success", None, 12.4),
    ("evidence_processed", "Extracted 41 field-evidence rows from 6 documents",
     "success", None, 10.9),
    ("agent_invoked", "Trying Claude Code", "success", None, 9.7),
    ("tool_call", "list_activities", "success", None, 8.8),
    ("tool_call", "get_critical_path", "success", None, 7.6),
    ("output_ready", "Structured output accepted", "success", None, 6.2),
    ("resolver_indexing", "Building semantic candidate floor", "success", None, 5.1),
    ("resolver_experts", "Engineering · Tree · Rescheduler v2 candidates merged",
     "success", None, 3.4),
    ("resolver_ranking", "Ranking candidates with LambdaMART MetaRank",
     "success", None, 1.2),
]
for name, label, state, detail, off in seq:
    step(live_job, name, label, state, detail, off)
call(live_job, "horizun", "list_activities", "success",
     "212 activities returned", 340, 8.7)
call(live_job, "horizun", "get_critical_path", "success",
     "38 critical activities", 510, 7.5)
call(live_job, "horizun", "get_relationships", "success",
     "476 relationships", 290, 4.0)

# ---- 2. A pending "question" job (Ask VEDA: live thinking bubble) ----
q_job = mkjob("question", "running", "agent_invoked", started_offset=6)
db.update("jobs", q_job, {"result_json": db.jdumps(
    {"input": {"question": "Why is the hydrotest package trending late against baseline?"}})})
step(q_job, "question_received", "Question received", "success", None, 5.7)
step(q_job, "agent_invoked", "Trying Claude Code", "success", None, 4.9)
step(q_job, "tool_call", "get_activity_detail", "success", None, 3.2)
call(q_job, "horizun", "get_activity_detail", "success",
     "Activity A-2140 · Hydrotest Package B", 210, 3.1)

# ---- 3. A finished "question" job + its answer artifact (Ask VEDA: done bubble) ----
done_q_job = mkjob("question", "done", "output_ready", started_offset=210, finished_offset=192)
step(done_q_job, "question_received", "Question received", "success", None, 209.5)
step(done_q_job, "agent_invoked", "Trying Claude Code", "success", None, 208.0)
step(done_q_job, "tool_call", "get_critical_path", "success", None, 202.0)
step(done_q_job, "tool_call", "list_evidence", "success", None, 197.0)
step(done_q_job, "output_ready", "Answer ready", "success", None, 192.4)
call(done_q_job, "horizun", "get_critical_path", "success", "38 critical activities", 480, 201.5)
call(done_q_job, "horizun", "list_evidence", "success", "6 supporting records", 260, 196.5)
db.insert("artifacts", {
    "project_id": PID, "job_id": done_q_job, "kind": "answer", "format": "markdown",
    "title": "Why is piling behind schedule on the north abutment?",
    "description": (
        "Piling on the north abutment (WBS 2.3.1) is 6 working days behind the "
        "current forecast. Two linked factors: (1) three field DPRs between "
        "2026-08-11 and 2026-08-14 report a stalled concrete batching plant, "
        "corroborated by the site chat export; (2) the driving predecessor "
        "'Access road compaction' finished 4 days late per its actual finish "
        "date in the schedule. No open risk record currently links these two "
        "causes together - consider raising one."),
    "provenance": "AI_INFERENCE", "created_at": now - 190,
})

# ---- 4. A FAILED historical run (Execution Intelligence: failed state, if desired later) ----
# left out by default; uncomment to test the failed banner:
# fail_job = mkjob("analysis", "failed", "agent_failed", started_offset=900, finished_offset=860,
#                   error="ProviderError: Claude Code: rate limited")
# step(fail_job, "agent_failed", "Claude Code failed; trying next provider", "failed",
#      "ProviderError: rate limited", 861)

print("Seeded project", PID)
print("live analysis job:", live_job)
print("pending question job:", q_job)
print("done question job:", done_q_job)
