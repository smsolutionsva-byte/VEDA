"""Rule-based analysis used when no reasoning provider is reachable.

This is not a pretend agent. It produces only what plain rules can justify from
data VEDA already holds, and every item it emits is stamped
DETERMINISTIC_CALCULATION or MCP_FACT - never AI_INFERENCE (spec 44). Where
judgement is genuinely required, it raises a review question instead of
guessing, which is the same thing the platform does anywhere else.
"""
from __future__ import annotations

import re

from .. import db
from ..agent.schemas import (AgentResult, Issue, Risk, ScheduleFinding)

# Wording that reliably distinguishes an existing problem from a future one.
ISSUE_WORDS = [
    ("ncr", "Non-conformance raised"),
    ("non-conformance", "Non-conformance raised"),
    ("reject", "Rejected work"),
    ("repair required", "Repair required"),
    ("failure", "Reported failure"),
    ("below spec", "Below specification"),
    ("collapse", "Physical failure on site"),
    ("backlog", "Work backlog"),
    ("shortage", "Resource or material shortage"),
    ("hold", "Work held"),
    ("stopped", "Work stopped"),
    ("suspended", "Work suspended"),
    ("delay", "Reported delay"),
]

SEVERITY_WORDS = {"critical": "critical", "high": "high", "major": "high",
                  "medium": "medium", "low": "low", "minor": "low"}


def analyse(project_id: str) -> AgentResult:
    findings: list = []
    issues: list = []
    risks: list = []

    snap = db.q1("SELECT * FROM schedule_snapshots WHERE project_id=? "
                 "AND is_current=1 ORDER BY created_at DESC LIMIT 1", [project_id])

    # ---- schedule findings, straight from the persisted Horizun results -----
    for f in db.q("SELECT * FROM qa_findings WHERE project_id=? AND status='fail' "
                  "ORDER BY CASE severity WHEN 'error' THEN 0 WHEN 'warning' "
                  "THEN 1 ELSE 2 END", [project_id]):
        findings.append(ScheduleFinding(
            title=str(f.get("title") or f.get("code")),
            detail=str(f.get("detail") or ""),
            activity_uids=db.jloads(f.get("task_uids_json"), [])[:40],
            basis="Horizun schedule_qa, rule " + str(f.get("code")),
            provenance="MCP_FACT",
        ))

    ev = db.q1("SELECT * FROM earned_value WHERE project_id=? AND scope='project' "
               "ORDER BY created_at DESC LIMIT 1", [project_id])
    if ev and ev.get("spi") is not None:
        spi = float(ev["spi"])
        findings.append(ScheduleFinding(
            title="Schedule performance index is " + str(round(spi, 3)),
            detail=("Earned value against the stored baseline gives SPI " +
                    str(round(spi, 3)) + " and schedule variance " +
                    str(ev.get("sv")) + ". " +
                    ("The project is behind the baseline plan."
                     if spi < 0.98 else "The project is at or ahead of plan.")),
            basis=str(ev.get("basis") or "Horizun baseline_compare"),
            provenance="MCP_FACT",
        ))
        if spi < 0.95:
            issues.append(Issue(
                ref="DET-SPI",
                title="Project is behind the baseline schedule (SPI " +
                      str(round(spi, 3)) + ")",
                description=("Earned value measured against the stored baseline "
                             "reports SPI " + str(round(spi, 3)) + ". This is a "
                             "measured condition, not a forecast."),
                source="Horizun baseline_compare",
                severity="high" if spi < 0.9 else "medium",
                priority="high" if spi < 0.9 else "medium",
                schedule_impact_note="SPI " + str(round(spi, 3)),
                confidence=1.0, provenance="DETERMINISTIC_CALCULATION"))

    if snap and snap.get("baseline_finish") and snap.get("forecast_finish"):
        bf = str(snap["baseline_finish"]).split("T")[0]
        ff = str(snap["forecast_finish"]).split("T")[0]
        if ff > bf:
            findings.append(ScheduleFinding(
                title="Forecast finish is later than the baseline finish",
                detail="Forecast " + ff + " against baseline " + bf + ".",
                basis="Horizun project_info and stored baseline",
                provenance="MCP_FACT"))

    neg = db.q1("SELECT COUNT(*) c FROM activities WHERE project_id=? "
                "AND total_float_days < 0 AND is_summary=0", [project_id])
    if neg and neg.get("c"):
        worst = db.q("SELECT uid, name, total_float_days FROM activities "
                     "WHERE project_id=? AND is_summary=0 AND total_float_days<0 "
                     "ORDER BY total_float_days LIMIT 10", [project_id])
        issues.append(Issue(
            ref="DET-NEGFLOAT",
            title=str(neg["c"]) + " activities carry negative float",
            description=("The network cannot meet the dates it is constrained to. "
                         "Worst: " + "; ".join(
                             str(w["name"]) + " (" +
                             str(round(w["total_float_days"], 1)) + "d)"
                             for w in worst[:5])),
            source="Horizun schedule_analyze",
            severity="high", priority="high",
            activity_uids=[w["uid"] for w in worst],
            schedule_impact_days=min((w["total_float_days"] for w in worst),
                                     default=None),
            confidence=1.0, provenance="DETERMINISTIC_CALCULATION"))

    # ---- issues drawn from evidence wording, one per source record ---------
    seen: set = set()
    rows = db.q("SELECT * FROM evidence WHERE project_id=? AND state NOT IN "
                "('quarantined','rejected','duplicate') ORDER BY date DESC "
                "LIMIT 4000", [project_id])
    for e in rows:
        text = str(e.get("description") or "").lower()
        raw = db.jloads(e.get("raw_json"), {}) or {}
        status = str(raw.get("_status") or "").lower()
        hit = next((label for word, label in ISSUE_WORDS if word in text), None)
        if hit is None and status in ("reject", "repair pending", "hold", "open"):
            hit = "Non-conformance raised"
        if hit is None:
            continue
        key = (hit, str(e.get("discipline")), str(e.get("chainage") or
                                                 e.get("location")))
        if key in seen:
            continue
        seen.add(key)
        links = db.q("SELECT activity_uid FROM evidence_links WHERE evidence_id=? "
                     "AND is_candidate=0 AND activity_uid IS NOT NULL", [e["id"]])
        sev = next((v for k, v in SEVERITY_WORDS.items() if k in text), "medium")
        issues.append(Issue(
            ref=_ref_of(e) or None,
            title=hit + (" - " + str(e.get("discipline")) if e.get("discipline")
                         else "") + (" at " + str(e.get("chainage"))
                                     if e.get("chainage") else ""),
            description=str(e.get("description") or "")[:600],
            source=str(e.get("source_file") or "uploaded document"),
            date=e.get("date"), severity=sev, priority=sev,
            activity_uids=[l["activity_uid"] for l in links],
            evidence_refs=[e["id"]],
            confidence=0.6,
            provenance="DETERMINISTIC_CALCULATION"))
        if len(issues) > 60:
            break

    # ---- risks: only where a rule can name a credible future event ---------
    late_crit = db.q(
        "SELECT uid, name, total_float_days, finish FROM activities "
        "WHERE project_id=? AND is_summary=0 AND critical=1 AND status!='complete' "
        "ORDER BY total_float_days LIMIT 5", [project_id])
    if late_crit:
        risks.append(Risk(
            ref="DET-CP",
            title="Critical path work remains incomplete with no float",
            description=("These critical activities are not complete and carry no "
                         "spare time, so any further loss on them moves the project "
                         "finish: " + "; ".join(str(a["name"]) for a in late_crit)),
            category="Schedule",
            probability="high" if (late_crit[0].get("total_float_days") or 0) < 0
            else "medium",
            impact="high",
            activity_uids=[a["uid"] for a in late_crit],
            critical_path_relevance="All listed activities are on the critical path.",
            confidence=0.7, provenance="DETERMINISTIC_CALCULATION"))

    over = db.q("SELECT name, overallocated_days FROM resources WHERE project_id=? "
                "AND overallocated=1 ORDER BY overallocated_days DESC LIMIT 5",
                [project_id])
    if over:
        risks.append(Risk(
            ref="DET-RES",
            title=str(len(over)) + " resource(s) are overbooked",
            description=("Day-by-day allocation shows these resources committed "
                         "beyond availability: " + ", ".join(
                             str(o["name"]) + " (" +
                             str(o.get("overallocated_days") or 0) + " days)"
                             for o in over) +
                         ". Work planned in parallel may not be deliverable."),
            category="Resource", probability="medium", impact="medium",
            confidence=0.65, provenance="DETERMINISTIC_CALCULATION"))

    summary = _summary(snap, issues, risks, findings, ev)
    return AgentResult(summary=summary, schedule_findings=findings,
                       issues=issues, risks=risks,
                       notes=["Produced by VEDA's rule-based analyser because no "
                              "reasoning provider was reachable. Findings are "
                              "limited to what deterministic rules can justify."])


def _ref_of(e: dict) -> str | None:
    m = re.match(r"^([A-Z]{2,5}-[\w\-/]+)\s*:", str(e.get("description") or ""))
    return m.group(1) if m else None


def _summary(snap, issues, risks, findings, ev) -> str:
    if not snap:
        return ("No schedule snapshot is available yet. " + str(len(issues)) +
                " issue(s) were derived from the uploaded documents.")
    bits = [
        "Schedule '" + str(snap.get("project_name")) + "' holds " +
        str(snap.get("task_count")) + " activities with data date " +
        str(snap.get("data_date")) + ".",
        "Forecast finish is " + str(snap.get("forecast_finish")) +
        " against a baseline finish of " +
        str(snap.get("baseline_finish") or "none stored") + ".",
        str(snap.get("critical_count")) + " activities are critical and " +
        str(snap.get("late_count")) + " are late.",
    ]
    if ev and ev.get("spi") is not None:
        bits.append("SPI is " + str(round(float(ev["spi"]), 3)) + ".")
    if snap.get("health_score") is not None:
        bits.append("Schedule quality score is " + str(snap["health_score"]) +
                    "% of checks passed.")
    bits.append(str(len(issues)) + " issue(s) and " + str(len(risks)) +
                " risk(s) were derived by rule from the persisted data.")
    return " ".join(bits)
