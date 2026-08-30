"""Job orchestration: events wake the agent, VEDA keeps the state (spec 5-7).

A single worker thread runs jobs in order. That keeps SQLite writes and the
Horizun session simple to reason about, and a construction project does not
need more concurrency than this. Failure never loses work: files, project,
reviews and previous results all survive, and the job can be retried (spec 57).
"""
from __future__ import annotations

import asyncio
import queue
import shutil
import threading
import traceback
from typing import Any

from . import audit, config, db, events, reviews
from .agent import registry, schemas
from .agent.prompts import SYSTEM, analysis_prompt, question_prompt, resume_prompt
from .mcpc import McpError, horizun, schedule_ops
from .pipeline import deterministic, extract, linking, proposals

_queue: "queue.Queue[str]" = queue.Queue()
_priority_queue: "queue.Queue[str]" = queue.Queue()
_worker: threading.Thread | None = None
_started = False
_state_lock = threading.RLock()
_cancelled: dict[str, str] = {}
_active_project_id: str | None = None
_current: dict = {"job_id": None, "project_id": None,
                  "provider": None, "session": None}


class JobCancelled(RuntimeError):
    """Raised inside the worker when the operator switches/deletes a project."""


# ----------------------------------------------------------------- job records
def create_job(project_id: str, kind: str, trigger_event_id: str | None = None,
               payload: dict | None = None) -> str:
    jid = db.insert("jobs", {
        "project_id": project_id, "kind": kind, "status": "queued",
        "phase": "queued", "progress": 0.0,
        "trigger_event_id": trigger_event_id,
        "provider": registry.active_provider_name(),
        "result_json": db.jdumps({"input": payload or {}}),
    })
    audit.record(project_id, actor="system", actor_type="system",
                 action="job_created", job_id=jid, entity_type="job",
                 entity_id=jid, new_value=kind, result="queued")
    events.notify_ui(project_id, "jobs_changed", {"job_id": jid})
    return jid


def step(job_id: str, project_id: str, name: str, label: str,
         state: str = "success", detail: str | None = None) -> None:
    """Safe, high-level agent progress (spec 50). No chain-of-thought."""
    if _is_cancelled(job_id):
        return
    db.insert("agent_activity", {
        "project_id": project_id, "job_id": job_id, "step": name,
        "label": label, "state": state, "detail": detail,
    })
    db.update("jobs", job_id, {"phase": name})
    events.notify_ui(project_id, "activity", {"job_id": job_id, "step": name,
                                              "label": label, "state": state})


def _finish(job_id: str, project_id: str, status: str, error: str | None = None,
            result: dict | None = None) -> None:
    current = db.q1("SELECT status FROM jobs WHERE id=?", [job_id])
    if not current or current.get("status") == "cancelled":
        return
    patch: dict = {"status": status, "finished_at": db.now(), "progress": 1.0}
    if error:
        patch["error"] = error[:4000]
    if result is not None:
        patch["result_json"] = db.jdumps(result)
    db.update("jobs", job_id, patch)
    audit.record(project_id, actor="system", actor_type="system",
                 action="job_" + status, job_id=job_id, entity_type="job",
                 entity_id=job_id, result=error or status)
    events.notify_ui(project_id, "jobs_changed", {"job_id": job_id,
                                                  "status": status})


# --------------------------------------------------------------- event wiring
def _merge_analysis_payload(existing: dict, incoming: dict, event_id: str | None) -> dict:
    out = dict(existing or {})
    # Analysis reads durable project state, so payload is mainly provenance and
    # schedule selection. Preserve the newest explicit schedule/file metadata.
    for k, v in (incoming or {}).items():
        if v not in (None, "", [], {}):
            out[k] = v
    evs = list(out.get("coalesced_event_ids") or [])
    if event_id and event_id not in evs:
        evs.append(event_id)
    out["coalesced_event_ids"] = evs[-100:]
    return out


def _ensure_analysis_job(project_id: str, event_id: str | None, payload: dict) -> str:
    """At most one running analysis plus one coalesced follow-up per project."""
    if event_id:
        existing = db.q1("SELECT id FROM jobs WHERE trigger_event_id=? LIMIT 1", [event_id])
        if existing:
            return existing["id"]
    running = db.q1("SELECT id FROM jobs WHERE project_id=? AND kind='analysis' "
                    "AND status='running' ORDER BY created_at DESC LIMIT 1", [project_id])
    queued = db.q1("SELECT * FROM jobs WHERE project_id=? AND kind='analysis' "
                   "AND status='queued' ORDER BY created_at DESC LIMIT 1", [project_id])
    if queued:
        stored = (db.jloads(queued.get("result_json"), {}) or {}).get("input", {})
        merged = _merge_analysis_payload(stored, payload, event_id)
        db.update("jobs", queued["id"], {"result_json": db.jdumps({"input": merged})})
        events.notify_ui(project_id, "project_state_changed", {"state": "updating"})
        return queued["id"]
    # No queued job: create one. If another analysis is running this becomes the
    # single follow-up; otherwise it is the active work waiting for the worker.
    merged = _merge_analysis_payload({}, payload, event_id)
    jid = create_job(project_id, "analysis", event_id, merged)
    enqueue(jid)
    return jid

def ensure_event_job(ev: dict) -> str | None:
    """Create exactly one durable job for a wake event.

    API endpoints call this after emitting critical ingestion events as a
    fail-safe.  The normal event handler calls the same function, so the
    workflow remains event-driven but cannot silently lose analysis if an
    in-process handler was not registered or raised unexpectedly.
    """
    etype = ev.get("type")
    project_id = ev.get("project_id")
    if not project_id or etype not in events.WAKE_EVENTS:
        return None
    payload = ev.get("payload") or {}
    event_id = ev.get("id")

    with _state_lock:
        if event_id:
            existing = db.q1(
                "SELECT id FROM jobs WHERE trigger_event_id=? ORDER BY created_at DESC LIMIT 1",
                [event_id])
            if existing:
                return existing["id"]

        if etype in (events.DATASET_UPLOADED, events.FILES_ADDED,
                     events.ANALYSIS_REQUESTED, events.REPROCESS_REQUESTED):
            return _ensure_analysis_job(project_id, event_id, payload)
        if etype in (events.REVIEW_ANSWERED, events.REVIEW_APPROVED,
                     events.REVIEW_REJECTED):
            if not payload.get("requires_job"):
                return None
            kind = "resume_review"
        elif etype == events.USER_QUESTION:
            kind = "question"
        elif etype == events.SCHEDULE_CHANGED:
            kind = "resnapshot"
        else:
            return None

        jid = create_job(project_id, kind, event_id, payload)
        # A question is short and interactive - a person (web app or VEDA
        # Anywhere) is waiting on it, so it jumps ahead of long analysis runs.
        enqueue(jid, priority=(kind == "question"))
        return jid


def handle_event(ev: dict) -> None:
    """Wake the platform on a backend event. Never polls (spec 5)."""
    ensure_event_job(ev)


def enqueue(job_id: str, *, priority: bool = False) -> None:
    if not priority:
        row = db.q1("SELECT project_id FROM jobs WHERE id=?", [job_id])
        with _state_lock:
            priority = bool(row and _active_project_id == row.get("project_id"))
    (_priority_queue if priority else _queue).put(job_id)


def _is_cancelled(job_id: str) -> bool:
    with _state_lock:
        if job_id in _cancelled:
            return True
    row = db.q1("SELECT status FROM jobs WHERE id=?", [job_id])
    return bool(row and row.get("status") == "cancelled")


def _raise_if_cancelled(job_id: str) -> None:
    with _state_lock:
        reason = _cancelled.get(job_id)
    row = db.q1("SELECT status FROM jobs WHERE id=?", [job_id])
    if reason is not None or (row and row.get("status") == "cancelled"):
        reason = reason or str((row or {}).get("error") or "cancelled")
        # Re-assert the terminal state in case cancellation raced with the
        # queued -> running transition in the worker thread.
        if row and row.get("status") != "cancelled":
            db.update("jobs", job_id, {"status": "cancelled",
                                       "phase": "cancelled",
                                       "finished_at": db.now(),
                                       "error": reason})
        raise JobCancelled(reason)


def cancel_job(job_id: str, reason: str = "Cancelled by operator") -> bool:
    """Cancel queued/running work and interrupt the active provider/MCP process."""
    job = db.q1("SELECT * FROM jobs WHERE id=?", [job_id])
    if not job or job.get("status") not in ("queued", "running"):
        return False

    with _state_lock:
        _cancelled[job_id] = reason
        is_current = _current.get("job_id") == job_id
        provider = _current.get("provider") if is_current else None
        session = _current.get("session") if is_current else None

    db.update("jobs", job_id, {
        "status": "cancelled", "phase": "cancelled",
        "finished_at": db.now(), "error": reason,
    })
    db.ex("UPDATE agent_inbox SET status='cancelled', finished_at=? "
          "WHERE job_id=? AND status IN ('pending','claimed')",
          [db.now(), job_id])
    events.notify_ui(job["project_id"], "jobs_changed",
                     {"job_id": job_id, "status": "cancelled"})

    if is_current:
        # Provider CLIs expose cancel() and kill their child process. Horizun is
        # also a child process; closing it makes an in-flight MCP RPC fail fast.
        if provider is not None and session is not None:
            try:
                _await(provider.cancel(session))
            except Exception:
                pass
        try:
            horizun.close()
        except Exception:
            pass
    return True


def activate_project(project_id: str) -> dict:
    """Make one project current: old work is cancelled, never left ahead of it."""
    global _active_project_id
    with _state_lock:
        _active_project_id = project_id
    cancelled = []
    others = db.q("SELECT id FROM jobs WHERE project_id<>? "
                  "AND status IN ('queued','running') ORDER BY created_at",
                  [project_id])
    for row in others:
        if cancel_job(row["id"], "Stopped because the current project changed"):
            cancelled.append(row["id"])

    # Existing queued work for the newly selected project jumps ahead of stale
    # queue entries. Duplicate queue ids are harmless because _run re-reads state.
    promoted = db.q("SELECT id FROM jobs WHERE project_id=? AND status='queued' "
                    "ORDER BY created_at", [project_id])
    for row in promoted:
        enqueue(row["id"], priority=True)
    return {"project_id": project_id, "cancelled": cancelled,
            "promoted": [r["id"] for r in promoted]}


def _purge_project(project_id: str) -> None:
    """Remove durable project rows plus its on-disk project workspace."""
    for f in db.q("SELECT stored_path FROM files WHERE project_id=? AND kind='schedule'",
                  [project_id]):
        try:
            schedule_ops.close_schedule(f["stored_path"], "readonly")
        except Exception:
            pass
    # These operational tables intentionally have no FK so audit history can
    # survive normal data changes. Explicit project deletion should remove it.
    db.ex("DELETE FROM agent_outbox WHERE project_id=?", [project_id])
    db.ex("DELETE FROM agent_inbox WHERE project_id=?", [project_id])
    db.ex("DELETE FROM agent_activity WHERE project_id=?", [project_id])
    db.ex("DELETE FROM mcp_calls WHERE project_id=?", [project_id])
    db.ex("DELETE FROM audit WHERE project_id=?", [project_id])
    db.ex("DELETE FROM events WHERE project_id=?", [project_id])
    db.ex("DELETE FROM projects WHERE id=?", [project_id])
    pdir = config.PROJECTS_DIR / project_id
    if pdir.exists():
        shutil.rmtree(pdir, ignore_errors=True)


def delete_project(project_id: str) -> dict:
    """Delete a project safely, deferring physical cleanup if its job is unwinding."""
    global _active_project_id
    p = db.q1("SELECT * FROM projects WHERE id=?", [project_id])
    if not p:
        return {"deleted": project_id, "already_missing": True}
    with _state_lock:
        if _active_project_id == project_id:
            _active_project_id = None

    running = db.q1("SELECT id FROM jobs WHERE project_id=? AND status='running' "
                    "ORDER BY created_at DESC LIMIT 1", [project_id])
    for row in db.q("SELECT id FROM jobs WHERE project_id=? "
                    "AND status IN ('queued','running')", [project_id]):
        cancel_job(row["id"], "Stopped because the project was deleted")

    with _state_lock:
        still_current = _current.get("project_id") == project_id
    if running or still_current:
        # Hide it from the UI immediately. The worker's finally block performs
        # physical cleanup after provider/MCP code has released its references.
        db.update("projects", project_id, {"status": "deleting",
                                           "updated_at": db.now()})
        return {"deleted": project_id, "cleanup_pending": True}

    _purge_project(project_id)
    return {"deleted": project_id, "cleanup_pending": False}


def _finalize_pending_delete(project_id: str | None) -> None:
    if not project_id:
        return
    p = db.q1("SELECT status FROM projects WHERE id=?", [project_id])
    if p and p.get("status") == "deleting":
        _purge_project(project_id)


def _recover_startup_jobs() -> list[str]:
    """Repair durable job state after a server/process restart.

    The in-memory worker queue cannot survive a restart. Any row still marked
    ``running`` is therefore stale at startup, while persisted ``queued`` rows
    need to be put back into the new process queue.
    """
    # Finish any deletion that was interrupted by an application restart.
    for p in db.q("SELECT id FROM projects WHERE status='deleting'"):
        _purge_project(p["id"])

    # Old builds used awaiting_review as a pseudo-running state. Work had
    # already finished; keep the review row and retire the job state.
    db.ex("UPDATE jobs SET status='done', phase='done', finished_at=COALESCE(finished_at, ?) "
          "WHERE status='awaiting_review'", [db.now()])

    stale = db.q("SELECT id, project_id FROM jobs WHERE status='running' "
                 "ORDER BY created_at")
    for job in stale:
        jid = job["id"]
        # Do not leave old local-agent inbox work claimable after its worker is
        # gone; a late IDE response would otherwise be attached to a dead job.
        db.ex("UPDATE agent_inbox SET status='cancelled', finished_at=? "
              "WHERE job_id=? AND status IN ('pending','claimed')",
              [db.now(), jid])
        db.update("jobs", jid, {
            "status": "failed",
            "phase": "interrupted",
            "finished_at": db.now(),
            "error": ("VEDA restarted before this job finished. The stale "
                      "running state was cleared; retry this job if needed."),
        })
        events.notify_ui(job["project_id"], "jobs_changed",
                         {"job_id": jid, "status": "failed"})

    # Retire legacy review-resume queue entries for decisions that now apply
    # synchronously. This prevents old databases from resurfacing the queue UX
    # after an upgrade. Proposal/other resume jobs remain available because they
    # may perform a governed write.
    legacy_resume = db.q("SELECT * FROM jobs WHERE kind='resume_review' AND status='queued' ORDER BY created_at")
    for row in legacy_resume:
        payload = (db.jloads(row.get("result_json"), {}) or {}).get("input", {})
        review = reviews.get(payload.get("review_id")) if payload.get("review_id") else None
        if not review or review.get("kind") not in ("clarification", "security_review", "failed_validation"):
            continue
        try:
            if review.get("kind") == "clarification" and review.get("status") in ("answered", "deferred"):
                effect = linking.apply_cluster_answer(row["project_id"], review)
                reviews.record_effect(review["id"], effect)
            elif review.get("kind") == "security_review" and review.get("status") != "open":
                effect = apply_security_answer_now(row["project_id"], review)
                reviews.record_effect(review["id"], effect)
            elif review.get("kind") == "failed_validation" and review.get("status") != "open":
                if review.get("answer") == "Retry analysis":
                    ev = events.emit(events.ANALYSIS_REQUESTED, row["project_id"],
                                     {"reason": "legacy_review_retry"}, source="migration")
                    ensure_event_job(ev)
                reviews.record_effect(review["id"], {"action": "legacy_review_migrated"})
            db.update("jobs", row["id"], {"status": "done", "phase": "migrated_review_decision",
                                           "finished_at": db.now(),
                                           "error": "Legacy review-resume work migrated to immediate decision state"})
        except Exception as exc:
            db.update("jobs", row["id"], {"status": "failed", "phase": "migration_failed",
                                           "finished_at": db.now(), "error": str(exc)[:1000]})

    # Fold legacy duplicate queued analyses into one follow-up per project.
    for pr in db.q("SELECT DISTINCT project_id FROM jobs WHERE kind='analysis' AND status='queued'"):
        rows = db.q("SELECT * FROM jobs WHERE project_id=? AND kind='analysis' AND status='queued' ORDER BY created_at",
                    [pr["project_id"]])
        if len(rows) <= 1:
            continue
        keep = rows[-1]
        merged = {}
        event_ids = []
        for row in rows:
            inp = (db.jloads(row.get("result_json"), {}) or {}).get("input", {})
            merged = _merge_analysis_payload(merged, inp, row.get("trigger_event_id"))
            if row.get("trigger_event_id"):
                event_ids.append(row["trigger_event_id"])
        db.update("jobs", keep["id"], {"result_json": db.jdumps({"input": merged})})
        for row in rows[:-1]:
            db.update("jobs", row["id"], {"status": "cancelled", "phase": "coalesced",
                                           "finished_at": db.now(),
                                           "error": "Coalesced into " + keep["id"] + " during workflow upgrade"})
    return [r["id"] for r in db.q(
        "SELECT id FROM jobs WHERE status='queued' ORDER BY created_at")]


def start_worker() -> None:
    global _worker, _started
    if _started:
        return
    _started = True
    events.on_event(handle_event)
    pending = _recover_startup_jobs()
    _worker = threading.Thread(target=_loop, daemon=True, name="veda-jobs")
    _worker.start()
    for job_id in pending:
        enqueue(job_id)


def _next_job() -> tuple[str, queue.Queue]:
    while True:
        try:
            return _priority_queue.get_nowait(), _priority_queue
        except queue.Empty:
            try:
                return _queue.get(timeout=0.25), _queue
            except queue.Empty:
                continue


def _loop() -> None:
    while True:
        job_id, source_queue = _next_job()
        project_id = None
        try:
            row = db.q1("SELECT project_id FROM jobs WHERE id=?", [job_id]) or {}
            project_id = row.get("project_id")
            _run(job_id)
        except JobCancelled:
            # cancel_job already persisted the terminal state.
            pass
        except Exception:
            job = db.q1("SELECT * FROM jobs WHERE id=?", [job_id]) or {}
            if job and job.get("status") != "cancelled":
                _finish(job_id, job.get("project_id", ""), "failed",
                        traceback.format_exc()[-3000:])
        finally:
            with _state_lock:
                if _current.get("job_id") == job_id:
                    _current.update({"job_id": None, "project_id": None,
                                     "provider": None, "session": None})
                _cancelled.pop(job_id, None)
            _finalize_pending_delete(project_id)
            source_queue.task_done()


def current_job() -> str | None:
    with _state_lock:
        return _current.get("job_id")


# ------------------------------------------------------------------- the work
def _run(job_id: str) -> None:
    job = db.q1("SELECT * FROM jobs WHERE id=?", [job_id])
    if not job or job.get("status") in ("cancelled", "done"):
        return
    project_id = job["project_id"]
    with _state_lock:
        _current.update({"job_id": job_id, "project_id": project_id,
                         "provider": None, "session": None})
    _raise_if_cancelled(job_id)
    db.update("jobs", job_id, {
        "status": "running", "started_at": db.now(), "error": None,
        "attempts": (job.get("attempts") or 0) + 1,
        "provider": registry.active_provider_name(),
    })
    events.notify_ui(project_id, "jobs_changed", {"job_id": job_id})

    payload = (db.jloads(job.get("result_json"), {}) or {}).get("input", {})
    kind = job["kind"]
    try:
        _raise_if_cancelled(job_id)
        if kind == "analysis":
            result = _run_analysis(job_id, project_id, payload)
        elif kind == "resume_review":
            result = _run_resume(job_id, project_id, payload)
        elif kind == "question":
            result = _run_question(job_id, project_id, payload)
        elif kind == "resnapshot":
            result = _run_resnapshot(job_id, project_id, payload)
        else:
            raise ValueError("unknown job kind: " + kind)
    except JobCancelled:
        return
    except McpError as exc:
        if _is_cancelled(job_id):
            return
        step(job_id, project_id, "mcp_failed", "Horizun call failed", "failed",
             str(exc))
        _finish(job_id, project_id, "failed", "Horizun MCP: " + str(exc))
        return
    except Exception as exc:  # noqa: BLE001
        if _is_cancelled(job_id):
            return
        step(job_id, project_id, "job_failed", type(exc).__name__, "failed",
             str(exc)[:500])
        _finish(job_id, project_id, "failed",
                type(exc).__name__ + ": " + str(exc) + "\n" +
                traceback.format_exc()[-2000:])
        return

    _raise_if_cancelled(job_id)
    # Human attention is project decision state, never a worker-job status.
    _finish(job_id, project_id, "done", None, result)
    events.notify_ui(project_id, "refresh", {"job_id": job_id})


# ------------------------------------------------------------------ analysis
def _run_analysis(job_id: str, project_id: str, payload: dict) -> dict:
    _raise_if_cancelled(job_id)
    project = db.q1("SELECT * FROM projects WHERE id=?", [project_id]) or {}
    step(job_id, project_id, "files_received", "Files received")

    # ---- 1. Horizun capability matrix (spec 8) --------------------------
    try:
        health = horizun.health(project_id=project_id, job_id=job_id)
        caps = health.get("capabilities", {})
        step(job_id, project_id, "mcp_health",
             "Horizun ready on the " + str(health.get("backend")) + " backend",
             "success",
             ", ".join(k for k, v in caps.items() if v))
    except McpError as exc:
        step(job_id, project_id, "mcp_health", "Horizun unavailable", "failed",
             str(exc))
        raise

    _raise_if_cancelled(job_id)
    # ---- 2. schedule snapshot (spec 15) ---------------------------------
    # Incremental v0.1.2 rule: evidence-only batches reuse the current MCP
    # snapshot. Re-reading a 5k-task MPP because someone pasted one WhatsApp
    # update is expensive and also creates fake schedule revisions.
    selected_sched_id = payload.get("schedule_file_id") or project.get("schedule_file_id")
    latest_sched = None
    if selected_sched_id:
        latest_sched = db.q1("SELECT * FROM files WHERE project_id=? AND id=? AND kind='schedule'",
                             [project_id, selected_sched_id])
    if not latest_sched:
        all_scheds = db.q("SELECT * FROM files WHERE project_id=? AND kind='schedule' ORDER BY created_at DESC, id DESC",
                          [project_id])
        if len(all_scheds) == 1:
            latest_sched = all_scheds[0]
    current_snap = db.q1("SELECT * FROM schedule_snapshots WHERE project_id=? "
                         "AND is_current=1 ORDER BY created_at DESC LIMIT 1",
                         [project_id])
    incoming_ids = payload.get("file_ids") or []
    incoming_schedules: list[dict] = []
    if incoming_ids:
        marks = ",".join("?" for _ in incoming_ids)
        incoming_schedules = db.q(
            "SELECT * FROM files WHERE project_id=? AND kind='schedule' "
            "AND id IN (" + marks + ") ORDER BY created_at ASC, id ASC",
            [project_id, *incoming_ids])
        requested_schedule = payload.get("schedule_file_id")
        if requested_schedule:
            incoming_schedules = [f for f in incoming_schedules if f.get("id") == requested_schedule]
        elif len(incoming_schedules) > 1:
            # A mixed project folder can contain baseline/current/recovery/extended
            # revisions. Never silently process all of them in filename/upload order.
            chosen = project.get("schedule_file_id")
            incoming_schedules = [f for f in incoming_schedules if f.get("id") == chosen] if chosen else []

    snap_summary: dict = {}
    if incoming_schedules:
        # A single ingestion batch may intentionally contain a baseline/current
        # pair or several successive schedule exports. Preserve that history by
        # harvesting them in upload order; each one becomes a durable revision.
        for idx, sched in enumerate(incoming_schedules, start=1):
            label = "Schedule revision detected: " + str(sched["filename"])
            if len(incoming_schedules) > 1:
                label += " (" + str(idx) + "/" + str(len(incoming_schedules)) + ")"
            step(job_id, project_id, "schedule_detected", label)
            db.update("projects", project_id, {"schedule_file_id": sched["id"],
                                               "updated_at": db.now()})
            snap_summary = schedule_ops.collect_snapshot(
                project_id, sched["stored_path"], job_id=job_id, file_id=sched["id"],
                progress=lambda n, l, s: step(job_id, project_id, n, l, s))
            db.update("files", sched["id"], {"extract_state": "done",
                                              "extract_error": None})
    elif current_snap:
        snap_summary = {"snapshot_id": current_snap.get("id"),
                        "revision": current_snap.get("revision"),
                        "reused": True}
        step(job_id, project_id, "schedule_reused",
             "Existing schedule snapshot reused; processing new evidence only")
    elif latest_sched:
        # Compatibility/recovery path for an old project whose schedule upload
        # exists but whose snapshot was never successfully harvested.
        step(job_id, project_id, "schedule_detected",
             "Recovering schedule snapshot: " + str(latest_sched["filename"]))
        db.update("projects", project_id, {"schedule_file_id": latest_sched["id"],
                                           "updated_at": db.now()})
        snap_summary = schedule_ops.collect_snapshot(
            project_id, proposals.current_schedule_path(project_id) or
            latest_sched["stored_path"], job_id=job_id, file_id=latest_sched["id"],
            progress=lambda n, l, s: step(job_id, project_id, n, l, s))
        db.update("files", latest_sched["id"], {"extract_state": "done",
                                                "extract_error": None})
    else:
        candidate_count = (db.q1("SELECT COUNT(*) c FROM files WHERE project_id=? AND kind='schedule'", [project_id]) or {}).get("c", 0)
        if candidate_count and int(candidate_count) > 1 and not project.get("schedule_file_id"):
            step(job_id, project_id, "schedule_detected",
                 "Multiple schedule candidates detected; authoritative schedule selection required", "failed")
        else:
            step(job_id, project_id, "schedule_detected",
                 "No schedule file uploaded yet", "failed")

    # ---- 3. evidence extraction (spec 33, 34) ---------------------------
    ev_files = db.q("SELECT * FROM files WHERE project_id=? AND kind='evidence' "
                    "AND extract_state IN ('pending','failed')", [project_id])
    total_ev = 0
    for f in ev_files:
        _raise_if_cancelled(job_id)
        if f.get("security_state") == "quarantined":
            db.update("files", f["id"], {"extract_state": "skipped",
                                         "extract_error": "quarantined"})
            step(job_id, project_id, "evidence_quarantined",
                 "Withheld " + str(f["filename"]) + " - content tries to instruct "
                 "the system", "failed")
            continue
        try:
            rows = extract.extract_evidence(project_id, f, job_id)
            db.ex("DELETE FROM evidence WHERE file_id=?", [f["id"]])
            for r in rows:
                db.insert("evidence", extract.enrich_evidence_record(r))
            db.update("files", f["id"], {"extract_state": "done",
                                         "extract_error": None})
            total_ev += len(rows)
        except Exception as exc:  # noqa: BLE001
            db.update("files", f["id"], {"extract_state": "failed",
                                         "extract_error": str(exc)[:500]})
    if ev_files:
        step(job_id, project_id, "evidence_processed",
             str(total_ev) + " evidence records extracted from " +
             str(len(ev_files)) + " document(s)")
    else:
        ready_ev = int((db.q1(
            "SELECT COUNT(*) c FROM evidence WHERE project_id=?", [project_id])
            or {}).get("c", 0))
        step(job_id, project_id, "evidence_reused",
             str(ready_ev) + " existing evidence record(s) ready for reasoning")

    _raise_if_cancelled(job_id)
    # ---- 4. reasoning (spec 7 - VEDA invokes the agent itself) ----------
    files = db.q("SELECT id, filename, kind, size_bytes, security_state, "
                 "source_mode, batch_id FROM files WHERE project_id=?", [project_id])
    ev_sample = db.q("SELECT id, date, discipline, crew, location, chainage, "
                     "description FROM evidence WHERE project_id=? "
                     "ORDER BY date DESC LIMIT 40", [project_id])
    snap = db.q1("SELECT * FROM schedule_snapshots WHERE project_id=? "
                 "AND is_current=1 ORDER BY created_at DESC LIMIT 1", [project_id])
    answers = db.q("SELECT title, answer FROM reviews WHERE project_id=? "
                   "AND status IN ('answered','approved') ORDER BY answered_at DESC "
                   "LIMIT 20", [project_id])
    field_context = {
        "record_count": int((db.q1("SELECT COUNT(*) c FROM evidence WHERE project_id=?", [project_id]) or {}).get("c", 0)),
        "source_file_count": int((db.q1("SELECT COUNT(DISTINCT file_id) c FROM evidence WHERE project_id=? AND file_id IS NOT NULL", [project_id]) or {}).get("c", 0)),
        "latest_date": (db.q1("SELECT MAX(date) d FROM evidence WHERE project_id=? AND date IS NOT NULL AND TRIM(date)!=''", [project_id]) or {}).get("d"),
        "reported_progress_record_count": int((db.q1("SELECT COUNT(*) c FROM evidence WHERE project_id=? AND observed_progress IS NOT NULL", [project_id]) or {}).get("c", 0)),
        "validated_link_record_count": int((db.q1("SELECT COUNT(DISTINCT e.id) c FROM evidence e JOIN evidence_links l ON l.evidence_id=e.id WHERE e.project_id=? AND l.project_id=? AND l.is_candidate=0 AND l.relation='supporting' AND e.state IN ('linked','confirmed')", [project_id, project_id]) or {}).get("c", 0)),
        "validated_activity_count": int((db.q1("SELECT COUNT(DISTINCT l.activity_uid) c FROM evidence e JOIN evidence_links l ON l.evidence_id=e.id WHERE e.project_id=? AND l.project_id=? AND l.is_candidate=0 AND l.relation='supporting' AND e.state IN ('linked','confirmed') AND l.activity_uid IS NOT NULL", [project_id, project_id]) or {}).get("c", 0)),
        "numeric_observed_activity_count": int((db.q1("SELECT COUNT(*) c FROM observed_progress WHERE project_id=? AND observed_percent IS NOT NULL", [project_id]) or {}).get("c", 0)),
        "unresolved_record_count": int((db.q1("SELECT COUNT(*) c FROM evidence WHERE project_id=? AND state IN ('needs_review','conflicting','new','processing')", [project_id]) or {}).get("c", 0)),
    }
    prompt = analysis_prompt(project, snap, files, ev_sample,
                             reviews.open_for(project_id), answers,
                             field_context=field_context)

    result, used = _invoke_agent(job_id, project_id, prompt)

    _raise_if_cancelled(job_id)
    # ---- 5. persist, validate, link (spec 35, 43, 45) -------------------
    applied = apply_result(project_id, job_id, result, source=used)
    return {"snapshot": snap_summary, "evidence_extracted": total_ev,
            "provider": used, **applied}


def _invoke_agent(job_id: str, project_id: str, prompt: str,
                  resume_external: str | None = None) -> tuple:
    """Run reasoning with runtime fallback: Antigravity -> Claude -> Codex.

    In auto mode, an unavailable, unauthenticated, timed-out, or otherwise
    failed provider never owns the global worker indefinitely. VEDA records the
    failure, moves to the next provider, and only uses deterministic analysis
    after the whole chain is exhausted.
    """
    candidates = registry.candidate_names()
    failures: list[str] = []
    rejected_outputs: list[str] = []

    sess_row = None
    if resume_external:
        sess_row = db.q1("SELECT * FROM agent_sessions WHERE id=?",
                         [resume_external])
        # When continuing a prior conversation in auto mode, give its original
        # provider the first chance to preserve context, then return to the
        # normal fallback order without duplicates.
        if sess_row and registry.active_provider_name() == "auto":
            prior = sess_row.get("provider")
            if prior == "antigravity":
                prior = "gemini_api"
            if prior in registry.PROVIDERS:
                candidates = [prior] + [n for n in candidates if n != prior]

    for attempt_no, provider_name in enumerate(candidates, 1):
        _raise_if_cancelled(job_id)
        label = registry.LABELS.get(provider_name, provider_name)
        try:
            provider = registry.get_provider(provider_name)
        except Exception as exc:  # noqa: BLE001
            failures.append(label + ": " + str(exc))
            continue

        step(job_id, project_id, "agent_invoked",
             "Trying " + label + (" (fallback)" if attempt_no > 1 else ""))

        try:
            health = _await(provider.health())
        except Exception as exc:  # noqa: BLE001
            health = {"ok": False, "error": str(exc)}
        if not health.get("ok"):
            reason = str(health.get("error") or "unavailable")[:400]
            step(job_id, project_id, "agent_unavailable",
                 label + " unavailable; trying next provider", "failed", reason)
            failures.append(label + ": " + reason)
            continue

        resume_session = None
        if sess_row and sess_row.get("provider") in (provider_name,
                                                      "antigravity" if provider_name == "gemini_api" else ""):
            from .agent.base import AgentSession
            resume_session = AgentSession(
                session_id=sess_row["id"], external_id=sess_row.get("external_id"),
                provider=provider_name, model=sess_row.get("model"),
                meta={"project_id": project_id, "job_id": job_id})

        def on_event(ev) -> None:
            _raise_if_cancelled(job_id)
            if ev.kind == "tool_call":
                step(job_id, project_id, "tool_call", ev.label, "success")
            elif ev.kind == "error":
                step(job_id, project_id, "agent_error", ev.label[:200], "failed")
            elif ev.kind == "status":
                step(job_id, project_id, ev.step or "agent_status", ev.label)

        def on_session(session) -> None:
            should_cancel = False
            with _state_lock:
                if _current.get("job_id") == job_id:
                    _current["provider"] = provider
                    _current["session"] = session
                should_cancel = job_id in _cancelled
            if should_cancel:
                try:
                    _await(provider.cancel(session))
                except Exception:
                    pass

        try:
            run = _await(provider.run(
                project_id=project_id, job_id=job_id, prompt=prompt, system=SYSTEM,
                schema=schemas.json_schema(), workspace=str(config.DATA_DIR),
                resume=resume_session, on_event=on_event, on_session=on_session))
            _raise_if_cancelled(job_id)
        except Exception as exc:  # noqa: BLE001
            reason = type(exc).__name__ + ": " + str(exc)
            step(job_id, project_id, "agent_failed",
                 label + " failed; trying next provider", "failed", reason[:500])
            failures.append(label + ": " + reason[:500])
            continue

        # Persist each attempted session for auditability. If this was a true
        # resume on the same provider, update that row instead of forking it.
        sid = run.external_id or db.new_id("sess_")
        if sess_row and resume_session is not None:
            db.update("agent_sessions", sess_row["id"], {
                "turns": (sess_row.get("turns") or 0) + run.turns,
                "cost_usd": (sess_row.get("cost_usd") or 0) + run.cost_usd,
                "updated_at": db.now(),
                "external_id": run.external_id or sess_row.get("external_id")})
            session_id = sess_row["id"]
        else:
            session_id = db.insert("agent_sessions", {
                "project_id": project_id, "job_id": job_id,
                "provider": provider_name, "external_id": sid,
                "model": getattr(provider, "model", None),
                "turns": run.turns, "cost_usd": run.cost_usd,
                "status": "active" if run.ok else "failed", "updated_at": db.now()})
        db.update("jobs", job_id, {"agent_session_id": session_id})

        if not run.ok or (not run.text and run.structured is None):
            reason = str(run.error or "provider produced no result")[:500]
            step(job_id, project_id, "agent_failed",
                 label + " produced no usable result; trying next provider",
                 "failed", reason)
            failures.append(label + ": " + reason)
            continue

        outcome = schemas.parse_agent_result(run.structured or run.text)
        if not outcome.ok:
            reason = str(outcome.error)[:500]
            step(job_id, project_id, "structured_output_rejected",
                 label + " output did not validate; trying next provider",
                 "failed", reason)
            db.insert("artifacts", {
                "project_id": project_id, "job_id": job_id,
                "kind": "rejected_output", "title": "Rejected " + label + " output",
                "format": "text", "description": reason[:2000],
                "provenance": "AI_INFERENCE"})
            rejected_outputs.append(label + ": " + reason)
            continue

        if outcome.dropped:
            step(job_id, project_id, "structured_output_partial",
                 str(outcome.dropped) + " malformed row(s) dropped from " + label,
                 "failed", "; ".join(outcome.drop_reasons)[:1000])
        step(job_id, project_id, "provider_selected", "Using " + label)
        step(job_id, project_id, "output_ready", "Structured result received")
        db.update("jobs", job_id, {"provider": provider_name})
        return outcome.result, provider_name

    # Nothing in the preferred chain worked. A malformed result is worth a
    # review card, but only after we have actually tried every configured CLI.
    if rejected_outputs:
        reviews.create(
            project_id=project_id, kind="failed_validation", job_id=job_id,
            title="Reasoning providers returned unreadable output",
            question=("VEDA tried the configured provider chain, but the returned "
                      "structured output did not validate. Retry analysis, or "
                      "continue with deterministic results?"),
            detail=" | ".join(rejected_outputs)[:1600],
            options=["Retry analysis", "Continue without it"], priority="high")

    if not config.ALLOW_DETERMINISTIC_FALLBACK:
        raise RuntimeError("all reasoning providers unavailable: " +
                           " | ".join(failures + rejected_outputs))
    step(job_id, project_id, "fallback_analysis",
         "Antigravity, Claude Code and Codex unavailable; using VEDA rules",
         "failed", " | ".join(failures + rejected_outputs)[:1200])
    db.update("jobs", job_id, {"provider": "deterministic"})
    return deterministic.analyse(project_id), "deterministic"

def _await(coro):
    """Run a coroutine from the worker thread."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        try:
            loop.close()
        except Exception:
            pass


# ----------------------------------------------------- persisting the result
def apply_result(project_id: str, job_id: str, result: schemas.AgentResult,
                 source: str = "agent") -> dict:
    """Persist a validated agent result and run the deterministic gates."""
    _raise_if_cancelled(job_id)
    actor_type = "agent" if source != "deterministic" else "system"
    prov_default = "AI_INFERENCE" if source != "deterministic" \
        else "DETERMINISTIC_CALCULATION"

    ref_to_id: dict = {}
    for e in result.evidence:
        existing = db.q1("SELECT id FROM evidence WHERE project_id=? AND id=?",
                         [project_id, e.ref])
        if existing:
            ref_to_id[e.ref] = e.ref
            patch = {}
            if e.observed_progress is not None:
                patch["observed_progress"] = e.observed_progress
            if e.discipline:
                patch["discipline"] = e.discipline
            if e.chainage:
                patch["chainage"] = e.chainage
            if patch:
                db.update("evidence", e.ref, patch)
            continue
        new_id = db.insert("evidence", extract.enrich_evidence_record({
            "project_id": project_id, "job_id": job_id,
            "source_file": e.source_file, "locator": e.locator, "date": e.date,
            "author": e.author, "contractor": e.contractor, "crew": e.crew,
            "discipline": e.discipline, "location": e.location,
            "chainage": e.chainage, "quantity": e.quantity, "unit": e.unit,
            "description": e.description,
            "observed_progress": e.observed_progress,
            "confidence": e.confidence, "state": "new",
            "provenance": e.provenance}))
        ref_to_id[e.ref] = new_id

    # Candidate links from the model, keyed by the evidence row they cite.
    agent_links: dict = {}
    for l in result.evidence_links:
        eid = ref_to_id.get(l.evidence_ref, l.evidence_ref)
        if not db.q1("SELECT id FROM evidence WHERE id=? AND project_id=?",
                     [eid, project_id]):
            continue
        agent_links.setdefault(eid, []).append({
            "activity_uid": l.activity_uid, "confidence": l.confidence,
            "relation": l.relation,
            "supporting_signals": l.supporting_signals,
            "conflicting_signals": l.conflicting_signals})

    link_stats = linking.link_evidence(
        project_id, job_id=job_id, agent_links=agent_links,
        progress=lambda phase, label, detail=None: step(
            job_id, project_id, phase, label, "success", detail),
        cancel_check=lambda: _raise_if_cancelled(job_id))
    _raise_if_cancelled(job_id)
    step(job_id, project_id, "resolver_persisting",
         "Persisting governed findings and proposed actions")

    # ---- issues and risks, kept distinct (spec 32) ----------------------
    n_issues = 0
    for i in result.issues:
        _raise_if_cancelled(job_id)
        if db.q1("SELECT id FROM issues WHERE project_id=? AND title=?",
                 [project_id, i.title]):
            continue
        db.insert("issues", {
            "project_id": project_id, "job_id": job_id, "ref": i.ref,
            "title": i.title, "description": i.description, "source": i.source,
            "status": i.status, "priority": i.priority, "severity": i.severity,
            "owner": i.owner, "date": i.date,
            "target_resolution": i.target_resolution,
            "activity_uids_json": db.jdumps(i.activity_uids), "wbs": i.wbs,
            "schedule_impact_days": i.schedule_impact_days,
            "schedule_impact_note": i.schedule_impact_note,
            "evidence_ids_json": db.jdumps(
                [ref_to_id.get(r, r) for r in i.evidence_refs]),
            "confidence": i.confidence,
            "provenance": i.provenance or prov_default,
            "updated_at": db.now()})
        n_issues += 1

    n_risks = 0
    for r in result.risks:
        _raise_if_cancelled(job_id)
        if db.q1("SELECT id FROM risks WHERE project_id=? AND title=?",
                 [project_id, r.title]):
            continue
        db.insert("risks", {
            "project_id": project_id, "job_id": job_id, "ref": r.ref,
            "title": r.title, "description": r.description, "category": r.category,
            "probability": r.probability, "impact": r.impact,
            "rating": r.rating or _rating(r.probability, r.impact),
            "score": _score(r.probability, r.impact),
            "owner": r.owner, "status": r.status, "mitigation": r.mitigation,
            "trigger": r.trigger,
            "activity_uids_json": db.jdumps(r.activity_uids), "wbs": r.wbs,
            "schedule_impact_days": r.schedule_impact_days,
            "critical_path_relevance": r.critical_path_relevance,
            "evidence_ids_json": db.jdumps(
                [ref_to_id.get(x, x) for x in r.evidence_refs]),
            "confidence": r.confidence,
            "provenance": r.provenance or prov_default,
            "updated_at": db.now()})
        n_risks += 1

    # ---- review questions the model raised (spec 40, 41) ----------------
    n_reviews = 0
    for q in result.review_questions:
        _raise_if_cancelled(job_id)
        ids = [ref_to_id.get(r, r) for r in q.affected_evidence_refs]
        reviews.create(project_id=project_id, kind=q.kind, title=q.title,
                       question=q.question, detail=q.detail,
                       options=q.options, cluster_key=q.cluster_key,
                       affected_ids=ids, entity_type=q.entity_type,
                       entity_id=q.entity_id, priority=q.priority, job_id=job_id)
        n_reviews += 1

    # ---- change proposals: validated, then dry-run (spec 46, 47) --------
    n_props = 0
    for p in result.change_proposals:
        _raise_if_cancelled(job_id)
        pid = proposals.create(
            project_id, operation=p.operation, target_uid=p.target_uid,
            field=p.field, proposed_value=p.proposed_value, reason=p.reason,
            target_type=p.target_type, target_name=p.target_name,
            parent_uid=p.parent_uid, after_uid=p.after_uid,
            task_fields=p.task_fields,
            evidence_ids=[ref_to_id.get(r, r) for r in p.evidence_refs],
            confidence=p.confidence, job_id=job_id,
            provenance=p.provenance or prov_default)
        try:
            proposals.dry_run(pid, job_id=job_id)
        except Exception as exc:  # noqa: BLE001
            db.update("proposals", pid, {
                "dryrun_state": "failed",
                "dryrun_json": db.jdumps({"error": str(exc)})})
        n_props += 1
    if n_props:
        step(job_id, project_id, "dry_run_complete",
             str(n_props) + " proposal(s) dry-run against a throwaway copy")

    # ---- artifacts -------------------------------------------------------
    for a in result.artifacts:
        _raise_if_cancelled(job_id)
        path = None
        if a.content:
            out = config.project_dir(project_id) / "outputs"
            out.mkdir(parents=True, exist_ok=True)
            ext = {"markdown": ".md", "json": ".json", "csv": ".csv",
                   "text": ".txt"}.get(a.format, ".txt")
            fp = out / (db.new_id("art_") + ext)
            fp.write_text(a.content, encoding="utf-8")
            path = str(fp)
        db.insert("artifacts", {
            "project_id": project_id, "job_id": job_id, "kind": a.kind,
            "title": a.title, "path": path, "format": a.format,
            "size_bytes": len(a.content or "") or None,
            "description": a.description,
            "provenance": prov_default})

    if result.summary:
        db.insert("artifacts", {
            "project_id": project_id, "job_id": job_id, "kind": "summary",
            "title": "Analysis summary", "format": "markdown",
            "description": result.summary[:4000], "provenance": prov_default})

    audit.record(project_id, actor=source, actor_type=actor_type,
                 action="analysis_applied", job_id=job_id, entity_type="job",
                 entity_id=job_id, result="ok",
                 detail={"issues": n_issues, "risks": n_risks,
                         "reviews": n_reviews, "proposals": n_props,
                         "links": link_stats})

    step(job_id, project_id, "associations_validated",
         "Evidence validated: " + ", ".join(
             str(v) + " " + k for k, v in link_stats["stats"].items() if v))
    if link_stats["clusters"]:
        step(job_id, project_id, "human_review_required",
             str(link_stats["clusters"]) + " clustered question(s) need a human "
             "answer")

    events.notify_ui(project_id, "refresh", {"job_id": job_id})
    return {"issues": n_issues, "risks": n_risks, "reviews": n_reviews,
            "proposals": n_props, "links": link_stats,
            "summary": result.summary[:2000]}


_P = {"low": 0.2, "medium": 0.5, "high": 0.8, "very high": 0.95, "very low": 0.1}


def _score(p: str, i: str) -> float:
    return round(_P.get(str(p).lower(), 0.5) * _P.get(str(i).lower(), 0.5), 3)


def _rating(p: str, i: str) -> str:
    s = _score(p, i)
    if s >= 0.6:
        return "high"
    if s >= 0.25:
        return "medium"
    return "low"


# ------------------------------------------------------------------- resume
def _run_resume(job_id: str, project_id: str, payload: dict) -> dict:
    """A human answered; reprocess exactly what that unblocks (spec 42)."""
    review_id = payload.get("review_id")
    review = None
    if review_id:
        rows = [r for r in reviews.all_for(project_id) if r["id"] == review_id]
        review = rows[0] if rows else None
    if review is None:
        return {"note": "review not found"}

    step(job_id, project_id, "review_answered",
         "Human answered: " + str(review.get("title")))

    # Approvals of a proposal execute the verified write (spec 47, 48).
    if review.get("entity_type") == "proposal" and review.get("entity_id"):
        pid = review["entity_id"]
        approved = review.get("status") == "approved"
        proposals.approve(pid, approved_by=review.get("answered_by") or "human",
                          approve_it=approved)
        if approved:
            step(job_id, project_id, "verified_write",
                 "Applying approved change to a revision copy")
            res = proposals.execute(pid, job_id=job_id, actor="human")
            step(job_id, project_id, "verified_write",
                 "Write " + str(res.get("verification")),
                 "success" if res.get("ok") else "failed")
            return {"proposal": pid, **res}
        return {"proposal": pid, "approved": False}

    if review.get("entity_type") == "file" and review.get("entity_id"):
        return _apply_security_answer(job_id, project_id, review)

    # Clustered clarification: apply the answer to every affected record.
    applied = linking.apply_cluster_answer(project_id, review, job_id)
    step(job_id, project_id, "records_reprocessed",
         str(applied.get("reprocessed", 0)) + " record(s) reprocessed from one "
         "answer")

    affected = []
    ids = review.get("affected_ids") or []
    if ids:
        affected = db.q("SELECT id, date, crew, description FROM evidence "
                        "WHERE id IN (" + ",".join("?" for _ in ids) + ") LIMIT 30",
                        ids)

    sess = db.q1("SELECT id FROM agent_sessions WHERE project_id=? "
                 "ORDER BY created_at DESC LIMIT 1", [project_id])
    prompt = resume_prompt([review], affected)
    result, used = _invoke_agent(job_id, project_id, prompt,
                                 resume_external=(sess or {}).get("id"))
    out = apply_result(project_id, job_id, result, source=used)
    return {"reprocessed": applied, "provider": used, **out}


def apply_security_answer_now(project_id: str, review: dict) -> dict:
    """Apply a security decision synchronously; release may enqueue one reprocess."""
    return _apply_security_answer("human:" + str(review.get("id") or "review"), project_id, review)


def _apply_security_answer(job_id: str, project_id: str, review: dict) -> dict:
    fid = review["entity_id"]
    answer = (review.get("answer") or "").lower()
    f = db.q1("SELECT * FROM files WHERE id=?", [fid])
    if not f:
        return {"note": "file not found"}
    if "release" in answer:
        db.update("files", fid, {"security_state": "clean",
                                 "extract_state": "pending"})
        audit.record(project_id, actor=review.get("answered_by") or "human",
                     actor_type="human", action="file_released", job_id=job_id,
                     entity_type="file", entity_id=fid,
                     previous_value=f.get("security_state"), new_value="clean",
                     approval=review.get("answered_by"),
                     result="released for analysis as data only")
        step(job_id, project_id, "security_resolved",
             "File released as data only: " + str(f["filename"]))
        events.emit(events.REPROCESS_REQUESTED, project_id, {"file_id": fid},
                    source="human")
        return {"file": fid, "action": "released"}
    if "delete" in answer:
        try:
            import os
            os.remove(f["stored_path"])
        except Exception:
            pass
        db.ex("DELETE FROM evidence WHERE file_id=?", [fid])
        db.ex("DELETE FROM files WHERE id=?", [fid])
        audit.record(project_id, actor=review.get("answered_by") or "human",
                     actor_type="human", action="file_deleted", job_id=job_id,
                     entity_type="file", entity_id=fid,
                     previous_value=f.get("filename"), result="deleted on request",
                     approval=review.get("answered_by"))
        return {"file": fid, "action": "deleted"}
    db.update("files", fid, {"security_state": "quarantined"})
    step(job_id, project_id, "security_resolved",
         "File remains quarantined: " + str(f["filename"]))
    return {"file": fid, "action": "quarantined"}


# ----------------------------------------------------------------- question
def _run_question(job_id: str, project_id: str, payload: dict) -> dict:
    question = payload.get("question") or ""
    # A VEDA Anywhere question wraps the selection as quoted untrusted data; the
    # human-readable question is carried separately for display/audit.
    display_question = (payload.get("display_question") or question or "").strip()
    project = db.q1("SELECT * FROM projects WHERE id=?", [project_id]) or {}
    snap = db.q1("SELECT * FROM schedule_snapshots WHERE project_id=? "
                 "AND is_current=1 ORDER BY created_at DESC LIMIT 1", [project_id])
    step(job_id, project_id, "question_received", "Question received")
    prompt = question_prompt(question, project, snap)
    result, used = _invoke_agent(job_id, project_id, prompt)

    answer = result.summary or "No grounded answer could be produced."
    db.insert("artifacts", {
        "project_id": project_id, "job_id": job_id, "kind": "answer",
        "title": display_question[:180] or "Project question", "format": "markdown",
        "description": answer[:4000],
        "provenance": "AI_INFERENCE" if used != "deterministic"
        else "DETERMINISTIC_CALCULATION"})
    audit.record(project_id, actor="human", actor_type="human",
                 action="question_asked", job_id=job_id,
                 new_value=display_question[:500], result="answered")
    step(job_id, project_id, "output_ready", "Answer ready")
    return {"question": display_question, "answer": answer, "provider": used,
            "findings": [f.model_dump() for f in result.schedule_findings]}


# --------------------------------------------------------------- resnapshot
def _run_resnapshot(job_id: str, project_id: str, payload: dict) -> dict:
    """Re-harvest after a verified write (spec 13 - recalculate only when needed)."""
    path = payload.get("path") or proposals.current_schedule_path(project_id)
    if not path:
        return {"note": "no schedule to re-read"}
    step(job_id, project_id, "schedule_reopened", "Re-reading the updated schedule")
    schedule_ops.forget_handles()
    summary = schedule_ops.collect_snapshot(
        project_id, path, job_id=job_id,
        progress=lambda n, l, s: step(job_id, project_id, n, l, s))
    linking.rebuild_observed_progress(project_id)
    return {"snapshot": summary}
