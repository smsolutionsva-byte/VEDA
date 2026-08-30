"""VEDA v0.3.2 contextual multi-expert resolver.

Production-hardened accuracy-first fusion over four heterogeneous experts:
semantic, engineering, tree, and reality-first rescheduler.  Experts retain
independent candidate channels.  Learned query-level utility models estimate
expert usefulness, and a LambdaMART model ranks the deduplicated candidate
union.  Benchmark category labels are never features.

Important score semantics:
* LambdaMART margins are ranking scores, not probabilities.
* ``meta_rank_raw`` preserves the raw model margin.
* public ``score`` is a fixed monotonic bounded transform used only to preserve
  ranking and margin geometry for downstream rank features.
* calibrated correctness probability is produced later by VEDA's calibration
  layer, never here.
"""
from __future__ import annotations

import functools
import json
import math
import time
from pathlib import Path
from typing import Any

from ..retrieval.entities import extract_asset_tags, extract_location_tags
from . import events as event_model

EXPERTS = ("semantic", "engineering", "tree", "rescheduler")
MODEL_DIR = Path(__file__).with_name("meta_models_v032")
CONFIG_FILE = MODEL_DIR / "meta_config.json"
RANKER_MODEL = MODEL_DIR / "candidate_metarank.json"
UTILITY_MODELS = {e: MODEL_DIR / f"utility_{e}.json" for e in EXPERTS}
PUBLIC_SCORE_TEMPERATURE = 2.0

QUERY_FEATURES = [
    "asset_count", "location_count", "action_known", "phase_known",
    "positive_state", "finish_state", "historical_uid", "text_len", "explicit_wbs",
    *[f"{e}_margin" for e in EXPERTS],
    *[f"{e}_entropy" for e in EXPERTS],
    *[f"{e}_top_score" for e in EXPERTS],
    "top_disagreement", "sem_eng_agree", "eng_tree_agree",
    "tree_replan_agree", "eng_replan_agree",
]

CAND_FEATURES = [
    *[f"{e}_present" for e in EXPERTS],
    *[f"{e}_rr" for e in EXPERTS],
    *[f"{e}_norm" for e in EXPERTS],
    *[f"{e}_top1" for e in EXPERTS],
    "present_count", "top1_votes", "rr_mean", "rr_max", "rr_std",
    "rerank", "dense", "sparse", "bge_sparse", "rrf",
    "asset_exact", "asset_alias", "asset_conflict", "action", "phase", "location",
    "wbs", "wbs_ancestor", "wbs_code", "temporal", "graph", "pred_ready",
    "tree_asset", "tree_location", "tree_action", "tree_phase", "tree_branch",
    "tree_leaf_text", "tree_temporal",
    "replan_readiness", "replan_temporal", "replan_recent", "replan_future",
    "replan_unlock", "replan_oos", "replan_override", "replan_exception",
    *[f"q_{x}" for x in QUERY_FEATURES],
    *[f"utility_{e}" for e in EXPERTS],
]


def _f(v: Any, d: float = 0.0) -> float:
    try:
        x = float(v)
        return d if math.isnan(x) or math.isinf(x) else x
    except Exception:
        return d


def _uid(c: dict | None):
    try:
        return int(((c or {}).get("activity") or {}).get("uid"))
    except Exception:
        return None


def _margin(cs: list[dict]) -> float:
    if not cs:
        return 0.0
    return max(0.0, _f(cs[0].get("score")) - (_f(cs[1].get("score")) if len(cs) > 1 else 0.0))


def _entropy(cs: list[dict], t: float = 0.1) -> float:
    if len(cs) <= 1:
        return 0.0
    vals = [_f(c.get("score")) for c in cs[:12]]
    m = max(vals)
    exps = [math.exp(max(-40.0, min(40.0, (x - m) / t))) for x in vals]
    z = sum(exps) or 1.0
    probs = [x / z for x in exps]
    h = -sum(p * math.log(max(p, 1e-12)) for p in probs) / math.log(len(probs))
    return max(0.0, min(1.0, h))


def _norm(cs: list[dict]) -> dict[int, float]:
    """Per-expert min/max normalization used only as a MetaRank input feature."""
    if not cs:
        return {}
    vals = [_f(c.get("score")) for c in cs]
    lo, hi = min(vals), max(vals)
    out = {}
    for c, x in zip(cs, vals):
        uid = _uid(c)
        if uid is None:
            continue
        out[uid] = 0.5 if hi - lo < 1e-12 else (x - lo) / (hi - lo)
    return out


def _sigmoid_margin(raw: float) -> float:
    """Fixed monotonic bounded transform; deliberately not a probability."""
    z = max(-40.0, min(40.0, _f(raw) / PUBLIC_SCORE_TEMPERATURE))
    return 1.0 / (1.0 + math.exp(-z))


def _dedupe_text(items) -> list[str]:
    out, seen = [], set()
    for x in items or []:
        s = str(x)
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _path_signature(path: Path) -> tuple[str, int | None, int | None]:
    try:
        st = path.stat()
        return (str(path), int(st.st_mtime_ns), int(st.st_size))
    except Exception:
        return (str(path), None, None)


@functools.lru_cache(maxsize=16)
def _booster_cached(path_s: str, mtime_ns: int | None, size: int | None):
    """Load one XGBoost model keyed by path + file state."""
    if mtime_ns is None or size is None:
        return None
    try:
        import xgboost as xgb
        b = xgb.Booster()
        b.load_model(path_s)
        return b
    except Exception:
        return None


def _booster(path: Path):
    return _booster_cached(*_path_signature(path))


@functools.lru_cache(maxsize=8)
def _schema_health_cached(config_sig, ranker_sig, utility_sigs):
    problems = []
    cfg = None
    try:
        cfg = json.loads(Path(config_sig[0]).read_text(encoding="utf-8"))
    except Exception as ex:
        problems.append(f"meta_config_unreadable:{type(ex).__name__}:{ex}")
        cfg = {}

    if tuple(cfg.get("experts") or ()) != EXPERTS:
        problems.append("expert_schema_mismatch")
    if list(cfg.get("query_features") or []) != QUERY_FEATURES:
        problems.append("query_feature_schema_mismatch")
    if list(cfg.get("candidate_features") or []) != CAND_FEATURES:
        problems.append("candidate_feature_schema_mismatch")
    if str(cfg.get("version") or "") != "0.3.2":
        problems.append("model_version_mismatch")
    if ranker_sig[1] is None:
        problems.append("ranker_model_missing")
    for name, sig in zip(EXPERTS, utility_sigs):
        if sig[1] is None:
            problems.append(f"utility_model_missing:{name}")

    dependency = None
    try:
        import xgboost as xgb
        dependency = getattr(xgb, "__version__", "unknown")
    except Exception as ex:
        problems.append(f"xgboost_unavailable:{type(ex).__name__}:{ex}")

    return {
        "ok": not problems,
        "version": cfg.get("version"),
        "experts": list(EXPERTS),
        "query_feature_count": len(QUERY_FEATURES),
        "candidate_feature_count": len(CAND_FEATURES),
        "xgboost": dependency,
        "problems": problems,
    }


_HEALTH_TTL = 30.0
_health_snapshot: tuple[float, dict] | None = None


def model_health(*, fresh: bool = False) -> dict:
    """Return frozen-model/schema health without loading any query data.

    ``rank`` asks this once per observation, and the underlying check stats six
    model files.  Frozen release models do not change under a running server, so
    the answer is held for a short TTL; ``fresh=True`` forces a real re-stat for
    the /health endpoint and for warmup.
    """
    global _health_snapshot
    if not fresh and _health_snapshot is not None:
        stamp, snapshot = _health_snapshot
        if (time.monotonic() - stamp) < _HEALTH_TTL:
            return dict(snapshot)
    cfg_sig = _path_signature(CONFIG_FILE)
    ranker_sig = _path_signature(RANKER_MODEL)
    util_sigs = tuple(_path_signature(UTILITY_MODELS[e]) for e in EXPERTS)
    snapshot = dict(_schema_health_cached(cfg_sig, ranker_sig, util_sigs))
    snapshot["fast_predict_verified"] = _INPLACE_OK
    _health_snapshot = (time.monotonic(), snapshot)
    return dict(snapshot)


# ``inplace_predict`` skips DMatrix construction, which dominates runtime when
# each call scores a handful of rows -- exactly VEDA's per-observation shape.
# It is only used after warmup has proved, on this machine's xgboost build, that
# it reproduces DMatrix predictions bit-for-bit within float tolerance.  A frozen
# release model must not change its ranking to go faster.
_INPLACE_OK: bool | None = None
_INPLACE_TOLERANCE = 1e-6


def _predict_dmatrix(booster, matrix, names: list[str]):
    import xgboost as xgb
    return booster.predict(xgb.DMatrix(matrix, feature_names=names),
                           validate_features=False)


def _predict(booster, matrix, names: list[str]):
    """Score a small matrix with the cheapest verified path."""
    if _INPLACE_OK:
        try:
            return booster.inplace_predict(matrix)
        except Exception:
            pass
    return _predict_dmatrix(booster, matrix, names)


def _verify_inplace_path(booster, names: list[str]) -> bool:
    """Return True only when inplace and DMatrix predictions agree."""
    try:
        import numpy as np
        probes = np.asarray([
            [0.0] * len(names),
            [0.5] * len(names),
            list(np.linspace(0.0, 1.0, len(names))),
        ], dtype=np.float32)
        reference = np.asarray(_predict_dmatrix(booster, probes, names), dtype=np.float64)
        fast = np.asarray(booster.inplace_predict(probes), dtype=np.float64)
        return bool(reference.shape == fast.shape and
                    np.allclose(reference, fast, rtol=0.0, atol=_INPLACE_TOLERANCE))
    except Exception:
        return False


def warmup_models() -> dict:
    """Load the frozen router off the first user request's critical path."""
    health = model_health(fresh=True)
    if health.get("ok"):
        for path in [*UTILITY_MODELS.values(), RANKER_MODEL]:
            _booster(path)
        # Prove the fast prediction path reproduces the frozen model exactly,
        # then run one throwaway prediction per model so xgboost's first-call
        # allocation happens here rather than inside the first observation the
        # operator is waiting on.
        global _INPLACE_OK
        try:
            import numpy as np
            checks = [(_booster(UTILITY_MODELS[e]), QUERY_FEATURES) for e in EXPERTS]
            checks.append((_booster(RANKER_MODEL), CAND_FEATURES))
            loaded = [(b, names) for b, names in checks if b]
            _INPLACE_OK = bool(loaded) and all(
                _verify_inplace_path(b, names) for b, names in loaded)
            for b, names in loaded:
                _predict(b, np.zeros((1, len(names)), dtype=np.float32), names)
        except Exception:
            _INPLACE_OK = False
        # The snapshot taken above predates the fast-path verdict; drop it so the
        # next health read reports the verified state.
        global _health_snapshot
        _health_snapshot = None
        health = model_health()
    return health


def query_features(ev: dict, experts: dict[str, list[dict]]) -> dict[str, float]:
    tags = [x for x in extract_asset_tags(
        ev.get("description"), ev.get("asset_tag"), ev.get("asset_tags"))
        if isinstance(x, dict) and x.get("type") != "document"]
    locs = extract_location_tags(ev.get("description"), ev.get("location"),
                                 ev.get("wbs"), ev.get("wbs_path"))
    ei = event_model.classify_event(ev)
    st = ei.get("state")
    tops = {e: _uid((experts.get(e) or [{}])[0]) if experts.get(e) else None for e in EXPERTS}
    distinct = len({u for u in tops.values() if u is not None})
    q = {
        "asset_count": min(1.0, len(tags) / 2),
        "location_count": min(1.0, len(locs) / 3),
        "action_known": 1.0 if ei.get("action") else 0.0,
        "phase_known": 1.0 if ei.get("phase") else 0.0,
        "positive_state": 1.0 if st in {"start", "progress", "finish", "mixed"} else 0.0,
        "finish_state": 1.0 if st == "finish" else 0.0,
        "historical_uid": 1.0 if ev.get("historical_activity_uid") is not None else 0.0,
        "text_len": min(1.0, len(str(ev.get("description") or "")) / 180),
        "explicit_wbs": 1.0 if ev.get("wbs") or ev.get("wbs_path") else 0.0,
        "top_disagreement": max(0.0, distinct - 1) / 3,
    }
    for e in EXPERTS:
        cs = experts.get(e) or []
        q[f"{e}_margin"] = min(1.0, _margin(cs))
        q[f"{e}_entropy"] = _entropy(cs)
        q[f"{e}_top_score"] = _f(cs[0].get("score")) if cs else 0.0
    q["sem_eng_agree"] = 1.0 if tops["semantic"] is not None and tops["semantic"] == tops["engineering"] else 0.0
    q["eng_tree_agree"] = 1.0 if tops["engineering"] is not None and tops["engineering"] == tops["tree"] else 0.0
    q["tree_replan_agree"] = 1.0 if tops["tree"] is not None and tops["tree"] == tops["rescheduler"] else 0.0
    q["eng_replan_agree"] = 1.0 if tops["engineering"] is not None and tops["engineering"] == tops["rescheduler"] else 0.0
    return {k: _f(q.get(k)) for k in QUERY_FEATURES}


def _merge_carrier(uid: int, by: dict[str, dict[int, dict]]) -> dict:
    """Merge provenance/safety data without changing learned feature schema."""
    ordered = [by["engineering"].get(uid), by["semantic"].get(uid),
               by["tree"].get(uid), by["rescheduler"].get(uid)]
    ordered = [c for c in ordered if c]
    carrier = ordered[0] if ordered else {}
    merged_features = {}
    # Semantic first, then specialist features; Engineering last for safety fields.
    for name in ("semantic", "tree", "rescheduler", "engineering"):
        c = by[name].get(uid)
        if c:
            merged_features.update(dict(c.get("features") or {}))
    supporting, conflicting = [], []
    for c in ordered:
        supporting.extend(c.get("supporting") or [])
        conflicting.extend(c.get("conflicting") or [])
    return {
        "activity": carrier.get("activity"),
        "features": merged_features,
        "supporting": _dedupe_text(supporting),
        "conflicting": _dedupe_text(conflicting),
        "from_agent": any(bool(c.get("from_agent")) for c in ordered),
    }


def candidate_rows(ev: dict, experts: dict[str, list[dict]], utilities=None):
    utilities = utilities or {e: 0.5 for e in EXPERTS}
    q = query_features(ev, experts)
    ranks, norms, by = {}, {}, {}
    union, seen = [], set()

    for e in EXPERTS:
        cs = experts.get(e) or []
        ranks[e] = {_uid(c): i for i, c in enumerate(cs, 1) if _uid(c) is not None}
        norms[e] = _norm(cs)
        by[e] = {_uid(c): c for c in cs if _uid(c) is not None}

    # Round-robin candidate union avoids one expert monopolizing the short list.
    for i in range(24):
        for e in EXPERTS:
            cs = experts.get(e) or []
            if i < len(cs):
                uid = _uid(cs[i])
                if uid is not None and uid not in seen:
                    seen.add(uid)
                    union.append(uid)

    out = []
    for uid in union:
        f, rr = {}, []
        for e in EXPERTS:
            r = ranks[e].get(uid)
            f[f"{e}_present"] = 1.0 if r else 0.0
            f[f"{e}_rr"] = 1.0 / r if r else 0.0
            f[f"{e}_norm"] = norms[e].get(uid, 0.0)
            f[f"{e}_top1"] = 1.0 if r == 1 else 0.0
            if r:
                rr.append(1.0 / r)
        f["present_count"] = len(rr) / 4
        f["top1_votes"] = sum(f[f"{e}_top1"] for e in EXPERTS) / 4
        f["rr_mean"] = sum(rr) / len(rr) if rr else 0.0
        f["rr_max"] = max(rr) if rr else 0.0
        f["rr_std"] = (sum((x - f["rr_mean"]) ** 2 for x in rr) / len(rr)) ** 0.5 if rr else 0.0

        sf = (by["semantic"].get(uid) or {}).get("features") or {}
        ef = (by["engineering"].get(uid) or {}).get("features") or {}
        tf = (by["tree"].get(uid) or {}).get("features") or {}
        rf = (by["rescheduler"].get(uid) or {}).get("features") or {}
        for k in ("rerank", "dense", "sparse", "bge_sparse", "rrf"):
            f[k] = _f(sf.get(k))
        for k in ("asset_exact", "asset_alias", "asset_conflict", "action", "phase", "location",
                  "wbs", "wbs_ancestor", "wbs_code", "temporal", "graph", "pred_ready"):
            default = 0.5 if k in {"action", "phase", "location", "wbs", "temporal", "graph", "pred_ready"} else 0.0
            f[k] = _f(ef.get(k), default)
        for k in ("tree_asset", "tree_location", "tree_action", "tree_phase",
                  "tree_branch", "tree_leaf_text", "tree_temporal"):
            f[k] = _f(tf.get(k), 0.5)
        f.update({
            "replan_readiness": _f(rf.get("replan_pre_observation_readiness"), 0.5),
            "replan_temporal": _f(rf.get("replan_temporal"), 0.5),
            "replan_recent": _f(rf.get("replan_recent_state")),
            "replan_future": _f(rf.get("replan_future_utility"), 0.5),
            "replan_unlock": _f(rf.get("replan_unlock")),
            "replan_oos": 1.0 if rf.get("replan_oos_detected") else 0.0,
            "replan_override": _f(rf.get("replan_override_context")),
            "replan_exception": _f(rf.get("replan_exception_explained")),
        })
        for k, v in q.items():
            f[f"q_{k}"] = v
        for e in EXPERTS:
            f[f"utility_{e}"] = _f(utilities.get(e), 0.5)

        merged = _merge_carrier(uid, by)
        out.append({
            "uid": uid,
            "activity": merged["activity"],
            "features": f,
            "carrier_features": merged["features"],
            "supporting": merged["supporting"],
            "conflicting": merged["conflicting"],
            "from_agent": merged["from_agent"],
        })
    return out, q


def predict_utilities(q: dict[str, float]) -> dict[str, float]:
    try:
        import numpy as np
        row = np.asarray([[q[k] for k in QUERY_FEATURES]], dtype=np.float32)
        out = {}
        for e in EXPERTS:
            b = _booster(UTILITY_MODELS[e])
            out[e] = float(_predict(b, row, QUERY_FEATURES)[0]) if b else 0.5
        return {e: max(0.0, min(1.0, p)) for e, p in out.items()}
    except Exception:
        return {e: 0.5 for e in EXPERTS}


def weighted_rrf(experts: dict[str, list[dict]], utilities: dict[str, float], limit: int = 24):
    scores, by = {}, {e: {_uid(c): c for c in (experts.get(e) or []) if _uid(c) is not None} for e in EXPERTS}
    for e in EXPERTS:
        w = max(0.03, _f(utilities.get(e), 0.5))
        for r, c in enumerate(experts.get(e) or [], 1):
            uid = _uid(c)
            if uid is None:
                continue
            scores[uid] = scores.get(uid, 0.0) + w / (60 + r)
    ranked = sorted(scores.items(), key=lambda z: z[1], reverse=True)
    if not ranked:
        return []
    vals = [s for _, s in ranked]
    lo, hi = min(vals), max(vals)
    rows = []
    for uid, raw in ranked[:limit]:
        # Fallback score remains intentionally compressed when candidates are close.
        public = 0.5 if hi - lo < 1e-12 else 0.45 + 0.10 * ((raw - lo) / (hi - lo))
        merged = _merge_carrier(uid, by)
        feats = dict(merged["features"])
        if "raw_score" in feats:
            feats["pre_meta_raw_score"] = _f(feats.get("raw_score"))
        feats.update({
            "meta_rrf": raw,
            "meta_rank_raw": raw,
            "meta_rank_score": public,
            "meta_rank_score_semantics": "utility_rrf_fallback_not_probability",
        })
        rows.append({
            "activity": merged["activity"], "score": public, "features": feats,
            "supporting": merged["supporting"], "conflicting": merged["conflicting"],
            "from_agent": merged["from_agent"],
        })
    margin = max(0.0, rows[0]["score"] - (rows[1]["score"] if len(rows) > 1 else 0.0)) if rows else 0.0
    for c in rows:
        c["features"]["rank_margin"] = margin
    return rows


def rank(ev: dict, experts: dict[str, list[dict]], limit: int = 24) -> dict:
    q = query_features(ev, experts)
    utilities = predict_utilities(q)
    rows, _ = candidate_rows(ev, experts, utilities)
    health = model_health()
    booster = _booster(RANKER_MODEL) if health.get("ok") else None

    if not booster or not rows:
        return {
            "candidates": weighted_rrf(experts, utilities, limit),
            "diagnostics": {
                "mode": "utility_rrf_fallback", "utilities": utilities,
                "query": q, "model_health": health, "union": len(rows),
            },
        }

    try:
        import numpy as np
        X = np.asarray([[r["features"].get(k, 0.0) for k in CAND_FEATURES] for r in rows], dtype=np.float32)
        pred = _predict(booster, X, CAND_FEATURES)
        cand = []
        for r, raw in zip(rows, pred):
            raw = float(raw)
            public = _sigmoid_margin(raw)
            feats = dict(r.get("carrier_features") or {})
            if "raw_score" in feats:
                feats["pre_meta_raw_score"] = _f(feats.get("raw_score"))
            # Keep the learned feature vector too for audit/reproducibility.
            feats.update(r["features"])
            feats.update({
                "meta_rank_raw": raw,
                "meta_rank_score": public,
                "meta_rank_score_semantics": "fixed_logistic_margin_scale_not_probability",
            })
            cand.append({
                "activity": r["activity"], "score": public, "features": feats,
                "supporting": list(r.get("supporting") or []),
                "conflicting": list(r.get("conflicting") or []),
                "from_agent": bool(r.get("from_agent")),
            })
        cand.sort(key=lambda c: float(c.get("features", {}).get("meta_rank_raw", 0.0)), reverse=True)
        margin = max(0.0, cand[0]["score"] - (cand[1]["score"] if len(cand) > 1 else 0.0)) if cand else 0.0
        for c in cand:
            c["features"]["rank_margin"] = margin

        winner = _uid(cand[0]) if cand else None
        authority = {}
        for e in EXPERTS:
            rr = next((i for i, c in enumerate(experts.get(e) or [], 1) if _uid(c) == winner), None)
            authority[e] = {
                "utility": utilities[e], "winner_rank": rr,
                "winner_rr": 1.0 / rr if rr else 0.0,
            }
        return {
            "candidates": cand[:limit],
            "diagnostics": {
                "mode": "lambdamart_soft_router", "utilities": utilities,
                "authority": authority, "query": q, "union": len(rows),
                "model_health": health,
                "score_semantics": "fixed_logistic_margin_scale_not_probability",
            },
        }
    except Exception as ex:
        return {
            "candidates": weighted_rrf(experts, utilities, limit),
            "diagnostics": {
                "mode": "error_rrf_fallback", "error": f"{type(ex).__name__}: {ex}",
                "utilities": utilities, "query": q, "model_health": health,
                "union": len(rows),
            },
        }
