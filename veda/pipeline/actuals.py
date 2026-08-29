"""Governed actuals proposals derived from confirmed execution events.

This module is deliberately conservative.  It proposes only values that a
field reporter explicitly confirmed; it never turns "progress exists" into an
invented start date or guesses remaining duration from percent complete.
"""
from __future__ import annotations

from typing import Any

from .. import audit, db, events
from . import proposals


def _day(value: Any) -> str | None:
    if not value:
        return None
    return str(value).split("T")[0]


def _evidence_ids(event_id: str) -> list[str]:
    return [str(row["evidence_id"]) for row in db.q(
        "SELECT evidence_id FROM execution_event_sources "
        "WHERE execution_event_id=? ORDER BY created_at", [event_id])]


def record_confirmed_event(project_id: str, *, evidence_id: str,
                           activity_uid: int, event_state: str,
                           event_date: str | None,
                           observed_progress: float | None = None,
                           remaining_days: float | None = None,
                           confidence: float = 1.0,
                           source_file: str | None = None,
                           locator: str | None = None) -> str:
    """Idempotently create a canonical event from a human-confirmed capture."""
    state = str(event_state or "observation").strip().lower()
    if state not in {"start", "progress", "finish"}:
        raise ValueError("event_state must be start, progress, or finish")
    day = _day(event_date)
    if not day:
        raise ValueError("a confirmed event date is required")
    progress_key = "" if observed_progress is None else f"|p={float(observed_progress):.3f}"
    remaining_key = "" if remaining_days is None else f"|r={float(remaining_days):.3f}"
    key = f"{int(activity_uid)}|activity|{state}|{day}{progress_key}{remaining_key}"
    row = db.q1("SELECT id FROM execution_events WHERE project_id=? AND canonical_key=?",
                [project_id, key])
    if row:
        event_id = row["id"]
    else:
        event_id = db.insert("execution_events", {
            "project_id": project_id, "canonical_key": key,
            "activity_uid": int(activity_uid), "action_type": "activity",
            "event_state": state, "event_date": day,
            "observed_progress": observed_progress,
            "remaining_days": remaining_days,
            "confidence": max(0.0, min(1.0, float(confidence))),
            "state": "confirmed", "source_count": 0,
            "provenance": "HUMAN_INPUT", "updated_at": db.now(),
        })
    if not db.q1("SELECT id FROM execution_event_sources WHERE "
                 "execution_event_id=? AND evidence_id=?", [event_id, evidence_id]):
        db.insert("execution_event_sources", {
            "project_id": project_id, "execution_event_id": event_id,
            "evidence_id": evidence_id, "source_file": source_file,
            "locator": locator, "source_trust": 1.0,
        })
    count = (db.q1("SELECT COUNT(*) c FROM execution_event_sources "
                   "WHERE execution_event_id=?", [event_id]) or {}).get("c", 0)
    db.update("execution_events", event_id, {
        "source_count": count, "state": "confirmed", "updated_at": db.now()})
    return event_id


def generate_from_confirmed_evidence(project_id: str, evidence_id: str,
                                     activity_uid: int) -> dict:
    """Promote an existing linked observation after a human identity decision."""
    evidence = db.q1("SELECT * FROM evidence WHERE id=? AND project_id=?",
                     [evidence_id, project_id])
    if not evidence:
        raise KeyError("no such evidence")
    state = str(evidence.get("event_state") or "").lower()
    if state not in {"start", "progress", "finish"}:
        return {"event_id": None, "proposal_ids": [], "conflicts": [],
                "note": "evidence is not a start/progress/finish event"}
    if not _day(evidence.get("date")):
        return {"event_id": None, "proposal_ids": [],
                "conflicts": [{"field": "event_date",
                               "detail": "A planner must confirm the event date before actuals can be proposed."}]}
    raw = db.jloads(evidence.get("raw_json"), {}) or {}
    remaining_days = raw.get("remaining_days")
    try:
        remaining_days = None if remaining_days in (None, "") else float(remaining_days)
    except (TypeError, ValueError):
        remaining_days = None
    existing = db.q1(
        "SELECT ee.id FROM execution_events ee JOIN execution_event_sources es "
        "ON es.execution_event_id=ee.id WHERE es.evidence_id=? "
        "AND ee.project_id=? AND ee.activity_uid=? ORDER BY ee.created_at LIMIT 1",
        [evidence_id, project_id, activity_uid])
    if existing:
        event_id = existing["id"]
        db.update("execution_events", event_id, {
            "state": "confirmed", "event_state": state,
            "remaining_days": remaining_days, "updated_at": db.now()})
    else:
        event_id = record_confirmed_event(
            project_id, evidence_id=evidence_id, activity_uid=activity_uid,
            event_state=state, event_date=evidence.get("date"),
            observed_progress=evidence.get("observed_progress"),
            remaining_days=remaining_days,
            confidence=float(evidence.get("confidence") or 0.95),
            source_file=evidence.get("source_file"), locator=evidence.get("locator"))
    return generate_for_event(event_id)


def generate_for_event(event_id: str) -> dict:
    """Create one idempotent proposal bundle for a confirmed execution event."""
    event = db.q1("SELECT * FROM execution_events WHERE id=?", [event_id])
    if not event:
        raise KeyError("no such execution event")
    project_id = event["project_id"]
    activity = db.q1("SELECT * FROM activities WHERE project_id=? AND uid=?",
                     [project_id, event.get("activity_uid")])
    if not activity:
        return {"event_id": event_id, "proposal_ids": [],
                "conflicts": [{"field": "activity", "detail": "Target activity no longer exists."}]}

    state = str(event.get("event_state") or "").lower()
    event_day = _day(event.get("event_date"))
    evidence_ids = _evidence_ids(event_id)
    group_id = "actuals_" + event_id
    confidence = float(event.get("confidence") or 0.5)
    wanted: list[tuple[str, Any, str]] = []
    conflicts: list[dict] = []

    def date_value(field: str, current_key: str, label: str) -> None:
        current = _day(activity.get(current_key))
        if not current:
            wanted.append((field, event_day,
                           f"Confirmed field {label} on {event_day}."))
        elif current != event_day:
            conflicts.append({"field": field, "official": current,
                              "observed": event_day,
                              "detail": "Official and confirmed field dates differ; planner decision required."})

    if state == "start":
        date_value("actualStart", "actual_start", "start")
    elif state == "progress":
        progress = event.get("observed_progress")
        if progress is not None:
            official = activity.get("percent_complete")
            if official is None or float(progress) > float(official) + 0.01:
                wanted.append(("percentComplete", float(progress),
                               "Field reporter confirmed measured progress; no schedule value is changed until approval."))
            elif float(progress) < float(official) - 0.01:
                conflicts.append({"field": "percentComplete", "official": official,
                                  "observed": progress,
                                  "detail": "Observed progress would regress the official value."})
        if event.get("remaining_days") is not None:
            wanted.append(("remainingDuration", float(event["remaining_days"]),
                           "Field reporter explicitly confirmed remaining working duration."))
    elif state == "finish":
        date_value("actualFinish", "actual_finish", "finish")
        if activity.get("percent_complete") is None or float(activity.get("percent_complete") or 0) < 99.99:
            wanted.append(("percentComplete", 100.0,
                           "A confirmed finish requires 100% completion, subject to planner approval."))
        if activity.get("remaining_days") is None or float(activity.get("remaining_days") or 0) > 0.001:
            wanted.append(("remainingDuration", 0.0,
                           "A confirmed finish requires zero remaining duration, subject to planner approval."))

    proposal_ids: list[str] = []
    for field, value, reason in wanted:
        proposal_ids.append(proposals.create(
            project_id, target_uid=int(activity["uid"]), field=field,
            proposed_value=value, reason=reason, target_type="activity",
            target_name=activity.get("name"), evidence_ids=evidence_ids,
            confidence=confidence, provenance="DETERMINISTIC_CALCULATION",
            proposal_group_id=group_id, source_event_id=event_id))

    audit.record(
        project_id, actor="actuals.policy", actor_type="system",
        action="actuals_proposals_generated", source="confirmed_field_event",
        entity_type="execution_event", entity_id=event_id,
        result=f"{len(proposal_ids)} proposal(s), {len(conflicts)} conflict(s)",
        detail={"proposal_ids": proposal_ids, "conflicts": conflicts,
                "policy": "explicit-confirmation-only"})
    events.notify_ui(project_id, "proposals_changed", {
        "event_id": event_id, "proposal_ids": proposal_ids})
    return {"event_id": event_id, "proposal_group_id": group_id,
            "proposal_ids": proposal_ids, "conflicts": conflicts}


def generate_for_project(project_id: str) -> dict:
    results = [generate_for_event(row["id"]) for row in db.q(
        "SELECT id FROM execution_events WHERE project_id=? "
        "AND state='confirmed' ORDER BY created_at", [project_id])]
    return {"events": len(results),
            "proposal_ids": [pid for result in results for pid in result["proposal_ids"]],
            "conflicts": [conflict for result in results for conflict in result["conflicts"]]}
