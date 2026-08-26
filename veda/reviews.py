"""Durable human decisions.

Reviews are *decision state*, not worker state. A clarification is scoped to the
current schedule revision. Answering it either changes project state immediately
or, for the few decisions that truly need background work, emits one explicit
wake event. Missing/invalid answers never silently close a question.
"""
from __future__ import annotations

from . import audit, db, events


def current_schedule_context(project_id: str) -> dict:
    return db.q1("SELECT id, revision FROM schedule_snapshots WHERE project_id=? "
                 "AND is_current=1 ORDER BY created_at DESC LIMIT 1", [project_id]) or {}


def create(*, project_id: str, kind: str, title: str, question: str,
           detail: str | None = None, options: list | None = None,
           cluster_key: str | None = None, affected_ids: list | None = None,
           entity_type: str | None = None, entity_id: str | None = None,
           priority: str = "normal", job_id: str | None = None,
           extra: dict | None = None) -> str:
    """Create one durable decision, merging only inside the same schedule revision."""
    sched = current_schedule_context(project_id)
    revision = sched.get("revision")
    snapshot_id = sched.get("id")
    if cluster_key:
        existing = db.q1(
            "SELECT * FROM reviews WHERE project_id=? AND cluster_key=? "
            "AND status='open' AND (schedule_revision IS ? OR schedule_revision=?) LIMIT 1",
            [project_id, cluster_key, revision, revision])
        if existing:
            merged = sorted(set(db.jloads(existing.get("affected_ids_json"), []) or [])
                            | set(affected_ids or []))
            db.update("reviews", existing["id"], {
                "affected_ids_json": db.jdumps(merged),
                "affected_count": max(len(merged), 1),
            })
            return existing["id"]

    payload = dict(extra or {})
    rid = db.insert("reviews", {
        "project_id": project_id, "job_id": job_id, "kind": kind,
        "title": title, "question": question, "detail": detail,
        "options_json": db.jdumps(options or []), "cluster_key": cluster_key,
        "affected_count": max(len(affected_ids or []), 1),
        "affected_ids_json": db.jdumps(affected_ids or []),
        "entity_type": entity_type, "entity_id": entity_id,
        "priority": priority, "status": "open",
        "answer_json": db.jdumps({"context": payload}) if payload else None,
        "schedule_revision": revision, "schedule_snapshot_id": snapshot_id,
    })
    audit.record(project_id, actor="agent", actor_type="agent",
                 action="review_requested", source="analysis", job_id=job_id,
                 entity_type="review", entity_id=rid, new_value=title, result=kind)
    events.notify_ui(project_id, "attention_changed", {"review_id": rid})
    return rid


def get(review_id: str) -> dict | None:
    r = db.q1("SELECT * FROM reviews WHERE id=?", [review_id])
    return _shape(r) if r else None


def _validate_answer(r: dict, answer_text: str) -> None:
    if r.get("kind") != "clarification":
        return
    opts = db.jloads(r.get("options_json"), []) or []
    if answer_text not in opts:
        raise ValueError("Choose one of the displayed activity options, or 'Leave unassigned for now'.")


def answer(review_id: str, *, answer_text: str, answered_by: str = "human",
           payload: dict | None = None, status: str = "answered",
           wake: bool = True) -> dict:
    raw = db.q1("SELECT * FROM reviews WHERE id=?", [review_id])
    if not raw:
        raise KeyError("no such review: " + review_id)
    answer_text = (answer_text or "").strip()
    if not answer_text:
        raise ValueError("Choose an answer before continuing.")
    _validate_answer(raw, answer_text)

    # Idempotent repeat is fine; conflicting second answers require the explicit
    # correction flow instead of silently rewriting human history.
    if raw.get("status") != "open":
        if (raw.get("answer") or "") == answer_text:
            return _shape(raw)
        raise ValueError("This decision is already settled. Use Change decision to revise it.")

    prior = db.jloads(raw.get("answer_json"), {}) or {}
    prior["answer"] = payload or {}
    db.update("reviews", review_id, {
        "status": status, "answer": answer_text, "answer_json": db.jdumps(prior),
        "answered_by": answered_by, "answered_at": db.now(),
    })
    audit.record(raw["project_id"], actor=answered_by, actor_type="human",
                 action="review_" + status, source="website", job_id=raw.get("job_id"),
                 entity_type="review", entity_id=review_id,
                 previous_value=raw.get("status"), new_value=answer_text,
                 approval=answered_by, result=raw.get("title"))

    ev_type = {"answered": events.REVIEW_ANSWERED,
               "approved": events.REVIEW_APPROVED,
               "rejected": events.REVIEW_REJECTED}.get(status, events.REVIEW_ANSWERED)
    if wake:
        events.emit(ev_type, raw["project_id"], {
            "review_id": review_id, "kind": raw.get("kind"),
            "cluster_key": raw.get("cluster_key"),
            "affected_ids": db.jloads(raw.get("affected_ids_json"), []),
            "answer": answer_text, "answer_payload": payload or {},
            "job_id": raw.get("job_id"), "requires_job": True,
            "entity_type": raw.get("entity_type"), "entity_id": raw.get("entity_id"),
        }, source="human")
    events.notify_ui(raw["project_id"], "attention_changed", {"review_id": review_id})
    return get(review_id) or {}


def record_effect(review_id: str, effect: dict) -> None:
    db.update("reviews", review_id, {"resolution_effect_json": db.jdumps(effect or {})})


def reopen(review_id: str, *, by: str = "human") -> dict:
    r = get(review_id)
    if not r:
        raise KeyError("no such review: " + review_id)
    if r.get("kind") != "clarification":
        raise ValueError("Only evidence-to-activity decisions use Change decision.")
    sched = current_schedule_context(r["project_id"])
    if r.get("schedule_revision") is not None and sched.get("revision") != r.get("schedule_revision"):
        raise ValueError("This decision belongs to an older schedule revision and cannot be changed against the current schedule.")

    # Include later evidence that reused this human mapping, not just the rows
    # that happened to exist when the original question was created.
    linked = db.q("SELECT DISTINCT evidence_id FROM evidence_links WHERE project_id=? AND review_id=?",
                  [r["project_id"], review_id])
    ids = sorted(set((r.get("affected_ids") or []) + [x["evidence_id"] for x in linked]))
    if ids:
        db.ex("DELETE FROM evidence_links WHERE project_id=? AND review_id=?",
              [r["project_id"], review_id])
        ph = ",".join("?" for _ in ids)
        db.ex("UPDATE evidence SET state='needs_review', confidence=NULL WHERE id IN (" + ph + ")", ids)
    meta = {"context": r.get("context") or {}}
    db.update("reviews", review_id, {
        "status": "open", "answer": None, "answer_json": db.jdumps(meta),
        "answered_by": None, "answered_at": None, "resolution_effect_json": None,
        "affected_ids_json": db.jdumps(ids), "affected_count": max(len(ids), 1),
    })
    audit.record(r["project_id"], actor=by, actor_type="human",
                 action="review_reopened", source="website", entity_type="review",
                 entity_id=review_id, previous_value=r.get("answer"), result="decision reopened")
    events.notify_ui(r["project_id"], "attention_changed", {"review_id": review_id})
    return get(review_id) or {}


def invalidate_stale(project_id: str) -> int:
    sched = current_schedule_context(project_id)
    rev = sched.get("revision")
    if rev is None:
        return 0
    rows = db.q("SELECT id FROM reviews WHERE project_id=? AND status='open' "
                "AND kind='clarification' AND schedule_revision IS NOT NULL "
                "AND schedule_revision<>?", [project_id, rev])
    for r in rows:
        db.update("reviews", r["id"], {"status": "stale"})
    return len(rows)


def open_for(project_id: str) -> list:
    invalidate_stale(project_id)
    rows = db.q("SELECT * FROM reviews WHERE project_id=? AND status='open' "
                "ORDER BY CASE priority WHEN 'high' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END, created_at",
                [project_id])
    return [_shape(r) for r in rows]


def all_for(project_id: str, status: str | None = None) -> list:
    invalidate_stale(project_id)
    if status and status != "all":
        rows = db.q("SELECT * FROM reviews WHERE project_id=? AND status=? ORDER BY created_at DESC",
                    [project_id, status])
    else:
        rows = db.q("SELECT * FROM reviews WHERE project_id=? ORDER BY created_at DESC", [project_id])
    return [_shape(r) for r in rows]


def _shape(r: dict) -> dict:
    r = dict(r)
    r["options"] = db.jloads(r.pop("options_json", None), []) or []
    r["affected_ids"] = db.jloads(r.pop("affected_ids_json", None), []) or []
    meta = db.jloads(r.pop("answer_json", None), {}) or {}
    r["context"] = meta.get("context", {})
    r["answer_payload"] = meta.get("answer", {})
    r["resolution_effect"] = db.jloads(r.pop("resolution_effect_json", None), {}) or {}
    return r


def answers_for_cluster(project_id: str, cluster_key: str,
                        schedule_revision: int | None = None) -> dict | None:
    if schedule_revision is None:
        schedule_revision = current_schedule_context(project_id).get("revision")
    r = db.q1("SELECT * FROM reviews WHERE project_id=? AND cluster_key=? "
              "AND status IN ('answered','approved') AND schedule_revision=? "
              "ORDER BY answered_at DESC LIMIT 1",
              [project_id, cluster_key, schedule_revision]) if schedule_revision is not None else None
    return _shape(r) if r else None
