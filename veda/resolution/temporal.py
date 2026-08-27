"""Bitemporal-ish schedule/evidence time features.

Primavera exposes several date concepts (actual, current/remaining, early,
baseline, project data date).  We keep their evidential strength separate rather
than flattening them into one planned window.
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Any


def _d(v: Any):
    if not v:
        return None
    try:
        return datetime.strptime(str(v).split("T")[0], "%Y-%m-%d").date()
    except ValueError:
        return None


def _near(day, anchor, scale: float) -> float:
    if not day or not anchor:
        return 0.5
    return max(0.02, min(1.0, math.exp(-abs((day-anchor).days) / max(scale, 1.0))))


def features(ev: dict, act: dict, snapshot: dict | None, event_info: dict) -> dict:
    day = _d(ev.get("date"))
    if not day:
        return {"score": 0.5, "basis": "no_evidence_date", "distance_days": None,
                "actual": 0.5, "current": 0.5, "early": 0.5, "baseline": 0.5,
                "data_date_relation": 0.5}

    state = event_info.get("state")
    actual_anchor = _d(act.get("actual_finish") if state == "finish" else act.get("actual_start"))
    if state not in {"start", "finish"}:
        actual_anchor = _d(act.get("actual_finish")) or _d(act.get("actual_start"))

    current_anchor = _d(act.get("finish") if state == "finish" else act.get("start"))
    if state not in {"start", "finish"}:
        s, f = _d(act.get("start")), _d(act.get("finish"))
        if s and f and s <= day <= f:
            current_anchor = day
        else:
            current_anchor = min((x for x in (s, f) if x), key=lambda x: abs((day-x).days), default=None)

    early_anchor = _d(act.get("early_finish") if state == "finish" else act.get("early_start"))
    baseline_anchor = _d(act.get("baseline_finish") if state == "finish" else act.get("baseline_start"))
    actual = _near(day, actual_anchor, 16.0)
    current = _near(day, current_anchor, 36.0)
    early = _near(day, early_anchor, 42.0)
    baseline = _near(day, baseline_anchor, 75.0)

    # Actual dates are corroborating facts, not mere forecasts.  If absent,
    # current/early dates dominate and baseline remains a weak prior.
    if actual_anchor:
        score = 0.64 * actual + 0.18 * current + 0.10 * early + 0.08 * baseline
        basis = "actual_boundary"
        anchor = actual_anchor
    else:
        score = 0.50 * current + 0.28 * early + 0.22 * baseline
        basis = "current_early_baseline"
        anchor = current_anchor or early_anchor or baseline_anchor

    data_date = _d((snapshot or {}).get("data_date") or (snapshot or {}).get("status_date"))
    data_rel = 0.5
    if data_date:
        delta = (day - data_date).days
        # Very old or far-future evidence is suspicious for *current* progress,
        # but still valid historical evidence.  Keep this as a separate feature.
        data_rel = max(0.0, min(1.0, math.exp(-abs(delta) / 75.0)))

    return {
        "score": max(0.0, min(1.0, score)), "basis": basis,
        "distance_days": abs((day-anchor).days) if anchor else None,
        "actual": actual, "current": current, "early": early, "baseline": baseline,
        "data_date_relation": data_rel,
        "calendar": act.get("calendar"),
        "note": "Calendar-aware working-day distance requires calendar detail from the schedule engine; calendar name is retained but no fake weekday assumption is made.",
    }
