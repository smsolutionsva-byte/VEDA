"""Oracle Primavera P6 REST adapter with sandbox-first write gates.

The adapter targets the Release 26 Activity API. SyncService remains a second
transport option for larger external-system synchronization batches; the same
proposal mapping and allow-list gates apply before either transport is used.
"""
from __future__ import annotations

from typing import Any

import httpx

from .. import audit, config, db

FIELD_MAP = {
    "actualStart": "ActualStartDate",
    "actualFinish": "ActualFinishDate",
    "percentComplete": "DurationPercentComplete",
    "remainingDuration": "RemainingDuration",
}


def status() -> dict:
    configured = bool(config.P6_BASE_URL and config.P6_TOKEN_URL and
                      config.P6_CLIENT_ID and config.P6_CLIENT_SECRET)
    gates = {
        "sandbox_environment": config.P6_ENVIRONMENT == "sandbox",
        "write_enabled": config.P6_WRITE_ENABLED,
        "project_allowlist": bool(config.P6_ALLOWED_PROJECT_IDS),
        "activity_id_mapping": config.P6_UID_IS_OBJECT_ID,
        "duration_conversion": config.P6_HOURS_PER_DAY is not None,
    }
    return {
        "configured": configured, "environment": config.P6_ENVIRONMENT,
        "base_url": config.P6_BASE_URL or None,
        "transport": "P6 REST Activity API",
        "writes_armed": configured and all((gates["sandbox_environment"],
                                             gates["write_enabled"],
                                             gates["project_allowlist"])),
        "gates": gates,
        "allowed_project_count": len(config.P6_ALLOWED_PROJECT_IDS),
        "note": ("Sandbox adapter is configured; writes still require an approved "
                 "proposal and an allow-listed P6 ProjectObjectId." if configured else
                 "Set the VEDA_P6_* sandbox environment variables to connect."),
    }


def _token() -> str:
    if not status()["configured"]:
        raise RuntimeError("Primavera OAuth is not configured")
    with httpx.Client(timeout=30) as client:
        response = client.post(
            config.P6_TOKEN_URL,
            data={"grant_type": "client_credentials"},
            auth=(config.P6_CLIENT_ID, config.P6_CLIENT_SECRET),
            headers={"Accept": "application/json"})
        response.raise_for_status()
        token = response.json().get("access_token")
        if not token:
            raise RuntimeError("Primavera token endpoint returned no access_token")
        return str(token)


def probe_auth() -> dict:
    try:
        _token()
        return {**status(), "auth_ok": True}
    except Exception as exc:  # noqa: BLE001 - safe diagnostic boundary
        return {**status(), "auth_ok": False,
                "error": type(exc).__name__ + ": " + str(exc)[:300]}


def _activity_object_id(proposal: dict) -> tuple[int | None, str]:
    activity = db.q1("SELECT custom_json FROM activities WHERE project_id=? AND uid=?",
                     [proposal["project_id"], proposal.get("target_uid")])
    custom = db.jloads((activity or {}).get("custom_json"), {}) or {}
    for key in ("ObjectId", "objectId", "p6_object_id", "P6ObjectId"):
        if custom.get(key) is not None:
            return int(custom[key]), "activity.custom_json." + key
    if config.P6_UID_IS_OBJECT_ID and proposal.get("target_uid") is not None:
        return int(proposal["target_uid"]), "VEDA_P6_UID_IS_OBJECT_ID"
    return None, "unmapped"


def preview_proposal(proposal_id: str) -> dict:
    proposal = db.q1("SELECT * FROM proposals WHERE id=?", [proposal_id])
    if not proposal:
        raise KeyError("no such proposal")
    p6_field = FIELD_MAP.get(str(proposal.get("field")))
    object_id, mapping_basis = _activity_object_id(proposal)
    blockers: list[str] = []
    if not p6_field:
        blockers.append("field is outside the P6 actuals adapter allow-list")
    if object_id is None:
        blockers.append("activity has no verified P6 ObjectId mapping")
    value: Any = proposal.get("proposed_value")
    if proposal.get("field") == "percentComplete":
        value = float(str(value).replace("%", "").strip())
    elif proposal.get("field") == "remainingDuration":
        if config.P6_HOURS_PER_DAY is None:
            blockers.append("configure project hours/day before converting remaining days")
        else:
            value = float(str(value).lower().replace("days", "").replace("day", "").rstrip("d ")) * config.P6_HOURS_PER_DAY
    body = {"ObjectId": object_id}
    if p6_field:
        body[p6_field] = value
    return {
        "proposal_id": proposal_id, "ready": not blockers,
        "method": "PUT", "path": "/activity", "body": [body],
        "mapping_basis": mapping_basis, "blockers": blockers,
        "units": ("hours converted from VEDA working days" if
                  proposal.get("field") == "remainingDuration" else None),
        "governance": {
            "approval_state": proposal.get("approval_state"),
            "validation_state": proposal.get("validation_state"),
            "source_event_id": proposal.get("source_event_id"),
        },
    }


def write_approved(proposal_id: str, *, p6_project_object_id: str,
                   actor: str) -> dict:
    """Write one approved proposal after every independent sandbox gate passes."""
    adapter = status()
    if config.P6_ENVIRONMENT != "sandbox":
        raise RuntimeError("this release permits Primavera writes only in sandbox")
    if not adapter["writes_armed"]:
        raise RuntimeError("Primavera write gates are not armed")
    if str(p6_project_object_id) not in config.P6_ALLOWED_PROJECT_IDS:
        raise RuntimeError("P6 ProjectObjectId is not in the sandbox allow-list")
    proposal = db.q1("SELECT * FROM proposals WHERE id=?", [proposal_id])
    if not proposal or proposal.get("approval_state") != "approved":
        raise RuntimeError("proposal must be approved before P6 write")
    if proposal.get("validation_state") != "passed":
        raise RuntimeError("proposal must pass deterministic validation")
    preview = preview_proposal(proposal_id)
    if not preview["ready"]:
        raise RuntimeError("; ".join(preview["blockers"]))
    token = _token()
    with httpx.Client(timeout=60) as client:
        response = client.put(
            config.P6_BASE_URL + preview["path"], json=preview["body"],
            headers={"Authorization": "Bearer " + token,
                     "Accept": "application/json", "Content-Type": "application/json"})
        response.raise_for_status()
        result = response.json() if response.content else {}
    audit.record(
        proposal["project_id"], actor=actor, actor_type="human",
        action="primavera_activity_write", source="p6_rest_sandbox",
        entity_type="proposal", entity_id=proposal_id,
        approval=proposal.get("approved_by"), result="accepted by P6 sandbox",
        detail={"project_object_id": p6_project_object_id,
                "request": preview["body"], "response": result})
    return {"ok": True, "sandbox": True, "response": result}
