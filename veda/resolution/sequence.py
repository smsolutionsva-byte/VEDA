"""Historical schedule-sequence recommender and model-selection advice.

The runtime recommender is deliberately simple and explainable: association
statistics over canonical action transitions.  A separate advisor tells the
agent when historical data is large enough to evaluate graph embeddings/GNNs;
it does not choose a complex model merely because one exists.
"""
from __future__ import annotations

import threading
from collections import Counter
from typing import Any

from .. import db
from .events import detect_action

# ---------------------------------------------------------------- memoisation
# score_candidate() is called once per candidate, i.e. tens of times per
# evidence row.  Its inputs -- corpus counts, per-project action labels and
# cross-project transition statistics -- change only when a schedule revision is
# ingested.  Recomputing them per candidate turned an O(1) feature into a scan
# of every activity in every project.  These caches are keyed on a cheap corpus
# signature so a new revision still invalidates them immediately.
_LOCK = threading.Lock()
_STATS_CACHE: dict = {}
_ACTION_CACHE: dict[str, tuple[tuple, dict[int, str]]] = {}
_TRANSITION_CACHE: dict[str | None, tuple[tuple, tuple[Counter, Counter]]] = {}
_REL_CACHE: dict[str, tuple[tuple, dict[int, list[dict]]]] = {}


def _corpus_signature() -> tuple:
    # score_candidate() runs per candidate, so the freshness probe is itself
    # held briefly; every cache-invalidating write clears it.
    return db.cached_probe("seq_corpus_sig", _read_corpus_signature)


def _read_corpus_signature() -> tuple:
    row = db.q1("SELECT COUNT(*) e, COALESCE(MAX(rowid),0) m FROM relationships") or {}
    act = db.q1("SELECT COUNT(*) a, COALESCE(MAX(rowid),0) m FROM activities") or {}
    return (int(row.get("e") or 0), int(row.get("m") or 0),
            int(act.get("a") or 0), int(act.get("m") or 0))


def _project_signature(project_id: str) -> tuple:
    return db.cached_probe(("seq_project_sig", project_id),
                           lambda: _read_project_signature(project_id))


def _read_project_signature(project_id: str) -> tuple:
    row = db.q1("SELECT COUNT(*) c, COALESCE(MAX(rowid),0) m FROM relationships "
                "WHERE project_id=?", [project_id]) or {}
    act = db.q1("SELECT COUNT(*) c, COALESCE(MAX(rowid),0) m FROM activities "
                "WHERE project_id=?", [project_id]) or {}
    return (int(row.get("c") or 0), int(row.get("m") or 0),
            int(act.get("c") or 0), int(act.get("m") or 0))


def invalidate_cache(project_id: str | None = None) -> None:
    """Drop memoised corpus views. Called when a schedule revision lands."""
    db.clear_probe_cache()
    with _LOCK:
        _STATS_CACHE.clear()
        _TRANSITION_CACHE.clear()
        if project_id is None:
            _ACTION_CACHE.clear()
            _REL_CACHE.clear()
        else:
            _ACTION_CACHE.pop(project_id, None)
            _REL_CACHE.pop(project_id, None)


def corpus_stats() -> dict:
    sig = _corpus_signature()
    with _LOCK:
        cached = _STATS_CACHE.get("stats")
        if cached and cached[0] == sig:
            return dict(cached[1])
    projects = (db.q1("SELECT COUNT(DISTINCT project_id) c FROM relationships") or {}).get("c", 0)
    edges = (db.q1("SELECT COUNT(*) c FROM relationships") or {}).get("c", 0)
    nodes = (db.q1("SELECT COUNT(*) c FROM activities WHERE is_summary=0") or {}).get("c", 0)
    stats = {"projects": int(projects or 0), "edges": int(edges or 0), "nodes": int(nodes or 0),
             "edge_node_ratio": round(float(edges or 0) / max(1, int(nodes or 0)), 4)}
    with _LOCK:
        _STATS_CACHE["stats"] = (sig, stats)
    return dict(stats)


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
    sig = _project_signature(project_id)
    with _LOCK:
        cached = _ACTION_CACHE.get(project_id)
        if cached and cached[0] == sig:
            return cached[1]
    out = {}
    for a in db.q("SELECT uid,name FROM activities WHERE project_id=? AND is_summary=0", [project_id]):
        if a.get("uid") is None:
            continue
        action = detect_action(a.get("name"))["action"]
        if action:
            out[int(a["uid"])] = action
    with _LOCK:
        _ACTION_CACHE[project_id] = (sig, out)
    return out


def _relationships_by_uid(project_id: str) -> dict[int, list[dict]]:
    """Adjacency for one project, built once per revision instead of per candidate."""
    sig = _project_signature(project_id)
    with _LOCK:
        cached = _REL_CACHE.get(project_id)
        if cached and cached[0] == sig:
            return cached[1]
    index: dict[int, list[dict]] = {}
    for r in db.q("SELECT pred_uid,succ_uid FROM relationships WHERE project_id=?", [project_id]):
        for key in (r.get("pred_uid"), r.get("succ_uid")):
            if key is None:
                continue
            index.setdefault(int(key), []).append(r)
    with _LOCK:
        _REL_CACHE[project_id] = (sig, index)
    return index


def transition_counts(exclude_project: str | None = None) -> tuple[Counter, Counter]:
    sig = _corpus_signature()
    with _LOCK:
        cached = _TRANSITION_CACHE.get(exclude_project)
        if cached and cached[0] == sig:
            return cached[1]
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
    with _LOCK:
        _TRANSITION_CACHE[exclude_project] = (sig, (pair, src))
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
    try:
        act_uid = int(act.get("uid"))
    except (TypeError, ValueError):
        return {"score": 0.5, "available": True, "support": [], "stats": stats}
    rels = _relationships_by_uid(project_id).get(act_uid, ())
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
