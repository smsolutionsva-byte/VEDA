"""VEDA HTTP API.

Browsing is served entirely from persisted rows (spec 54). The agent is invoked
only for meaningful analysis or an explicit question, never for sorting,
filtering, paging or opening a detail view.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

from fastapi import APIRouter, Body, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

from .. import __version__, audit as audit_mod
from .. import config, db, events, jobs, reviews
from ..agent import registry
from ..integrations import primavera
from ..mcpc import horizun, schedule_ops
from ..pipeline import actuals, field_capture, ingest, linking, proposals, security

router = APIRouter(prefix="/api")


def _project_or_404(pid: str) -> dict:
    p = db.q1("SELECT * FROM projects WHERE id=?", [pid])
    if not p:
        raise HTTPException(404, "no such project")
    return p


def _snapshot(pid: str) -> dict | None:
    return db.q1("SELECT * FROM schedule_snapshots WHERE project_id=? "
                 "AND is_current=1 ORDER BY created_at DESC LIMIT 1", [pid])


# =====================================================================
#  System / MCP health  (spec 52)
# =====================================================================
@router.get("/health")
async def health(deep: bool = False):
    out: dict = {"veda": {"ok": True, "version": __version__,
                          "data_dir": str(config.DATA_DIR)}}
    try:
        h = await asyncio.get_event_loop().run_in_executor(
            None, lambda: horizun.health(deep=deep))
        out["horizun"] = {"ok": True, **h, "command": config.HORIZUN_CMD,
                          "tools": sorted(horizun.tool_names())}
    except Exception as exc:  # noqa: BLE001
        out["horizun"] = {"ok": False, "error": str(exc),
                          "command": config.HORIZUN_CMD}
    out["providers"] = await registry.health_all()
    out["active_provider"] = registry.active_provider_name()
    out["worker"] = {"current_job": jobs.current_job()}
    return out


@router.get("/providers")
async def providers():
    return {"active": registry.active_provider_name(),
            "providers": await registry.health_all()}


@router.post("/providers/active")
async def set_provider(body: dict = Body(...)):
    name = body.get("provider", "")
    try:
        registry.set_active_provider(name)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    audit_mod.record(None, actor="human", actor_type="human",
                     action="provider_changed", source="website",
                     new_value=name, result="ok")
    return {"active": name}


@router.get("/mcp/tools")
def mcp_tools():
    try:
        return {"tools": horizun.list_tools(refresh=True),
                "capabilities": horizun.capabilities()}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(503, str(exc))


# =====================================================================
#  Projects
# =====================================================================
@router.get("/projects")
def list_projects():
    rows = db.q("SELECT * FROM projects WHERE status<>'deleting' "
                "ORDER BY created_at DESC")
    for r in rows:
        snap = _snapshot(r["id"])
        r["snapshot"] = snap
        r["counts"] = {
            "files": _count("files", r["id"]),
            "activities": _count("activities", r["id"]),
            "evidence": _count("evidence", r["id"]),
            "issues": _count("issues", r["id"]),
            "risks": _count("risks", r["id"]),
            "open_reviews": (db.q1("SELECT COUNT(*) c FROM reviews WHERE "
                                   "project_id=? AND status='open'",
                                   [r["id"]]) or {}).get("c", 0),
        }
    return {"projects": rows}


def _count(table: str, pid: str) -> int:
    return (db.q1("SELECT COUNT(*) c FROM " + table + " WHERE project_id=?",
                  [pid]) or {}).get("c", 0)


@router.post("/projects")
def create_project(body: dict = Body(...)):
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "name is required")
    pid = db.insert("projects", {
        "name": name, "client": body.get("client"),
        "location": body.get("location"), "description": body.get("description"),
        "status": "active", "agent_provider": registry.active_provider_name(),
        "created_at": db.now(), "updated_at": db.now()})
    audit_mod.record(pid, actor="human", actor_type="human",
                     action="project_created", source="website",
                     entity_type="project", entity_id=pid, new_value=name,
                     result="created")
    return {"id": pid, "project": db.q1("SELECT * FROM projects WHERE id=?", [pid])}


@router.post("/projects/{pid}/activate")
def activate_project(pid: str):
    """Make pid the operator's current project and pre-empt old project work."""
    p = _project_or_404(pid)
    if p.get("status") == "deleting":
        raise HTTPException(409, "project is being deleted")
    return jobs.activate_project(pid)


@router.delete("/projects/{pid}")
def delete_project(pid: str):
    _project_or_404(pid)
    return jobs.delete_project(pid)


def _field_evidence_context(pid: str) -> dict:
    total = int((db.q1("SELECT COUNT(*) c FROM evidence WHERE project_id=?", [pid]) or {}).get("c", 0))
    source_files = int((db.q1("SELECT COUNT(DISTINCT file_id) c FROM evidence WHERE project_id=? AND file_id IS NOT NULL", [pid]) or {}).get("c", 0))
    progress_records = int((db.q1("SELECT COUNT(*) c FROM evidence WHERE project_id=? AND observed_progress IS NOT NULL", [pid]) or {}).get("c", 0))
    latest = (db.q1("SELECT MAX(date) d FROM evidence WHERE project_id=? AND date IS NOT NULL AND TRIM(date)!=''", [pid]) or {}).get("d")
    linked_records = int((db.q1(
        "SELECT COUNT(DISTINCT e.id) c FROM evidence e JOIN evidence_links l ON l.evidence_id=e.id "
        "WHERE e.project_id=? AND l.project_id=? AND l.is_candidate=0 "
        "AND l.relation='supporting' AND e.state IN ('linked','confirmed')", [pid, pid]) or {}).get("c", 0))
    linked_activities = int((db.q1(
        "SELECT COUNT(DISTINCT l.activity_uid) c FROM evidence e JOIN evidence_links l ON l.evidence_id=e.id "
        "WHERE e.project_id=? AND l.project_id=? AND l.is_candidate=0 "
        "AND l.relation='supporting' AND e.state IN ('linked','confirmed') "
        "AND l.activity_uid IS NOT NULL", [pid, pid]) or {}).get("c", 0))
    numeric_observed_activities = int((db.q1(
        "SELECT COUNT(*) c FROM observed_progress WHERE project_id=? AND observed_percent IS NOT NULL", [pid]) or {}).get("c", 0))
    reviewed_or_unresolved = int((db.q1(
        "SELECT COUNT(*) c FROM evidence WHERE project_id=? AND state IN "
        "('needs_review','conflicting','new','processing')", [pid]) or {}).get("c", 0))
    deferred = int((db.q1("SELECT COUNT(*) c FROM evidence WHERE project_id=? AND state='deferred'", [pid]) or {}).get("c", 0))
    return {
        "record_count": total,
        "source_file_count": source_files,
        "latest_date": latest,
        "reported_progress_record_count": progress_records,
        "validated_link_record_count": linked_records,
        "validated_activity_count": linked_activities,
        "numeric_observed_activity_count": numeric_observed_activities,
        "unresolved_record_count": reviewed_or_unresolved,
        "deferred_record_count": deferred,
    }


def _overview_state_summary(snap: dict | None, quality: dict, counts: dict,
                            field: dict, reference_context: dict) -> str:
    if not snap:
        return ("No authoritative schedule snapshot has been analysed yet. "
                + str(field.get("record_count", 0)) +
                " field-evidence record(s) are stored separately.")
    parts = [
        "Schedule '" + str(snap.get("project_name") or "") + "' contains " +
        str(snap.get("task_count") or 0) + " source activities across " +
        str(snap.get("wbs_count") or 0) + " active WBS node(s)."
    ]
    if snap.get("data_date"):
        parts.append("The supplied data/status date is " + str(snap.get("data_date")) + ".")
    else:
        parts.append("The source does not supply a data/status date.")
    if snap.get("baseline_finish"):
        parts.append("The stored baseline/reference finish is " + str(snap.get("baseline_finish")) + ".")
    if snap.get("forecast_finish"):
        parts.append("The current forecast finish is " + str(snap.get("forecast_finish")) + ".")
    else:
        parts.append("A current forecast finish is not established by the source.")
    if int(snap.get("criticality_available") or 0) == 1:
        parts.append(str(snap.get("critical_count") or 0) +
                     " activities are critical under " +
                     str(snap.get("criticality_basis") or "the stored criticality method") + ".")
    else:
        parts.append("Criticality is not evaluable from the supplied source; missing criticality is not treated as zero.")
    evaluated = int(quality.get("passed", 0)) + int(quality.get("failed", 0))
    parts.append("Source-evaluable schedule QA: " + str(quality.get("passed", 0)) +
                 " passed, " + str(quality.get("failed", 0)) + " failed, " +
                 str(quality.get("not_evaluated", 0)) + " not evaluated" +
                 ((" (" + str(snap.get("health_score")) + "% of " + str(evaluated) +
                   " evaluable checks passed).") if evaluated and snap.get("health_score") is not None else "."))
    if field.get("record_count"):
        parts.append(str(field.get("record_count")) + " field-evidence record(s) from " +
                     str(field.get("source_file_count")) + " source file(s) are stored; " +
                     str(field.get("reported_progress_record_count")) +
                     " record(s) contain a reported progress percentage, and " +
                     str(field.get("validated_activity_count")) +
                     " schedule activity/activities currently have validated supporting evidence. " +
                     "Field-observed values remain separate from official schedule progress.")
    else:
        parts.append("No field/report evidence records are stored yet; project-control reference tables are tracked separately.")
    parts.append(str(counts.get("open_issues", 0)) + " open derived issue(s) and " +
                 str(counts.get("open_risks", 0)) +
                 " open derived risk(s) are stored separately from the schedule-QA findings.")
    return " ".join(parts)


def _project_state(pid: str) -> dict:
    awaiting = db.q1("SELECT id FROM ingestion_batches WHERE project_id=? AND status='awaiting_schedule' "
                     "ORDER BY created_at DESC LIMIT 1", [pid])
    if awaiting:
        return {"code": "choose_schedule", "label": "Choose schedule",
                "detail": "Multiple schedule revisions were detected; choose the authoritative schedule to continue."}
    active = db.q1("SELECT id, kind, status, phase FROM jobs WHERE project_id=? "
                   "AND kind IN ('analysis','resnapshot') AND status IN ('queued','running') "
                   "ORDER BY created_at DESC LIMIT 1", [pid])
    if active:
        return {"code": "updating", "label": "Updating project",
                "detail": "New project inputs are being incorporated.", "job_id": active["id"]}
    terminal = db.q1("SELECT id, status, error FROM jobs WHERE project_id=? "
                     "AND kind IN ('analysis','resnapshot') AND status IN ('done','failed') "
                     "ORDER BY COALESCE(finished_at,created_at) DESC LIMIT 1", [pid])
    if terminal and terminal.get("status") == "failed":
        return {"code": "retry", "label": "Project update needs retry",
                "detail": (terminal.get("error") or "The latest project update failed.")[:220],
                "job_id": terminal["id"]}
    open_reviews = int((db.q1("SELECT COUNT(*) c FROM reviews WHERE project_id=? AND status='open'", [pid]) or {}).get("c", 0))
    pending_changes = int((db.q1("SELECT COUNT(*) c FROM proposals WHERE project_id=? AND approval_state='pending'", [pid]) or {}).get("c", 0))
    unresolved = int((db.q1("SELECT COUNT(*) c FROM evidence WHERE project_id=? AND state IN ('needs_review','conflicting')", [pid]) or {}).get("c", 0))
    if open_reviews or pending_changes or unresolved:
        return {"code": "needs_input", "label": "Needs your input",
                "detail": f"{open_reviews} decision(s), {pending_changes} change approval(s), {unresolved} unresolved evidence record(s)."}
    return {"code": "up_to_date", "label": "Up to date",
            "detail": "All stored project inputs have been incorporated; no decision is waiting on you."}


@router.get("/projects/{pid}/overview")
def overview(pid: str):
    """spec 16. Missing data stays missing - nothing is fabricated."""
    p = _project_or_404(pid)
    snap = _snapshot(pid)
    ev = db.q1("SELECT * FROM earned_value WHERE project_id=? AND scope='project' "
               "ORDER BY created_at DESC LIMIT 1", [pid])
    qa = db.q("SELECT status, COUNT(*) c FROM qa_findings WHERE project_id=? "
              "GROUP BY status", [pid])
    qa_map = {r["status"]: r["c"] for r in qa}
    quality = {"passed": qa_map.get("pass", 0), "failed": qa_map.get("fail", 0),
               "not_evaluated": qa_map.get("not_evaluated", 0)}
    job = db.q1("SELECT * FROM jobs WHERE project_id=? ORDER BY created_at DESC "
                "LIMIT 1", [pid])
    snap_info = db.jloads((snap or {}).get("info_json"), {}) or {}
    reference_context = snap_info.get("reference_context") or {}
    critical_count = None
    if snap and int(snap.get("criticality_available") or 0) == 1:
        critical_count = int(snap.get("critical_count") or 0)
    overdue_count = None
    if snap and int(snap.get("overdue_evaluable") or 0) == 1:
        overdue_count = int(snap.get("overdue_count") or 0)
    completed_late_count = None
    if snap and int(snap.get("completed_late_evaluable") or 0) == 1:
        completed_late_count = int(snap.get("completed_late_count") or 0)

    field_context = _field_evidence_context(pid)
    open_issues = int((db.q1("SELECT COUNT(*) c FROM issues WHERE project_id=? AND status='open'", [pid]) or {}).get("c", 0))
    open_risks = int((db.q1("SELECT COUNT(*) c FROM risks WHERE project_id=? AND status='open'", [pid]) or {}).get("c", 0))
    count_view = {
        "open_issues": open_issues,
        "open_risks": open_risks,
    }
    state_summary = _overview_state_summary(snap, quality, count_view, field_context, reference_context)

    return {
        "project": p,
        "schedule": snap,
        "earned_value": ev,
        "reference_context": reference_context,
        "quality": quality,
        "field_context": field_context,
        "counts": {
            "activities": int((snap or {}).get("task_count") or _count("activities", pid)),
            "wbs": int((snap or {}).get("wbs_count") or _count("wbs_nodes", pid)),
            "summary_activities": int((snap or {}).get("summary_activity_count") or 0),
            "loe": int((snap or {}).get("loe_count") or 0),
            "milestones": _count("milestones", pid),
            "relationships": _count("relationships", pid),
            "resources": _count("resources", pid),
            "assignments": _count("assignments", pid),
            "evidence": _count("evidence", pid),
            "issues": _count("issues", pid),
            "risks": _count("risks", pid),
            "open_issues": open_issues,
            "open_risks": open_risks,
            "files": _count("files", pid),
            "artifacts": _count("artifacts", pid),
            "critical": critical_count,
            # Back-compat: "late" now consistently means currently overdue.
            # Preserve NULL when the status boundary is unavailable.
            "late": overdue_count,
            "overdue": overdue_count,
            "completed_late": completed_late_count,
            "pending_reviews": (db.q1("SELECT COUNT(*) c FROM reviews WHERE "
                                      "project_id=? AND status='open'",
                                      [pid]) or {}).get("c", 0),
            "pending_proposals": (db.q1("SELECT COUNT(*) c FROM proposals WHERE "
                                        "project_id=? AND approval_state='pending'",
                                        [pid]) or {}).get("c", 0),
            "unresolved_evidence": field_context.get("unresolved_record_count", 0),
            "deferred_evidence": field_context.get("deferred_record_count", 0),
        },
        "project_state": _project_state(pid),
        "active_provider": registry.active_provider_name(),
        "provider_label": registry.LABELS.get(registry.active_provider_name()),
        "latest_job": job,
        "state_summary": state_summary,
        "summary": (db.q1("SELECT description FROM artifacts WHERE project_id=? "
                          "AND kind='summary' ORDER BY created_at DESC LIMIT 1",
                          [pid]) or {}).get("description"),
    }


# =====================================================================
#  Files / upload  (spec 6)
# =====================================================================

@router.get("/projects/{pid}/field-captures")
def field_captures(pid: str, limit: int = Query(100, le=500)):
    _project_or_404(pid)
    rows = field_capture.list_for_project(pid, limit=limit)
    return {
        "captures": rows,
        "counts": {row["status"]: int(row["c"]) for row in db.q(
            "SELECT status, COUNT(*) c FROM field_captures "
            "WHERE project_id=? GROUP BY status", [pid])},
    }


@router.post("/projects/{pid}/field-captures")
async def create_field_capture(pid: str, payload: str = Form(...),
                               files: list[UploadFile] | None = File(None)):
    _project_or_404(pid)
    try:
        body = json.loads(payload)
        if not isinstance(body, dict):
            raise ValueError("payload must be a JSON object")
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(400, "invalid field-capture payload: " + str(exc)) from exc
    if len(list(files or [])) > field_capture.MAX_ATTACHMENTS:
        raise HTTPException(413, f"at most {field_capture.MAX_ATTACHMENTS} media attachments are allowed")
    attachments = []
    total_bytes = 0
    for uploaded in list(files or []):
        blob = await uploaded.read(field_capture.MAX_ATTACHMENT_BYTES + 1)
        if len(blob) > field_capture.MAX_ATTACHMENT_BYTES:
            raise HTTPException(413, (uploaded.filename or "field-media") +
                                " exceeds the 25 MB field-capture limit")
        total_bytes += len(blob)
        if total_bytes > field_capture.MAX_TOTAL_BYTES:
            raise HTTPException(413, "field-capture media exceeds 80 MB in total")
        attachments.append((uploaded.filename or "field-media", blob,
                            uploaded.content_type))
    try:
        capture = field_capture.store(pid, body, attachments)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"capture": capture,
            "note": ("Field update was already synced; the retry was safely ignored."
                     if capture.get("idempotent_replay") else
                     "Confirmed field evidence stored; any resulting actuals remain proposals until approval.")}


@router.post("/projects/{pid}/actuals/generate")
def generate_actuals(pid: str):
    _project_or_404(pid)
    return actuals.generate_for_project(pid)


async def _store_ingestion_batch(pid: str, files: list[UploadFile] | None,
                                 text: str = "", text_mode: str = "field_note",
                                 text_title: str = "",
                                 relative_paths: list[str] | None = None) -> dict:
    """Store one user action as one ingestion batch and emit one analysis event."""
    _project_or_404(pid)
    incoming = list(files or [])
    if not incoming and not (text or "").strip():
        raise HTTPException(400, "add at least one file or pasted text")

    batch_id = db.insert("ingestion_batches", {
        "project_id": pid, "source": "website", "status": "receiving",
        "note": "multi-source ingestion",
    })
    results: list[dict] = []
    try:
        rels = list(relative_paths or [])
        for idx, f in enumerate(incoming):
            data = await f.read()
            if len(data) > config.MAX_UPLOAD_MB * 1024 * 1024:
                raise HTTPException(413, (f.filename or "upload") + " exceeds " +
                                    str(config.MAX_UPLOAD_MB) + " MB")
            rel = rels[idx] if idx < len(rels) and rels[idx].strip() else (f.filename or "upload")
            results.append(ingest.store_upload(
                pid, f.filename or "upload", data, f.content_type,
                batch_id=batch_id, source_mode="file", relative_path=rel))

        if (text or "").strip():
            results.append(ingest.store_text_input(
                pid, text.strip(), text_mode, text_title or None,
                batch_id=batch_id))

        unique = [r for r in results if not r.get("skipped")]
        duplicates = [r for r in results if r.get("skipped")]
        schedules = [r for r in unique if r.get("kind") == "schedule"]
        evidence = [r for r in unique if r.get("kind") == "evidence"]
        db.update("ingestion_batches", batch_id, {
            "status": "stored", "file_count": len(unique),
            "duplicate_count": len(duplicates), "schedule_count": len(schedules),
            "evidence_count": len(evidence),
            "note": ("pasted " + text_mode if (text or "").strip() else None),
        })

        ev = None
        job_id = None
        selection_required = len(schedules) > 1
        if selection_required:
            db.update("ingestion_batches", batch_id, {
                "status": "awaiting_schedule",
                "note": "multiple schedule candidates; authoritative selection required",
            })
        elif unique:
            selected = schedules[0]["id"] if len(schedules) == 1 else None
            if selected:
                db.update("projects", pid, {"schedule_file_id": selected, "updated_at": db.now()})
            ev = events.emit(
                events.DATASET_UPLOADED if schedules else events.FILES_ADDED,
                pid, {"batch_id": batch_id,
                      "file_ids": [r["id"] for r in unique],
                      "filenames": [r["filename"] for r in unique],
                      "source_modes": [r.get("source_mode", "file") for r in unique],
                      "schedule_file_id": selected,
                      "schedule_count": len(schedules),
                      "evidence_count": len(evidence)}, source="website")
            job_id = jobs.ensure_event_job(ev)
        else:
            job_id = None

        return {"batch_id": batch_id, "files": results,
                "stored_count": len(unique), "duplicate_count": len(duplicates),
                "schedule_count": len(schedules), "evidence_count": len(evidence),
                "schedule_selection_required": selection_required,
                "schedule_candidates": [{
                    "id": r["id"], "filename": r["filename"],
                    "relative_path": r.get("relative_path") or r["filename"],
                    "alternate_hint": bool((r.get("schedule_candidate") or {}).get("alternate_hint")),
                } for r in schedules],
                "event": (ev or {}).get("id"), "job_id": job_id,
                "note": ("choose the authoritative schedule before analysis" if selection_required else
                         ("analysis job created; the agent wakes automatically"
                          if ev else "all submitted sources were already present"))}
    except Exception:
        db.update("ingestion_batches", batch_id, {"status": "failed"})
        raise


@router.post("/projects/{pid}/ingest")
async def ingest_batch(pid: str,
                       files: list[UploadFile] | None = File(None),
                       text: str = Form(""),
                       text_mode: str = Form("field_note"),
                       text_title: str = Form(""),
                       relative_paths: list[str] | None = Form(None)):
    """Multi-source intake, including recursively selected project folders."""
    return await _store_ingestion_batch(pid, files, text, text_mode, text_title, relative_paths)


@router.post("/projects/{pid}/ingest/{batch_id}/select-schedule")
def select_batch_schedule(pid: str, batch_id: str, body: dict = Body(...)):
    _project_or_404(pid)
    fid = str(body.get("file_id") or "")
    candidates = db.q("SELECT * FROM files WHERE project_id=? AND batch_id=? AND kind='schedule' ORDER BY created_at, id", [pid, batch_id])
    chosen = next((f for f in candidates if f.get("id") == fid), None)
    if not chosen:
        raise HTTPException(400, "choose one of this batch's detected schedule candidates")
    batch_files = db.q("SELECT * FROM files WHERE project_id=? AND batch_id=? ORDER BY created_at, id", [pid, batch_id])
    db.update("projects", pid, {"schedule_file_id": fid, "updated_at": db.now()})
    db.update("ingestion_batches", batch_id, {"status": "stored",
              "note": "authoritative schedule selected: " + str(chosen.get("relative_path") or chosen.get("filename"))})
    ev = events.emit(events.DATASET_UPLOADED, pid, {
        "batch_id": batch_id, "file_ids": [f["id"] for f in batch_files],
        "filenames": [f["filename"] for f in batch_files],
        "schedule_file_id": fid, "schedule_count": len(candidates),
        "evidence_count": sum(1 for f in batch_files if f.get("kind") == "evidence"),
    }, source="website")
    job_id = jobs.ensure_event_job(ev)
    if not job_id:
        raise HTTPException(500, "authoritative schedule was saved but analysis could not be queued")
    return {"ok": True, "schedule_file_id": fid, "event": ev.get("id"),
            "job_id": job_id, "analysis_started": True,
            "selected": chosen.get("relative_path") or chosen.get("filename")}


@router.post("/projects/{pid}/files")
async def upload(pid: str, files: list[UploadFile] = File(...)):
    """Backward-compatible upload endpoint; now batch-aware and deduplicated."""
    return await _store_ingestion_batch(pid, files)


@router.get("/projects/{pid}/files")
def list_files(pid: str):
    _project_or_404(pid)
    files = db.q("SELECT * FROM files WHERE project_id=? ORDER BY created_at DESC",
                 [pid])
    batches = db.q("SELECT * FROM ingestion_batches WHERE project_id=? "
                   "ORDER BY created_at DESC LIMIT 20", [pid])
    revisions = db.q(
        "SELECT s.*, "
        "SUM(CASE WHEN c.change_type='added' THEN 1 ELSE 0 END) AS added_count, "
        "SUM(CASE WHEN c.change_type='removed' THEN 1 ELSE 0 END) AS removed_count, "
        "SUM(CASE WHEN c.change_type='updated' THEN 1 ELSE 0 END) AS updated_count "
        "FROM schedule_snapshots s LEFT JOIN schedule_revision_changes c "
        "ON c.snapshot_id=s.id WHERE s.project_id=? GROUP BY s.id "
        "ORDER BY s.revision DESC LIMIT 20", [pid])
    return {"files": files, "batches": batches, "schedule_revisions": revisions}


@router.get("/projects/{pid}/schedule-revisions/{revision}/changes")
def schedule_revision_changes(pid: str, revision: int):
    _project_or_404(pid)
    rows = db.q("SELECT * FROM schedule_revision_changes WHERE project_id=? "
                "AND revision=? ORDER BY change_type, activity_uid", [pid, revision])
    for r in rows:
        r["changed_fields"] = db.jloads(r.get("changed_fields_json"), [])
        r["before"] = db.jloads(r.get("before_json"), None)
        r["after"] = db.jloads(r.get("after_json"), None)
    return {"revision": revision, "changes": rows}


@router.get("/projects/{pid}/files/{fid}/preview")
def preview_file(pid: str, fid: str, limit: int = 4000):
    f = db.q1("SELECT * FROM files WHERE id=? AND project_id=?", [fid, pid])
    if not f:
        raise HTTPException(404, "no such file")
    from ..pipeline import extract
    text = extract.full_text(f["stored_path"], f.get("ext") or "")
    return {"file": f["filename"], "security_state": f.get("security_state"),
            "security_notes": f.get("security_notes"),
            "content": security.sanitize_for_display(text, limit),
            "truncated": len(text) > limit}


# =====================================================================
#  EPS / WBS  (spec 17, 18)
# =====================================================================
@router.get("/projects/{pid}/eps")
def eps(pid: str):
    rows = db.q("SELECT * FROM eps_nodes WHERE project_id=? ORDER BY code", [pid])
    if rows:
        return {"available": True, "nodes": rows}
    snap = _snapshot(pid)
    src = (snap or {}).get("source_path") or ""
    ext = os.path.splitext(src)[1].lower()
    return {
        "available": False,
        "message": "EPS information unavailable",
        "detail": ("The uploaded schedule is " + (ext or "an unknown format") +
                   ". Genuine Primavera EPS structure is only present in "
                   "Primavera sources that carry it, and VEDA will not invent "
                   "one." if ext else
                   "No schedule has been analysed yet."),
        "nodes": [],
    }


@router.get("/projects/{pid}/wbs")
def wbs(pid: str):
    nodes = db.q("SELECT * FROM wbs_nodes WHERE project_id=? ORDER BY code", [pid])
    for n in nodes:
        n["issues"] = (db.q1("SELECT COUNT(*) c FROM issues WHERE project_id=? "
                             "AND wbs=?", [pid, n["code"]]) or {}).get("c", 0)
        n["risks"] = (db.q1("SELECT COUNT(*) c FROM risks WHERE project_id=? "
                            "AND wbs=?", [pid, n["code"]]) or {}).get("c", 0)
        n["evidence"] = (db.q1(
            "SELECT COUNT(*) c FROM evidence_links l JOIN activities a "
            "ON a.uid=l.activity_uid AND a.project_id=l.project_id "
            "WHERE l.project_id=? AND a.wbs LIKE ? AND l.is_candidate=0",
            [pid, str(n["code"]) + "%"]) or {}).get("c", 0)
    return {"nodes": nodes}


# =====================================================================
#  Activities  (spec 19, 20)
# =====================================================================
@router.get("/projects/{pid}/activities")
def activities(pid: str, q: str = "", wbs: str = "", status: str = "",
               critical: str = "", milestone: str = "", late: str = "",
               sort: str = "start", direction: str = "asc",
               limit: int = Query(100, le=1000), offset: int = 0):
    sql = "SELECT * FROM activities WHERE project_id=?"
    params: list = [pid]
    if q:
        sql += " AND (lower(name) LIKE ? OR display_id LIKE ? OR wbs LIKE ?)"
        params += ["%" + q.lower() + "%", "%" + q + "%", "%" + q + "%"]
    if wbs:
        sql += " AND wbs LIKE ?"
        params.append(wbs + "%")
    if status:
        sql += " AND status=?"
        params.append(status)
    snap = _snapshot(pid)
    criticality_available = bool(snap and int(snap.get("criticality_available") or 0) == 1)
    completed_late_evaluable = bool(snap and int(snap.get("completed_late_evaluable") or 0) == 1)
    if critical in ("1", "true") and criticality_available:
        sql += " AND critical=1"
    if milestone in ("1", "true"):
        sql += " AND is_milestone=1"
    elif milestone in ("0", "false"):
        sql += " AND is_milestone=0"
    if late in ("1", "true"):
        if completed_late_evaluable:
            sql += " AND actual_finish IS NOT NULL AND baseline_finish IS NOT NULL " \
                   "AND date(actual_finish) > date(baseline_finish)"
        else:
            sql += " AND 1=0"

    total = (db.q1("SELECT COUNT(*) c FROM (" + sql + ")", params) or {}).get("c", 0)
    cols = {"start": "start", "finish": "finish", "float": "total_float_days",
            "duration": "duration_days", "wbs": "wbs", "name": "name",
            "progress": "percent_complete", "uid": "uid",
            "variance": "finish_variance_days"}
    col = cols.get(sort, "start")
    dirn = "DESC" if direction.lower() == "desc" else "ASC"
    sql += " ORDER BY is_summary ASC, " + col + " " + dirn + " LIMIT ? OFFSET ?"
    params += [limit, offset]
    rows = db.q(sql, params)

    uids = [r["uid"] for r in rows]
    counts = _activity_counts(pid, uids)
    for r in rows:
        c = counts.get(r["uid"], {})
        r["evidence_count"] = c.get("evidence", 0)
        r["issue_count"] = c.get("issues", 0)
        r["risk_count"] = c.get("risks", 0)
        r["review_state"] = c.get("review_state")
        r["observed_progress"] = c.get("observed")
    return {"total": total, "returned": len(rows), "offset": offset,
            "activities": rows, "criticality_available": criticality_available,
            "completed_late_evaluable": completed_late_evaluable}


def _activity_counts(pid: str, uids: list) -> dict:
    if not uids:
        return {}
    ph = ",".join("?" for _ in uids)
    out: dict = {u: {} for u in uids}
    for r in db.q("SELECT activity_uid u, COUNT(*) c FROM evidence_links "
                  "WHERE project_id=? AND is_candidate=0 AND activity_uid IN (" +
                  ph + ") GROUP BY activity_uid", [pid] + uids):
        out.setdefault(r["u"], {})["evidence"] = r["c"]
    for r in db.q("SELECT activity_uid u, observed_percent o FROM observed_progress "
                  "WHERE project_id=? AND activity_uid IN (" + ph + ")",
                  [pid] + uids):
        out.setdefault(r["u"], {})["observed"] = r["o"]
    for tbl, key in (("issues", "issues"), ("risks", "risks")):
        for r in db.q("SELECT activity_uids_json j FROM " + tbl +
                      " WHERE project_id=?", [pid]):
            for u in db.jloads(r["j"], []) or []:
                if u in out:
                    out[u][key] = out[u].get(key, 0) + 1
    for r in db.q("SELECT activity_uid u, COUNT(*) c FROM evidence_links "
                  "WHERE project_id=? AND is_candidate=1 AND activity_uid IN (" +
                  ph + ") GROUP BY activity_uid", [pid] + uids):
        out.setdefault(r["u"], {})["review_state"] = "candidates pending"
    return out


@router.get("/projects/{pid}/activities/{uid}")
def activity_detail(pid: str, uid: int):
    """spec 20, 53 - every neighbouring entity reachable from one place."""
    a = db.q1("SELECT * FROM activities WHERE project_id=? AND uid=?", [pid, uid])
    if not a:
        raise HTTPException(404, "no such activity")
    preds = db.q("SELECT * FROM relationships WHERE project_id=? AND succ_uid=?",
                 [pid, uid])
    succs = db.q("SELECT * FROM relationships WHERE project_id=? AND pred_uid=?",
                 [pid, uid])
    assigns = db.q("SELECT * FROM assignments WHERE project_id=? AND task_uid=?",
                   [pid, uid])
    res_uids = [x["resource_uid"] for x in assigns if x.get("resource_uid")]
    resources = db.q("SELECT * FROM resources WHERE project_id=? AND uid IN (" +
                     ",".join("?" for _ in res_uids) + ")",
                     [pid] + res_uids) if res_uids else []
    links = db.q("SELECT l.*, e.source_file, e.locator, e.date, e.description, "
                 "e.discipline, e.crew, e.chainage, e.quantity, e.unit, "
                 "e.observed_progress, e.state AS evidence_state "
                 "FROM evidence_links l JOIN evidence e ON e.id=l.evidence_id "
                 "WHERE l.project_id=? AND l.activity_uid=? "
                 "ORDER BY l.is_candidate, l.confidence DESC", [pid, uid])
    for l in links:
        l["supporting_signals"] = db.jloads(l.get("supporting_signals"), []) or []
        l["conflicting_signals"] = db.jloads(l.get("conflicting_signals"), []) or []
        l["validator"] = db.jloads(l.pop("validator_json", None), {}) or {}
    grouped: dict = {}
    for l in links:
        grouped.setdefault(l["relation"], []).append(l)

    issues = [i for i in db.q("SELECT * FROM issues WHERE project_id=?", [pid])
              if uid in (db.jloads(i.get("activity_uids_json"), []) or [])]
    risks = [r for r in db.q("SELECT * FROM risks WHERE project_id=?", [pid])
             if uid in (db.jloads(r.get("activity_uids_json"), []) or [])]
    props = [proposals.shape(p) for p in
             db.q("SELECT * FROM proposals WHERE project_id=? AND target_uid=? "
                  "ORDER BY created_at DESC", [pid, uid])]
    obs = db.q1("SELECT * FROM observed_progress WHERE project_id=? "
                "AND activity_uid=?", [pid, uid])
    ms = db.q1("SELECT * FROM milestones WHERE project_id=? AND uid=?", [pid, uid])
    return {
        "activity": a, "predecessors": preds, "successors": succs,
        "assignments": assigns, "resources": resources,
        "evidence": grouped, "evidence_total": len(links),
        "issues": issues, "risks": risks, "proposals": props,
        "observed_progress": obs, "milestone": ms,
        "baseline": {"baseline_start": a.get("baseline_start"),
                     "baseline_finish": a.get("baseline_finish"),
                     "start_variance_days": a.get("start_variance_days"),
                     "finish_variance_days": a.get("finish_variance_days"),
                     "duration_variance_days": a.get("duration_variance_days")},
        "schedule_semantics": (lambda ss: {
            "criticality_available": bool(ss and int(ss.get("criticality_available") or 0) == 1),
            "progress_available": bool(ss and int(ss.get("progress_available") or 0) == 1),
            "progress_basis": (ss or {}).get("progress_basis"),
        })(_snapshot(pid)),
        "audit": audit_mod.for_project(pid, limit=40, entity_type="activity",
                                       entity_id=str(uid)),
    }


# =====================================================================
#  Milestones / relationships / critical path  (spec 21, 22, 29)
# =====================================================================
@router.get("/projects/{pid}/milestones")
def milestones(pid: str):
    return {"milestones": db.q("SELECT * FROM milestones WHERE project_id=? "
                               "ORDER BY forecast_date, planned_date", [pid])}


@router.get("/projects/{pid}/relationships")
def relationships(pid: str, type: str = "", driving: str = "",
                  q: str = "", limit: int = Query(300, le=3000), offset: int = 0):
    sql = "SELECT * FROM relationships WHERE project_id=?"
    params: list = [pid]
    if type:
        sql += " AND type=?"
        params.append(type)
    if driving in ("1", "true"):
        sql += " AND driving=1"
    if q:
        sql += " AND (lower(pred_name) LIKE ? OR lower(succ_name) LIKE ?)"
        params += ["%" + q.lower() + "%", "%" + q.lower() + "%"]
    total = (db.q1("SELECT COUNT(*) c FROM (" + sql + ")", params) or {}).get("c", 0)
    sql += " ORDER BY pred_uid LIMIT ? OFFSET ?"
    rows = db.q(sql, params + [limit, offset])

    leaves = db.q("SELECT uid, name FROM activities WHERE project_id=? "
                  "AND is_summary=0", [pid])
    have_pred = {r["succ_uid"] for r in db.q(
        "SELECT DISTINCT succ_uid FROM relationships WHERE project_id=?", [pid])}
    have_succ = {r["pred_uid"] for r in db.q(
        "SELECT DISTINCT pred_uid FROM relationships WHERE project_id=?", [pid])}
    missing_pred = [l for l in leaves if l["uid"] not in have_pred]
    missing_succ = [l for l in leaves if l["uid"] not in have_succ]
    by_type = {r["type"]: r["c"] for r in db.q(
        "SELECT type, COUNT(*) c FROM relationships WHERE project_id=? "
        "GROUP BY type", [pid])}
    return {"total": total, "relationships": rows, "by_type": by_type,
            "missing_predecessor": missing_pred,
            "missing_successor": missing_succ}


@router.get("/projects/{pid}/critical-path")
def critical_path(pid: str):
    rows = db.q("SELECT * FROM activities WHERE project_id=? AND is_summary=0 "
                "AND critical=1 ORDER BY start", [pid])
    snap = _snapshot(pid)
    info = db.jloads((snap or {}).get("info_json"), {}) or {}
    dist = db.q("SELECT CASE WHEN total_float_days<0 THEN 'negative' "
                "WHEN total_float_days=0 THEN 'zero' "
                "WHEN total_float_days<=5 THEN 'upTo5' "
                "WHEN total_float_days<=20 THEN 'upTo20' "
                "WHEN total_float_days<=44 THEN 'upTo44' ELSE 'over44' END band, "
                "COUNT(*) c FROM activities WHERE project_id=? AND is_summary=0 "
                "AND total_float_days IS NOT NULL GROUP BY band", [pid])
    drivers = db.q("SELECT * FROM relationships WHERE project_id=? AND driving=1",
                   [pid])
    criticality_available = bool(snap and int(snap.get("criticality_available") or 0) == 1)
    return {"critical": rows if criticality_available else [],
            "float_distribution": ({d["band"]: d["c"] for d in dist}
                                   if criticality_available else {}),
            "driving_links": drivers if criticality_available else [],
            "analysis": info.get("analyze", {}) if criticality_available else {},
            "finish": (snap or {}).get("forecast_finish"),
            "criticality_available": criticality_available,
            "criticality_basis": (snap or {}).get("criticality_basis"),
            "criticality_threshold_days": (snap or {}).get("criticality_threshold_days"),
            "basis": ("Horizun schedule_analyze (MCP_FACT); VEDA preserves the source criticality method"
                      if criticality_available else
                      "Criticality is N/E: the selected source does not establish critical/float semantics, so transport or engine defaults are not presented as source facts.")}


# =====================================================================
#  Schedule quality / baselines / EV  (spec 23, 24, 28)
# =====================================================================
@router.get("/projects/{pid}/quality")
def quality(pid: str):
    rows = db.q("SELECT * FROM qa_findings WHERE project_id=? ORDER BY "
                "CASE status WHEN 'fail' THEN 0 WHEN 'not_evaluated' THEN 1 "
                "ELSE 2 END, code", [pid])
    for r in rows:
        r["task_uids"] = db.jloads(r.pop("task_uids_json", None), []) or []
    snap = _snapshot(pid)
    info = db.jloads((snap or {}).get("info_json"), {}) or {}
    return {"findings": rows, "summary": info.get("qa", {}),
            "health_score": (snap or {}).get("health_score"),
            "basis": "Horizun schedule_qa plus VEDA source-semantic guards "
                     "(DCMA 14-point plus Horizun rules)"}


@router.get("/projects/{pid}/baselines")
def baselines(pid: str, limit: int = Query(200, le=2000)):
    snap = _snapshot(pid)
    info = db.jloads((snap or {}).get("info_json"), {}) or {}
    present = bool((info.get("baseline") or {}).get("present"))
    rows = db.q("SELECT uid, display_id, name, wbs, start, finish, baseline_start, "
                "baseline_finish, start_variance_days, finish_variance_days, "
                "duration_days, baseline_duration_days, duration_variance_days, "
                "status, critical FROM activities WHERE project_id=? "
                "AND is_summary=0 AND baseline_finish IS NOT NULL "
                "ORDER BY finish_variance_days DESC LIMIT ?", [pid, limit])
    missed = [r for r in rows if (r.get("finish_variance_days") or 0) > 0]
    return {"baseline_present": present, "activities": rows,
            "missed_count": len(missed),
            "baseline_finish": (snap or {}).get("baseline_finish"),
            "message": None if present else
            "No baseline is stored in this schedule, so variance cannot be "
            "measured. Horizun reports baseline checks as not evaluated rather "
            "than passing them."}


@router.get("/projects/{pid}/earned-value")
def earned_value(pid: str):
    rows = db.q("SELECT * FROM earned_value WHERE project_id=? ORDER BY scope, "
                "scope_key", [pid])
    project = next((r for r in rows if r["scope"] == "project"), None)
    snap = _snapshot(pid)
    baseline_present = bool(snap and int(snap.get("baseline_present") or 0) == 1)
    if rows:
        message = None
    elif baseline_present:
        message = ("Baseline/reference dates are available, but current earned-value "
                   "metrics are N/E because the source does not establish the required "
                   "status/progress/cost inputs.")
    else:
        message = ("Earned value requires a usable baseline/reference plus current "
                   "status/progress/cost inputs. The required source facts are unavailable.")
    return {"project": project,
            "branches": [r for r in rows if r["scope"] == "branch"],
            "available": bool(rows), "baseline_present": baseline_present,
            "message": message}


@router.get("/projects/{pid}/timephased")
def timephased(pid: str):
    rows = db.q("SELECT * FROM timephased WHERE project_id=? ORDER BY period", [pid])
    return {"series": rows, "available": bool(rows),
            "measure": rows[0]["measure"] if rows else None,
            "granularity": rows[0]["granularity"] if rows else None,
            "message": None if rows else
            "No timephased curve is available for this schedule."}


# =====================================================================
#  Resources / assignments  (spec 25, 26)
# =====================================================================
@router.get("/projects/{pid}/resources")
def resources(pid: str):
    rows = db.q("SELECT * FROM resources WHERE project_id=? ORDER BY name", [pid])
    for r in rows:
        r["assigned_activities"] = (db.q1(
            "SELECT COUNT(DISTINCT task_uid) c FROM assignments WHERE project_id=? "
            "AND resource_uid=?", [pid, r["uid"]]) or {}).get("c", 0)
    return {"resources": rows}


@router.get("/projects/{pid}/assignments")
def assignments(pid: str, resource_uid: int | None = None,
                task_uid: int | None = None, limit: int = Query(500, le=5000)):
    sql = "SELECT * FROM assignments WHERE project_id=?"
    params: list = [pid]
    if resource_uid is not None:
        sql += " AND resource_uid=?"
        params.append(resource_uid)
    if task_uid is not None:
        sql += " AND task_uid=?"
        params.append(task_uid)
    sql += " ORDER BY resource_name, start LIMIT ?"
    return {"assignments": db.q(sql, params + [limit])}


# =====================================================================
#  Issues / risks  (spec 30, 31)
# =====================================================================
@router.get("/projects/{pid}/issues")
def issues(pid: str, status: str = "", severity: str = ""):
    sql = "SELECT * FROM issues WHERE project_id=?"
    params: list = [pid]
    if status:
        sql += " AND status=?"
        params.append(status)
    if severity:
        sql += " AND severity=?"
        params.append(severity)
    rows = db.q(sql + " ORDER BY CASE severity WHEN 'critical' THEN 0 "
                "WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, created_at DESC",
                params)
    for r in rows:
        r["activity_uids"] = db.jloads(r.pop("activity_uids_json", None), []) or []
        r["evidence_ids"] = db.jloads(r.pop("evidence_ids_json", None), []) or []
    return {"issues": rows}


@router.get("/projects/{pid}/risks")
def risks(pid: str, status: str = ""):
    sql = "SELECT * FROM risks WHERE project_id=?"
    params: list = [pid]
    if status:
        sql += " AND status=?"
        params.append(status)
    rows = db.q(sql + " ORDER BY score DESC, created_at DESC", params)
    for r in rows:
        r["activity_uids"] = db.jloads(r.pop("activity_uids_json", None), []) or []
        r["evidence_ids"] = db.jloads(r.pop("evidence_ids_json", None), []) or []
    return {"risks": rows}


@router.post("/projects/{pid}/issues/{iid}/status")
def set_issue_status(pid: str, iid: str, body: dict = Body(...)):
    row = db.q1("SELECT * FROM issues WHERE id=? AND project_id=?", [iid, pid])
    if not row:
        raise HTTPException(404, "no such issue")
    new = body.get("status", "open")
    db.update("issues", iid, {"status": new, "review_state": "confirmed",
                              "updated_at": db.now()})
    audit_mod.record(pid, actor="human", actor_type="human",
                     action="issue_status_changed", source="website",
                     entity_type="issue", entity_id=iid,
                     previous_value=row.get("status"), new_value=new,
                     approval="human", result="ok")
    return {"ok": True}


@router.post("/projects/{pid}/risks/{rid}/status")
def set_risk_status(pid: str, rid: str, body: dict = Body(...)):
    row = db.q1("SELECT * FROM risks WHERE id=? AND project_id=?", [rid, pid])
    if not row:
        raise HTTPException(404, "no such risk")
    new = body.get("status", "open")
    db.update("risks", rid, {"status": new, "review_state": "confirmed",
                             "updated_at": db.now()})
    audit_mod.record(pid, actor="human", actor_type="human",
                     action="risk_status_changed", source="website",
                     entity_type="risk", entity_id=rid,
                     previous_value=row.get("status"), new_value=new,
                     approval="human", result="ok")
    return {"ok": True}


# =====================================================================
#  Evidence  (spec 33-39)
# =====================================================================
@router.get("/projects/{pid}/evidence")
def evidence(pid: str, state: str = "", q: str = "", discipline: str = "",
             source: str = "", limit: int = Query(100, le=1000), offset: int = 0):
    sql = "SELECT * FROM evidence WHERE project_id=?"
    params: list = [pid]
    if state:
        sql += " AND state=?"
        params.append(state)
    if discipline:
        sql += " AND discipline=?"
        params.append(discipline)
    if source:
        sql += " AND source_file=?"
        params.append(source)
    if q:
        sql += " AND (lower(description) LIKE ? OR lower(IFNULL(crew,'')) LIKE ? " \
               "OR lower(IFNULL(chainage,'')) LIKE ?)"
        params += ["%" + q.lower() + "%"] * 3
    total = (db.q1("SELECT COUNT(*) c FROM (" + sql + ")", params) or {}).get("c", 0)
    rows = db.q(sql + " ORDER BY date DESC, created_at DESC LIMIT ? OFFSET ?",
                params + [limit, offset])
    ids = [r["id"] for r in rows]
    if ids:
        ph = ",".join("?" for _ in ids)
        links = db.q("SELECT * FROM evidence_links WHERE evidence_id IN (" + ph + ")",
                     ids)
        by_ev: dict = {}
        for l in links:
            by_ev.setdefault(l["evidence_id"], []).append(l)
        for r in rows:
            ls = by_ev.get(r["id"], [])
            primary = next((l for l in ls if not l.get("is_candidate")), None)
            r["linked_activity_uid"] = (primary or {}).get("activity_uid")
            r["linked_activity_name"] = (primary or {}).get("activity_name")
            r["link_relation"] = (primary or {}).get("relation")
            r["validator_result"] = (primary or {}).get("validator_result")
            r["candidate_count"] = sum(1 for l in ls if l.get("is_candidate"))
    counts = {r["state"]: r["c"] for r in db.q(
        "SELECT state, COUNT(*) c FROM evidence WHERE project_id=? GROUP BY state",
        [pid])}
    sources = [r["source_file"] for r in db.q(
        "SELECT DISTINCT source_file FROM evidence WHERE project_id=?", [pid])]
    disciplines = [r["discipline"] for r in db.q(
        "SELECT DISTINCT discipline FROM evidence WHERE project_id=? "
        "AND discipline IS NOT NULL", [pid])]
    return {"total": total, "evidence": rows, "state_counts": counts,
            "sources": sources, "disciplines": disciplines, "offset": offset}


@router.get("/projects/{pid}/evidence/{eid}")
def evidence_detail(pid: str, eid: str):
    e = db.q1("SELECT * FROM evidence WHERE id=? AND project_id=?", [eid, pid])
    if not e:
        raise HTTPException(404, "no such evidence")
    e["raw"] = db.jloads(e.pop("raw_json", None), {}) or {}
    links = db.q("SELECT * FROM evidence_links WHERE evidence_id=? "
                 "ORDER BY is_candidate, confidence DESC", [eid])
    for l in links:
        l["supporting_signals"] = db.jloads(l.get("supporting_signals"), []) or []
        l["conflicting_signals"] = db.jloads(l.get("conflicting_signals"), []) or []
        l["validator"] = db.jloads(l.pop("validator_json", None), {}) or {}
    f = db.q1("SELECT id, filename, sha256, ext, security_state, security_notes "
              "FROM files WHERE id=?", [e.get("file_id")]) if e.get("file_id") else None
    return {"evidence": e, "links": links, "source": f,
            "primary": next((l for l in links if not l.get("is_candidate")), None),
            "alternatives": [l for l in links if l.get("is_candidate")]}


@router.post("/projects/{pid}/evidence/{eid}/decision")
def evidence_decision(pid: str, eid: str, body: dict = Body(...)):
    """spec 36 - a human sets the evidence state, or accepts a link."""
    e = db.q1("SELECT * FROM evidence WHERE id=? AND project_id=?", [eid, pid])
    if not e:
        raise HTTPException(404, "no such evidence")
    decision = body.get("decision", "")
    uid = body.get("activity_uid")
    who = body.get("by", "human")

    if decision == "accept_link" and uid is not None:
        act = db.q1("SELECT * FROM activities WHERE project_id=? AND uid=?",
                    [pid, uid])
        if not act:
            raise HTTPException(404, "the selected activity does not exist")
        from ..pipeline import validators
        v = validators.validate_link(e, act, project_id=pid)
        db.ex("UPDATE evidence_links SET is_candidate=1, human_decision='rejected' "
              "WHERE evidence_id=?", [eid])
        row = db.q1("SELECT id FROM evidence_links WHERE evidence_id=? "
                    "AND activity_uid=?", [eid, uid])
        patch = {"is_candidate": 0, "human_decision": "accepted",
                 "decided_by": who, "decided_at": db.now(), "relation": "supporting",
                 "confidence": 0.95, "validator_result": v["result"],
                 "validator_json": db.jdumps(v), "provenance": "HUMAN_INPUT"}
        if row:
            db.update("evidence_links", row["id"], patch)
        else:
            db.insert("evidence_links", {
                "project_id": pid, "evidence_id": eid, "activity_uid": uid,
                "activity_name": (act or {}).get("name"),
                "supporting_signals": db.jdumps(["accepted by " + who]),
                **patch})
        db.update("evidence", eid, {"state": "confirmed"})
        actuals_result = actuals.generate_from_confirmed_evidence(pid, eid, int(uid))
        new_state = "confirmed"
    else:
        allowed = {"confirmed", "rejected", "duplicate", "conflicting",
                   "historical", "needs_review", "quarantined", "linked"}
        if decision not in allowed:
            raise HTTPException(400, "unknown decision")
        db.update("evidence", eid, {"state": decision})
        new_state = decision

    audit_mod.record(pid, actor=who, actor_type="human",
                     action="evidence_decision", source="website",
                     entity_type="evidence", entity_id=eid,
                     previous_value=e.get("state"), new_value=new_state,
                     approval=who, result=decision)
    linking.rebuild_observed_progress(pid)
    events.notify_ui(pid, "evidence_changed", {"evidence_id": eid})
    return {"ok": True, "state": new_state,
            "actuals": actuals_result if decision == "accept_link" and uid is not None else None}


@router.get("/projects/{pid}/observed-progress")
def observed_progress(pid: str):
    rows = db.q("SELECT o.*, a.name, a.wbs, a.display_id, a.status "
                "FROM observed_progress o LEFT JOIN activities a "
                "ON a.uid=o.activity_uid AND a.project_id=o.project_id "
                "WHERE o.project_id=? ORDER BY ABS(IFNULL(o.delta,0)) DESC", [pid])
    return {"rows": rows,
            "note": "Official progress comes from the schedule. Observed progress "
                    "is derived from field evidence. VEDA never replaces one with "
                    "the other."}


# =====================================================================
#  Reviews / proposals  (spec 40-42, 46-48)
# =====================================================================
@router.get("/projects/{pid}/reviews")
def list_reviews(pid: str, status: str = "open"):
    rows = reviews.open_for(pid) if status == "open" else reviews.all_for(pid, status)
    for r in rows:
        ids = r.get("affected_ids") or []
        if ids:
            r["affected_sample"] = db.q(
                "SELECT id, source_file, locator, date, crew, discipline, "
                "description FROM evidence WHERE id IN (" +
                ",".join("?" for _ in ids[:6]) + ")", ids[:6])
    return {"reviews": rows}


@router.post("/reviews/{rid}/answer")
def answer_review(rid: str, body: dict = Body(...)):
    r0 = reviews.get(rid)
    if not r0:
        raise HTTPException(404, "no such review")
    answer = (body.get("answer") or "").strip()
    by = body.get("by", "human")
    try:
        if r0.get("kind") == "clarification":
            final_status = "deferred" if answer == "Leave unassigned for now" else "answered"
            r = reviews.answer(rid, answer_text=answer, answered_by=by,
                               payload=body.get("payload") or {}, status=final_status,
                               wake=False)
            effect = linking.apply_cluster_answer(r["project_id"], r)
            reviews.record_effect(rid, effect)
            events.notify_ui(r["project_id"], "project_state_changed", {"reason": "human_decision"})
            return {"review": reviews.get(rid), "effect": effect,
                    "project_state": _project_state(r["project_id"]),
                    "note": "Decision applied immediately; no background review job was created."}

        if r0.get("kind") == "security_review":
            r = reviews.answer(rid, answer_text=answer, answered_by=by,
                               payload=body.get("payload") or {}, wake=False)
            effect = jobs.apply_security_answer_now(r["project_id"], r)
            reviews.record_effect(rid, effect)
            events.notify_ui(r["project_id"], "project_state_changed", {"reason": "security_decision"})
            return {"review": reviews.get(rid), "effect": effect,
                    "project_state": _project_state(r["project_id"]),
                    "note": "Security decision applied immediately."}

        if r0.get("kind") == "failed_validation":
            r = reviews.answer(rid, answer_text=answer, answered_by=by,
                               payload=body.get("payload") or {}, wake=False)
            if answer == "Retry analysis":
                ev = events.emit(events.ANALYSIS_REQUESTED, r["project_id"],
                                 {"reason": "human_retry_after_provider_failure"}, source="human")
                jid = jobs.ensure_event_job(ev)
                effect = {"action": "analysis_retry_queued", "job_id": jid}
            else:
                effect = {"action": "deterministic_results_kept"}
            reviews.record_effect(rid, effect)
            return {"review": reviews.get(rid), "effect": effect,
                    "project_state": _project_state(r["project_id"])}

        # Rare decisions that truly require background execution (for example a
        # legacy proposal review) may still wake one resume job.
        r = reviews.answer(rid, answer_text=answer, answered_by=by,
                           payload=body.get("payload") or {},
                           status=body.get("status", "answered"), wake=True)
        return {"review": r, "project_state": _project_state(r["project_id"]),
                "note": "Decision saved; required background work was queued."}
    except ValueError as exc:
        raise HTTPException(409, str(exc))


@router.post("/reviews/{rid}/reopen")
def reopen_review(rid: str, body: dict = Body(default={})):
    try:
        r = reviews.reopen(rid, by=body.get("by", "human"))
        ids = r.get("affected_ids") or []
        if ids:
            rows = db.q("SELECT * FROM evidence WHERE id IN (" + ",".join("?" for _ in ids) + ")", ids)
            linking.link_evidence(r["project_id"], evidence_rows=rows, raise_reviews=False)
        return {"review": reviews.get(rid), "project_state": _project_state(r["project_id"]),
                "note": "Decision reopened; affected evidence returned to review without creating an analysis job."}
    except KeyError:
        raise HTTPException(404, "no such review")
    except ValueError as exc:
        raise HTTPException(409, str(exc))


@router.get("/projects/{pid}/attention")
def attention(pid: str):
    _project_or_404(pid)
    open_reviews = reviews.open_for(pid)
    for r in open_reviews:
        ids = r.get("affected_ids") or []
        if ids:
            r["affected_sample"] = db.q(
                "SELECT id, source_file, locator, date, crew, discipline, description "
                "FROM evidence WHERE id IN (" + ",".join("?" for _ in ids[:6]) + ")", ids[:6])
            r["candidate_explanations"] = _review_candidate_explanations(pid, r, ids)
    props = [proposals.shape(p) for p in db.q(
        "SELECT * FROM proposals WHERE project_id=? AND approval_state='pending' ORDER BY created_at DESC", [pid])]
    deferred = int((db.q1("SELECT COUNT(*) c FROM evidence WHERE project_id=? AND state='deferred'", [pid]) or {}).get("c", 0))
    unresolved = int((db.q1("SELECT COUNT(*) c FROM evidence WHERE project_id=? AND state IN ('needs_review','conflicting')", [pid]) or {}).get("c", 0))
    recent = [r for r in reviews.all_for(pid, "all")
              if r.get("kind") == "clarification" and r.get("status") in ("answered","deferred")][:12]
    state_counts = {row["state"]: int(row["c"]) for row in db.q(
        "SELECT state, COUNT(*) c FROM evidence WHERE project_id=? GROUP BY state", [pid])}
    kind_counts = {row["kind"]: int(row["c"]) for row in db.q(
        "SELECT kind, COUNT(*) c FROM reviews WHERE project_id=? AND status='open' GROUP BY kind", [pid])}
    inbox_counts = {
        "matches": kind_counts.get("clarification", 0),
        "security": kind_counts.get("security_review", 0),
        "failures": kind_counts.get("failed_validation", 0),
        "changes": len(props),
        "conflicts": state_counts.get("conflicting", 0),
        "unresolved": (state_counts.get("needs_review", 0) +
                       state_counts.get("conflicting", 0)),
        "deferred": deferred,
    }
    return {"state": _project_state(pid), "reviews": open_reviews,
            "proposals": props, "recent_decisions": recent,
            "deferred_evidence": deferred, "unresolved_evidence": unresolved,
            "evidence_state_counts": state_counts, "inbox_counts": inbox_counts,
            "attention_count": len(open_reviews) + len(props) + (1 if unresolved and not open_reviews else 0)}


def _review_candidate_explanations(pid: str, review: dict, evidence_ids: list) -> list[dict]:
    """Explain activity options with persisted ranking evidence, never a fresh AI call."""
    if review.get("kind") != "clarification" or not evidence_ids:
        return []
    option_uids = (review.get("context") or {}).get("option_uids") or {}
    ordered_options = []
    for label in review.get("options") or []:
        uid = option_uids.get(label)
        if uid is not None and uid not in ordered_options:
            ordered_options.append(uid)
    if not ordered_options:
        return []

    evidence_ph = ",".join("?" for _ in evidence_ids)
    uid_ph = ",".join("?" for _ in ordered_options)
    links = db.q(
        "SELECT * FROM evidence_links WHERE project_id=? "
        "AND evidence_id IN (" + evidence_ph + ") "
        "AND activity_uid IN (" + uid_ph + ")",
        [pid, *evidence_ids, *ordered_options])
    activities = {row["uid"]: row for row in db.q(
        "SELECT uid, display_id, name, wbs, status, start, finish, "
        "percent_complete, critical FROM activities WHERE project_id=? "
        "AND uid IN (" + uid_ph + ")", [pid, *ordered_options])}

    grouped: dict[int, list[dict]] = {}
    for link in links:
        grouped.setdefault(link.get("activity_uid"), []).append(link)
    result = []
    for uid in ordered_options:
        rows = grouped.get(uid, [])
        act = activities.get(uid) or {}
        support: list[str] = []
        conflict: list[str] = []
        for link in rows:
            for signal in db.jloads(link.get("supporting_signals"), []) or []:
                if signal not in support:
                    support.append(signal)
            for signal in db.jloads(link.get("conflicting_signals"), []) or []:
                if signal not in conflict:
                    conflict.append(signal)
        probabilities = [float(row["calibrated_probability"])
                         for row in rows if row.get("calibrated_probability") is not None]
        rank_scores = [float(row["rank_score"])
                       for row in rows if row.get("rank_score") is not None]
        empirical = any(bool(row.get("calibration_is_empirical")) for row in rows)
        modes = [row.get("calibration_mode") for row in rows if row.get("calibration_mode")]
        result.append({
            "uid": uid,
            "option_label": next((label for label, option_uid in option_uids.items()
                                  if option_uid == uid), None),
            "display_id": act.get("display_id"),
            "name": act.get("name") or next((row.get("activity_name") for row in rows), None),
            "wbs": act.get("wbs"),
            "status": act.get("status"),
            "planned_start": act.get("start"),
            "planned_finish": act.get("finish"),
            "percent_complete": act.get("percent_complete"),
            "critical": bool(act.get("critical")),
            "matched_records": len({row.get("evidence_id") for row in rows}),
            "probability": max(probabilities) if probabilities else None,
            "calibration_mode": modes[0] if modes else None,
            "calibration_is_empirical": empirical,
            "rank_score": max(rank_scores) if rank_scores else None,
            "supporting_signals": support[:5],
            "conflicting_signals": conflict[:4],
        })
    return result


@router.get("/projects/{pid}/proposals")
def list_proposals(pid: str, state: str = ""):
    sql = "SELECT * FROM proposals WHERE project_id=?"
    params: list = [pid]
    if state:
        sql += " AND approval_state=?"
        params.append(state)
    rows = [proposals.shape(p) for p in
            db.q(sql + " ORDER BY created_at DESC", params)]
    return {"proposals": rows}


@router.get("/integrations/primavera/status")
def primavera_status(probe: bool = False):
    return primavera.probe_auth() if probe else primavera.status()


@router.get("/integrations/primavera/proposals/{proposal_id}/preview")
def primavera_proposal_preview(proposal_id: str):
    try:
        return primavera.preview_proposal(proposal_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/proposals/{pid_}/dry-run")
async def proposal_dry_run(pid_: str):
    res = await asyncio.get_event_loop().run_in_executor(
        None, lambda: proposals.dry_run(pid_))
    return res


@router.post("/proposals/{pid_}/decision")
async def proposal_decision(pid_: str, body: dict = Body(...)):
    """Approve (and execute) or reject a proposal - the human gate (spec 47)."""
    p = db.q1("SELECT * FROM proposals WHERE id=?", [pid_])
    if not p:
        raise HTTPException(404, "no such proposal")
    approve = bool(body.get("approve"))
    who = body.get("by", "human")
    proposals.approve(pid_, approved_by=who, approve_it=approve,
                      note=body.get("note"))
    if not approve:
        return {"ok": True, "approved": False}
    if p.get("dryrun_state") != "ok":
        await asyncio.get_event_loop().run_in_executor(
            None, lambda: proposals.dry_run(pid_))
    res = await asyncio.get_event_loop().run_in_executor(
        None, lambda: proposals.execute(pid_, actor=who))
    return {"ok": res.get("ok"), "approved": True, "execution": res}


# =====================================================================
#  Jobs / agent activity / MCP calls  (spec 50, 51)
# =====================================================================
@router.get("/projects/{pid}/jobs")
def list_jobs(pid: str, limit: int = 50):
    rows = db.q("SELECT * FROM jobs WHERE project_id=? ORDER BY created_at DESC "
                "LIMIT ?", [pid, limit])
    for r in rows:
        r["result"] = db.jloads(r.pop("result_json", None), {}) or {}
    return {"jobs": rows}


@router.post("/projects/{pid}/jobs/{jid}/retry")
def retry_job(pid: str, jid: str):
    job = db.q1("SELECT * FROM jobs WHERE id=? AND project_id=?", [jid, pid])
    if not job:
        raise HTTPException(404, "no such job")
    db.update("jobs", jid, {"status": "queued", "error": None, "phase": "queued"})
    jobs.enqueue(jid)
    return {"ok": True, "job": jid}


@router.get("/projects/{pid}/agent-activity")
def agent_activity(pid: str, job_id: str = "", limit: int = 200):
    sql = "SELECT * FROM agent_activity WHERE project_id=?"
    params: list = [pid]
    if job_id:
        sql += " AND job_id=?"
        params.append(job_id)
    rows = db.q(sql + " ORDER BY created_at DESC LIMIT ?", params + [limit])
    return {"activity": rows}


@router.get("/projects/{pid}/mcp-calls")
def mcp_calls(pid: str, limit: int = 200):
    return {"calls": db.q("SELECT * FROM mcp_calls WHERE project_id=? "
                          "ORDER BY created_at DESC LIMIT ?", [pid, limit])}


@router.get("/projects/{pid}/artifacts")
def artifacts(pid: str):
    return {"artifacts": db.q("SELECT * FROM artifacts WHERE project_id=? "
                              "ORDER BY created_at DESC", [pid])}


@router.get("/projects/{pid}/artifacts/{aid}/download")
def download_artifact(pid: str, aid: str):
    a = db.q1("SELECT * FROM artifacts WHERE id=? AND project_id=?", [aid, pid])
    if not a or not a.get("path") or not os.path.exists(a["path"]):
        raise HTTPException(404, "artifact has no stored file")
    return FileResponse(a["path"], filename=Path(a["path"]).name)


@router.get("/projects/{pid}/audit")
def audit_rows(pid: str, limit: int = Query(300, le=3000), offset: int = 0):
    return {"audit": audit_mod.for_project(pid, limit=limit, offset=offset)}


@router.get("/projects/{pid}/events")
def project_events(pid: str, limit: int = 100):
    return {"events": events.recent(pid, limit)}


# =====================================================================
#  Agent bridge (local_antigravity provider)
# =====================================================================
@router.get("/agent/inbox")
def agent_inbox():
    """The Antigravity agent polls this to find pending work."""
    # Never hand the IDE stale inbox work from a job that already failed,
    # timed out, or belonged to a previous server process.
    item = db.q1(
        "SELECT i.* FROM agent_inbox i JOIN jobs j ON j.id=i.job_id "
        "WHERE i.status='pending' AND j.status='running' "
        "ORDER BY i.created_at ASC LIMIT 1")
    if not item:
        return {"item": None}
    db.update("agent_inbox", item["id"], {
        "status": "claimed", "claimed_at": db.now()})
    # Gather project context for the agent
    project = db.q1("SELECT * FROM projects WHERE id=?",
                    [item["project_id"]]) or {}
    files = db.q("SELECT id, filename, kind, size_bytes, security_state "
                 "FROM files WHERE project_id=?", [item["project_id"]])
    return {
        "item": {
            "inbox_id": item["id"],
            "project_id": item["project_id"],
            "job_id": item["job_id"],
            "prompt": item["prompt"],
            "system_prompt": item.get("system_prompt", ""),
            "schema": db.jloads(item.get("schema_json"), None),
            "project": {k: project.get(k)
                        for k in ("id", "name", "client", "location",
                                  "description", "status")},
            "files": files,
            "created_at": item.get("created_at"),
        },
    }


@router.post("/agent/tool")
def agent_tool(body: dict = Body(...)):
    """The Antigravity agent calls VEDA tools through this endpoint."""
    tool_name = body.get("tool", "")
    args = body.get("args") or {}
    project_id = body.get("project_id", "")
    from ..mcpc import veda_server as vtools
    fn = vtools.HANDLERS.get(tool_name)
    if fn is None:
        raise HTTPException(400, "unknown tool: " + tool_name)
    try:
        result = fn(args, project_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, type(exc).__name__ + ": " + str(exc))
    text = "".join(c.get("text", "") for c in result.get("content", []))
    if result.get("isError"):
        return {"ok": False, "error": text}
    try:
        return {"ok": True, "result": json.loads(text)}
    except Exception:
        return {"ok": True, "result": text}


@router.post("/agent/result")
def agent_result(body: dict = Body(...)):
    """The Antigravity agent posts its structured result here."""
    inbox_id = body.get("inbox_id")
    if not inbox_id:
        raise HTTPException(400, "inbox_id is required")
    inbox = db.q1("SELECT * FROM agent_inbox WHERE id=?", [inbox_id])
    if not inbox:
        raise HTTPException(404, "no such inbox item")
    result = body.get("result")
    error = body.get("error")
    agent_events = body.get("events") or []
    # Write to the outbox so the provider thread picks it up
    oid = db.insert("agent_outbox", {
        "inbox_id": inbox_id,
        "project_id": inbox["project_id"],
        "job_id": inbox["job_id"],
        "result_json": db.jdumps(result) if result is not None else None,
        "error": error,
        "events_json": db.jdumps(agent_events) if agent_events else None,
    })
    db.update("agent_inbox", inbox_id, {
        "status": "done", "finished_at": db.now()})
    return {"ok": True, "outbox_id": oid}


@router.get("/agent/inbox/all")
def agent_inbox_all(limit: int = 20):
    """View all inbox items (for debugging)."""
    items = db.q("SELECT * FROM agent_inbox ORDER BY created_at DESC "
                 "LIMIT ?", [limit])
    return {"items": items}


# =====================================================================
#  Actions
# =====================================================================
@router.post("/projects/{pid}/analyze")
def analyze(pid: str):
    _project_or_404(pid)
    ev = events.emit(events.ANALYSIS_REQUESTED, pid, {"manual": True},
                     source="website")
    return {"event": ev["id"], "note": "analysis job queued"}


@router.post("/projects/{pid}/ask")
def ask(pid: str, body: dict = Body(...)):
    """spec 55 - optional grounded project questions."""
    _project_or_404(pid)
    question = (body.get("question") or "").strip()
    if not question:
        raise HTTPException(400, "question is required")
    ev = events.emit(events.USER_QUESTION, pid, {"question": question},
                     source="website")
    return {"event": ev["id"], "note": "the agent will investigate before answering"}


@router.get("/projects/{pid}/answers")
def answers(pid: str, limit: int = 20):
    return {"answers": db.q("SELECT * FROM artifacts WHERE project_id=? "
                            "AND kind='answer' ORDER BY created_at DESC LIMIT ?",
                            [pid, limit])}


# =====================================================================
#  Live event stream (SSE) - replaces polling for the dashboard
# =====================================================================
@router.get("/stream")
async def stream(request: Request, project_id: str = ""):
    s = events.open_stream(project_id or None)

    async def gen():
        loop = asyncio.get_event_loop()
        last = time.time()
        try:
            yield "event: hello\ndata: {}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                rec = await loop.run_in_executor(None, lambda: s.get(1.0))
                if rec is not None:
                    payload = {"type": rec.get("type"),
                               "project_id": rec.get("project_id"),
                               "payload": rec.get("payload", {})}
                    yield "data: " + json.dumps(payload, default=str) + "\n\n"
                    last = time.time()
                elif time.time() - last > 15:
                    yield ": keepalive\n\n"
                    last = time.time()
        finally:
            s.close()

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})
