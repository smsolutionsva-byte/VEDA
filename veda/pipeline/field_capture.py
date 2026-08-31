"""Mobile field capture persistence and confirmation workflow."""
from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timedelta
from typing import Any

from .. import audit, db, events
from . import actuals, extract, ingest

_CLIENT_ID = re.compile(r"^[A-Za-z0-9._:-]{8,120}$")
_LANG = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")
_EVENT_STATES = {"start", "progress", "finish"}
MAX_ATTACHMENTS = 8
MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024
MAX_TOTAL_BYTES = 80 * 1024 * 1024


def _float(value: Any, *, minimum: float | None = None,
           maximum: float | None = None, label: str) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(label + " must be numeric") from exc
    if minimum is not None and number < minimum:
        raise ValueError(label + " is below the permitted range")
    if maximum is not None and number > maximum:
        raise ValueError(label + " is above the permitted range")
    return number


def _occurred(value: Any) -> tuple[str, str]:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("occurred_at is required")
    normalized = raw.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
        day = parsed.date()
    except ValueError:
        try:
            day = date.fromisoformat(raw[:10])
        except ValueError as exc:
            raise ValueError("occurred_at must be an ISO date or date-time") from exc
    if day > date.today() + timedelta(days=1):
        raise ValueError("a field actual cannot be dated in the future")
    return raw, day.isoformat()


def validate_payload(payload: dict) -> dict:
    client_id = str(payload.get("client_capture_id") or "").strip()
    if not _CLIENT_ID.fullmatch(client_id):
        raise ValueError("client_capture_id is invalid")
    text = str(payload.get("confirmed_text") or "").strip()
    if not text:
        raise ValueError("confirm the field update before saving")
    if len(text) > 5000:
        raise ValueError("confirmed_text exceeds 5,000 characters")
    state = str(payload.get("event_state") or "").strip().lower()
    if state not in _EVENT_STATES:
        raise ValueError("event_state must be start, progress, or finish")
    language = str(payload.get("language") or "en").strip()
    if not _LANG.fullmatch(language):
        raise ValueError("language must be a valid language tag")
    occurred_at, event_date = _occurred(payload.get("occurred_at"))
    progress = _float(payload.get("observed_progress"), minimum=0, maximum=100,
                      label="observed_progress")
    remaining = _float(payload.get("remaining_days"), minimum=0,
                       label="remaining_days")
    if state == "finish":
        progress, remaining = 100.0, 0.0
    latitude = _float(payload.get("latitude"), minimum=-90, maximum=90,
                      label="latitude")
    longitude = _float(payload.get("longitude"), minimum=-180, maximum=180,
                       label="longitude")
    accuracy = _float(payload.get("location_accuracy_m"), minimum=0,
                      label="location_accuracy_m")
    activity_uid = payload.get("activity_uid")
    if activity_uid not in (None, ""):
        try:
            activity_uid = int(activity_uid)
        except (TypeError, ValueError) as exc:
            raise ValueError("activity_uid must be an integer") from exc
    else:
        activity_uid = None
    return {
        "client_capture_id": client_id, "confirmed_text": text,
        "original_text": str(payload.get("original_text") or "")[:5000],
        "event_state": state, "language": language,
        "occurred_at": occurred_at, "event_date": event_date,
        "reporter": str(payload.get("reporter") or "Field reporter").strip()[:180],
        "observed_progress": progress, "remaining_days": remaining,
        "activity_uid": activity_uid,
        "location_label": str(payload.get("location_label") or "").strip()[:500],
        "latitude": latitude, "longitude": longitude,
        "location_accuracy_m": accuracy,
        "location_source": str(payload.get("location_source") or "manual")[:30],
        "sync_source": str(payload.get("sync_source") or "online")[:30],
    }


def _shape(row: dict) -> dict:
    out = dict(row)
    out["media_file_ids"] = db.jloads(out.pop("media_file_ids_json", None), []) or []
    out["proposal_ids"] = db.jloads(out.pop("proposal_ids_json", None), []) or []
    return out


def list_for_project(project_id: str, limit: int = 100) -> list[dict]:
    return [_shape(row) for row in db.q(
        "SELECT * FROM field_captures WHERE project_id=? "
        "ORDER BY created_at DESC LIMIT ?", [project_id, limit])]


def store(project_id: str, payload: dict,
          attachments: list[tuple[str, bytes, str | None]]) -> dict:
    data = validate_payload(payload)
    existing = db.q1("SELECT * FROM field_captures WHERE project_id=? "
                     "AND client_capture_id=?",
                     [project_id, data["client_capture_id"]])
    if existing:
        result = _shape(existing)
        result["idempotent_replay"] = True
        return result
    if len(attachments) > MAX_ATTACHMENTS:
        raise ValueError(f"at most {MAX_ATTACHMENTS} media attachments are allowed")
    if any(len(blob) > MAX_ATTACHMENT_BYTES for _, blob, _ in attachments):
        raise ValueError("one attachment exceeds the 25 MB field-capture limit")
    if sum(len(blob) for _, blob, _ in attachments) > MAX_TOTAL_BYTES:
        raise ValueError("field-capture media exceeds 80 MB in total")

    activity = None
    if data["activity_uid"] is not None:
        activity = db.q1("SELECT * FROM activities WHERE project_id=? AND uid=?",
                         [project_id, data["activity_uid"]])
        if not activity:
            raise ValueError("the selected schedule activity does not exist")
        if int(activity.get("is_summary") or 0):
            raise ValueError("choose a working activity, not a WBS/summary row")

    stable = hashlib.sha256(
        (project_id + "\0" + data["client_capture_id"]).encode("utf-8")).hexdigest()[:16]
    capture_id = "cap_" + stable
    media_ids: list[str] = []
    for index, (filename, blob, content_type) in enumerate(attachments, 1):
        stored = ingest.store_upload(
            project_id, filename or f"field-media-{index}", blob, content_type,
            uploaded_by=data["reporter"], batch_id=capture_id,
            source_mode="field_capture", trusted_human=True,
            relative_path="Field captures/" + (filename or f"media-{index}"))
        media_ids.append(stored["id"])
        # The capture envelope is the citable evidence record. Photos/audio are
        # immutable supporting assets, not separate rows waiting for OCR.
        db.update("files", stored["id"], {
            "extract_state": "done", "extract_error": None})

    source_name = "Field capture " + capture_id
    raw = {
        "field_capture_id": capture_id,
        "client_capture_id": data["client_capture_id"],
        "event_state": data["event_state"], "language": data["language"],
        "original_text": data["original_text"], "confirmed_by": data["reporter"],
        "remaining_days": data["remaining_days"],
        "media_file_ids": media_ids,
        "coordinates": {"latitude": data["latitude"],
                        "longitude": data["longitude"],
                        "accuracy_m": data["location_accuracy_m"]},
    }
    evidence_state = "confirmed" if activity else "needs_review"
    evidence_id = db.insert("evidence", extract.enrich_evidence_record({
        "id": "fcev_" + stable,
        "project_id": project_id, "source_file": source_name,
        "locator": "confirmed mobile capture", "date": data["event_date"],
        "author": data["reporter"], "location": data["location_label"] or None,
        "event_type": "activity", "action_type": "activity",
        "event_state": data["event_state"], "event_confidence": 1.0,
        "description": data["confirmed_text"],
        "activity_description": data["confirmed_text"],
        "observed_progress": data["observed_progress"],
        "observation_type": "activity_progress", "section": "mobile_capture",
        "extraction_method": "field_capture", "extraction_confidence": 1.0,
        "confidence": 1.0, "state": evidence_state,
        "security_state": "clean", "raw_json": db.jdumps(raw),
        "provenance": "HUMAN_INPUT",
    }))

    execution_event_id = None
    proposal_ids: list[str] = []
    conflicts: list[dict] = []
    status = "needs_activity"
    if activity:
        db.insert("evidence_links", {
            "project_id": project_id, "evidence_id": evidence_id,
            "activity_uid": activity["uid"], "activity_name": activity.get("name"),
            "confidence": 1.0, "calibrated_probability": 1.0,
            "calibration_mode": "human_confirmed",
            "calibration_is_empirical": 0, "policy_decision": "human_confirmed",
            "committed_uid": activity["uid"], "relation": "supporting",
            "supporting_signals": db.jdumps(["Field reporter selected this activity"]),
            "validator_result": "pass", "validator_json": db.jdumps({
                "result": "pass", "summary": "Explicit human identity confirmation"}),
            "human_decision": "accepted", "decided_by": data["reporter"],
            "decided_at": db.now(), "is_candidate": 0,
            "provenance": "HUMAN_INPUT",
        })
        execution_event_id = actuals.record_confirmed_event(
            project_id, evidence_id=evidence_id, activity_uid=int(activity["uid"]),
            event_state=data["event_state"], event_date=data["event_date"],
            observed_progress=data["observed_progress"],
            remaining_days=data["remaining_days"], confidence=1.0,
            source_file=source_name, locator="confirmed mobile capture")
        generated = actuals.generate_for_event(execution_event_id)
        proposal_ids = generated["proposal_ids"]
        conflicts = generated["conflicts"]
        status = "conflict" if conflicts else (
            "proposal_ready" if proposal_ids else "confirmed_no_change")

    db.insert("field_captures", {
        "id": capture_id, "project_id": project_id,
        "client_capture_id": data["client_capture_id"], "status": status,
        "occurred_at": data["occurred_at"], "event_state": data["event_state"],
        "language": data["language"], "reporter": data["reporter"],
        "original_text": data["original_text"],
        "confirmed_text": data["confirmed_text"],
        "activity_uid": (activity or {}).get("uid"),
        "activity_display_id": (activity or {}).get("display_id"),
        "activity_name": (activity or {}).get("name"),
        "observed_progress": data["observed_progress"],
        "remaining_days": data["remaining_days"],
        "location_label": data["location_label"], "latitude": data["latitude"],
        "longitude": data["longitude"],
        "location_accuracy_m": data["location_accuracy_m"],
        "location_source": data["location_source"],
        "media_file_ids_json": db.jdumps(media_ids), "evidence_id": evidence_id,
        "execution_event_id": execution_event_id,
        "proposal_ids_json": db.jdumps(proposal_ids),
        "sync_source": data["sync_source"], "updated_at": db.now(),
    })
    audit.record(
        project_id, actor=data["reporter"], actor_type="human",
        action="field_capture_confirmed", source=data["sync_source"],
        entity_type="field_capture", entity_id=capture_id,
        result=status, detail={"event_state": data["event_state"],
                               "activity_uid": data["activity_uid"],
                               "evidence_id": evidence_id,
                               "execution_event_id": execution_event_id,
                               "proposal_ids": proposal_ids,
                               "conflicts": conflicts,
                               "media_file_ids": media_ids})
    events.notify_ui(project_id, "field_capture_saved", {"capture_id": capture_id})
    result = _shape(db.q1("SELECT * FROM field_captures WHERE id=?", [capture_id]) or {})
    result["conflicts"] = conflicts
    return result
