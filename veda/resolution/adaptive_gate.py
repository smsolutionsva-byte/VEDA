"""Learned query-level gate between EngineeringRank and WorkfrontRank.

The gate is deliberately *not* a collection of domain rules such as
"disable graph when WBS exists".  It learns, from planner-labelled or benchmark
resolver outcomes, which expert tends to be more trustworthy for a given
observation context.

Runtime inference has no scikit-learn dependency: training exports a transparent
linear logistic model (standardisation statistics + coefficients) to JSON.
If no trained model is present, VEDA safely falls back to EngineeringRank.

The expert outputs remain separate:
  * EngineeringRank: textual + structured engineering identity.
  * WorkfrontRank: live execution-frontier / graph conditioned identity.

The gate only decides which expert should have authority for this observation.
It never changes schedule data and its probability is not the activity-match
confidence.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from ..retrieval.entities import extract_asset_tags, extract_location_tags
from . import events as event_model

MODEL_PATH = Path(__file__).with_name("adaptive_execution_gate_v030.json")

# Query-level, benchmark-category-independent features.  These describe the
# evidence and the *shape of disagreement* between the two experts rather than
# encoding handcrafted case labels such as "WBS" or "workfront".
FEATURE_NAMES = [
    "evidence_asset_count",
    "evidence_location_count",
    "evidence_action_known",
    "evidence_phase_known",
    "evidence_historical_uid",
    "base_top_score",
    "base_margin",
    "base_entropy_top8",
    "base_asset_exact",
    "base_asset_alias",
    "base_asset_conflict",
    "base_action",
    "base_phase",
    "base_location",
    "base_wbs",
    "base_wbs_ancestor",
    "base_wbs_code",
    "base_temporal",
    "base_graph",
    "base_pred_ready",
    "candidate_asset_spread",
    "candidate_wbs_spread",
    "candidate_location_spread",
    "candidate_temporal_spread",
    "candidate_graph_spread",
    "frontier_top",
    "frontier_margin",
    "frontier_entropy",
    "frontier_count_norm",
    "wf_top_score",
    "wf_margin",
    "wf_execution_frontier",
    "wf_ppr",
    "wf_frontier_channel",
    "wf_graph_spread",
    "expert_top_agree",
    "expert_top_base_rank_in_wf",
    "expert_top_wf_rank_in_base",
]


def _f(v: Any, default: float = 0.0) -> float:
    try:
        x = float(v)
        if math.isnan(x) or math.isinf(x):
            return default
        return x
    except Exception:
        return default


def _clip01(v: Any) -> float:
    return max(0.0, min(1.0, _f(v)))


def _margin(cands: list[dict]) -> float:
    if not cands:
        return 0.0
    a = _f(cands[0].get("score"))
    b = _f(cands[1].get("score")) if len(cands) > 1 else 0.0
    return max(0.0, a - b)


def _entropy_from_scores(scores: list[float], temperature: float = 0.10) -> float:
    """Normalised softmax entropy in [0,1]; 1 means highly ambiguous."""
    vals = [_f(x) for x in scores if x is not None]
    n = len(vals)
    if n <= 1:
        return 0.0
    m = max(vals)
    ex = [math.exp(max(-40.0, min(40.0, (x - m) / max(temperature, 1e-6)))) for x in vals]
    s = sum(ex) or 1.0
    p = [x / s for x in ex]
    h = -sum(x * math.log(max(x, 1e-12)) for x in p)
    return max(0.0, min(1.0, h / math.log(n)))


def _spread(cands: list[dict], key: str, n: int = 8) -> float:
    vals = [_clip01((c.get("features") or {}).get(key, 0.5)) for c in cands[:n]]
    return (max(vals) - min(vals)) if vals else 0.0


def _rank_uid(cands: list[dict], uid: int | None) -> int | None:
    if uid is None:
        return None
    for i, c in enumerate(cands, 1):
        try:
            if int((c.get("activity") or {}).get("uid")) == int(uid):
                return i
        except Exception:
            pass
    return None


def _frontier_stats(frontier_info: dict | None) -> tuple[float, float, float, float]:
    scores = sorted((_f(v) for v in ((frontier_info or {}).get("scores") or {}).values()), reverse=True)
    if not scores:
        return 0.0, 0.0, 1.0, 0.0
    top = scores[0]
    margin = top - (scores[1] if len(scores) > 1 else 0.0)
    entropy = _entropy_from_scores(scores[:24], temperature=0.12)
    # Saturates around 48 frontier candidates (the current retrieval cap).
    count_norm = min(1.0, len(scores) / 48.0)
    return _clip01(top), _clip01(margin), entropy, count_norm


def context_features(ev: dict, engineering_candidates: list[dict], workfront_candidates: list[dict],
                     frontier_info: dict | None = None) -> dict[str, float]:
    """Build gate features without any benchmark-category or answer label."""
    base = engineering_candidates or []
    wf = workfront_candidates or []
    btop = base[0] if base else {}
    wtop = wf[0] if wf else {}
    bf = btop.get("features") or {}
    wff = wtop.get("features") or {}

    tags = [x for x in extract_asset_tags(ev.get("description"), ev.get("asset_tag"), ev.get("asset_tags"))
            if isinstance(x, dict) and x.get("type") != "document"]
    locs = extract_location_tags(ev.get("description"), ev.get("location"), ev.get("wbs"), ev.get("wbs_path"))
    einfo = event_model.classify_event(ev)
    ftop, fmargin, fent, fcount = _frontier_stats(frontier_info)

    base_uid = (btop.get("activity") or {}).get("uid") if btop else None
    wf_uid = (wtop.get("activity") or {}).get("uid") if wtop else None
    br_in_wf = _rank_uid(wf, base_uid)
    wr_in_base = _rank_uid(base, wf_uid)

    out = {
        "evidence_asset_count": min(1.0, len(tags) / 2.0),
        "evidence_location_count": min(1.0, len(locs) / 3.0),
        "evidence_action_known": 1.0 if einfo.get("action") else 0.0,
        "evidence_phase_known": 1.0 if einfo.get("phase") else 0.0,
        "evidence_historical_uid": 1.0 if ev.get("historical_activity_uid") is not None else 0.0,
        "base_top_score": _clip01(btop.get("score") if btop else 0.0),
        "base_margin": _clip01(_margin(base)),
        "base_entropy_top8": _entropy_from_scores([_f(c.get("score")) for c in base[:8]]),
        "base_asset_exact": _clip01(bf.get("asset_exact", 0.0)),
        "base_asset_alias": _clip01(bf.get("asset_alias", 0.0)),
        "base_asset_conflict": _clip01(bf.get("asset_conflict", 0.0)),
        "base_action": _clip01(bf.get("action", 0.5)),
        "base_phase": _clip01(bf.get("phase", 0.5)),
        "base_location": _clip01(bf.get("location", 0.5)),
        "base_wbs": _clip01(bf.get("wbs", 0.5)),
        "base_wbs_ancestor": _clip01(bf.get("wbs_ancestor", 0.0)),
        "base_wbs_code": _clip01(bf.get("wbs_code", 0.0)),
        "base_temporal": _clip01(bf.get("temporal", 0.5)),
        "base_graph": _clip01(bf.get("graph", 0.5)),
        "base_pred_ready": _clip01(bf.get("pred_ready", 0.5)),
        "candidate_asset_spread": _spread(base, "asset_exact"),
        "candidate_wbs_spread": _spread(base, "wbs"),
        "candidate_location_spread": _spread(base, "location"),
        "candidate_temporal_spread": _spread(base, "temporal"),
        "candidate_graph_spread": _spread(base, "graph"),
        "frontier_top": ftop,
        "frontier_margin": fmargin,
        "frontier_entropy": fent,
        "frontier_count_norm": fcount,
        "wf_top_score": _clip01(wtop.get("score") if wtop else 0.0),
        "wf_margin": _clip01(_margin(wf)),
        "wf_execution_frontier": _clip01(wff.get("execution_frontier", 0.0)),
        "wf_ppr": _clip01(wff.get("workfront_ppr", 0.0)),
        "wf_frontier_channel": _clip01(wff.get("frontier_channel", 0.0)),
        "wf_graph_spread": _spread(wf, "execution_frontier"),
        "expert_top_agree": 1.0 if base_uid is not None and wf_uid is not None and int(base_uid) == int(wf_uid) else 0.0,
        # Reciprocal ranks are bounded and represent how violently the experts disagree.
        "expert_top_base_rank_in_wf": 1.0 / br_in_wf if br_in_wf else 0.0,
        "expert_top_wf_rank_in_base": 1.0 / wr_in_base if wr_in_base else 0.0,
    }
    return {k: _f(out.get(k), 0.0) for k in FEATURE_NAMES}


def load_model(path: str | Path | None = None) -> dict | None:
    p = Path(path) if path else MODEL_PATH
    if not p.exists():
        return None
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    if obj.get("feature_names") != FEATURE_NAMES:
        return None
    if len(obj.get("coef") or []) != len(FEATURE_NAMES):
        return None
    return obj


def predict(features: dict[str, float], model: dict | None = None) -> dict:
    """Predict probability that WorkfrontRank should be the authoritative expert."""
    model = model or load_model()
    if not model:
        return {
            "route": "engineering",
            "p_workfront": 0.0,
            "p_engineering": 1.0,
            "model_loaded": False,
            "reason": "no_trained_gate_model_safe_default",
            "contributions": [],
        }
    mean = model.get("mean") or [0.0] * len(FEATURE_NAMES)
    scale = model.get("scale") or [1.0] * len(FEATURE_NAMES)
    coef = model.get("coef") or [0.0] * len(FEATURE_NAMES)
    intercept = _f(model.get("intercept"), 0.0)
    z = intercept
    contrib = []
    for i, name in enumerate(FEATURE_NAMES):
        x = _f(features.get(name), 0.0)
        s = _f(scale[i], 1.0) or 1.0
        std = (x - _f(mean[i])) / s
        c = std * _f(coef[i])
        z += c
        contrib.append((name, c, x))
    z = max(-40.0, min(40.0, z))
    p = 1.0 / (1.0 + math.exp(-z))
    # Argmax over the two experts.  This is model selection, not a handcrafted
    # WBS/workfront rule.  Exact ties retain the cheaper/default engineering expert.
    route = "workfront" if p > 0.5 else "engineering"
    top = sorted(contrib, key=lambda x: abs(x[1]), reverse=True)[:8]
    return {
        "route": route,
        "p_workfront": p,
        "p_engineering": 1.0 - p,
        "model_loaded": True,
        "model_version": model.get("version"),
        "contributions": [{"feature": n, "logit_contribution": c, "value": v} for n, c, v in top],
    }


def route(ev: dict, engineering_candidates: list[dict], workfront_candidates: list[dict],
          frontier_info: dict | None = None, model: dict | None = None) -> dict:
    features = context_features(ev, engineering_candidates, workfront_candidates, frontier_info)
    pred = predict(features, model=model)
    pred["features"] = features
    return pred
