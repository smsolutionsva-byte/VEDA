"""Proposed schedule changes (spec 46, 47, 48).

    agent proposes -> validators -> Horizun dry-run -> impact -> human approval
    -> verified write

Two rules dominate this module:

  spec 12  the uploaded schedule is a source document. Every write happens on a
           revision copy; the original file is never opened read-write.
  spec 48  a write is not a success because the tool returned. VEDA re-reads the
           value independently and records requested vs resulting.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from .. import audit, config, db, events
from ..mcpc import McpError, horizun, schedule_ops
from . import validators

FIELD_TO_OP = {
    "percentComplete": "percentComplete",
    "actualStart": "actualStart",
    "actualFinish": "actualFinish",
    "start": "start",
    "finish": "finish",
    "duration": "duration",
    "deadline": "deadline",
    "notes": "notes",
    "name": "name",
    "constraintType": "constraintType",
    "constraintDate": "constraintDate",
}

ACTIVITY_FIELD = {
    "percentComplete": "percent_complete",
    "actualStart": "actual_start",
    "actualFinish": "actual_finish",
    "start": "start",
    "finish": "finish",
    "duration": "duration_days",
    "deadline": "deadline",
    "notes": "notes",
    "name": "name",
    "constraintType": "constraint_type",
    "constraintDate": "constraint_date",
}

TASK_QUERY_FIELD = {
    "percentComplete": "percentComplete",
    "actualStart": "actualStart",
    "actualFinish": "actualFinish",
    "start": "start",
    "finish": "finish",
    "duration": "duration",
    "deadline": "deadline",
    "notes": "notes",
    "name": "name",
    "constraintType": "constraintType",
    "constraintDate": "constraintDate",
}


def current_schedule_path(project_id: str) -> str | None:
    """The newest schedule VEDA holds - the latest revision, else the upload."""
    snap = db.q1("SELECT source_path FROM schedule_snapshots WHERE project_id=? "
                 "AND is_current=1 ORDER BY created_at DESC LIMIT 1", [project_id])
    if snap and snap.get("source_path") and os.path.exists(snap["source_path"]):
        return snap["source_path"]
    p = db.q1("SELECT schedule_file_id FROM projects WHERE id=?", [project_id])
    if p and p.get("schedule_file_id"):
        f = db.q1("SELECT stored_path FROM files WHERE id=?", [p["schedule_file_id"]])
        if f and os.path.exists(f["stored_path"]):
            return f["stored_path"]
    f = db.q1("SELECT stored_path FROM files WHERE project_id=? AND kind='schedule' "
              "ORDER BY created_at DESC LIMIT 1", [project_id])
    return f["stored_path"] if f and os.path.exists(f["stored_path"]) else None


def create(project_id: str, *, target_uid: int | None, field: str,
           proposed_value: str, reason: str = "", target_type: str = "activity",
           target_name: str | None = None, evidence_ids: list | None = None,
           confidence: float = 0.5, job_id: str | None = None,
           provenance: str = "AI_INFERENCE") -> str:
    act = db.q1("SELECT * FROM activities WHERE project_id=? AND uid=?",
                [project_id, target_uid]) if target_uid is not None else None
    current = None
    if act:
        col = ACTIVITY_FIELD.get(field)
        if col:
            current = act.get(col)

    pid = db.insert("proposals", {
        "project_id": project_id, "job_id": job_id,
        "target_type": target_type, "target_uid": target_uid,
        "target_name": target_name or (act or {}).get("name"),
        "field": field,
        "current_value": None if current is None else str(current),
        "proposed_value": str(proposed_value),
        "requested_value": str(proposed_value),
        "reason": reason,
        "evidence_ids_json": db.jdumps(evidence_ids or []),
        "confidence": confidence,
        "provenance": provenance,
        "updated_at": db.now(),
    })
    audit.record(project_id, actor="agent", actor_type="agent",
                 action="proposal_created", job_id=job_id,
                 entity_type="proposal", entity_id=pid,
                 previous_value=current, new_value=proposed_value,
                 result=reason[:200] if reason else None,
                 detail={"field": field, "target_uid": target_uid})
    validate(pid)
    return pid


def validate(proposal_id: str) -> dict:
    p = db.q1("SELECT * FROM proposals WHERE id=?", [proposal_id])
    if not p:
        raise KeyError("no such proposal")
    act = db.q1("SELECT * FROM activities WHERE project_id=? AND uid=?",
                [p["project_id"], p["target_uid"]])
    res = validators.validate_proposal(
        p, act, project_id=p["project_id"],
        approved=(p.get("approval_state") == "approved"),
        capabilities=horizun.capabilities())
    db.update("proposals", proposal_id, {
        "validation_state": "passed" if res["result"] != validators.FAIL else "failed",
        "validation_json": db.jdumps(res),
        "updated_at": db.now(),
    })
    return res


def _op_for(p: dict) -> dict:
    field = p["field"]
    val: Any = p["proposed_value"]
    if field == "percentComplete":
        try:
            val = float(str(val).replace("%", "").strip())
        except ValueError:
            pass
    return {"op": "update", "uid": p["target_uid"], FIELD_TO_OP[field]: val}


def dry_run(proposal_id: str, job_id: str | None = None) -> dict:
    """Simulate through Horizun and store the real impact (spec 47).

    The simulation runs against a throwaway copy of the schedule, so neither the
    original upload nor any stored revision is touched.
    """
    p = db.q1("SELECT * FROM proposals WHERE id=?", [proposal_id])
    if not p:
        raise KeyError("no such proposal")
    project_id = p["project_id"]

    if p.get("validation_state") != "passed":
        res = validate(proposal_id)
        if res["result"] == validators.FAIL:
            db.update("proposals", proposal_id, {
                "dryrun_state": "failed",
                "dryrun_json": db.jdumps({"error": "validation failed",
                                          "validation": res}),
                "updated_at": db.now()})
            return {"ok": False, "error": "validation failed", "validation": res}

    if p["field"] not in FIELD_TO_OP:
        return {"ok": False, "error": "field is not writable: " + str(p["field"])}

    if not horizun.capabilities().get("dry_run_simulation", True):
        db.update("proposals", proposal_id, {"dryrun_state": "failed",
                                             "dryrun_json": db.jdumps(
                                                 {"error": "dry run unsupported"})})
        return {"ok": False, "error": "Horizun reports dry-run is unavailable"}

    src = current_schedule_path(project_id)
    if not src:
        return {"ok": False, "error": "no schedule file is available"}

    scratch = Path(config.project_dir(project_id)) / "revisions" / "_dryrun"
    scratch.mkdir(parents=True, exist_ok=True)
    tmp = scratch / ("dry_" + proposal_id + Path(src).suffix)
    shutil.copy2(src, tmp)

    try:
        handle = horizun.call("project_open",
                              {"path": str(tmp), "mode": "readwrite"},
                              project_id=project_id, job_id=job_id, timeout=300)["handle"]
        before = _read_field(handle, p["target_uid"], p["field"], project_id, job_id)
        info_before = horizun.call("project_info", {"handle": handle},
                                   project_id=project_id, job_id=job_id, log=False)
        res = horizun.call("tasks_write",
                           {"handle": handle, "ops": [_op_for(p)], "dryRun": True},
                           project_id=project_id, job_id=job_id, timeout=300)
        horizun.try_call("project_save",
                         {"handle": handle, "op": "close", "discardChanges": True},
                         log=False)
    except McpError as exc:
        db.update("proposals", proposal_id, {
            "dryrun_state": "failed",
            "dryrun_json": db.jdumps({"error": str(exc)}),
            "updated_at": db.now()})
        audit.record(project_id, actor="system", actor_type="mcp",
                     action="proposal_dry_run", tool="Horizun/tasks_write",
                     job_id=job_id, entity_type="proposal", entity_id=proposal_id,
                     result="failed: " + str(exc)[:300])
        return {"ok": False, "error": str(exc)}
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass

    impact = (res or {}).get("impact") or {}
    rejected = (res or {}).get("rejected") or []
    finish_before = (info_before or {}).get("finishDate")
    payload = {
        "applied": (res or {}).get("applied"),
        "rejected": rejected,
        "impact": impact,
        "current_value": before,
        "finish_before": finish_before,
        "finish_after": impact.get("projectFinishAfter"),
        "notes": (res or {}).get("notes") or [],
    }
    ok = not rejected and (res or {}).get("applied", 0) > 0
    db.update("proposals", proposal_id, {
        "dryrun_state": "ok" if ok else "failed",
        "dryrun_json": db.jdumps(payload),
        "impact_tasks_moved": impact.get("tasksMoved"),
        "impact_finish_before": _day(finish_before),
        "impact_finish_after": _day(impact.get("projectFinishAfter")),
        "impact_critical_change": 1 if impact.get("criticalPathChanged") else 0,
        "impact_negative_float": impact.get("newNegativeFloat"),
        "current_value": None if before is None else str(before),
        "updated_at": db.now(),
    })
    audit.record(project_id, actor="system", actor_type="mcp",
                 action="proposal_dry_run", tool="Horizun/tasks_write",
                 job_id=job_id, entity_type="proposal", entity_id=proposal_id,
                 new_value=p["proposed_value"],
                 result="ok" if ok else "rejected",
                 detail={"impact": impact, "rejected": rejected})
    events.notify_ui(project_id, "proposals_changed", {"proposal_id": proposal_id})
    return {"ok": ok, **payload}


def _day(v: Any) -> str | None:
    if not v:
        return None
    return str(v).split("T")[0]


def _read_field(handle: str, uid: int, field: str, project_id: str,
                job_id: str | None) -> Any:
    res = horizun.call("tasks_query", {"handle": handle, "uids": [uid], "limit": 1},
                       project_id=project_id, job_id=job_id, log=False, timeout=120)
    rows = schedule_ops._rows(res)
    if not rows:
        return None
    return rows[0].get(TASK_QUERY_FIELD.get(field, field))


def approve(proposal_id: str, approved_by: str = "human",
            approve_it: bool = True, note: str | None = None) -> dict:
    p = db.q1("SELECT * FROM proposals WHERE id=?", [proposal_id])
    if not p:
        raise KeyError("no such proposal")
    state = "approved" if approve_it else "rejected"
    db.update("proposals", proposal_id, {
        "approval_state": state, "approved_by": approved_by,
        "approved_at": db.now(), "updated_at": db.now(),
    })
    audit.record(p["project_id"], actor=approved_by, actor_type="human",
                 action="proposal_" + state, source="website",
                 job_id=p.get("job_id"), entity_type="proposal",
                 entity_id=proposal_id, previous_value=p.get("current_value"),
                 new_value=p.get("proposed_value"), approval=approved_by,
                 result=note or state)
    validate(proposal_id)
    events.notify_ui(p["project_id"], "proposals_changed",
                     {"proposal_id": proposal_id})
    return db.q1("SELECT * FROM proposals WHERE id=?", [proposal_id]) or {}


def execute(proposal_id: str, job_id: str | None = None,
            actor: str = "human") -> dict:
    """Apply an approved proposal to a revision copy, then verify it (spec 48)."""
    p = db.q1("SELECT * FROM proposals WHERE id=?", [proposal_id])
    if not p:
        raise KeyError("no such proposal")
    project_id = p["project_id"]

    if p.get("approval_state") != "approved":
        return {"ok": False, "error": "proposal is not approved"}
    if p.get("validation_state") != "passed":
        return {"ok": False, "error": "proposal has not passed validation"}
    if p.get("dryrun_state") != "ok":
        return {"ok": False, "error": "proposal has no successful dry-run"}
    if p.get("execution_state") == "executed":
        return {"ok": False, "error": "proposal has already been executed"}

    src = current_schedule_path(project_id)
    if not src:
        return {"ok": False, "error": "no schedule file is available"}

    from . import ingest
    dest = ingest.copy_for_edit(project_id, src, suffix="rev")

    requested = p["proposed_value"]
    try:
        handle = horizun.call("project_open", {"path": dest, "mode": "readwrite"},
                              project_id=project_id, job_id=job_id,
                              timeout=300)["handle"]
        before = _read_field(handle, p["target_uid"], p["field"], project_id, job_id)
        res = horizun.call("tasks_write",
                           {"handle": handle, "ops": [_op_for(p)], "dryRun": False},
                           project_id=project_id, job_id=job_id, timeout=300)
        # Independent re-read. Horizun verifies too; VEDA does not take its word.
        after = _read_field(handle, p["target_uid"], p["field"], project_id, job_id)
        save = horizun.call("project_save",
                            {"handle": handle, "op": "save_as", "path": dest,
                             "format": "mspdi", "keepOpen": False},
                            project_id=project_id, job_id=job_id, timeout=300)
    except McpError as exc:
        db.update("proposals", proposal_id, {
            "execution_state": "failed", "verification_state": "failed",
            "resulting_value": None, "updated_at": db.now(),
            "rejected_fields_json": db.jdumps([{"field": p["field"],
                                                "reason": str(exc)}])})
        audit.record(project_id, actor=actor, actor_type="agent",
                     action="proposal_execute", tool="Horizun/tasks_write",
                     job_id=job_id, entity_type="proposal", entity_id=proposal_id,
                     previous_value=p.get("current_value"), new_value=requested,
                     approval=p.get("approved_by"), verification="failed",
                     result="error: " + str(exc)[:300])
        return {"ok": False, "error": str(exc)}

    schedule_ops.forget_handles()
    rejected = (res or {}).get("rejected") or []
    verified = _matches(requested, after, p["field"])
    if rejected:
        verification = "failed"
    elif verified:
        verification = "verified"
    else:
        verification = "partial"

    db.update("proposals", proposal_id, {
        "execution_state": "executed" if not rejected else "failed",
        "executed_at": db.now(),
        "verification_state": verification,
        "requested_value": str(requested),
        "resulting_value": None if after is None else str(after),
        "verified_fields_json": db.jdumps([p["field"]] if verified else []),
        "rejected_fields_json": db.jdumps(rejected),
        "output_path": dest,
        "updated_at": db.now(),
    })

    db.insert("artifacts", {
        "project_id": project_id, "job_id": job_id, "kind": "schedule_revision",
        "title": Path(dest).name, "path": dest, "format": "mspdi",
        "size_bytes": os.path.getsize(dest) if os.path.exists(dest) else None,
        "description": ("Revision produced by applying proposal " + proposal_id +
                        " (" + str(p["field"]) + " on uid " +
                        str(p["target_uid"]) + "). The original upload is "
                        "unchanged."),
        "provenance": "DERIVED",
    })

    audit.record(project_id, actor=actor, actor_type="agent",
                 action="proposal_execute", tool="Horizun/tasks_write",
                 source="proposal", job_id=job_id, entity_type="proposal",
                 entity_id=proposal_id, previous_value=before,
                 new_value=requested, approval=p.get("approved_by"),
                 verification=verification,
                 result=("written to " + Path(dest).name),
                 detail={"requested": requested, "resulting": after,
                         "rejected": rejected, "save": save,
                         "output_path": dest})

    events.emit(events.SCHEDULE_CHANGED, project_id, {
        "proposal_id": proposal_id, "path": dest,
        "verification": verification, "field": p["field"],
        "target_uid": p["target_uid"],
    }, source="proposal")

    return {"ok": not rejected, "verification": verification,
            "requested_value": requested, "resulting_value": after,
            "rejected": rejected, "output_path": dest}


def _matches(requested: Any, actual: Any, field: str) -> bool:
    if actual is None:
        return False
    if field == "percentComplete":
        try:
            return abs(float(str(requested).replace("%", "")) -
                       float(str(actual).replace("%", ""))) < 0.51
        except (TypeError, ValueError):
            return False
    if field in ("actualStart", "actualFinish", "start", "finish", "deadline",
                 "constraintDate"):
        return str(actual).split("T")[0] == str(requested).split("T")[0]
    if field == "duration":
        a = str(actual).strip().lower().rstrip("d")
        b = str(requested).strip().lower().rstrip("d")
        try:
            return abs(float(a) - float(b)) < 0.01
        except ValueError:
            return a == b
    return str(actual).strip() == str(requested).strip()


def shape(p: dict) -> dict:
    p = dict(p)
    p["evidence_ids"] = db.jloads(p.pop("evidence_ids_json", None), []) or []
    p["validation"] = db.jloads(p.pop("validation_json", None), {}) or {}
    p["dryrun"] = db.jloads(p.pop("dryrun_json", None), {}) or {}
    p["verified_fields"] = db.jloads(p.pop("verified_fields_json", None), []) or []
    p["rejected_fields"] = db.jloads(p.pop("rejected_fields_json", None), []) or []
    return p
