"""Evidence to activity association (spec 35-39, 41).

The agent proposes candidate links; this module scores them deterministically,
runs the validators, and decides one of three outcomes per evidence item:

  linked        a clear winner that the validators accept
  needs_review  genuine ambiguity - clustered so one question covers many rows
  unresolved    nothing plausible to attach it to

Identity is not mutation permission (spec 39): linking evidence to an activity
never changes that activity's official progress.
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta
from typing import Any, Callable

from .. import db, reviews
from ..retrieval import engine as retrieval_engine, calibration
from ..resolution import events as event_model, risk as risk_policy
from . import validators

STOP = {"the", "and", "for", "with", "of", "to", "in", "on", "at", "a", "an",
        "works", "work", "site", "no", "nos", "shift", "day", "daily", "progress",
        "report", "spread", "section", "ch", "km", "from", "as", "per", "is", "was"}


def _tokens(text: str | None) -> set:
    if not text:
        return set()
    words = re.findall(r"[a-z0-9]+", str(text).lower())
    return {w for w in words if len(w) > 2 and w not in STOP}


def _d(v: Any):
    if not v:
        return None
    try:
        return datetime.strptime(str(v).split("T")[0], "%Y-%m-%d").date()
    except ValueError:
        return None


def score_candidate(ev: dict, act: dict) -> tuple:
    """Return (score, supporting_signals, conflicting_signals, substantive).

    `substantive` records whether anything other than a date overlap argued for
    the match. On a real schedule dozens of activities span any given day, so a
    date overlap on its own is not evidence of association and must never carry
    a candidate on its own.
    """
    support: list = []
    conflict: list = []
    score = 0.0
    substantive = False

    ev_disc = validators.discipline_key(ev.get("discipline")) or \
        validators.discipline_key(ev.get("description"))
    act_disc = validators.discipline_key(act.get("name"))
    if ev_disc and act_disc:
        if ev_disc == act_disc:
            score += 0.42
            substantive = True
            support.append("discipline matches (" + ev_disc + ")")
        else:
            score -= 0.55
            conflict.append("discipline differs (" + ev_disc + " vs " + act_disc + ")")
    elif ev_disc and not act_disc:
        score += 0.04

    ev_loc = validators.location_tokens(
        str(ev.get("location") or "") + " " + str(ev.get("description") or ""))
    act_loc = validators.location_tokens(str(act.get("name") or ""))
    if ev_loc and act_loc:
        if ev_loc & act_loc:
            score += 0.3
            substantive = True
            support.append("location matches (" +
                           ", ".join(sorted(ev_loc & act_loc)) + ")")
        else:
            score -= 0.45
            conflict.append("location differs")

    ev_ch = validators.chainage_values(
        str(ev.get("chainage") or "") + " " + str(ev.get("description") or ""))
    lo, hi = validators.chainage_window(act.get("name"))
    if ev_ch and lo is not None and hi is not None and hi > lo:
        if any(lo - 500 <= c <= hi + 500 for c in ev_ch):
            score += 0.26
            substantive = True
            support.append("chainage inside activity range")
        else:
            score -= 0.5
            conflict.append("chainage outside activity range")

    ed = _d(ev.get("date"))
    a_s = _d(act.get("actual_start") or act.get("start"))
    a_f = _d(act.get("actual_finish") or act.get("finish"))
    if ed and a_s and a_f:
        if a_s - timedelta(days=7) <= ed <= a_f + timedelta(days=7):
            score += 0.22
            support.append("date within activity window")
        elif ed < a_s - timedelta(days=30):
            score -= 0.2
            conflict.append("date well before activity window")
        elif ed > a_f + timedelta(days=30):
            score -= 0.2
            conflict.append("date well after activity window")

    overlap = _tokens(ev.get("description")) & _tokens(act.get("name"))
    if overlap:
        bump = min(0.2, 0.07 * len(overlap))
        score += bump
        if len(overlap) >= 2:
            substantive = True
        support.append("wording overlap: " + ", ".join(sorted(overlap)[:4]))

    if act.get("is_summary"):
        score -= 0.3
        conflict.append("target is a summary row")

    return max(0.0, min(1.0, score)), support, conflict, substantive


def candidates_for(ev: dict, activities: list, top: int = 4) -> list:
    scored = []
    for a in activities:
        if a.get("is_summary"):
            continue
        s, sup, con, substantive = score_candidate(ev, a)
        # A date overlap alone never qualifies a candidate.
        if s > 0.12 and substantive:
            scored.append({"activity": a, "score": round(s, 3),
                           "supporting": sup, "conflicting": con})
    scored.sort(key=lambda x: -x["score"])
    return scored[:top]


def _candidate_signature(cands: list) -> str:
    """Order-independent candidate identity; prevents unsafe broad clustering."""
    uids = sorted({str(c.get("activity", {}).get("uid")) for c in cands[:5]
                   if c.get("activity", {}).get("uid") is not None})
    return "|cands=" + (",".join(uids) if uids else "none")


def cluster_key_for(ev: dict, cands: list) -> tuple:
    """Identify the *shared root cause* of ambiguity (spec 41).

    Many rows failing for the same reason must produce one question, not many.
    """
    has_loc = bool(validators.location_tokens(
        str(ev.get("location") or "") + " " + str(ev.get("description") or "")))
    has_ch = bool(validators.chainage_values(
        str(ev.get("chainage") or "") + " " + str(ev.get("description") or "")))
    disc = validators.discipline_key(ev.get("discipline")) or \
        validators.discipline_key(ev.get("description"))
    crew = (ev.get("crew") or "").strip()

    if not has_loc and not has_ch and crew:
        # The classic case: a crew code with no spread and no chainage.
        return ("crew_location:" + crew.lower() + _candidate_signature(cands),
                "Records from crew " + crew + " carry no spread or chainage",
                "Which part of the works does crew " + crew + " belong to?")
    if not has_loc and not has_ch and not crew:
        return ("no_location:" + str(disc or "unknown") + _candidate_signature(cands),
                "Records in " + str(ev.get("source_file")) +
                " carry no location, chainage or crew",
                "How should records from " + str(ev.get("source_file")) +
                " be attributed?")
    if not disc:
        return ("no_discipline:" + _candidate_signature(cands),
                "Records in " + str(ev.get("source_file")) +
                " do not state a discipline",
                "Which discipline do these records describe?")
    if len(cands) >= 2 and abs(cands[0]["score"] - cands[1]["score"]) < 0.08:
        return ("tie:" + str(disc) + _candidate_signature(cands),
                str(disc).title() + " records match more than one activity equally",
                "Which activity should " + str(disc) + " records attach to when the "
                "signals tie?")
    return ("weak:" + str(disc or "unknown") + _candidate_signature(cands),
            "Records in " + str(ev.get("source_file")) +
            " match no activity strongly",
            "How should these records be attributed?")



def _upsert_execution_event(project_id: str, ev: dict, cand: dict, event_info: dict,
                            cal: dict) -> str | None:
    """Create/deduplicate the canonical execution-event layer.

    Source observations remain immutable evidence.  Multiple DPR/diary/voice
    records can corroborate one canonical event without becoming duplicate
    schedule updates.
    """
    if event_info.get("state") not in {"start", "progress", "finish"}:
        return None
    uid = int(cand["activity"]["uid"])
    action = str(event_info.get("action") or "activity")
    state = str(event_info.get("state") or "observation")
    day = str(ev.get("date") or "unknown")
    progress = event_info.get("progress")
    bucket = "" if progress is None else f"|p={round(float(progress),1)}"
    key = f"{uid}|{action}|{state}|{day}{bucket}"
    row = db.q1("SELECT * FROM execution_events WHERE project_id=? AND canonical_key=?", [project_id, key])
    prob = float(cal.get("probability") or 0.0)
    if row:
        eid = row["id"]
    else:
        eid = db.insert("execution_events", {
            "project_id": project_id, "canonical_key": key, "activity_uid": uid,
            "action_type": action, "event_state": state, "event_date": ev.get("date"),
            "observed_progress": progress, "quantity": ev.get("quantity"), "unit": ev.get("unit"),
            "confidence": prob, "source_count": 0, "provenance": "DERIVED",
            "updated_at": db.now(),
        })
    exists = db.q1("SELECT id FROM execution_event_sources WHERE execution_event_id=? AND evidence_id=?", [eid, ev["id"]])
    if not exists:
        try:
            trust = next((c.get("detail",{}).get("trust") for c in validators.validate_link(
                ev, cand["activity"], project_id=project_id).get("checks",[]) if c.get("name")=="source_trust"), None)
        except Exception:
            trust = None
        db.insert("execution_event_sources", {"project_id": project_id, "execution_event_id": eid,
                  "evidence_id": ev["id"], "source_file": ev.get("source_file"),
                  "locator": ev.get("locator"), "source_trust": trust})
    n = (db.q1("SELECT COUNT(*) c FROM execution_event_sources WHERE execution_event_id=?", [eid]) or {}).get("c",0)
    db.update("execution_events", eid, {"source_count": n, "confidence": prob, "updated_at": db.now()})
    return eid


def link_evidence(project_id: str, *, job_id: str | None = None,
                  evidence_rows: list | None = None,
                  agent_links: dict | None = None,
                  status_date: str | None = None,
                  raise_reviews: bool = True,
                  progress: Callable[[str, str, str | None], None] | None = None,
                  cancel_check: Callable[[], None] | None = None) -> dict:
    """Resolve evidence identity through hybrid retrieval + engineering risk policy.

    `linked` means the evidence identity was associated with an activity.  It
    still does NOT authorize a Primavera actual/progress write; mutation remains
    proposal/approval/verified-write territory.
    """
    def checkpoint() -> None:
        if cancel_check:
            cancel_check()

    def report(phase: str, label: str, detail: str | None = None) -> None:
        if progress:
            progress(phase, label, detail)

    checkpoint()
    if evidence_rows is None:
        evidence_rows = db.q(
            "SELECT * FROM evidence WHERE project_id=? AND state IN "
            "('new','processing','needs_review')", [project_id])

    if status_date is None:
        snap = db.q1("SELECT status_date FROM schedule_snapshots WHERE project_id=? "
                     "AND is_current=1", [project_id])
        status_date = (snap or {}).get("status_date")

    stats = {"linked": 0, "needs_review": 0, "unresolved": 0, "conflicting": 0,
             "historical": 0, "duplicate": 0, "quarantined": 0, "non_progress": 0}
    clusters: dict = {}

    # Build/refresh the schedule representation once per batch.  Each DPR row
    # then performs a warm query against the same revision rather than scanning
    # and re-embedding the schedule repeatedly.
    total = len(evidence_rows)
    report("resolver_indexing", "Building the semantic candidate floor",
           str(total) + " evidence record(s) queued for identity resolution")
    index_info = retrieval_engine.index_project(
        project_id, cancel_check=cancel_check)
    checkpoint()
    report("resolver_experts",
           "Semantic, Engineering, Tree and Rescheduler experts are ready",
           "Four candidate lists will be fused by MetaRank · " +
           str(index_info.get("embedding_backend") or "retrieval ready"))

    last_progress_at = 0.0
    for position, ev in enumerate(evidence_rows, start=1):
        checkpoint()
        progress_now = time.monotonic()
        if (position == 1 or position == total or
                progress_now - last_progress_at >= 1.0):
            report("resolver_ranking",
                   "Resolving field evidence " + str(position) + " of " + str(total),
                   "Candidate union → expert utilities → LambdaMART MetaRank")
            last_progress_at = progress_now
        if ev.get("security_state") in ("suspicious", "quarantined"):
            db.update("evidence", ev["id"], {"state": "quarantined"})
            stats["quarantined"] += 1
            continue

        event_info = event_model.classify_event(ev)
        with db.transaction():
            db.ex("DELETE FROM evidence_links WHERE evidence_id=? AND "
                  "(human_decision IS NULL OR human_decision='')", [ev["id"]])
            db.update("evidence", ev["id"], {
                "action_type": event_info.get("action"), "event_state": event_info.get("state"),
                "event_confidence": event_info.get("confidence"),
                "event_type": ev.get("event_type") or event_info.get("action"),
            })
        # Refresh local copy because dynamically-added fields may be used below.
        ev = {**ev, "action_type": event_info.get("action"), "event_state": event_info.get("state")}

        agent_proposed = (agent_links or {}).get(ev["id"], [])
        hs = retrieval_engine.hybrid_search(
            project_id, ev, top_k=8, agent_links=agent_proposed,
            ensure_index=False, cancel_check=cancel_check)
        checkpoint()
        cands = hs.get("candidates") or []

        if not cands:
            db.update("evidence", ev["id"], {"state": "needs_review"})
            stats["unresolved"] += 1
            _add_cluster(clusters, ev, cands)
            continue

        best = cands[0]
        vres = validators.validate_link(ev, best["activity"], project_id=project_id,
                                        status_date=status_date)
        cal = calibration.calibrated_probability(best["score"], project_id,
                                                  features=best.get("features") or {})
        policy = risk_policy.assess(candidates=cands, calibration=cal,
                                    validator=vres, event=event_info)

        historical = any(c["name"] == "historical_detection" and
                         c["result"] == validators.WARN for c in vres["checks"])
        dup = any(c["name"] == "duplicate_detection" and
                  c["result"] == validators.WARN for c in vres["checks"])

        if dup:
            state, relation, is_cand = "duplicate", "duplicate", 0
            stats["duplicate"] += 1
        elif historical:
            state, relation, is_cand = "historical", "historical", 0
            stats["historical"] += 1
        elif policy["decision"] == "conflicting":
            state, relation, is_cand = "conflicting", "conflicting", 1
            stats["conflicting"] += 1
        elif policy["decision"] == "link_identity_only":
            state, relation, is_cand = "linked", "supporting", 0
            stats["linked"] += 1
        else:
            state, relation, is_cand = "needs_review", "non_progress" if event_info.get("non_progress") else "unresolved", 1
            stats["needs_review"] += 1
            if event_info.get("non_progress"):
                stats["non_progress"] += 1
            _add_cluster(clusters, ev, cands)

        best_features = dict(best.get("features") or {})
        # Keep pre-Meta retrieval diagnostics distinct from final MetaRank score.
        # MetaRank's public score is deliberately a bounded ranking margin, not
        # the original retrieval score and not a probability.
        retrieval_score = float(best_features.get("pre_meta_raw_score",
                                                  best_features.get("raw_score") or 0.0) or 0.0)
        rank_score = float(best.get("score") or 0.0)
        committed_uid = best["activity"]["uid"] if state == "linked" else None
        # One transaction per evidence row: the recommended link, its alternates
        # and the resulting state must all land together, and grouping them also
        # collapses five fsyncs into one.
        with db.transaction():
            db.insert("evidence_links", {
                "project_id": project_id, "evidence_id": ev["id"],
                "activity_uid": best["activity"]["uid"],
                "activity_name": best["activity"]["name"],
                "confidence": float(cal.get("probability") or 0.0),
                "retrieval_score": retrieval_score, "rank_score": rank_score,
                "calibrated_probability": float(cal.get("probability") or 0.0),
                "calibration_mode": cal.get("mode"),
                "calibration_is_empirical": 1 if cal.get("is_calibrated") else 0,
                "calibration_model_version": cal.get("model_version"),
                "feature_json": db.jdumps(best_features),
                "policy_json": db.jdumps(policy),
                "prediction_set_json": db.jdumps(policy.get("candidate_set") or {}),
                "policy_decision": policy.get("decision"),
                "recommended_uid": best["activity"]["uid"], "committed_uid": committed_uid,
                "relation": relation,
                "supporting_signals": db.jdumps(best["supporting"]),
                "conflicting_signals": db.jdumps(best["conflicting"]),
                "validator_result": vres["result"], "validator_json": db.jdumps(vres),
                "is_candidate": is_cand,
                "provenance": "AI_INFERENCE" if best.get("from_agent") else "DETERMINISTIC_CALCULATION",
            })
            db.insertmany("evidence_links", [{
                "project_id": project_id, "evidence_id": ev["id"],
                "activity_uid": alt["activity"]["uid"], "activity_name": alt["activity"]["name"],
                "confidence": None, "retrieval_score": float(alt.get("features",{}).get("pre_meta_raw_score",
                                                           alt.get("features",{}).get("raw_score") or 0) or 0),
                "rank_score": float(alt.get("score") or 0),
                "feature_json": db.jdumps(alt.get("features") or {}),
                "relation": "unresolved", "supporting_signals": db.jdumps(alt["supporting"]),
                "conflicting_signals": db.jdumps(alt["conflicting"]),
                "is_candidate": 1, "recommended_uid": best["activity"]["uid"],
                "provenance": "DETERMINISTIC_CALCULATION",
            } for alt in cands[1:4]])
            db.update("evidence", ev["id"], {"state": state,
                     "confidence": float(cal.get("probability") or 0.0)})
            if state == "linked":
                _upsert_execution_event(project_id, ev, best, event_info, cal)

    checkpoint()
    report("resolver_validating",
           "Calibrating ranks and applying deterministic risk policy",
           "Identity confidence is separated from schedule-write authority")
    if raise_reviews:
        _raise_cluster_reviews(project_id, clusters, job_id)
    checkpoint()
    rebuild_observed_progress(project_id)
    return {"stats": stats, "clusters": len(clusters)}


def _add_cluster(clusters: dict, ev: dict, cands: list) -> None:
    key, title, question = cluster_key_for(ev, cands)
    c = clusters.setdefault(key, {"title": title, "question": question,
                                  "ids": [], "options": {}, "votes": {},
                                  "samples": []})
    c["ids"].append(ev["id"])
    # Score candidates across the whole cluster rather than per row: an option
    # that only ever came second for one record should not be offered to a
    # human as though the cluster agreed on it.
    for cand in cands[:3]:
        act = cand["activity"]
        ident = str(act.get("display_id") or act.get("uid"))
        label = ident + " · " + str(act.get("name") or "Unnamed activity")
        if act.get("wbs"):
            label += " · " + str(act.get("wbs"))
        c["options"][label] = act["uid"]
        v = c["votes"].setdefault(label, {"n": 0, "score": 0.0})
        v["n"] += 1
        v["score"] += cand["score"]
    if len(c["samples"]) < 4:
        c["samples"].append({
            "id": ev["id"], "source": ev.get("source_file"),
            "locator": ev.get("locator"), "date": ev.get("date"),
            "crew": ev.get("crew"), "discipline": ev.get("discipline"),
            "description": (ev.get("description") or "")[:200],
        })


def _raise_cluster_reviews(project_id: str, clusters: dict,
                           job_id: str | None) -> None:
    sched = reviews.current_schedule_context(project_id)
    revision = sched.get("revision")
    for key, c in clusters.items():
        votes = c.get("votes") or {}
        ranked = sorted(votes.items(), key=lambda kv: (-kv[1]["score"], -kv[1]["n"], kv[0]))
        options = [name for name, _ in ranked[:5]] or list(c["options"].keys())[:5]
        options.append("Leave unassigned for now")

        # A prior human mapping is reusable only for the same schedule revision
        # and the same order-independent candidate set (encoded in cluster key).
        prior = reviews.answers_for_cluster(project_id, key, revision)
        if prior and prior.get("answer") != "Leave unassigned for now":
            memory = dict(prior)
            memory["affected_ids"] = list(c["ids"])
            memory["context"] = {**(prior.get("context") or {}), "option_uids": c["options"]}
            try:
                effect = apply_cluster_answer(project_id, memory, job_id, from_memory=True)
                reviews.record_effect(prior["id"], {**(prior.get("resolution_effect") or {}),
                                                     "last_memory_application": effect})
                continue
            except ValueError:
                # If the current schedule/candidates make the old answer invalid,
                # ask again rather than forcing a stale mapping.
                pass

        reviews.create(
            project_id=project_id, kind="clarification", title=c["title"],
            question=(c["question"] + "\n\nOne choice applies only to these " +
                      str(len(c["ids"])) + " records with the same candidate set."),
            detail=("VEDA grouped only records with the same ambiguity and the same "
                    "candidate activities. The decision applies immediately."),
            options=options, cluster_key=key, affected_ids=c["ids"], job_id=job_id,
            priority="high" if len(c["ids"]) > 20 else "normal",
            extra={"samples": c["samples"], "option_uids": c["options"]})


def apply_cluster_answer(project_id: str, review: dict,
                         job_id: str | None = None, *, from_memory: bool = False) -> dict:
    """Apply a human mapping immediately; missing/stale answers never become no-ops."""
    ids = review.get("affected_ids") or []
    if not ids:
        return {"reprocessed": 0, "assigned": 0}
    sched = reviews.current_schedule_context(project_id)
    review_rev = review.get("schedule_revision")
    if review_rev is not None and sched.get("revision") != review_rev:
        raise ValueError("This decision belongs to an older schedule revision. Re-review it against the current schedule.")

    ctx = review.get("context") or {}
    option_uids = ctx.get("option_uids") or {}
    answer = (review.get("answer") or "").strip()
    rows = db.q("SELECT * FROM evidence WHERE id IN (" + ",".join("?" for _ in ids) + ")", ids)

    if answer == "Leave unassigned for now":
        for ev in rows:
            db.update("evidence", ev["id"], {"state": "deferred"})
        rebuild_observed_progress(project_id)
        return {"reprocessed": len(rows), "assigned": 0, "deferred": len(rows),
                "note": "left unassigned for now"}

    chosen_uid = option_uids.get(answer)
    if chosen_uid is None:
        raise ValueError("Choose one of the displayed activity options.")
    act = db.q1("SELECT * FROM activities WHERE project_id=? AND uid=?", [project_id, chosen_uid])
    if not act:
        raise ValueError("That activity is no longer present in the current schedule revision.")
    if sched.get("id") and act.get("snapshot_id") and act.get("snapshot_id") != sched.get("id"):
        raise ValueError("That activity belongs to an older schedule snapshot.")

    assigned = 0
    for ev in rows:
        vres = validators.validate_link(ev, act, project_id=project_id)
        db.ex("DELETE FROM evidence_links WHERE evidence_id=?", [ev["id"]])
        db.insert("evidence_links", {
            "project_id": project_id, "evidence_id": ev["id"],
            "activity_uid": chosen_uid, "activity_name": act.get("name"),
            "confidence": 0.95, "relation": "supporting",
            "supporting_signals": db.jdumps([
                ("reused human mapping from review " if from_memory else "assigned by human answer to review ") +
                str(review.get("id"))]),
            "conflicting_signals": db.jdumps(vres.get("failed") or []),
            "validator_result": vres["result"], "validator_json": db.jdumps(vres),
            "human_decision": "accepted", "review_id": review.get("id"),
            "decided_by": review.get("answered_by") or "human", "decided_at": db.now(),
            "is_candidate": 0, "provenance": "HUMAN_INPUT",
        })
        db.update("evidence", ev["id"], {"state": "confirmed", "confidence": 0.95})
        # A human identity decision is the point at which a field event may
        # enter the actuals proposal policy. This still creates proposals only.
        from . import actuals
        actuals.generate_from_confirmed_evidence(project_id, ev["id"], int(chosen_uid))
        assigned += 1

    rebuild_observed_progress(project_id)
    return {"reprocessed": len(rows), "assigned": assigned,
            "activity_uid": chosen_uid, "activity_display_id": act.get("display_id"),
            "activity_name": act.get("name"), "from_memory": from_memory}


def rebuild_observed_progress(project_id: str) -> None:
    """Observed field progress, kept strictly separate from official (spec 38)."""
    db.ex("DELETE FROM observed_progress WHERE project_id=?", [project_id])
    rows = db.q(
        "SELECT l.activity_uid AS uid, COUNT(*) AS n, "
        "       MAX(e.observed_progress) AS max_obs, "
        "       SUM(COALESCE(e.quantity,0)) AS qty, MAX(e.date) AS as_of "
        "FROM evidence_links l JOIN evidence e ON e.id=l.evidence_id "
        "WHERE l.project_id=? AND l.activity_uid IS NOT NULL "
        "AND l.relation IN ('supporting') AND l.is_candidate=0 "
        "AND e.state IN ('linked','confirmed') "
        "GROUP BY l.activity_uid", [project_id])
    if not rows:
        return
    # One read of the official percentages instead of one query per activity,
    # and one transaction instead of one commit per rebuilt row.
    official_by_uid = {r["uid"]: r.get("percent_complete") for r in db.q(
        "SELECT uid, percent_complete FROM activities WHERE project_id=?",
        [project_id]) if r.get("uid") is not None}
    stamp = db.now()
    payload = []
    for r in rows:
        official = official_by_uid.get(r["uid"])
        observed = r.get("max_obs")
        basis = "max reported observed_progress across linked evidence"
        if observed is None:
            basis = ("no evidence row states a progress percentage; " +
                     str(int(r["n"])) + " linked record(s) with quantity " +
                     str(round(r.get("qty") or 0, 1)))
        payload.append({
            "project_id": project_id, "activity_uid": r["uid"],
            "official_percent": official, "observed_percent": observed,
            "delta": (round(observed - official, 1)
                      if observed is not None and official is not None else None),
            "evidence_count": int(r["n"]), "as_of": r.get("as_of"),
            "basis": basis, "provenance": "DERIVED",
            "updated_at": stamp,
        })
    with db.transaction():
        for row in payload:
            db.insert("observed_progress", row)
