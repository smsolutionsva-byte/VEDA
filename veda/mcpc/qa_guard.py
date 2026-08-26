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
        sem = _read_xer_semantics(path) if path else None
    except Exception:
        # A provenance guard must never turn a successful Horizun call into an
        # application failure.  If source inspection itself is unavailable,
        # return the MCP result unchanged.
        return result
    if not sem:
        return result

    out = copy.deepcopy(result)
    changes: list[str] = []

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
