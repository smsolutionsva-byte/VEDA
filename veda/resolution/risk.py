"""Risk-controlled identity-link policy.

A candidate ranking score is not probability.  A model probability is not write
permission.  This module combines calibration state, deterministic validators,
ambiguity, and event semantics into an explicit decision.
"""
from __future__ import annotations

from .. import db

TARGET_PRECISION=0.99


def candidate_set(candidates: list[dict]) -> dict:
    if not candidates:
        return {"uids":[],"size":0,"method":"none"}
    top=float(candidates[0].get("score") or 0)
    # Cold-start uncertainty set: retain close alternatives.  This is NOT called
    # conformal because project-specific exchangeability/calibration assumptions
    # have not been established yet.
    delta=max(0.045, min(0.14, 0.22*(1-top)+0.045))
    kept=[c for c in candidates if top-float(c.get("score") or 0)<=delta]
    return {"uids":[int(c["activity"]["uid"]) for c in kept],"size":len(kept),
            "method":"risk_margin_set","delta":round(delta,4),"is_conformal":False}


def assess(*, candidates: list[dict], calibration: dict | None,
           validator: dict | None, event: dict) -> dict:
    p=float((calibration or {}).get("probability") or 0.0)
    calibrated=bool((calibration or {}).get("is_calibrated"))
    cset=candidate_set(candidates)
    top=candidates[0] if candidates else None
    f=(top or {}).get("features",{})
    hard_fail=(validator or {}).get("result")=="fail"
    if hard_fail:
        return {"decision":"conflicting","reason":"deterministic_validator_failed","candidate_set":cset}
    if event.get("state") in {"planned_future","blocked","no_progress","cancelled","correction"}:
        return {"decision":"review_non_progress","reason":"event_state_must_not_advance_progress","candidate_set":cset}
    if not top:
        return {"decision":"unresolved","reason":"no_candidate","candidate_set":cset}
    if cset["size"]>1:
        return {"decision":"needs_review","reason":"multiple_plausible_candidates","candidate_set":cset}
    # A single field statement can legitimately describe multiple spools/assets.
    # Never collapse that into one L6 task merely because one candidate wins
    # semantically; this is a granularity/composite observation for review.
    if float(f.get("evidence_asset_count",0) or 0) > 1 and float(f.get("asset_coverage",0) or 0) < .999:
        return {"decision":"needs_review","reason":"multi_asset_or_composite_observation","candidate_set":cset}

    # Cold-start deterministic identity links are allowed only when independent
    # engineering signals agree.  This links evidence identity; it still does not
    # authorize a Primavera actual/progress write.
    deterministic=(f.get("asset_exact",0)>=1 and f.get("action",0)>=.9 and
                   f.get("location_conflict",0)<.5 and f.get("asset_conflict",0)<.5 and
                   f.get("engineering_rank_score",0)>=.76 and f.get("rank_margin",0)>=.08)
    if deterministic:
        return {"decision":"link_identity_only","reason":"strong_multi_signal_cold_start",
                "candidate_set":cset,"schedule_write_allowed":False,
                "probability":p,"is_calibrated":calibrated}
    validated_threshold=(calibration or {}).get("validated_auto_link_threshold")
    risk_validation=(calibration or {}).get("risk_validation") or {}
    if calibrated and validated_threshold is not None and risk_validation.get("validated") and p>=float(validated_threshold):
        return {"decision":"link_identity_only","reason":"held_out_validated_high_precision_candidate",
                "candidate_set":cset,"schedule_write_allowed":False,
                "probability":p,"is_calibrated":True,
                "validated_threshold":validated_threshold,"risk_validation":risk_validation}
    return {"decision":"needs_review","reason":"confidence_not_validated_for_automation",
            "candidate_set":cset,"schedule_write_allowed":False,
            "probability":p,"is_calibrated":calibrated}
