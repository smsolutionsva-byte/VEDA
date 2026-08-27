"""Probability calibration for evidence->activity identity matches.

Ranking and probability are deliberately separate. The resolver emits a raw
ranking score plus independent retrieval/context/agent features. Human
accept/reject decisions then fit either:

1. a multivariate logistic meta-model once enough reviewed examples exist, or
2. a Platt-style sigmoid over the raw ranking score during early learning.

Until enough labels exist, VEDA returns an explicitly-labelled conservative
prior rather than pretending cosine/reranker/LLM scores are probabilities.
"""
from __future__ import annotations

import json
import math
from typing import Any

from .. import db

MIN_LOCAL = 24
MIN_GLOBAL = 60
MIN_CLASS = 5
MIN_FEATURE_LOCAL = 80
MIN_FEATURE_GLOBAL = 200
MIN_FEATURE_CLASS = 15

# Deliberately small, interpretable identity feature set. Agent judgement is one
# corroborating signal rather than a privileged probability source.
FEATURE_KEYS = (
    "raw_score", "rerank", "dense", "sparse", "bge_sparse",
    "asset_exact", "asset_alias", "asset_ocr", "asset_negative", "asset_conflict", "asset_coverage",
    "action", "action_conflict", "phase", "phase_conflict", "location", "location_conflict", "discipline",
    "wbs", "wbs_ancestor", "wbs_code",
    "temporal", "actual_date", "current_date", "baseline_date", "date_corroboration",
    "graph", "pred_ready", "driving_pred_ready", "successor_progress",
    "relationship_consistency", "historical_sequence", "chainage", "source_trust",
    "rank_margin", "agent_support",
)



def _sigmoid(z: float) -> float:
    if z >= 0:
        e = math.exp(-z)
        return 1.0 / (1.0 + e)
    e = math.exp(z)
    return e / (1.0 + e)


def _label_records(project_id: str | None = None) -> list[tuple[dict, int]]:
    sql = ("SELECT feature_json, human_decision FROM evidence_links "
           "WHERE human_decision IN ('accepted','rejected') AND feature_json IS NOT NULL")
    params: list[Any] = []
    if project_id:
        sql += " AND project_id=?"
        params.append(project_id)
    out = []
    for r in db.q(sql, params):
        try:
            feat = json.loads(r.get("feature_json") or "{}")
            raw = float(feat.get("raw_score"))
        except Exception:
            continue
        feat["raw_score"] = max(0.0, min(1.0, raw))
        feat["agent_support"] = max(0.0, min(1.0,
            float(feat.get("agent_agreement") or 0.0) * float(feat.get("agent_confidence") or 0.0)))
        out.append((feat, 1 if r.get("human_decision") == "accepted" else 0))
    return out


def _label_records_by_project() -> dict[str, list[tuple[dict, int]]]:
    out: dict[str, list[tuple[dict, int]]] = {}
    rows = db.q("SELECT project_id,feature_json,human_decision FROM evidence_links "
                "WHERE human_decision IN ('accepted','rejected') AND feature_json IS NOT NULL")
    for r in rows:
        try:
            feat = json.loads(r.get("feature_json") or "{}")
            raw = float(feat.get("raw_score"))
        except Exception:
            continue
        feat["raw_score"] = max(0.0, min(1.0, raw))
        feat["agent_support"] = max(0.0, min(1.0,
            float(feat.get("agent_agreement") or 0.0) * float(feat.get("agent_confidence") or 0.0)))
        out.setdefault(str(r.get("project_id") or "unknown"), []).append(
            (feat, 1 if r.get("human_decision") == "accepted" else 0))
    return out


def _labels(project_id: str | None = None) -> list[tuple[float, int]]:
    return [(float(f["raw_score"]), y) for f, y in _label_records(project_id)]


def _eligible(rows: list, minimum: int, min_class: int = MIN_CLASS) -> bool:
    if len(rows) < minimum:
        return False
    pos = sum(y for _, y in rows)
    return pos >= min_class and len(rows) - pos >= min_class


def _fit_platt(rows: list[tuple[float, int]]) -> tuple[float, float]:
    """Fit p=sigmoid(a*x+b) with small L2 regularization, pure Python."""
    a, b = 5.0, -2.5
    lr = 0.08
    reg = 0.015
    n = max(1, len(rows))
    for step in range(900):
        ga = gb = 0.0
        for x, y in rows:
            p = _sigmoid(a * x + b)
            err = p - y
            ga += err * x
            gb += err
        ga = ga / n + reg * a
        gb = gb / n + reg * b
        rate = lr / (1.0 + step / 500.0)
        a -= rate * ga
        b -= rate * gb
    return a, b


def _vector(feat: dict) -> list[float]:
    f = dict(feat or {})
    f["agent_support"] = max(0.0, min(1.0,
        float(f.get("agent_agreement") or 0.0) * float(f.get("agent_confidence") or 0.0)))
    vals = []
    for k in FEATURE_KEYS:
        try:
            vals.append(max(0.0, min(1.0, float(f.get(k, 0.5 if k not in
                {"asset_exact", "agent_support"} else 0.0)))))
        except Exception:
            vals.append(0.5)
    return vals


def _feature_rows(records: list[tuple[dict, int]]) -> list[tuple[list[float], int]]:
    # Require evidence of the richer resolver rather than fitting 13 mostly
    # default-valued features on legacy decisions.
    out = []
    for feat, y in records:
        observed = sum(1 for k in ("rerank", "dense", "sparse", "asset_exact", "action", "wbs", "temporal", "graph")
                       if k in feat)
        if observed >= 4:
            out.append((_vector(feat), y))
    return out


def _fit_feature_logit(rows: list[tuple[list[float], int]]) -> dict:
    """Regularized, standardized logistic meta-model with class balancing.

    This learns how much to trust semantic retrieval, exact engineering tags,
    WBS/graph/date context and agent agreement from actual planner decisions.
    """
    m = len(FEATURE_KEYS)
    n = len(rows)
    means = [sum(x[j] for x, _ in rows) / n for j in range(m)]
    scales = []
    for j in range(m):
        var = sum((x[j] - means[j]) ** 2 for x, _ in rows) / max(1, n - 1)
        scales.append(max(math.sqrt(var), 0.08))
    zrows = [([(x[j] - means[j]) / scales[j] for j in range(m)], y) for x, y in rows]
    pos = sum(y for _, y in rows); neg = n - pos
    pos_w = n / max(2.0 * pos, 1.0); neg_w = n / max(2.0 * neg, 1.0)
    w = [0.0] * m
    # Initialize the raw-score feature positively so very small datasets do not
    # spend many iterations discovering the obvious direction.
    w[0] = 0.8
    b = math.log((pos + 1.0) / (neg + 1.0))
    reg, lr = 0.045, 0.06
    for step in range(1300):
        gw = [0.0] * m; gb = 0.0; total_w = 0.0
        for x, y in zrows:
            p = _sigmoid(sum(wj*xj for wj, xj in zip(w, x)) + b)
            sw = pos_w if y else neg_w
            err = (p - y) * sw
            total_w += sw
            for j in range(m): gw[j] += err * x[j]
            gb += err
        denom = max(total_w, 1.0)
        rate = lr / (1.0 + step / 700.0)
        for j in range(m):
            w[j] -= rate * (gw[j] / denom + reg * w[j])
        b -= rate * gb / denom
    return {"weights": w, "bias": b, "means": means, "scales": scales}


def _feature_predict(model: dict, feat: dict) -> float:
    x = _vector(feat)
    z = model["bias"]
    for j, v in enumerate(x):
        z += model["weights"][j] * ((v - model["means"][j]) / model["scales"][j])
    return _sigmoid(z)


def _prior(raw: float) -> float:
    # Conservative cold-start mapping: moderate ranking scores remain review
    # candidates; only very strong multi-signal matches approach auto-link range.
    return _sigmoid(7.0 * (raw - 0.66))


def _meta(mode: str, rows: list, *, scope: str) -> dict:
    pos = sum(y for _, y in rows) if rows else 0
    return {"mode": mode, "scope": scope, "n": len(rows), "positive_count": pos,
            "negative_count": max(0, len(rows)-pos), "is_calibrated": mode != "conservative_prior",
            "model_version": "veda-calibration-0.3"}


_VALIDATION_CACHE: dict[tuple[int, int], dict] = {}


def _probability_metrics(pred_pairs: list[tuple[float, int]]) -> dict:
    if not pred_pairs:
        return {"n":0,"brier":None,"ece":None,"bins":[]}
    brier = sum((p-y)**2 for p,y in pred_pairs)/len(pred_pairs)
    bins=[]
    for i in range(10):
        lo=i/10; hi=(i+1)/10
        vals=[(p,y) for p,y in pred_pairs if lo <= p < hi or (i==9 and p<=1.0)]
        if vals:
            mp=sum(p for p,_ in vals)/len(vals); acc=sum(y for _,y in vals)/len(vals)
            bins.append({"from":lo,"to":hi,"n":len(vals),"mean_predicted":round(mp,4),"empirical_accuracy":round(acc,4)})
    ece=sum((b["n"]/len(pred_pairs))*abs(b["mean_predicted"]-b["empirical_accuracy"]) for b in bins)
    return {"n":len(pred_pairs),"brier":round(brier,5),"ece":round(ece,5),"bins":bins}


def _precision_threshold(pred_pairs: list[tuple[float,int]], target: float = 0.99, min_selected: int = 20) -> dict:
    if not pred_pairs:
        return {"threshold":None,"precision":None,"coverage":0.0,"selected":0}
    thresholds=sorted({round(p,6) for p,_ in pred_pairs}, reverse=True)
    best=None
    for t in thresholds:
        sel=[y for p,y in pred_pairs if p>=t]
        if len(sel)<min_selected:
            continue
        precision=sum(sel)/len(sel)
        if precision+1e-12 >= target:
            cand={"threshold":t,"precision":precision,"coverage":len(sel)/len(pred_pairs),"selected":len(sel)}
            if best is None or cand["coverage"]>best["coverage"]:
                best=cand
    if best is None:
        return {"threshold":None,"precision":None,"coverage":0.0,"selected":0}
    return {"threshold":round(best["threshold"],6),"precision":round(best["precision"],5),
            "coverage":round(best["coverage"],5),"selected":best["selected"]}


def validation_diagnostics(target_precision: float = 0.99) -> dict:
    """Leave-one-project-out validation for calibration/risk thresholds.

    Random row splits leak project-specific naming/WBS conventions.  This
    validation trains on other projects and predicts the held-out project, then
    derives an automation threshold only if the requested precision is actually
    observed on those out-of-project predictions.
    """
    grouped=_label_records_by_project()
    total=sum(len(v) for v in grouped.values())
    key=(len(grouped),total)
    if key in _VALIDATION_CACHE:
        return _VALIDATION_CACHE[key]
    if len(grouped)<3 or total<120:
        out={"validated":False,"method":"leave_one_project_out","projects":len(grouped),"n":total,
             "reason":"need at least 3 reviewed projects and 120 labelled candidate decisions",
             "target_precision":target_precision,"threshold":None}
        _VALIDATION_CACHE[key]=out; return out
    preds=[]; folds=[]
    for holdout, test_records in grouped.items():
        train_records=[r for pid,rows in grouped.items() if pid!=holdout for r in rows]
        train_feat=_feature_rows(train_records); test_feat=_feature_rows(test_records)
        if _eligible(train_feat, MIN_FEATURE_GLOBAL, MIN_FEATURE_CLASS) and test_feat:
            model=_fit_feature_logit(train_feat)
            fold=[(_feature_predict(model,f),y) for f,y in test_records
                  if sum(1 for k in ("rerank","dense","sparse","asset_exact","wbs","temporal","graph") if k in f)>=4]
            mode="feature_logit"
        else:
            train_raw=[(float(f["raw_score"]),y) for f,y in train_records]
            test_raw=[(float(f["raw_score"]),y) for f,y in test_records]
            if not _eligible(train_raw, MIN_GLOBAL):
                continue
            a,b=_fit_platt(train_raw); fold=[(_sigmoid(a*x+b),y) for x,y in test_raw]; mode="platt"
        if fold:
            preds.extend(fold); folds.append({"project_id":holdout,"n":len(fold),"mode":mode})
    metrics=_probability_metrics(preds)
    threshold=_precision_threshold(preds,target_precision,min_selected=max(20,int(.03*len(preds))))
    out={"validated":bool(preds),"method":"leave_one_project_out","projects":len(folds),
         "n":len(preds),"target_precision":target_precision,**metrics,**threshold,"folds":folds}
    _VALIDATION_CACHE[key]=out
    return out




def _validated_meta(payload: dict) -> dict:
    val=validation_diagnostics()
    payload["risk_validation"]={k:val.get(k) for k in ("validated","method","projects","n","target_precision","threshold","precision","coverage","brier","ece")}
    payload["validated_auto_link_threshold"]=val.get("threshold") if val.get("validated") else None
    return payload

def calibrated_probability(raw_score: float, project_id: str, features: dict | None = None) -> dict:
    raw = max(0.0, min(1.0, float(raw_score)))
    current = dict(features or {})
    current["raw_score"] = raw

    local_records = _label_records(project_id)
    local_features = _feature_rows(local_records)
    if features is not None and _eligible(local_features, MIN_FEATURE_LOCAL, MIN_FEATURE_CLASS):
        model = _fit_feature_logit(local_features)
        return _validated_meta({"probability": _feature_predict(model, current),
                **_meta("project_feature_logit", local_features, scope="project"),
                "features": list(FEATURE_KEYS)})

    local = [(float(f["raw_score"]), y) for f, y in local_records]
    if _eligible(local, MIN_LOCAL):
        a, b = _fit_platt(local)
        return _validated_meta({"probability": _sigmoid(a * raw + b),
                **_meta("project_platt", local, scope="project"), "a": a, "b": b})

    global_records = _label_records(None)
    global_features = _feature_rows(global_records)
    if features is not None and _eligible(global_features, MIN_FEATURE_GLOBAL, MIN_FEATURE_CLASS):
        model = _fit_feature_logit(global_features)
        return _validated_meta({"probability": _feature_predict(model, current),
                **_meta("global_feature_logit", global_features, scope="global"),
                "features": list(FEATURE_KEYS)})

    global_rows = [(float(f["raw_score"]), y) for f, y in global_records]
    if _eligible(global_rows, MIN_GLOBAL):
        a, b = _fit_platt(global_rows)
        return _validated_meta({"probability": _sigmoid(a * raw + b),
                **_meta("global_platt", global_rows, scope="global"), "a": a, "b": b})
    return {"probability": _prior(raw),
            **_meta("conservative_prior", local, scope="project" if local else "none"),
            "note": "Cold-start prior is NOT an empirically calibrated probability."}


def diagnostics(project_id: str) -> dict:
    local_records = _label_records(project_id)
    local_features = _feature_rows(local_records)
    if _eligible(local_features, MIN_FEATURE_LOCAL, MIN_FEATURE_CLASS):
        records, scope, mode = local_records, "project", "project_feature_logit"
        feature_rows = local_features
        model = _fit_feature_logit(feature_rows)
        pred_pairs = [(_feature_predict(model, f), y) for f, y in records
                      if sum(1 for k in ("rerank", "dense", "sparse", "wbs", "temporal", "graph") if k in f) >= 4]
        coeff = sorted(zip(FEATURE_KEYS, model["weights"]), key=lambda z: abs(z[1]), reverse=True)
    else:
        global_records = _label_records(None)
        global_features = _feature_rows(global_records)
        if _eligible(global_features, MIN_FEATURE_GLOBAL, MIN_FEATURE_CLASS):
            records, scope, mode = global_records, "global", "global_feature_logit"
            model = _fit_feature_logit(global_features)
            pred_pairs = [(_feature_predict(model, f), y) for f, y in global_records
                          if sum(1 for k in ("rerank", "dense", "sparse", "wbs", "temporal", "graph") if k in f) >= 4]
            coeff = sorted(zip(FEATURE_KEYS, model["weights"]), key=lambda z: abs(z[1]), reverse=True)
        else:
            local = [(float(f["raw_score"]), y) for f, y in local_records]
            global_rows = [(float(f["raw_score"]), y) for f, y in global_records]
            if _eligible(local, MIN_LOCAL):
                use, scope, mode = local, "project", "project_platt"
            elif _eligible(global_rows, MIN_GLOBAL):
                use, scope, mode = global_rows, "global", "global_platt"
            else:
                use = local or global_rows
                scope, mode = ("project" if local else "global" if global_rows else "none"), "conservative_prior"
            if not use:
                return {"mode": "conservative_prior", "scope": "none", "n": 0,
                        "brier": None, "bins": [], "note": "collect human accept/reject decisions"}
            if mode.endswith("platt"):
                a, b = _fit_platt(use); pred = lambda x: _sigmoid(a*x+b)
            else:
                pred = _prior
            pred_pairs = [(pred(x), y) for x, y in use]
            coeff = []

    brier = sum((p-y)**2 for p, y in pred_pairs) / max(1, len(pred_pairs))
    bins = []
    for lo in [i / 10 for i in range(10)]:
        hi = lo + 0.1
        items = [(p, y) for p, y in pred_pairs if lo <= p < hi or (hi >= 1 and p <= hi)]
        if items:
            bins.append({"from": round(lo, 1), "to": round(hi, 1), "n": len(items),
                         "mean_predicted": round(sum(p for p, _ in items) / len(items), 3),
                         "empirical_accuracy": round(sum(y for _, y in items) / len(items), 3)})
    ece = sum((b["n"] / max(1, len(pred_pairs))) * abs(b["mean_predicted"] - b["empirical_accuracy"]) for b in bins)
    return {"mode": mode, "scope": scope, "n": len(pred_pairs),
            "positives": sum(y for _, y in pred_pairs), "negatives": len(pred_pairs)-sum(y for _, y in pred_pairs),
            "brier": round(brier, 4), "ece": round(ece, 4), "bins": bins,
            "top_feature_weights": [{"feature": k, "weight": round(v, 3)} for k, v in coeff[:8]],
            "model_version": "veda-calibration-0.3",
            "held_out_validation": validation_diagnostics(),
            "note": "In-sample Brier/ECE are descriptive; held_out_validation uses leave-one-project-out folds and is the only source allowed to propose an automation threshold."}
