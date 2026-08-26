"""Source-aware schedule semantics.

Horizun owns schedule calculations.  This module answers a different question:
what does the uploaded source *actually contain*?  It is deliberately narrow and
read-only.  The first supported format is Primavera XER because XER exposes WBS,
activity, project, baseline and date semantics in separate tables/columns.

The manifest is used to keep VEDA's UI/persistence honest when an adapter returns
structural WBS nodes alongside activities, or when a date-like field is not a
current forecast date.
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any


FORECAST_FIELDS = {
    "restart_date",          # Remaining Early Start
    "reend_date",            # Remaining Early Finish
    "rem_late_start_date",   # Remaining Late Start
    "rem_late_end_date",     # Remaining Late Finish
    "early_start_date",
    "early_end_date",
    "late_start_date",
    "late_end_date",
}


def nonempty(v: Any) -> bool:
    return v is not None and str(v).strip() not in ("", "0")


def parse_dt(v: Any) -> datetime | None:
    if not nonempty(v):
        return None
    s = str(v).strip().replace("Z", "+00:00")
    for candidate in (s, s.replace(" ", "T", 1)):
        try:
            return datetime.fromisoformat(candidate)
        except ValueError:
            pass
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d",
                "%d-%b-%y", "%d-%b-%Y"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    return None


def iso_date(v: Any) -> str | None:
    d = parse_dt(v)
    return d.date().isoformat() if d else None


def _read_xer(path: str) -> tuple[dict[str, list[str]], dict[str, list[dict]]]:
    fields: dict[str, list[str]] = {}
    rows: dict[str, list[dict]] = {}
    table = None
    with open(path, "r", encoding="utf-8-sig", errors="replace") as fh:
        for raw in fh:
            line = raw.rstrip("\r\n")
            if not line:
                continue
            parts = line.split("\t")
            marker = parts[0]
            if marker == "%T":
                table = parts[1].strip().upper() if len(parts) > 1 else None
            elif marker == "%F" and table:
                fields[table] = [x.strip() for x in parts[1:]]
            elif marker == "%R" and table:
                cols = fields.get(table) or []
                vals = parts[1:]
                row = {cols[i]: vals[i] if i < len(vals) else ""
                       for i in range(len(cols))}
                rows.setdefault(table, []).append(row)
    return fields, rows


def _norm_id(v: Any) -> str:
    if v is None:
        return ""
    s = str(v).strip()
    try:
        # Handles Horizun returning 40000.0 for an integer XER task id.
        f = float(s)
        if f.is_integer():
            return str(int(f))
    except (TypeError, ValueError):
        pass
    return s


def _choose_project(projects: list[dict], tasks: list[dict], info: dict | None,
                    task_uid_hints: list[Any] | None) -> tuple[dict | None, str]:
    live = [p for p in projects if not nonempty(p.get("orig_proj_id"))]
    pool = live or projects
    if not pool:
        return None, "none"
    if len(pool) == 1:
        return pool[0], "single_live_project"

    info = info or {}
    # Prefer numeric/object identifiers when the adapter exposes them.
    id_hints = {_norm_id(info.get(k)) for k in (
        "projId", "projectId", "projectObjectId", "objectId", "uid")}
    id_hints.discard("")
    for p in pool:
        if _norm_id(p.get("proj_id")) in id_hints:
            return p, "project_id_match"

    # Then project code/name-like values.
    name_hints = {str(info.get(k) or "").strip().casefold() for k in (
        "name", "title", "id", "projectId", "shortName", "projectCode")}
    name_hints.discard("")
    for p in pool:
        if str(p.get("proj_short_name") or "").strip().casefold() in name_hints:
            return p, "project_code_match"

    # Finally use exact activity uid overlap. This is extremely useful for
    # multi-project XERs when Horizun has already opened one project handle.
    hints = {_norm_id(x) for x in (task_uid_hints or []) if _norm_id(x)}
    if hints:
        scores = []
        for p in pool:
            pid = _norm_id(p.get("proj_id"))
            tids = {_norm_id(t.get("task_id")) for t in tasks
                    if _norm_id(t.get("proj_id")) == pid}
            scores.append((len(hints & tids), p))
        scores.sort(key=lambda x: x[0], reverse=True)
        if scores and scores[0][0] > 0 and (len(scores) == 1 or
                                             scores[0][0] > scores[1][0]):
            return scores[0][1], "task_uid_overlap"
    return None, "ambiguous_multi_project"


def _wbs_manifest(wbs_rows: list[dict], pid: str, sep: str = ".") -> tuple[list[dict], dict[str, dict]]:
    selected = [w for w in wbs_rows if not pid or _norm_id(w.get("proj_id")) == pid]
    by_id = {_norm_id(w.get("wbs_id")): w for w in selected if _norm_id(w.get("wbs_id"))}
    memo: dict[str, tuple[str, int]] = {}

    def path_level(wid: str, trail: set[str] | None = None) -> tuple[str, int]:
        if wid in memo:
            return memo[wid]
        row = by_id.get(wid) or {}
        code = str(row.get("wbs_short_name") or row.get("wbs_name") or wid).strip()
        parent = _norm_id(row.get("parent_wbs_id"))
        trail = set(trail or ())
        if not parent or parent not in by_id or wid in trail or parent == wid:
            out = (code, 1)
        else:
            trail.add(wid)
            pp, lvl = path_level(parent, trail)
            out = ((pp + sep + code) if pp and code else (code or pp), lvl + 1)
        memo[wid] = out
        return out

    out = []
    for w in selected:
        wid = _norm_id(w.get("wbs_id"))
        if not wid:
            continue
        path, level = path_level(wid)
        parent = _norm_id(w.get("parent_wbs_id"))
        parent_path = path_level(parent)[0] if parent in by_id else None
        out.append({
            "wbs_id": wid,
            "parent_wbs_id": parent or None,
            "code": path or str(w.get("wbs_short_name") or wid),
            "short_code": str(w.get("wbs_short_name") or ""),
            "name": w.get("wbs_name") or w.get("wbs_short_name") or wid,
            "parent_code": parent_path,
            "level": level,
            "project_node": str(w.get("proj_node_flag") or "").upper() == "Y",
        })
    return out, by_id


def inspect_source(path: str, *, info: dict | None = None,
                   task_uid_hints: list[Any] | None = None) -> dict | None:
    """Return source semantics when the format can be inspected safely."""
    if not path or not os.path.isfile(path):
        return None
    ext = os.path.splitext(path)[1].lower()
    if ext != ".xer":
        return {"format": ext.lstrip(".") or "unknown", "source_guarded": False}
    try:
        fields, rows = _read_xer(path)
    except OSError:
        return None

    projects = rows.get("PROJECT", [])
    all_tasks = rows.get("TASK", [])
    current, resolution = _choose_project(projects, all_tasks, info, task_uid_hints)
    if current is None:
        return {
            "format": "xer", "source_guarded": False,
            "project_resolution": resolution,
            "ambiguous_project": True,
            "project_count": len(projects),
        }

    pid = _norm_id(current.get("proj_id"))
    tasks = [t for t in all_tasks if not pid or _norm_id(t.get("proj_id")) == pid]
    task_ids = {_norm_id(t.get("task_id")) for t in tasks if _norm_id(t.get("task_id"))}
    task_by_id = {_norm_id(t.get("task_id")): t for t in tasks if _norm_id(t.get("task_id"))}
    task_to_wbs = {tid: _norm_id(t.get("wbs_id")) or None for tid, t in task_by_id.items()}

    wbs_sep = str(current.get("name_sep_char") or ".")
    wbs_nodes, _ = _wbs_manifest(rows.get("PROJWBS", []), pid, wbs_sep)
    task_fields = set(fields.get("TASK") or [])
    forecast_columns = sorted(task_fields & FORECAST_FIELDS)
    forecast_values = any(nonempty(t.get(c)) for t in tasks for c in forecast_columns)

    # Project Schedule Finish is the cleanest source-level current finish.  If
    # absent, Remaining Early Finish is the proper activity-level forecast date.
    forecast_finish = iso_date(current.get("scd_end_date"))
    forecast_basis = "PROJECT.scd_end_date" if forecast_finish else None
    if not forecast_finish and forecast_values:
        for field, basis in (("reend_date", "max TASK.reend_date"),
                             ("early_end_date", "max TASK.early_end_date")):
            if field not in task_fields:
                continue
            vals = [parse_dt(t.get(field)) for t in tasks if nonempty(t.get(field))]
            vals = [v for v in vals if v]
            if vals:
                forecast_finish = max(vals).date().isoformat()
                forecast_basis = basis
                break

    planned_ends = [parse_dt(t.get("target_end_date")) for t in tasks
                    if nonempty(t.get("target_end_date"))]
    planned_ends = [x for x in planned_ends if x]
    planned_starts = [parse_dt(t.get("target_start_date")) for t in tasks
                      if nonempty(t.get("target_start_date"))]
    planned_starts = [x for x in planned_starts if x]

    baseline_id = _norm_id(current.get("sum_base_proj_id"))
    baseline_assigned = bool(baseline_id)

    hours_per_day = None
    cal_id = _norm_id(current.get("clndr_id"))
    for cal in rows.get("CALENDAR", []):
        if cal_id and _norm_id(cal.get("clndr_id")) != cal_id:
            continue
        try:
            if nonempty(cal.get("day_hr_cnt")):
                hours_per_day = float(cal.get("day_hr_cnt"))
                break
        except (TypeError, ValueError):
            pass

    type_counts: dict[str, int] = {}
    for t in tasks:
        typ = str(t.get("task_type") or "unknown")
        type_counts[typ] = type_counts.get(typ, 0) + 1

    return {
        "format": "xer",
        "source_guarded": True,
        "project_resolution": resolution,
        "ambiguous_project": False,
        "project_id": pid,
        "project_code": current.get("proj_short_name"),
        "project_fields": sorted(fields.get("PROJECT") or []),
        "task_fields": sorted(task_fields),
        "task_ids": task_ids,
        "task_by_id": task_by_id,
        "task_to_wbs": task_to_wbs,
        "task_count": len(tasks),
        "task_type_counts": type_counts,
        "wbs_nodes": wbs_nodes,
        "wbs_count": len(wbs_nodes),
        "wbs_separator": wbs_sep,
        "forecast_columns": forecast_columns,
        "forecast_values_available": bool(forecast_values or forecast_finish),
        "forecast_finish": forecast_finish,
        "forecast_basis": forecast_basis,
        "planned_start": (iso_date(current.get("plan_start_date")) or
                          (min(planned_starts).date().isoformat() if planned_starts else None)),
        "planned_finish": (max(planned_ends).date().isoformat() if planned_ends else None),
        "project_planned_start": iso_date(current.get("plan_start_date")),
        # Oracle maps plan_end_date to Must Finish By, not Planned Finish.
        "must_finish_by": iso_date(current.get("plan_end_date")),
        "schedule_finish": iso_date(current.get("scd_end_date")),
        "data_date": (iso_date(current.get("last_recalc_date")) or
                      iso_date(current.get("sum_data_date"))),
        "baseline_assigned": baseline_assigned,
        "baseline_id": baseline_id or None,
        "baseline_basis": "assigned_project_baseline" if baseline_assigned
                          else "current_project_fallback_possible",
        "critical_path_type": current.get("critical_path_type"),
        "critical_float_threshold_hours": (
            float(current.get("critical_drtn_hr_cnt"))
            if nonempty(current.get("critical_drtn_hr_cnt")) else None),
        "hours_per_day": hours_per_day,
    }


def raw_task_id(task: dict) -> str:
    return _norm_id(task.get("uid"))


__all__ = ["FORECAST_FIELDS", "inspect_source", "iso_date", "nonempty",
           "parse_dt", "raw_task_id"]
