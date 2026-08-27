"""Canonical construction event/action interpretation.

Identity and state are different questions.  A report can correctly identify an
activity while saying that it is blocked, planned for tomorrow, partially
complete, corrected, or cancelled.  This module keeps those concepts separate
so a good activity match cannot accidentally become a false Actual Finish.
"""
from __future__ import annotations

import re
from typing import Any

# Canonical executable actions.  Longer/more specific expressions are checked
# first so "hydrotest" does not collapse into generic "test".
ACTION_ALIASES: dict[str, tuple[str, ...]] = {
    "hydrotest": ("hydrotest", "hydro test", "hydro testing", "hydro-testing", "hydrotest line", "water pressure test"),
    "pneumatic_test": ("pneumatic test", "air pressure test", "nitrogen pressure test"),
    "flushing": ("flush", "flushing", "flushed", "line flush", "chemical flush"),
    "ndt": ("ndt", "radiography", "radiographic", "rt completed", "ut completed", "ultrasonic test", "mpi", "dpi", "dpt"),
    "fitup": ("fit-up", "fit up", "fitup", "fitted up", "joint fit"),
    "welding": ("weld", "welding", "welded", "weld complete", "golden weld", "root pass", "hot pass", "cap weld"),
    "erection": ("erect", "erection", "erected", "position", "positioned", "mount", "mounted", "set in position", "placed in position"),
    "installation": ("install", "installation", "installed", "installing", "installed in position"),
    "fabrication": ("fabricate", "fabrication", "fabricated", "prefabrication", "prefabricated", "shop fabrication"),
    "alignment": ("align", "alignment", "aligned", "laser alignment", "shaft alignment", "final alignment"),
    "grouting": ("grout", "grouting", "grouted", "non-shrink grout", "baseplate grout"),
    "commissioning": ("commission", "commissioning", "commissioned", "pre-commissioning", "precommissioning", "precommissioned"),
    "calibration": ("calibrate", "calibration", "calibrated", "bench calibration", "field calibration"),
    "loop_check": ("loop check", "loop checking", "loop checked"),
    "cable_pull": ("pull cable", "cable pull", "cable pulling", "cable pulled", "cable laying", "cable laid"),
    "termination": ("terminate", "termination", "terminated", "glanding", "glanded", "lugging", "lugged"),
    "excavation": ("excavate", "excavation", "excavated", "trenching", "trenched"),
    "backfill": ("backfill", "backfilling", "backfilled", "reinstate", "reinstatement", "reinstated"),
    "formwork": ("formwork", "shuttering", "shutter erected", "shutter removed"),
    "rebar": ("rebar", "reinforcement", "reinforcement fixing", "steel fixing"),
    "concrete": ("concreting", "concrete pour", "concrete cast", "poured concrete", "casting completed"),
    "inspection": ("inspect", "inspection", "inspected", "witnessed", "accepted by qc", "qc accepted"),
    "delivery": ("delivered", "received at site", "material received", "dispatch", "dispatched"),
    "transport": ("transported", "transportation", "shifted to site", "moved to site"),
}

# State phrases are ordered from safety-critical/non-progress states toward
# positive execution states.  Negation/future detection therefore wins over the
# mere presence of words like "complete".
STATE_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("cancelled", ("cancelled", "canceled", "abandoned", "deleted from scope")),
    ("correction", ("correction", "corrected report", "supersedes", "revised entry", "please read as", "erratum")),
    ("blocked", ("blocked", "on hold", "held up", "stopped due", "cannot proceed", "waiting for", "delayed due", "suspended")),
    ("no_progress", ("not started", "not commenced", "not completed", "not finished", "no progress", "nil progress", "no work", "did not start", "did not complete", "pending")),
    ("planned_future", ("will start", "will commence", "planned for", "scheduled for tomorrow", "to start tomorrow", "will complete", "expected to complete", "targeted for")),
    ("finish", ("completed", "complete", "finished", "done", "closed out", "100% complete")),
    ("start", ("started", "commenced", "mobilized", "mobilised", "began", "work started")),
)

_PROGRESS = re.compile(r"(?<!\d)(\d{1,3}(?:\.\d+)?)\s*%")
_QUANTITY = re.compile(r"\b(\d+(?:\.\d+)?)\s*(joints?|spools?|m|mtr|meters?|metres?|nos?|numbers?|cables?|loops?)\b", re.I)


def _text(ev: dict | str | None) -> str:
    if isinstance(ev, dict):
        bits = [ev.get("description"), ev.get("event_type"), ev.get("raw_json")]
        return " ".join(str(x or "") for x in bits).strip()
    return str(ev or "")


def detect_action(value: Any) -> dict:
    text = " " + str(value or "").lower() + " "
    found: list[tuple[str, str]] = []
    for action, aliases in ACTION_ALIASES.items():
        for alias in aliases:
            if alias in text:
                found.append((action, alias))
                break
    # Some construction verbs are context-sensitive.  Prefer erection when the
    # explicit verb erect/position/mount is present; otherwise installation is a
    # broader action and remains separate.
    action = found[0][0] if found else None
    return {"action": action, "matches": [{"action": a, "phrase": p} for a, p in found],
            "confidence": 0.96 if found else 0.0}


PHASE_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("precommissioning", ("mechanical completion", "punch closeout", "punch list", "pre-commission", "precommission")),
    ("commissioning", ("commissioning", "commissioned", "start-up", "startup")),
    ("engineering", ("engineering", "design", "review ", "approve", "approval", "drawing", "document review", "ifc issue")),
    ("procurement", ("procurement", "purchase", "purchase order", "vendor", "material requisition", "expediting")),
    ("fabrication", ("shop fabrication", "prefabrication", "fabrication yard", "fabricated")),
    ("construction", ("construction", "execution", "site installation", "field installation")),
)


def detect_phase(value: Any, action: str | None = None) -> dict:
    """Identify the lifecycle/workface phase independently of activity action.

    A schedule can contain identical names under Engineering, Construction and
    Precommissioning WBS branches.  Semantic similarity alone cannot resolve
    those siblings, so preserve phase as a structured discriminator.
    """
    text = " " + str(value or "").lower() + " "
    for phase, aliases in PHASE_ALIASES:
        phrase = next((p for p in aliases if p in text), None)
        if phrase:
            return {"phase": phase, "phrase": phrase, "confidence": 0.96}
    if action == "fabrication":
        return {"phase": "fabrication", "phrase": "action:fabrication", "confidence": 0.84}
    if action == "commissioning":
        return {"phase": "commissioning", "phrase": "action:commissioning", "confidence": 0.84}
    if action in {"installation","erection","fitup","welding","alignment","grouting",
                  "cable_pull","termination","excavation","backfill","formwork",
                  "rebar","concrete","hydrotest","pneumatic_test","flushing","ndt"}:
        return {"phase": "field_execution", "phrase": "execution_action", "confidence": 0.74}
    return {"phase": None, "phrase": None, "confidence": 0.0}


def phase_compatibility(evidence_phase: str | None, activity_phase: str | None) -> tuple[float, str | None]:
    if not evidence_phase or not activity_phase:
        return 0.5, None
    if evidence_phase == activity_phase:
        return 1.0, None
    if evidence_phase == "field_execution":
        if activity_phase == "construction": return 1.0, None
        if activity_phase == "precommissioning": return 0.82, None
        if activity_phase == "commissioning": return 0.76, None
        if activity_phase == "fabrication": return 0.58, None
        return 0.05, f"work phase differs ({evidence_phase} vs {activity_phase})"
    if activity_phase == "field_execution":
        return phase_compatibility(activity_phase, evidence_phase)
    # Construction and fabrication can overlap depending on whether a spool or
    # equipment module is fabricated on-site. Keep this a soft mismatch.
    if {evidence_phase, activity_phase} == {"construction", "fabrication"}:
        return 0.35, None
    return 0.05, f"work phase differs ({evidence_phase} vs {activity_phase})"


def classify_event(ev: dict | str | None) -> dict:
    text = " " + _text(ev).lower() + " "
    action = detect_action(text)
    phase = detect_phase(text, action.get("action"))
    state = "observation"
    state_phrase = None
    for candidate, phrases in STATE_PATTERNS:
        phrase = next((p for p in phrases if p in text), None)
        if phrase:
            state, state_phrase = candidate, phrase
            break

    progress = None
    m = _PROGRESS.search(text)
    if m:
        try:
            progress = max(0.0, min(100.0, float(m.group(1))))
        except ValueError:
            progress = None
    if progress is not None and state == "observation":
        state = "finish" if progress >= 99.5 else "progress"

    # Quantity-only execution is progress unless a stronger safety state was found.
    q = _QUANTITY.search(text)
    if q and state == "observation" and action.get("action"):
        state = "progress"

    # A single DPR row can contain a completed primary event plus a blocked or
    # pending sibling ("P-101A complete; P-101B pending").  Row-level negation
    # must not erase the positive clause. Preserve this as a mixed observation;
    # asset-level assertion logic will decide which candidate each clause supports.
    clause_states = []
    if re.search(r"[;\n]", text):
        for clause in [c.strip() for c in re.split(r"[;\n]+", text) if c.strip()]:
            cstate = "observation"
            for cand, phrases in STATE_PATTERNS:
                if any(p in (" " + clause + " ") for p in phrases):
                    cstate = cand; break
            clause_states.append(cstate)
        positives = {"start","finish","progress","observation"}
        negatives = {"blocked","no_progress","planned_future","cancelled","correction"}
        if any(x in positives for x in clause_states) and any(x in negatives for x in clause_states):
            state = "mixed"
            state_phrase = "mixed_clause_states"

    # Explicit report columns outrank free-text inference where supplied.
    if isinstance(ev, dict):
        observed = ev.get("observed_progress")
        try:
            observed = float(observed) if observed is not None else None
        except (TypeError, ValueError):
            observed = None
        if observed is not None:
            progress = max(0.0, min(100.0, observed))
            if state == "observation":
                state = "finish" if progress >= 99.5 else "progress"

    non_progress = state in {"blocked", "no_progress", "planned_future", "cancelled", "correction"}
    update_effect = {
        "start": "actual_start",
        "finish": "actual_finish",
        "progress": "observed_progress",
    }.get(state)
    if non_progress:
        update_effect = None

    return {
        "state": state,
        "action": action.get("action"),
        "action_matches": action.get("matches"),
        "phase": phase.get("phase"),
        "phase_phrase": phase.get("phrase"),
        "progress": progress,
        "non_progress": non_progress,
        "update_effect": update_effect,
        "state_phrase": state_phrase,
        "clause_states": clause_states,
        "confidence": 0.98 if state_phrase and state != "mixed" else (0.88 if state == "mixed" else (0.9 if progress is not None else 0.55)),
    }


def action_compatibility(evidence_action: str | None, activity_action: str | None) -> tuple[float, str | None]:
    """Return a soft compatibility score and optional conflict reason."""
    if not evidence_action or not activity_action:
        return 0.5, None
    if evidence_action == activity_action:
        return 1.0, None
    compatible = {
        frozenset(("erection", "installation")): 0.74,
        frozenset(("inspection", "ndt")): 0.58,
        frozenset(("commissioning", "loop_check")): 0.45,
    }
    score = compatible.get(frozenset((evidence_action, activity_action)))
    if score is not None:
        return score, None
    return 0.05, f"action differs ({evidence_action} vs {activity_action})"
