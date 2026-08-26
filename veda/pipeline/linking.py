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
from datetime import datetime, timedelta
from typing import Any

from .. import db, reviews
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
        return ("crew_location:" + crew.lower(),
                "Records from crew " + crew + " carry no spread or chainage",
                "Which part of the works does crew " + crew + " belong to?")
    if not has_loc and not has_ch and not crew:
        return ("no_location:" + str(ev.get("source_file") or "unknown"),
                "Records in " + str(ev.get("source_file")) +
                " carry no location, chainage or crew",
                "How should records from " + str(ev.get("source_file")) +
                " be attributed?")
    if not disc:
        return ("no_discipline:" + str(ev.get("source_file") or "unknown"),
                "Records in " + str(ev.get("source_file")) +
                " do not state a discipline",
                "Which discipline do these records describe?")
    if len(cands) >= 2 and abs(cands[0]["score"] - cands[1]["score"]) < 0.08:
        return ("tie:" + str(disc),
                str(disc).title() + " records match more than one activity equally",
                "Which activity should " + str(disc) + " records attach to when the "
                "signals tie?")
    return ("weak:" + str(ev.get("source_file") or "unknown"),
            "Records in " + str(ev.get("source_file")) +
            " match no activity strongly",
            "How should these records be attributed?")


ACCEPT = 0.62
MARGIN = 0.10


def link_evidence(project_id: str, *, job_id: str | None = None,
                  evidence_rows: list | None = None,
                  agent_links: dict | None = None,
                  status_date: str | None = None,
                  raise_reviews: bool = True) -> dict:
    """Associate evidence with activities and record the outcome.

    agent_links maps evidence_id -> list of {activity_uid, confidence, relation,
    supporting_signals, conflicting_signals} proposed by the model. Model
    proposals are treated as candidates, then validated like any other.
    """
    acts = db.q("SELECT * FROM activities WHERE project_id=?", [project_id])
    by_uid = {a["uid"]: a for a in acts}
    if evidence_rows is None:
        evidence_rows = db.q(
            "SELECT * FROM evidence WHERE project_id=? AND state IN "
            "('new','processing','needs_review')", [project_id])

    if status_date is None:
        snap = db.q1("SELECT status_date FROM schedule_snapshots WHERE project_id=? "
                     "AND is_current=1", [project_id])
        status_date = (snap or {}).get("status_date")

    stats = {"linked": 0, "needs_review": 0, "unresolved": 0, "conflicting": 0,
             "historical": 0, "duplicate": 0, "quarantined": 0}
    clusters: dict = {}

    for ev in evidence_rows:
        if ev.get("security_state") in ("suspicious", "quarantined"):
            db.update("evidence", ev["id"], {"state": "quarantined"})
            stats["quarantined"] += 1
            continue

        db.ex("DELETE FROM evidence_links WHERE evidence_id=? AND "
              "(human_decision IS NULL OR human_decision='')", [ev["id"]])

        cands = candidates_for(ev, acts)

        # Fold in whatever the model proposed, so its judgement is scored too.
        for prop in (agent_links or {}).get(ev["id"], []):
            uid = prop.get("activity_uid")
            act = by_uid.get(uid)
            if act is None:
                continue
            existing = next((c for c in cands if c["activity"]["uid"] == uid), None)
            model_conf = float(prop.get("confidence") or 0.5)
            if existing:
                existing["score"] = round(
                    min(1.0, existing["score"] * 0.7 + model_conf * 0.45), 3)
                existing["supporting"] = list(dict.fromkeys(
                    existing["supporting"] + list(prop.get("supporting_signals") or [])))
                existing["conflicting"] = list(dict.fromkeys(
                    existing["conflicting"] +
                    list(prop.get("conflicting_signals") or [])))
                existing["from_agent"] = True
            else:
                cands.append({"activity": act, "score": round(model_conf * 0.8, 3),
                              "supporting": list(prop.get("supporting_signals") or []),
                              "conflicting": list(
                                  prop.get("conflicting_signals") or []),
                              "from_agent": True})
        cands.sort(key=lambda x: -x["score"])

        if not cands:
            db.update("evidence", ev["id"], {"state": "needs_review"})
            stats["unresolved"] += 1
            _add_cluster(clusters, ev, cands)
            continue

        best = cands[0]
        runner = cands[1] if len(cands) > 1 else None
        vres = validators.validate_link(ev, best["activity"], project_id=project_id,
                                        status_date=status_date)

        decisive = best["score"] >= ACCEPT and (
            runner is None or best["score"] - runner["score"] >= MARGIN)

        if vres["result"] == validators.FAIL:
            state, relation, is_cand = "conflicting", "conflicting", 1
            stats["conflicting"] += 1
        elif not decisive:
            state, relation, is_cand = "needs_review", "unresolved", 1
            stats["needs_review"] += 1
            _add_cluster(clusters, ev, cands)
        else:
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
            else:
                state, relation, is_cand = "linked", "supporting", 0
                stats["linked"] += 1

        db.insert("evidence_links", {
            "project_id": project_id, "evidence_id": ev["id"],
            "activity_uid": best["activity"]["uid"],
            "activity_name": best["activity"]["name"],
            "confidence": best["score"], "relation": relation,
            "supporting_signals": db.jdumps(best["supporting"]),
            "conflicting_signals": db.jdumps(best["conflicting"]),
            "validator_result": vres["result"],
            "validator_json": db.jdumps(vres),
            "is_candidate": is_cand,
            "provenance": "AI_INFERENCE" if best.get("from_agent")
            else "DETERMINISTIC_CALCULATION",
        })
        # Keep the alternatives visible - contradictions are never hidden (spec 37).
        for alt in cands[1:3]:
            db.insert("evidence_links", {
                "project_id": project_id, "evidence_id": ev["id"],
                "activity_uid": alt["activity"]["uid"],
                "activity_name": alt["activity"]["name"],
                "confidence": alt["score"], "relation": "unresolved",
                "supporting_signals": db.jdumps(alt["supporting"]),
                "conflicting_signals": db.jdumps(alt["conflicting"]),
                "validator_result": None, "is_candidate": 1,
                "provenance": "DETERMINISTIC_CALCULATION",
            })

        db.update("evidence", ev["id"], {"state": state,
                                         "confidence": best["score"]})

    if raise_reviews:
        _raise_cluster_reviews(project_id, clusters, job_id)

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
        c["options"][act["name"]] = act["uid"]
        v = c["votes"].setdefault(act["name"], {"n": 0, "score": 0.0})
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
    for key, c in clusters.items():
        if reviews.answers_for_cluster(project_id, key):
            continue  # already settled by a human
        votes = c.get("votes") or {}
        ranked = sorted(votes.items(),
                        key=lambda kv: (-kv[1]["score"], -kv[1]["n"]))
        options = [name for name, _ in ranked[:5]] or \
            list(c["options"].keys())[:5]
        options.append("Leave unassigned for now")
        reviews.create(
            project_id=project_id, kind="clarification",
            title=c["title"],
            question=(c["question"] + "\n\nAnswering once resolves all " +
                      str(len(c["ids"])) + " affected records."),
            detail=("VEDA grouped " + str(len(c["ids"])) + " records that are "
                    "ambiguous for the same reason, so only this one question "
                    "needs answering."),
            options=options, cluster_key=key, affected_ids=c["ids"],
            job_id=job_id, priority="high" if len(c["ids"]) > 20 else "normal",
            extra={"samples": c["samples"],
                   "option_uids": c["options"]})


def apply_cluster_answer(project_id: str, review: dict,
                         job_id: str | None = None) -> dict:
    """Re-process every record a single human answer unblocks (spec 42)."""
    ids = review.get("affected_ids") or []
    if not ids:
        return {"reprocessed": 0}
    ctx = review.get("context") or {}
    option_uids = ctx.get("option_uids") or {}
    answer = (review.get("answer") or "").strip()
    chosen_uid = option_uids.get(answer)

    if chosen_uid is None:
        for label, uid in option_uids.items():
            if answer and (answer.lower() in label.lower()
                           or label.lower() in answer.lower()):
                chosen_uid = uid
                break

    rows = db.q("SELECT * FROM evidence WHERE id IN (" +
                ",".join("?" for _ in ids) + ")", ids)

    if chosen_uid is None:
        # The human declined to assign. Record that and stop asking.
        for ev in rows:
            db.update("evidence", ev["id"], {"state": "needs_review"})
        return {"reprocessed": 0, "assigned": 0,
                "note": "no activity chosen; records left for review"}

    act = db.q1("SELECT * FROM activities WHERE project_id=? AND uid=?",
                [project_id, chosen_uid])
    assigned = 0
    for ev in rows:
        vres = validators.validate_link(ev, act, project_id=project_id)
        db.ex("DELETE FROM evidence_links WHERE evidence_id=?", [ev["id"]])
        db.insert("evidence_links", {
            "project_id": project_id, "evidence_id": ev["id"],
            "activity_uid": chosen_uid,
            "activity_name": (act or {}).get("name"),
            "confidence": 0.95, "relation": "supporting",
            "supporting_signals": db.jdumps(
                ["assigned by human answer to review " + str(review.get("id"))]),
            "conflicting_signals": db.jdumps(vres.get("failed") or []),
            "validator_result": vres["result"],
            "validator_json": db.jdumps(vres),
            "human_decision": "accepted",
            "decided_by": review.get("answered_by") or "human",
            "decided_at": db.now(),
            "is_candidate": 0,
            "provenance": "HUMAN_INPUT",
        })
        db.update("evidence", ev["id"], {"state": "confirmed", "confidence": 0.95})
        assigned += 1

    rebuild_observed_progress(project_id)
    return {"reprocessed": len(rows), "assigned": assigned,
            "activity_uid": chosen_uid}


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
    for r in rows:
        act = db.q1("SELECT percent_complete, name FROM activities "
                    "WHERE project_id=? AND uid=?", [project_id, r["uid"]])
        official = (act or {}).get("percent_complete")
        observed = r.get("max_obs")
        basis = "max reported observed_progress across linked evidence"
        if observed is None:
            observed = None
            basis = ("no evidence row states a progress percentage; " +
                     str(int(r["n"])) + " linked record(s) with quantity " +
                     str(round(r.get("qty") or 0, 1)))
        db.insert("observed_progress", {
            "project_id": project_id, "activity_uid": r["uid"],
            "official_percent": official, "observed_percent": observed,
            "delta": (round(observed - official, 1)
                      if observed is not None and official is not None else None),
            "evidence_count": int(r["n"]), "as_of": r.get("as_of"),
            "basis": basis, "provenance": "DERIVED",
            "updated_at": db.now(),
        })
