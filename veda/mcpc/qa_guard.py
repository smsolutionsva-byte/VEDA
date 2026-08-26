"""Source-semantic guards for schedule QA returned by Horizun.

Horizun owns the CPM/DCMA calculations, but VEDA also owns the contract that a
reported fact must be supported by the source file.  A few P6/XER columns have
very different meanings despite looking date-like:

* target_start_date / target_end_date are Planned Start / Planned Finish.
* restart_date / reend_date are Remaining Early Start / Remaining Early Finish.
* act_start_date / act_end_date are Actual Start / Actual Finish.

If an XER does not carry forecast/remaining date fields, treating target dates
as current forecast dates creates false DCMA-09 failures.  Likewise, DCMA-11
and DCMA-14 require a real assigned baseline; planned target dates are not a
substitute for an assigned P6 baseline.

This module does NOT recalculate CPM.  It only prevents a downstream QA result
from claiming more than the source can establish, and performs the narrow
actual-date integrity check needed to avoid hiding a genuine DCMA-09 failure
when forecast dates are unavailable.
"""
from __future__ import annotations

import copy
import os
from datetime import datetime
from typing import Any

from .. import db
from .source_semantics import inspect_source, parse_dt
from . import tabular_schedule


_FORECAST_FIELDS = {
    # Remaining/forecast fields exported by Primavera P6.
    "restart_date",          # Remaining Early Start
    "reend_date",            # Remaining Early Finish
    "rem_late_start_date",   # Remaining Late Start
    "rem_late_end_date",     # Remaining Late Finish
    # Some exporters surface calculated early/late fields as well.
    "early_start_date",
    "early_end_date",
    "late_start_date",
    "late_end_date",
}


def _nonempty(value: Any) -> bool:
    return value is not None and str(value).strip() not in ("", "0")


def _parse_dt(value: Any) -> datetime | None:
    if not _nonempty(value):
        return None
    s = str(value).strip().replace("Z", "+00:00")
    # XER commonly uses ``YYYY-MM-DD HH:MM`` while some tools emit ISO.
    for candidate in (s, s.replace(" ", "T", 1)):
        try:
            return datetime.fromisoformat(candidate)
        except ValueError:
            pass
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d", "%d-%b-%y", "%d-%b-%Y"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    return None


def _read_xer_semantics(path: str) -> dict | None:
    """Read XER semantics through the shared source manifest.

    QA adds only the narrow future-actual check; structural/date semantics live in
    source_semantics so dashboard, QA and persistence cannot disagree.
    """
    sem = inspect_source(path)
    if not sem or sem.get("format") != "xer" or not sem.get("source_guarded"):
        return None
    data_date = parse_dt(sem.get("data_date"))
    future_actual_uids: list[Any] = []
    if data_date:
        dd = data_date.date()
        for tid, t in (sem.get("task_by_id") or {}).items():
            astart = parse_dt(t.get("act_start_date"))
            afin = parse_dt(t.get("act_end_date"))
            if ((astart and astart.date() > dd) or
                    (afin and afin.date() > dd)):
                uid: Any = tid
                try:
                    uid = int(uid)
                except (TypeError, ValueError):
                    pass
                future_actual_uids.append(uid)
    return {
        "format": "xer",
        "task_fields": sem.get("task_fields") or [],
        "forecast_columns": sem.get("forecast_columns") or [],
        "forecast_values_available": bool(sem.get("forecast_values_available")),
        # Strict DCMA checks require an explicit/frozen project baseline. P6 may
        # use the current project as a UI/EV fallback, but that is disclosed
        # separately by the snapshot rather than silently treated as an approved
        # DCMA baseline.
        "baseline_assigned": bool(sem.get("baseline_assigned")),
        "data_date": sem.get("data_date"),
        "future_actual_uids": future_actual_uids,
    }



def _read_tabular_semantics(path: str) -> dict | None:
    try:
        sem = tabular_schedule.inspect_semantics(path)
    except Exception:
        return None
    if not sem or not sem.get("source_guarded"):
        return None
    return sem


def _rule_like(out: dict, *needles: str) -> dict | None:
    needles = tuple(n.casefold() for n in needles)
    for f in out.get("findings") or []:
        if not isinstance(f, dict):
            continue
        hay = (str(f.get("rule") or "") + " " +
               str(f.get("summary") or "") + " " +
               str(f.get("reason") or "")).casefold()
        if any(n in hay for n in needles):
            return f
    return None


def _ensure_finding(out: dict, rule: str, title_hint: str) -> dict:
    f = _finding(out, rule)
    if f is None:
        needle = title_hint.casefold().replace("_", " ")
        # Match the rule identifier, not a previously rewritten summary.  A rule
        # like DCMA-10 can legitimately contain the phrase "non-milestone duration"
        # in its explanation and must never be mistaken for the milestone rule.
        for cand in out.get("findings") or []:
            if not isinstance(cand, dict):
                continue
            rule_text = str(cand.get("rule") or "").casefold().replace("_", " ")
            if needle in rule_text:
                f = cand
                break
    if f is not None:
        return f
    f = {"rule": rule, "evaluated": False, "passed": False,
         "summary": title_hint + " — not evaluated.", "reason": "",
         "measured": None, "uids": [], "severity": "info"}
    out.setdefault("findings", []).append(f)
    return f


def _set_source_result(f: dict, *, passed: bool, summary: str,
                       measured: Any = None, uids: list[Any] | None = None,
                       severity: str | None = None, threshold: Any = None) -> None:
    _remember_original(f)
    f["evaluated"] = True
    f["passed"] = bool(passed)
    f["summary"] = summary
    f["reason"] = summary
    f["measured"] = measured
    f["uids"] = list(uids or [])
    f["severity"] = severity or ("info" if passed else "warning")
    if threshold is not None:
        f["threshold"] = threshold
    f["_veda_provenance"] = "DETERMINISTIC_CALCULATION"
    f["_veda_guarded"] = True


def _apply_tabular_guard(out: dict, sem: dict) -> list[str]:
    """Make QA capability-driven for CSV/XLSX schedules.

    The MSPDI file is a transport adapter.  Any semantics inserted only to make
    that interchange file parsable (FS/0 links, noncritical defaults, summary
    inference, etc.) are never accepted as source evidence.
    """
    changes: list[str] = []
    total = int(sem.get("activity_count") or 0)

    # DCMA 01: predecessor/successor existence is source-visible even when
    # relationship type and lag are not.
    f = _finding(out, "dcma_01_logic")
    if f is not None:
        if sem.get("predecessor_values_available"):
            uids = list(sem.get("open_logic_uids") or [])
            pct = round(100.0 * len(uids) / total, 1) if total else 0.0
            passed = pct <= 5.0
            _set_source_result(
                f, passed=passed, measured=pct, uids=uids, threshold=5.0,
                severity="info" if passed else "warning",
                summary=("Missing logic — " + str(len(uids)) + " of " + str(total) +
                         " activities (" + str(pct) + "%) have no predecessor or no "
                         "successor in the source predecessor network (threshold 5%)."))
            changes.append("DCMA-01 recomputed from source predecessor IDs")
        else:
            _not_evaluated(f, "Missing logic — not evaluated. The tabular source has no predecessor/successor field.")
            changes.append("DCMA-01 N/E (source logic unavailable)")

    # Relationship semantics are only evaluable when explicitly encoded in the
    # source tokens. Plain predecessor IDs do not prove FS or zero lag.
    for rule, label in (("dcma_02_leads", "Leads"),
                        ("dcma_03_lags", "Lags"),
                        ("dcma_04_relationship_types", "Relationship types")):
        f = _finding(out, rule)
        if f is not None and not sem.get("relationship_type_values_available"):
            _not_evaluated(f, label + " — not evaluated. The source supplies predecessor IDs but does not explicitly supply relationship type/lag semantics; adapter FS/0 defaults are ignored.")
            changes.append(rule + " N/E (relationship semantics absent)")

    f = _finding(out, "dcma_05_hard_constraints")
    if f is not None and not sem.get("constraint_columns_available"):
        _not_evaluated(f, "Hard constraints — not evaluated. No source constraint fields are present.")
        changes.append("DCMA-05 N/E (constraints absent)")

    for rule, label in (("dcma_06_high_float", "High float"),
                        ("dcma_07_negative_float", "Negative float")):
        f = _finding(out, rule)
        if f is not None and not sem.get("total_float_complete"):
            _not_evaluated(f, label + " — not evaluated. Total float is not supplied for the source activities; adapter/scheduler values are not substituted.")
            changes.append(rule + " N/E (float absent)")

    f = _finding(out, "dcma_08_high_duration")
    if f is not None:
        if sem.get("duration_values_complete"):
            uids = list(sem.get("high_duration_uids") or [])
            pct = round(100.0 * len(uids) / total, 1) if total else 0.0
            _set_source_result(f, passed=pct <= 5.0, measured=pct, uids=uids,
                               threshold=5.0, severity="info" if pct <= 5.0 else "warning",
                               summary=("High duration — " + str(len(uids)) + " of " + str(total) +
                                        " source activities exceed 44 days (" + str(pct) + "%, threshold 5%)."))
            changes.append("DCMA-08 recomputed from source duration")
        else:
            _not_evaluated(f, "High duration — not evaluated. Source duration is incomplete.")

    f = _finding(out, "dcma_09_invalid_dates")
    if f is not None and not sem.get("data_date_available"):
        _not_evaluated(f, "Invalid dates — not evaluated. No data/status date is supplied, so actual/forecast date integrity cannot be assessed against a status boundary.")
        changes.append("DCMA-09 N/E (data date absent)")

    f = _finding(out, "dcma_10_resources")
    if f is not None:
        if sem.get("resource_values_available"):
            uids = list(sem.get("unresourced_uids") or [])
            duration_n = int(sem.get("duration_activity_count") or max(0, total - len(sem.get("milestone_uids") or [])))
            pct = round(100.0 * len(uids) / duration_n, 1) if duration_n else 0.0
            _set_source_result(f, passed=len(uids) == 0, measured=pct, uids=uids, threshold=0,
                               severity="info" if not uids else "warning",
                               summary=("Unresourced work — " + str(len(uids)) + " of " + str(duration_n) +
                                        " non-summary, non-milestone duration activities lack a source resource assignment."))
            changes.append("DCMA-10 recomputed from source resource assignments")
        else:
            _not_evaluated(f, "Unresourced work — not evaluated. No source resource-assignment field is present.")

    for rule, label, reason in (
        ("dcma_11_missed_tasks", "Missed baseline tasks", "a baseline comparison requires a data/status date and actual completion status"),
        ("dcma_12_critical_path_test", "Critical path test", "the tabular source does not provide enough explicit scheduling semantics to validate a CPM perturbation result"),
        ("dcma_13_cpli", "Critical path length index", "critical-path/float semantics are not source-established"),
        ("dcma_14_bei", "Baseline execution index", "BEI requires baseline dates plus a data/status date and execution status"),
    ):
        f = _finding(out, rule)
        if f is None:
            continue
        if rule == "dcma_11_missed_tasks" and sem.get("baseline_values_available") and sem.get("data_date_available") and sem.get("actual_finish_values_available"):
            continue
        if rule == "dcma_14_bei" and sem.get("baseline_values_available") and sem.get("data_date_available") and sem.get("progress_available"):
            continue
        _not_evaluated(f, label + " — not evaluated. " + reason.capitalize() + ".")
        changes.append(rule + " N/E")

    # Source-integrity rules. Reuse Horizun's equivalent finding when present;
    # otherwise add one so adapter normalization cannot hide a source defect.
    f = _ensure_finding(out, "veda_source_duplicate_sibling_names", "duplicate names")
    dup = list(sem.get("duplicate_sibling_affected_ids") or [])
    _set_source_result(f, passed=not dup, measured=len(dup), uids=dup,
                       severity="info" if not dup else "warning",
                       summary=("Duplicate sibling names — " + str(len(dup)) + " source activities are in duplicate-name groups under the same WBS parent."))
    changes.append("duplicate-name rule source-grounded")

    f = _ensure_finding(out, "veda_source_milestone_duration", "milestone duration")
    bad_ms = list(sem.get("milestone_duration_uids") or [])
    _set_source_result(f, passed=not bad_ms, measured=len(bad_ms), uids=bad_ms,
                       severity="info" if not bad_ms else "warning",
                       summary=("Milestone duration — " + str(len(bad_ms)) + " source milestone activities have non-zero duration; P6 milestones must be zero-duration."))
    changes.append("milestone-duration rule source-grounded")

    f = _ensure_finding(out, "veda_source_progress_recorded", "progress recorded")
    if not sem.get("data_date_available"):
        _not_evaluated(f, "Progress recorded — not evaluated. The source has no data/status date, so there is no status boundary against which progress completeness can be judged.")
    elif sem.get("progress_available"):
        _set_source_result(f, passed=True, measured=sem.get("source_progress_pct"), uids=[],
                           severity="info", summary="Progress recorded — source progress/status fields are available for the status boundary.")
    else:
        _not_evaluated(f, "Progress recorded — not evaluated. Source progress/status fields are incomplete.")
    changes.append("progress-recorded rule source-grounded")

    f = _ensure_finding(out, "veda_source_unnamed_tasks", "unnamed")
    unnamed = list(sem.get("unnamed_ids") or [])
    _set_source_result(f, passed=not unnamed, measured=len(unnamed), uids=unnamed,
                       severity="info" if not unnamed else "warning",
                       summary=("Unnamed tasks — " + str(len(unnamed)) + " source activities have no activity name."))
    changes.append("unnamed-task rule source-grounded")
    return changes

def _project_schedule_path(project_id: str | None) -> str | None:
    if not project_id:
        return None
    # Prefer the project's currently selected schedule file.  During a fresh
    # harvest the new snapshot does not exist yet, so snapshot-first can inspect
    # the previous revision by mistake.
    row = db.q1(
        "SELECT f.stored_path FROM projects p LEFT JOIN files f "
        "ON f.id=p.schedule_file_id WHERE p.id=?", [project_id])
    path = (row or {}).get("stored_path")
    if path and os.path.isfile(path):
        return path
    snap = db.q1(
        "SELECT source_path FROM schedule_snapshots WHERE project_id=? "
        "ORDER BY is_current DESC, revision DESC, created_at DESC LIMIT 1",
        [project_id])
    path = (snap or {}).get("source_path")
    return path if path and os.path.isfile(path) else None


def _finding(out: dict, rule: str) -> dict | None:
    for f in out.get("findings") or []:
        if isinstance(f, dict) and str(f.get("rule") or "") == rule:
            return f
    return None


def _remember_original(f: dict) -> None:
    if "_veda_original" not in f:
        f["_veda_original"] = {
            "evaluated": f.get("evaluated", True),
            "passed": f.get("passed"),
            "summary": f.get("summary"),
            "reason": f.get("reason"),
            "measured": f.get("measured"),
            "uids": list(f.get("uids") or []),
            "severity": f.get("severity"),
        }


def _not_evaluated(f: dict, message: str) -> None:
    _remember_original(f)
    f["evaluated"] = False
    f["passed"] = False
    f["summary"] = message
    f["reason"] = message
    f["measured"] = None
    f["uids"] = []
    f["severity"] = "info"
    f["_veda_provenance"] = "DETERMINISTIC_CALCULATION"
    f["_veda_guarded"] = True


def _fail_actual_dates_only(f: dict, uids: list[Any], data_date: str | None) -> None:
    _remember_original(f)
    n = len(uids)
    suffix = "" if n == 1 else "s"
    dd = (data_date or "unknown").split("T")[0]
    msg = ("Invalid dates — " + str(n) + " actual date violation" + suffix +
           " occurs after the data date " + dd +
           ". Forecast-date portion was not evaluated because the XER carries "
           "no current remaining/forecast date fields.")
    f["evaluated"] = True
    f["passed"] = False
    f["summary"] = msg
    f["reason"] = msg
    f["measured"] = n
    f["uids"] = uids
    f["severity"] = "error"
    f["_veda_provenance"] = "DETERMINISTIC_CALCULATION"
    f["_veda_guarded"] = True


def _recount(out: dict) -> None:
    findings = [f for f in (out.get("findings") or []) if isinstance(f, dict)]
    if not findings:
        return
    passed = sum(1 for f in findings if f.get("evaluated", True) and f.get("passed") is True)
    failed = sum(1 for f in findings if f.get("evaluated", True) and f.get("passed") is not True)
    not_eval = sum(1 for f in findings if not f.get("evaluated", True))
    out["checks"] = len(findings)
    out["passed"] = passed
    out["failed"] = failed
    out["notEvaluated"] = not_eval
    # Keep a snake-case alias for callers that use that convention.
    out["not_evaluated"] = not_eval


def guard_schedule_qa(result: Any, *, project_id: str | None = None,
                      schedule_path: str | None = None) -> Any:
    """Return a source-honest schedule_qa result.

    Non-XER formats are left untouched because their date/baseline semantics are
    supplied by their own importer.  For XER, only claims that can be disproved
    from missing source semantics are guarded.
    """
    if not isinstance(result, dict) or not isinstance(result.get("findings"), list):
        return result

    try:
        path = schedule_path or _project_schedule_path(project_id)
        sem = None
        if path:
            ext = os.path.splitext(path)[1].lower()
            if ext == ".xer":
                sem = _read_xer_semantics(path)
            elif ext in tabular_schedule.SUPPORTED:
                sem = _read_tabular_semantics(path)
    except Exception:
        # A provenance guard must never turn a successful Horizun call into an
        # application failure.  If source inspection itself is unavailable,
        # return the MCP result unchanged.
        return result
    if not sem:
        return result

    out = copy.deepcopy(result)
    changes: list[str] = []

    if sem.get("format") in {"csv", "tsv", "xlsx", "xlsm"}:
        changes.extend(_apply_tabular_guard(out, sem))
        _recount(out)
        notes = out.get("notes")
        if notes is None:
            notes = []
        elif isinstance(notes, str):
            notes = [notes]
        elif not isinstance(notes, list):
            notes = [str(notes)]
        notes.append("VEDA source-semantic guard: tabular QA is capability-driven; MSPDI transport defaults are never treated as source facts.")
        out["notes"] = notes
        out["vedaSemanticGuard"] = {
            "applied": True, "sourceFormat": sem.get("format"),
            "dataDate": sem.get("data_date"),
            "baselineValuesAvailable": bool(sem.get("baseline_values_available")),
            "criticalityAvailable": bool(sem.get("criticality_available")),
            "relationshipTypesAvailable": bool(sem.get("relationship_type_values_available")),
            "resourceAssignmentsAvailable": bool(sem.get("resource_values_available")),
        }
        return out

    dcma09 = _finding(out, "dcma_09_invalid_dates")
    if dcma09 is not None and not sem["forecast_values_available"]:
        future_actuals = sem.get("future_actual_uids") or []
        if future_actuals:
            _fail_actual_dates_only(dcma09, future_actuals, sem.get("data_date"))
            changes.append("DCMA-09 restricted to actual-date violations")
        else:
            reason = (
                "Invalid dates — not evaluated. The XER contains planned/target "
                "dates but no current remaining/forecast date fields "
                "(for example restart_date/reend_date). Planned Finish is not "
                "substituted for Forecast Finish. Actual dates contain no "
                "future-day violations relative to the available data date."
            )
            if not sem.get("data_date"):
                reason = (
                    "Invalid dates — not evaluated. The XER contains no usable "
                    "current remaining/forecast dates and no usable project data "
                    "date, so DCMA-09 cannot be established from the source."
                )
            _not_evaluated(dcma09, reason)
            changes.append("DCMA-09 marked not evaluated (forecast dates absent)")

    if not sem["baseline_assigned"]:
        dcma11 = _finding(out, "dcma_11_missed_tasks")
        if dcma11 is not None:
            _not_evaluated(
                dcma11,
                "Missed baseline tasks — not evaluated. No assigned P6 project "
                "baseline is present in the XER; planned/target dates are not "
                "treated as baseline dates."
            )
            changes.append("DCMA-11 marked not evaluated (baseline absent)")
        dcma14 = _finding(out, "dcma_14_bei")
        if dcma14 is not None:
            _not_evaluated(
                dcma14,
                "Baseline execution index — not evaluated. BEI requires an "
                "assigned baseline. This XER has no assigned P6 project baseline, "
                "and planned/target dates are not substituted for one."
            )
            changes.append("DCMA-14 marked not evaluated (baseline absent)")

    if changes:
        _recount(out)
        notes = out.get("notes")
        if notes is None:
            notes = []
        elif isinstance(notes, str):
            notes = [notes]
        elif not isinstance(notes, list):
            notes = [str(notes)]
        notes.append("VEDA source-semantic guard: " + "; ".join(changes) + ".")
        out["notes"] = notes
        out["vedaSemanticGuard"] = {
            "applied": True,
            "sourceFormat": sem["format"],
            "forecastColumns": sem["forecast_columns"],
            "forecastValuesAvailable": sem["forecast_values_available"],
            "baselineAssigned": sem["baseline_assigned"],
            "dataDate": sem["data_date"],
        }
    return out


__all__ = ["guard_schedule_qa"]
