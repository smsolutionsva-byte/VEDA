"""Engineering candidate ranking.

Cold-start uses transparent domain weights.  When enough planner-labelled
candidate groups exist and XGBoost is available, VEDA can learn a LambdaMART
ranker (`rank:ndcg`) from the same audited features.  Retrieval score and
probability remain separate concepts.
"""
from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from .. import db

FEATURES = (
    "rerank", "dense", "sparse", "bge_sparse", "asset_exact", "asset_alias", "asset_ocr", "asset_negative", "asset_conflict", "asset_coverage",
    "action", "action_conflict", "phase", "phase_conflict", "location", "location_conflict", "discipline",
    "wbs", "wbs_ancestor", "wbs_code", "temporal", "actual_date", "current_date",
    "baseline_date", "date_corroboration", "graph", "pred_ready", "driving_pred_ready",
    "successor_progress", "relationship_consistency", "historical_sequence", "chainage",
    "source_trust", "agent_agreement",
)

# These are ordering priors, not probabilities.  They intentionally favor
# explicit engineering identity over planned dates or agent self-confidence.
COLD_WEIGHTS = {
    "rerank": .15, "dense": .075, "sparse": .055, "bge_sparse": .04,
    "asset_exact": .18, "asset_alias": .04, "asset_ocr": .065, "asset_negative": -.24, "asset_conflict": -.20, "asset_coverage": .05,
    "action": .13, "action_conflict": -.18,
    "phase": .09, "phase_conflict": -.16,
    "location": .08, "location_conflict": -.13,
    "discipline": .05,
    "wbs": .10, "wbs_ancestor": .05, "wbs_code": .06,
    "temporal": .11, "actual_date": .055, "current_date": .045, "baseline_date": .005,
    "date_corroboration": .025,
    "graph": .065, "pred_ready": .025, "driving_pred_ready": .02,
    "successor_progress": .01, "relationship_consistency": .02,
    "historical_sequence": .015,
    "chainage": .03, "source_trust": .01, "agent_agreement": .01,
}


def _v(feat: dict, name: str) -> float:
    try:
        return max(0.0, min(1.0, float(feat.get(name, 0.5))))
    except Exception:
        return 0.5


def cold_score(feat: dict) -> float:
    # Positive/negative weighted evidence around a neutral zero baseline.
    raw = 0.0
    positive_total = 0.0
    for k, w in COLD_WEIGHTS.items():
        val = _v(feat, k)
        if w >= 0:
            raw += w * val; positive_total += w
        else:
            raw += w * val
    return max(0.0, min(1.0, raw / max(positive_total, 1e-6)))


def _training_rows(project_id: str | None) -> tuple[list[list[float]], list[int], list[int]]:
    sql = "SELECT evidence_id,feature_json,human_decision FROM evidence_links WHERE human_decision IN ('accepted','rejected') AND feature_json IS NOT NULL"
    params: list[Any] = []
    if project_id:
        sql += " AND project_id=?"; params.append(project_id)
    rows = db.q(sql, params)
    grouped: dict[str, list[tuple[list[float], int]]] = {}
    for r in rows:
        try: f = json.loads(r.get("feature_json") or "{}")
        except Exception: continue
        if sum(1 for k in FEATURES if k in f) < 10: continue
        grouped.setdefault(str(r.get("evidence_id")), []).append(([_v(f,k) for k in FEATURES], 1 if r.get("human_decision") == "accepted" else 0))
    X: list[list[float]]=[]; y: list[int]=[]; qid: list[int]=[]
    gid=0
    for items in grouped.values():
        if len(items) < 2 or not any(v for _,v in items):
            continue
        for x, lab in items:
            X.append(x); y.append(lab); qid.append(gid)
        gid += 1
    return X,y,qid


_MODEL_CACHE: dict[tuple[str,int], Any] = {}


def _learned_model(project_id: str):
    X,y,qid = _training_rows(project_id)
    scope="project"
    if len(set(qid)) < 35 or len(X) < 120:
        X,y,qid = _training_rows(None); scope="global"
    if len(set(qid)) < 60 or len(X) < 220:
        return None, {"mode":"cold_start", "training_rows":len(X), "groups":len(set(qid))}
    key=(scope,len(X))
    if key in _MODEL_CACHE:
        return _MODEL_CACHE[key], {"mode":"xgb_lambdamart", "scope":scope, "training_rows":len(X), "groups":len(set(qid))}
    try:
        from xgboost import XGBRanker  # optional dependency
    except Exception:
        return None, {"mode":"cold_start", "reason":"xgboost_not_installed", "training_rows":len(X), "groups":len(set(qid))}
    order=sorted(range(len(qid)), key=lambda i: qid[i])
    X=[X[i] for i in order]; y=[y[i] for i in order]; qid=[qid[i] for i in order]
    model=XGBRanker(objective="rank:ndcg", n_estimators=160, max_depth=4,
                    learning_rate=.045, subsample=.9, colsample_bytree=.9,
                    reg_lambda=1.2, random_state=26122, tree_method="hist")
    model.fit(X,y,qid=qid,verbose=False)
    _MODEL_CACHE[key]=model
    return model, {"mode":"xgb_lambdamart", "scope":scope, "training_rows":len(X), "groups":len(set(qid))}


def rank(project_id: str, candidates: list[dict]) -> dict:
    model, diag = _learned_model(project_id)
    if model is None:
        for c in candidates:
            c["features"]["engineering_rank_score"] = cold_score(c["features"])
            c["score"] = c["features"]["engineering_rank_score"]
    else:
        X=[[_v(c["features"],k) for k in FEATURES] for c in candidates]
        pred=model.predict(X)
        lo,hi=min(pred),max(pred)
        for c,s in zip(candidates,pred):
            norm=.5 if hi-lo<1e-9 else float((s-lo)/(hi-lo))
            c["features"]["engineering_rank_score"] = norm
            c["score"] = norm
    candidates.sort(key=lambda c:c["score"], reverse=True)
    for pos,c in enumerate(candidates):
        runner=max((x["score"] for j,x in enumerate(candidates) if j!=pos), default=0.0)
        c["features"]["rank_margin"] = max(0.0, c["score"]-runner) if pos==0 else 0.0
        c["features"]["rank_position"] = 1.0/(pos+1)
    return {"candidates":candidates, "diagnostics":diag}
