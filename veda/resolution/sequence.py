"""Historical schedule-sequence recommender and model-selection advice.

The runtime recommender is deliberately simple and explainable: association
statistics over canonical action transitions.  A separate advisor tells the
agent when historical data is large enough to evaluate graph embeddings/GNNs;
it does not choose a complex model merely because one exists.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

from .. import db
from .events import detect_action


def corpus_stats() -> dict:
    projects = (db.q1("SELECT COUNT(DISTINCT project_id) c FROM relationships") or {}).get("c", 0)
    edges = (db.q1("SELECT COUNT(*) c FROM relationships") or {}).get("c", 0)
    nodes = (db.q1("SELECT COUNT(*) c FROM activities WHERE is_summary=0") or {}).get("c", 0)
    return {"projects": int(projects or 0), "edges": int(edges or 0), "nodes": int(nodes or 0),
            "edge_node_ratio": round(float(edges or 0) / max(1, int(nodes or 0)), 4)}


def model_advice() -> dict:
    s = corpus_stats()
    if s["projects"] < 8 or s["edges"] < 500:
        rec = "association_rules"
        reason = "Historical graph corpus is small; prefer explainable transition counts and explicit schedule logic."
    elif s["projects"] < 40 or s["edges"] < 20000:
        rec = "evaluate_deepwalk_node2vec"
        reason = "Corpus is large enough to benchmark random-walk graph embeddings; keep association rules as baseline."
    else:
        rec = "benchmark_gnn_against_recommenders"
        reason = "Graph corpus is substantial enough to justify a controlled GNN benchmark, but promotion requires held-out-project improvement over simpler recommenders."
    return {**s, "recommended_strategy": rec, "reason": reason,
            "principle": "Choose by held-out project accuracy/latency, not model complexity."}


def _action_by_uid(project_id: str) -> dict[int, str]:
    out = {}
    for a in db.q("SELECT uid,name FROM activities WHERE project_id=? AND is_summary=0", [project_id]):
        if a.get("uid") is None:
            continue
        action = detect_action(a.get("name"))["action"]
        if action:
            out[int(a["uid"])] = action
    return out


def transition_counts(exclude_project: str | None = None) -> tuple[Counter, Counter]:
    pair, src = Counter(), Counter()
    projects = [r["project_id"] for r in db.q("SELECT DISTINCT project_id FROM relationships")
                if r.get("project_id") and r.get("project_id") != exclude_project]
    for pid in projects:
        acts = _action_by_uid(pid)
        for r in db.q("SELECT pred_uid,succ_uid FROM relationships WHERE project_id=?", [pid]):
            try:
                pa, sa = acts.get(int(r.get("pred_uid"))), acts.get(int(r.get("succ_uid")))
            except Exception:
                continue
            if pa and sa:
                pair[(pa, sa)] += 1
                src[pa] += 1
    return pair, src


def score_candidate(project_id: str, act: dict) -> dict:
    """Estimate support from historical action transitions around this candidate."""
    stats = corpus_stats()
    if stats["projects"] < 3 or stats["edges"] < 100:
        return {"score": 0.5, "available": False, "support": [], "stats": stats}
    pair, src = transition_counts(exclude_project=project_id)
    action = detect_action(act.get("name"))["action"]
    if not action:
        return {"score": 0.5, "available": True, "support": [], "stats": stats}
    support = []
    vals = []
    rels = db.q("SELECT pred_uid,succ_uid FROM relationships WHERE project_id=? AND (pred_uid=? OR succ_uid=?)",
                [project_id, act.get("uid"), act.get("uid")])
    acts = _action_by_uid(project_id)
    for r in rels:
        if int(r.get("succ_uid") or -1) == int(act.get("uid") or -2):
            paction = acts.get(int(r.get("pred_uid") or -1))
            if paction and src[paction]:
                conf = pair[(paction, action)] / src[paction]
                vals.append(conf); support.append({"transition": f"{paction}->{action}", "confidence": round(conf,4), "count": pair[(paction, action)]})
    if not vals:
        return {"score": 0.5, "available": True, "support": support, "stats": stats}
    return {"score": max(0.0, min(1.0, sum(vals)/len(vals))), "available": True,
            "support": support[:6], "stats": stats}
