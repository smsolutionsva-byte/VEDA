"""Human Review Required (spec 40, 41, 42).

One question stands for a whole cluster of shared ambiguity. Answers are
persisted by VEDA and raise review_answered, which resumes the same logical
job - the human never opens the reasoning provider.
"""
from __future__ import annotations

from typing import Any

from . import audit, db, events


def create(*, project_id: str, kind: str, title: str, question: str,
           detail: str | None = None, options: list | None = None,
           cluster_key: str | None = None, affected_ids: list | None = None,
           entity_type: str | None = None, entity_id: str | None = None,
           priority: str = "normal", job_id: str | None = None,
           extra: dict | None = None) -> str:
    """Create a review, merging into an open question with the same cluster key."""
    if cluster_key:
        existing = db.q1(
            "SELECT * FROM reviews WHERE project_id=? AND cluster_key=? "
            "AND status='open' LIMIT 1", [project_id, cluster_key])
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
        "options_json": db.jdumps(options or []),
        "cluster_key": cluster_key,
        "affected_count": max(len(affected_ids or []), 1),
        "affected_ids_json": db.jdumps(affected_ids or []),
        "entity_type": entity_type, "entity_id": entity_id,
        "priority": priority, "status": "open",
        "answer_json": db.jdumps({"context": payload}) if payload else None,
    })
    audit.record(project_id, actor="agent", actor_type="agent",
                 action="review_requested", source="analysis", job_id=job_id,
                 entity_type="review", entity_id=rid, new_value=title,
                 result=kind)
    events.notify_ui(project_id, "reviews_changed", {"review_id": rid})
    return rid


def answer(review_id: str, *, answer_text: str, answered_by: str = "human",
           payload: dict | None = None, status: str = "answered") -> dict:
    r = db.q1("SELECT * FROM reviews WHERE id=?", [review_id])
    if not r:
        raise KeyError("no such review: " + review_id)

    prior = db.jloads(r.get("answer_json"), {}) or {}
    prior["answer"] = payload or {}
    db.update("reviews", review_id, {
        "status": status, "answer": answer_text,
        "answer_json": db.jdumps(prior),
        "answered_by": answered_by, "answered_at": db.now(),
    })
    audit.record(r["project_id"], actor=answered_by, actor_type="human",
                 action="review_" + status, source="website",
                 job_id=r.get("job_id"), entity_type="review", entity_id=review_id,
                 previous_value=r.get("status"), new_value=answer_text,
                 approval=answered_by, result=r.get("title"))

    ev_type = {
        "answered": events.REVIEW_ANSWERED,
        "approved": events.REVIEW_APPROVED,
        "rejected": events.REVIEW_REJECTED,
    }.get(status, events.REVIEW_ANSWERED)

    events.emit(ev_type, r["project_id"], {
        "review_id": review_id, "kind": r.get("kind"),
        "cluster_key": r.get("cluster_key"),
        "affected_ids": db.jloads(r.get("affected_ids_json"), []),
        "answer": answer_text, "answer_payload": payload or {},
        "job_id": r.get("job_id"),
        "entity_type": r.get("entity_type"), "entity_id": r.get("entity_id"),
    }, source="human")
    events.notify_ui(r["project_id"], "reviews_changed", {"review_id": review_id})
    return db.q1("SELECT * FROM reviews WHERE id=?", [review_id]) or {}


def open_for(project_id: str) -> list:
    rows = db.q("SELECT * FROM reviews WHERE project_id=? AND status='open' "
                "ORDER BY CASE priority WHEN 'high' THEN 0 WHEN 'normal' THEN 1 "
                "ELSE 2 END, created_at", [project_id])
    return [_shape(r) for r in rows]


def all_for(project_id: str, status: str | None = None) -> list:
    if status and status != "all":
        rows = db.q("SELECT * FROM reviews WHERE project_id=? AND status=? "
                    "ORDER BY created_at DESC", [project_id, status])
    else:
        rows = db.q("SELECT * FROM reviews WHERE project_id=? "
                    "ORDER BY created_at DESC", [project_id])
    return [_shape(r) for r in rows]


def _shape(r: dict) -> dict:
    r = dict(r)
    r["options"] = db.jloads(r.pop("options_json", None), []) or []
    r["affected_ids"] = db.jloads(r.pop("affected_ids_json", None), []) or []
    meta = db.jloads(r.pop("answer_json", None), {}) or {}
    r["context"] = meta.get("context", {})
    r["answer_payload"] = meta.get("answer", {})
    return r


def answers_for_cluster(project_id: str, cluster_key: str) -> dict | None:
    r = db.q1("SELECT * FROM reviews WHERE project_id=? AND cluster_key=? "
              "AND status IN ('answered','approved','rejected') "
              "ORDER BY answered_at DESC LIMIT 1", [project_id, cluster_key])
    return _shape(r) if r else None
