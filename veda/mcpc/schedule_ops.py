"""Horizun facade: open a schedule, harvest facts, normalise into VEDA.

Design rules honoured here:
  spec 10  VEDA never recomputes CPM/DCMA itself - Horizun owns that.
  spec 12  the uploaded file is a source document; analysis opens it read-only.
  spec 13  imported dates and engine-computed dates are stored separately.
  spec 14  the stable uid is identity; display id is presentation only.
  spec 15  everything useful is persisted so the UI never needs the agent.
  spec 44  every stored row carries a provenance category.
"""
from __future__ import annotations

import os
import threading
from typing import Any, Callable

from .. import config, db
from .client import McpError, horizun
from .source_semantics import inspect_source, raw_task_id, parse_dt
from . import tabular_schedule
from .reference_semantics import inspect_project_references

_handles: dict = {}
_hlock = threading.RLock()


def _iso(v: Any) -> str | None:
    if not v:
        return None
    s = str(v)
    return s.split("T")[0] if "T" in s else s


def _dt(v: Any) -> str | None:
    return str(v) if v else None


def _num(v: Any) -> float | None:
    try:
        if v is None or v == "":
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _rows(res: Any) -> list:
    """Horizun paged reads return items[]; a few return tasks[]/links[]."""
    if isinstance(res, list):
        return res
    if not isinstance(res, dict):
        return []
    for key in ("items", "tasks", "links", "resources", "rows", "results"):
        v = res.get(key)
        if isinstance(v, list):
            return v
    return []



def _count_assignments_local(project_id: str) -> int:
    row = db.q1("SELECT COUNT(*) AS c FROM assignments WHERE project_id=?", [project_id])
    return int((row or {}).get("c") or 0)

def _dur_days(v: Any) -> float | None:
    """'12d' / '8h' / '2w' -> days. Horizun also emits plain numbers."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().lower()
    if not s:
        return None
    try:
        if s.endswith("d"):
            return float(s[:-1])
        if s.endswith("h"):
            return float(s[:-1]) / 8.0
        if s.endswith("w"):
            return float(s[:-1]) * 5.0
        if s.endswith("mo"):
            return float(s[:-2]) * 20.0
        return float(s)
    except ValueError:
        return None


# --------------------------------------------------------------- handles
def open_schedule(path: str, mode: str = "readonly", project_id: str | None = None,
                  job_id: str | None = None) -> str:
    """Open (or reuse) a Horizun handle for a schedule file."""
    path = os.path.abspath(path)
    key = (path, mode)
    with _hlock:
        cached = _handles.get(key)
        if cached:
            try:
                horizun.call("project_info", {"handle": cached}, log=False, timeout=60)
                return cached
            except Exception:
                _handles.pop(key, None)
        res = horizun.call("project_open", {"path": path, "mode": mode},
                           project_id=project_id, job_id=job_id, timeout=300)
        handle = res.get("handle") if isinstance(res, dict) else None
        if not handle:
            raise McpError("project_open returned no handle for " + path)
        _handles[key] = handle
        return handle


def close_schedule(path: str, mode: str = "readonly") -> None:
    with _hlock:
        h = _handles.pop((os.path.abspath(path), mode), None)
    if h:
        horizun.try_call("project_save",
                         {"handle": h, "op": "close", "discardChanges": True}, log=False)


def forget_handles() -> None:
    with _hlock:
        _handles.clear()


def page_all(tool: str, args: dict, *, project_id=None, job_id=None,
             limit: int = 500, cap: int = 20000) -> list:
    """Walk a Horizun cursor to the end."""
    out: list = []
    cursor = 0
    while len(out) < cap:
        a = dict(args)
        a["limit"] = limit
        a["cursor"] = cursor
        res = horizun.call(tool, a, project_id=project_id, job_id=job_id,
                           log=(cursor == 0), timeout=300)
        rows = _rows(res)
        out.extend(rows)
        nxt = res.get("nextCursor") if isinstance(res, dict) else None
        if not rows or nxt in (None, "", 0) or not isinstance(nxt, int) or nxt <= cursor:
            break
        cursor = nxt
    return out


# ------------------------------------------------------------- normalising
def collect_snapshot(project_id: str, schedule_path: str, *, job_id: str | None = None,
                     file_id: str | None = None,
                     progress: Callable[[str, str, str], None] | None = None) -> dict:
    """Full read-only harvest of one schedule into VEDA's tables.

    Returns a compact summary dict; the detail lives in the database.
    """
    def step(name: str, label: str, state: str = "success") -> None:
        if progress:
            try:
                progress(name, label, state)
            except Exception:
                pass

    caps = horizun.capabilities()
    if not caps:
        horizun.health(project_id=project_id, job_id=job_id)
        caps = horizun.capabilities()
    if not caps.get("read_schedule", True):
        raise McpError("Horizun reports read_schedule is unavailable on this machine")

    analysis_path = schedule_path
    tabular_source = None
    if os.path.splitext(schedule_path)[1].lower() in tabular_schedule.SUPPORTED:
        try:
            analysis_path, tabular_source = tabular_schedule.prepare_mspdi(
                schedule_path, cache_dir=str(config.project_dir(project_id) / "adapted"))
            step("schedule_adapted", "Tabular schedule normalized to Microsoft Project XML for Horizun")
        except Exception as exc:
            raise McpError("Tabular schedule could not be normalized: " + str(exc)) from exc

    handle = open_schedule(analysis_path, "readonly", project_id, job_id)
    step("schedule_opened", "Schedule opened")

    info = horizun.call("project_info", {"handle": handle},
                        project_id=project_id, job_id=job_id, timeout=300)
    if not isinstance(info, dict):
        info = {}

    snapshot_id = db.new_id("snap_")
    prev = db.q1("SELECT MAX(revision) AS r FROM schedule_snapshots WHERE project_id=?",
                 [project_id])
    revision = int((prev or {}).get("r") or 0) + 1
    # Capture the previous current activity set before the live tables are
    # replaced. The immutable source files + this delta form the schedule
    # revision audit trail used by v0.1.2.
    previous_activities = db.q(
        "SELECT uid, display_id, name, wbs, parent_uid, is_summary, is_milestone, "
        "status, start, finish, actual_start, actual_finish, duration_days, "
        "remaining_days, percent_complete, constraint_type, constraint_date, "
        "deadline, baseline_start, baseline_finish FROM activities "
        "WHERE project_id=?", [project_id])
    db.ex("UPDATE schedule_snapshots SET is_current=0 WHERE project_id=?", [project_id])

    # ---- tasks --------------------------------------------------------
    tasks = page_all("tasks_query", {"handle": handle, "shape": "flat",
                                     "sort": "wbs", "includeCustom": True},
                     project_id=project_id, job_id=job_id)

    # XER is explicit about structure: PROJWBS rows are WBS nodes and TASK rows
    # are activities. Some adapters flatten both into tasks_query. Resolve the
    # source project first, then retain only rows that map to source TASK ids.
    source = tabular_source or inspect_source(schedule_path, info=info,
                            task_uid_hints=[t.get("uid") for t in tasks])
    raw_task_count = len(tasks)
    if source and source.get("source_guarded") and source.get("task_ids"):
        source_ids = set(source.get("task_ids") or ())
        returned_ids = {raw_task_id(t) for t in tasks if raw_task_id(t)}
        overlap = returned_ids & source_ids
        denom = min(len(returned_ids), len(source_ids)) or 1
        # Only apply identity filtering when the adapter/source identity systems
        # clearly agree. Otherwise preserve the MCP rows and disclose that source
        # structure could not safely constrain them.
        if overlap and (len(overlap) / denom) >= 0.80:
            tasks = [t for t in tasks if raw_task_id(t) in source_ids]
    wbs_n = int((source or {}).get("wbs_count") or 0)
    label = str(len(tasks)) + " activities loaded"
    if wbs_n:
        label += " · " + str(wbs_n) + " WBS nodes kept separate"
    if raw_task_count != len(tasks):
        label += " · " + str(raw_task_count - len(tasks)) + " structural rows excluded"
    step("activities_loaded", label)

    db.ex("DELETE FROM activities WHERE project_id=?", [project_id])
    act_rows = []
    by_uid = {}
    source_guarded = bool((source or {}).get("source_guarded"))
    is_tabular_source = bool(tabular_source and source_guarded)
    source_task_by_id = (source or {}).get("task_by_id") or {}
    source_criticality_available = bool((source or {}).get("criticality_available"))

    for t in tasks:
        uid = t.get("uid")
        if uid is None:
            continue
        by_uid[uid] = t
        raw = source_task_by_id.get(raw_task_id(t), {})
        tab = ((tabular_source or {}).get("by_uid") or {}).get(str(uid), {})

        # For adapted tabular schedules the original row is authoritative. MSPDI
        # values are transport-only and may contain defaults inserted for compatibility.
        if is_tabular_source:
            pct = raw.get("percent_complete")
            if pct is None and raw.get("status") == "not_started": pct = 0.0
            if pct is None and raw.get("status") == "complete": pct = 100.0
            status = raw.get("status")
            actual_finish = raw.get("actual_finish_date") or None
            bstart, bfin = raw.get("baseline_start_date"), raw.get("baseline_end_date")
            raw_type = str(raw.get("activity_type") or raw.get("task_type") or "")
            source_summary = bool(raw.get("is_summary"))
            source_milestone = bool(raw.get("is_milestone"))
            is_summary = source_summary
            is_milestone = source_milestone
            start_v = raw.get("target_start_date") or None
            finish_v = raw.get("target_end_date") or None
            actual_start_v = raw.get("actual_start_date") or None
            duration_v = raw.get("duration_days")
            total_float_v = raw.get("total_float_days") if (source or {}).get("float_values_available") else None
            free_float_v = raw.get("free_float_days") if (source or {}).get("float_values_available") else None
            critical_v = 1 if source_criticality_available and raw.get("critical") is True else 0
            calendar_v = raw.get("calendar") or None
            constraint_type_v = raw.get("constraint_type")
            constraint_date_v = raw.get("constraint_date")
            resource_names_v = "; ".join(raw.get("resource_names") or []) or None
            provenance_v = "SOURCE_FILE"
        else:
            pct = _num(t.get("percentComplete"))
            if pct is None: pct = 0.0
            actual_finish = t.get("actualFinish")
            if actual_finish:
                status = "complete"
            elif t.get("actualStart") or pct > 0:
                status = "in_progress"
            else:
                status = "not_started"
            bstart, bfin = t.get("baselineStart"), t.get("baselineFinish")
            raw_type = str(raw.get("task_type") or "")
            source_summary = raw_type in ("TT_WBS", "WBS Summary")
            source_milestone = raw_type in ("TT_Mile", "TT_FinMile", "Start Milestone", "Finish Milestone")
            is_summary = bool(t.get("summary") or source_summary)
            is_milestone = bool(t.get("milestone") or source_milestone)
            start_v, finish_v = t.get("start"), t.get("finish")
            actual_start_v = t.get("actualStart")
            duration_v = _dur_days(t.get("duration"))
            total_float_v = _num(t.get("totalFloatDays"))
            free_float_v = _num(t.get("freeFloatDays"))
            critical_v = 1 if t.get("critical") else 0
            calendar_v = t.get("calendar")
            constraint_type_v = t.get("constraintType")
            constraint_date_v = _dt(t.get("constraintDate"))
            resource_names_v = t.get("resourceNames") or t.get("resources")
            provenance_v = "MCP_FACT"

        if not status:
            if actual_finish: status = "complete"
            elif actual_start_v or (pct is not None and pct > 0): status = "in_progress"
            else: status = "not_started"

        act_rows.append({
            "id": db.new_id("act_"), "project_id": project_id,
            "snapshot_id": snapshot_id,
            "uid": uid, "display_id": str(tab.get("source_id") or raw.get("source_id") or t.get("id") or uid),
            "name": tab.get("name") or raw.get("name") or t.get("name"),
            "wbs": tab.get("wbs") or raw.get("wbs") or t.get("wbs"),
            "outline_level": tab.get("outline_level") or t.get("outlineLevel"),
            "parent_uid": None if is_tabular_source else t.get("parentUid"),
            "is_summary": 1 if is_summary else 0,
            "is_milestone": 1 if is_milestone else 0,
            "status": status,
            "start": _dt(start_v), "finish": _dt(finish_v),
            "actual_start": _dt(actual_start_v),
            "actual_finish": _dt(actual_finish),
            "early_start": None if is_tabular_source else _dt(t.get("earlyStart")),
            "early_finish": None if is_tabular_source else _dt(t.get("earlyFinish")),
            "late_start": None if is_tabular_source else _dt(t.get("lateStart")),
            "late_finish": None if is_tabular_source else _dt(t.get("lateFinish")),
            "duration_days": duration_v,
            "remaining_days": None if is_tabular_source else _dur_days(t.get("remainingDuration")),
            "percent_complete": pct,
            "total_float_days": total_float_v,
            "free_float_days": free_float_v,
            "critical": critical_v,
            "calendar": calendar_v,
            "constraint_type": constraint_type_v,
            "constraint_date": _dt(constraint_date_v),
            "deadline": None if is_tabular_source else _dt(t.get("deadline")),
            "baseline_start": _dt(bstart), "baseline_finish": _dt(bfin),
            "baseline_duration_days": raw.get("duration_days") if is_tabular_source and bstart and bfin else _dur_days(t.get("baselineDuration")),
            "cost": None if is_tabular_source else _num(t.get("cost")),
            "work_hours": None if is_tabular_source else _num(t.get("workHours")),
            "resource_names": resource_names_v,
            "custom_json": db.jdumps(t.get("custom")) if t.get("custom") else None,
            "notes": t.get("notes"),
            "provenance": provenance_v,
        })

    for r in act_rows:
        bf, fin = r.get("baseline_finish"), r.get("finish")
        r["finish_variance_days"] = _daydiff(fin, bf)
        r["start_variance_days"] = _daydiff(r.get("start"), r.get("baseline_start"))
        if r.get("duration_days") is not None and r.get("baseline_duration_days") is not None:
            r["duration_variance_days"] = round(r["duration_days"] - r["baseline_duration_days"], 2)
    for r in act_rows:
        db.insert("activities", r)

    # ---- relationships -------------------------------------------------
    engine_links = page_all("links_query", {"handle": handle, "direction": "both"},
                            project_id=project_id, job_id=job_id)
    db.ex("DELETE FROM relationships WHERE project_id=?", [project_id])
    seen = set()
    names_by_uid = {int(r["uid"]): r.get("name") for r in act_rows if r.get("uid") is not None}
    if is_tabular_source and (source or {}).get("predecessor_values_available"):
        for l in (source or {}).get("source_relationships") or []:
            a, b = l.get("pred_uid"), l.get("succ_uid")
            if a is None or b is None or (a, b) in seen: continue
            seen.add((a, b))
            db.insert("relationships", {
                "project_id": project_id, "snapshot_id": snapshot_id,
                "pred_uid": a, "succ_uid": b,
                "pred_name": names_by_uid.get(int(a)), "succ_name": names_by_uid.get(int(b)),
                "type": l.get("type") or "unspecified",
                "lag_days": l.get("lag_days"), "driving": 0,
                "provenance": "SOURCE_FILE",
            })
    else:
        for l in engine_links:
            a, b = l.get("fromUid"), l.get("toUid")
            if a is None or b is None or (a, b, l.get("type")) in seen: continue
            seen.add((a, b, l.get("type")))
            db.insert("relationships", {
                "project_id": project_id, "snapshot_id": snapshot_id,
                "pred_uid": a, "succ_uid": b,
                "pred_name": l.get("fromName"), "succ_name": l.get("toName"),
                "type": l.get("type") or "FS", "lag_days": _num(l.get("lagDays")),
                "driving": 1 if l.get("driving") else 0,
                "provenance": "MCP_FACT",
            })
    step("relationships_analyzed", str(len(seen)) + " relationships analysed")

    # ---- resources & assignments ---------------------------------------
    engine_resources = page_all("resources_query", {"handle": handle, "includeAssignments": True},
                                project_id=project_id, job_id=job_id, limit=200)
    db.ex("DELETE FROM resources WHERE project_id=?", [project_id])
    db.ex("DELETE FROM assignments WHERE project_id=?", [project_id])
    resources = []
    if is_tabular_source and (source or {}).get("resource_values_available"):
        labels = list((source or {}).get("resource_labels") or [])
        uid_by_resource = {name: i + 1 for i, name in enumerate(labels)}
        counts = {}
        for a in (source or {}).get("source_assignments") or []:
            counts[a["resource_name"]] = counts.get(a["resource_name"], 0) + 1
        for name in labels:
            rr = {"uid": uid_by_resource[name], "name": name, "assignments": counts.get(name, 0)}
            resources.append(rr)
            db.insert("resources", {
                "project_id": project_id, "snapshot_id": snapshot_id,
                "uid": rr["uid"], "name": name, "type": "source assignment label",
                "calendar": None, "max_units": None, "standard_rate": None,
                "work_hours": None, "cost": None, "overallocated": 0,
                "peak_units": None, "assignment_count": counts.get(name, 0),
                "provenance": "SOURCE_FILE",
            })
        for a in (source or {}).get("source_assignments") or []:
            task_uid = a.get("task_uid")
            db.insert("assignments", {
                "project_id": project_id, "snapshot_id": snapshot_id,
                "task_uid": task_uid, "resource_uid": uid_by_resource.get(a.get("resource_name")),
                "task_name": names_by_uid.get(int(task_uid)) if task_uid is not None else None,
                "resource_name": a.get("resource_name"),
                "units": _num(a.get("budgeted_units")), "work_hours": None,
                "actual_work_hours": None, "remaining_work_hours": None,
                "cost": None, "actual_cost": None, "start": None, "finish": None,
                "provenance": "SOURCE_FILE",
            })
    else:
        resources = engine_resources
        for r in resources:
            assigns = r.get("assignments") or []
            db.insert("resources", {
                "project_id": project_id, "snapshot_id": snapshot_id,
                "uid": r.get("uid"), "name": r.get("name"), "type": r.get("type"),
                "calendar": r.get("calendar"), "max_units": _num(r.get("maxUnits")),
                "standard_rate": _num(r.get("standardRate")),
                "work_hours": _num(r.get("workHours")), "cost": _num(r.get("cost")),
                "overallocated": 1 if r.get("overallocated") else 0,
                "peak_units": _num(r.get("peakUnits")), "assignment_count": len(assigns),
                "provenance": "MCP_FACT",
            })
            for a in assigns:
                db.insert("assignments", {
                    "project_id": project_id, "snapshot_id": snapshot_id,
                    "task_uid": a.get("taskUid"), "resource_uid": a.get("resourceUid"),
                    "task_name": a.get("taskName"), "resource_name": a.get("resourceName"),
                    "units": _num(a.get("units")), "work_hours": _num(a.get("workHours")),
                    "actual_work_hours": _num(a.get("actualWorkHours")),
                    "remaining_work_hours": _num(a.get("remainingWorkHours")),
                    "cost": _num(a.get("cost")), "actual_cost": _num(a.get("actualCost")),
                    "start": _dt(a.get("start")), "finish": _dt(a.get("finish")),
                    "provenance": "MCP_FACT",
                })

    # ---- analysis (spec 22) --------------------------------------------
    analyze = {}
    ok, res = horizun.try_call("schedule_analyze", {"handle": handle},
                               project_id=project_id, job_id=job_id, timeout=300)
    if ok and isinstance(res, dict):
        analyze = res
        step("critical_path_analyzed", "Critical path and float computed")
    else:
        step("critical_path_analyzed", "Schedule analysis unavailable", "failed")

    over = {}
    for o in (analyze.get("overallocation") or []):
        uid = o.get("resourceUid")
        if uid is None:
            continue
        e = over.setdefault(uid, {"days": 0, "peak": 0})
        e["days"] += 1
        e["peak"] = max(e["peak"], _num(o.get("peakUnits")) or 0)
    for uid, e in over.items():
        db.ex("UPDATE resources SET overallocated=1, overallocated_days=?, peak_units=? "
              "WHERE project_id=? AND uid=?",
              [e["days"], e["peak"], project_id, uid])

    # ---- milestones (spec 29) ------------------------------------------
    db.ex("DELETE FROM milestones WHERE project_id=?", [project_id])
    ms_analysis = {m.get("uid"): m for m in (analyze.get("milestones") or [])}
    for r in act_rows:
        if not r["is_milestone"]:
            continue
        m = ms_analysis.get(r["uid"], {})
        db.insert("milestones", {
            "project_id": project_id, "snapshot_id": snapshot_id,
            "uid": r["uid"], "display_id": r["display_id"], "name": r["name"],
            "planned_date": r["start"], "baseline_date": r["baseline_finish"],
            "forecast_date": (None if source_guarded and not (source or {}).get("forecast_values_available")
                              else (_dt(m.get("finish")) or r["finish"])),
            "actual_date": r["actual_finish"], "deadline": r["deadline"],
            "variance_days": _num(m.get("slipDays")) if m.get("slipDays") is not None
            else r.get("finish_variance_days"),
            "status": m.get("status") or r["status"],
            "critical": r["critical"],
            "total_float_days": r["total_float_days"],
            "provenance": "SOURCE_FILE" if is_tabular_source else "MCP_FACT",
        })

    # ---- WBS rollup (spec 18) ------------------------------------------
    _build_wbs(project_id, snapshot_id, act_rows, by_uid, source=source)

    # ---- schedule quality (spec 23) ------------------------------------
    qa = {}
    if caps.get("schedule_qa", True):
        ok, res = horizun.try_call("schedule_qa", {"handle": handle},
                                   project_id=project_id, job_id=job_id, timeout=300)
        if ok and isinstance(res, dict):
            qa = res
            db.ex("DELETE FROM qa_findings WHERE project_id=?", [project_id])
            for f in res.get("findings") or []:
                evaluated = f.get("evaluated", True)
                if not evaluated:
                    status = "not_evaluated"
                else:
                    status = "pass" if f.get("passed") else "fail"
                db.insert("qa_findings", {
                    "project_id": project_id, "snapshot_id": snapshot_id,
                    "code": f.get("rule"), "category": _qa_category(f.get("rule")),
                    "title": _qa_title(f.get("rule")),
                    "detail": f.get("summary") or f.get("reason"),
                    "severity": f.get("severity"), "status": status,
                    "threshold": _s(f.get("threshold")), "actual": _s(f.get("measured")),
                    "count": len(f.get("uids") or []),
                    "percent": _num(f.get("measured")),
                    "task_uids_json": db.jdumps(f.get("uids") or []),
                    "provenance": f.get("_veda_provenance") or "MCP_FACT",
                })
            step("schedule_quality_assessed",
                 str(res.get("failed", 0)) + " of " + str(res.get("checks", 0)) +
                 " DCMA checks failed")

    # ---- baseline / earned value (spec 24, 28) -------------------------
    # A source can legitimately contain baseline/reference dates without enough
    # status/progress/cost information to support earned-value metrics. Keep
    # those concepts separate and never let baseline_compare erase explicit
    # source baseline columns.
    db.ex("DELETE FROM earned_value WHERE project_id=?", [project_id])
    bc = {}
    ok, res = horizun.try_call("baseline_compare", {"handle": handle, "byBranch": True},
                               project_id=project_id, job_id=job_id, timeout=300)
    source_baseline_present = bool((source or {}).get("baseline_values_available"))
    ev_eligible = bool((source or {}).get("ev_eligible")) if is_tabular_source else True
    if ok and isinstance(res, dict) and res.get("baselinePresent") and ev_eligible:
        bc = res
        basis = "Horizun baseline_compare, measure=" + \
                str((res.get("project") or {}).get("measure", "unknown")) + \
                ", baseline " + str(res.get("baselineNumber", 0))
        for scope_row, scope, key in _ev_rows(res):
            db.insert("earned_value", {
                "project_id": project_id, "snapshot_id": snapshot_id,
                "scope": scope, "scope_key": key,
                "status_date": ((source or {}).get("data_date") if source_guarded
                                else _iso(res.get("statusDate") or info.get("statusDate"))),
                "pv": _num(scope_row.get("bcws")), "ev": _num(scope_row.get("bcwp")),
                "ac": _num(scope_row.get("acwp")),
                "sv": _num(scope_row.get("scheduleVariance")),
                "cv": _num(scope_row.get("costVariance")),
                "spi": _num(scope_row.get("spi")), "cpi": _num(scope_row.get("cpi")),
                "eac": _num(scope_row.get("eac")), "bac": _num(scope_row.get("bac")),
                "tcpi": _num(scope_row.get("tcpi")),
                "basis": basis, "provenance": "MCP_FACT",
            })
        step("baseline_compared", "Earned value computed against stored baseline")
    elif ok and isinstance(res, dict) and not source_baseline_present:
        # Only clear adapter-shaped baseline fields when the original source does
        # not itself contain baseline values. A source baseline is evidence even
        # if Horizun does not recognise it as an assigned P6 baseline.
        db.ex("UPDATE activities SET baseline_start=NULL, baseline_finish=NULL, "
              "baseline_duration_days=NULL, start_variance_days=NULL, "
              "finish_variance_days=NULL, duration_variance_days=NULL "
              "WHERE project_id=?", [project_id])
        for r in act_rows:
            r["baseline_start"] = None
            r["baseline_finish"] = None
            r["baseline_duration_days"] = None
            r["start_variance_days"] = None
            r["finish_variance_days"] = None
            r["duration_variance_days"] = None
    elif source_baseline_present and not ev_eligible:
        step("baseline_compared", "Baseline/reference dates retained; earned value not evaluable from source", "success")

    # ---- timephased S-curve (spec 27) ----------------------------------
    if caps.get("timephased", True):
        db.ex("DELETE FROM timephased WHERE project_id=?", [project_id])
        # Try the richest measure the file actually carries. Horizun reports an
        # empty series (with the reason) when a schedule has no loaded hours or
        # cost, so fall back rather than assume the file is loaded.
        for measure in ("work", "cost", "duration"):
            ok, res = horizun.try_call(
                "timephased_query",
                {"handle": handle, "measure": measure, "granularity": "month"},
                project_id=project_id, job_id=job_id, timeout=300)
            if not (ok and isinstance(res, dict) and res.get("series")):
                continue
            cum = {c.get("period"): _num(c.get("value"))
                   for c in (res.get("cumulative") or [])}
            for s in res.get("series") or []:
                db.insert("timephased", {
                    "project_id": project_id, "snapshot_id": snapshot_id,
                    "measure": res.get("measure", measure),
                    "granularity": res.get("granularity", "month"),
                    "period": _iso(s.get("period")), "value": _num(s.get("value")),
                    "cumulative": cum.get(s.get("period")),
                    "provenance": "MCP_FACT",
                })
            break

    # ---- EPS (spec 17) -------------------------------------------------
    _build_eps(project_id, info, schedule_path)

    # ---- snapshot header -----------------------------------------------
    leaves = [r for r in act_rows if not r["is_summary"]]

    # Availability is a first-class fact. A transport default of false/zero is
    # not the same as the source establishing that the true value is zero.
    criticality_available = (bool((source or {}).get("criticality_available"))
                             if is_tabular_source else True)
    crit = (sum(1 for r in leaves if r["critical"])
            if criticality_available else None)
    status_date = ((source or {}).get("data_date") if source_guarded
                   else _iso(info.get("statusDate")))

    # Keep two different delay concepts separate and preserve N/E when their
    # required reference date/status evidence is missing.
    overdue_evaluable = bool(status_date)
    overdue = 0 if overdue_evaluable else None
    if overdue_evaluable:
        for r in leaves:
            if r["status"] == "complete":
                continue
            raw = source_task_by_id.get(str(r.get("uid")))
            ref_finish = _iso((raw or {}).get("target_end_date")) or _iso(r.get("finish"))
            if ref_finish and ref_finish < status_date:
                overdue += 1

    source_baseline_present = bool((source or {}).get("baseline_values_available"))
    baseline_present = source_baseline_present or bool(bc)
    completed_with_actual = [r for r in leaves if r.get("actual_finish")]
    completed_late_evaluable = bool(baseline_present and completed_with_actual)
    completed_late = None
    if completed_late_evaluable:
        completed_late = sum(1 for r in completed_with_actual
                             if r.get("baseline_finish") and
                             (_daydiff(r.get("actual_finish"), r.get("baseline_finish")) or 0) > 0)

    if is_tabular_source:
        progress_available = bool((source or {}).get("progress_available"))
        progress_basis = (source or {}).get("progress_basis") or "not available in source"
        overall = (source or {}).get("source_progress_pct") if progress_available else None
    else:
        progress_available = True
        progress_basis = "schedule progress"
        pct = (bc.get("project") or {})
        overall = None
        if pct.get("bac"):
            overall = round(100.0 * (_num(pct.get("bcwp")) or 0) / _num(pct["bac"]), 1)
            progress_basis = "EV/BAC"
        if overall is None and leaves:
            durs = [(r.get("duration_days") or 0) for r in leaves]
            tot = sum(durs) or len(leaves)
            overall = round(sum((r.get("percent_complete") or 0) *
                                ((r.get("duration_days") or 1)) for r in leaves) / (tot or 1), 1)

    if source_guarded:
        planned_start = (source or {}).get("planned_start")
        planned_finish = (source or {}).get("planned_finish")
        forecast_finish = (source or {}).get("forecast_finish")
        forecast_basis = ((source or {}).get("forecast_basis") or "not available in source")
        must_finish_by = (source or {}).get("must_finish_by")
    else:
        planned_start = _iso(info.get("startDate"))
        planned_finish = _iso(info.get("finishDate"))
        forecast_finish = _iso(info.get("finishDate"))
        forecast_basis = "Horizun project_info.finishDate" if forecast_finish else None
        must_finish_by = None

    if source_baseline_present:
        baseline_start = (source or {}).get("baseline_start")
        baseline_finish = (source or {}).get("baseline_finish")
        baseline_basis = (source or {}).get("baseline_basis") or "embedded source baseline/reference"
    elif bc:
        baseline_start_vals = [r.get("baseline_start") for r in act_rows if r.get("baseline_start")]
        baseline_start = _iso(min(baseline_start_vals)) if baseline_start_vals else None
        baseline_finish = _baseline_finish(act_rows)
        if source_guarded and not (source or {}).get("baseline_assigned"):
            baseline_basis = "P6 current-project fallback baseline"
        elif source_guarded:
            baseline_basis = "assigned P6 project baseline"
        else:
            baseline_basis = "Horizun stored baseline"
    else:
        baseline_start = None
        baseline_finish = None
        baseline_basis = None

    cptype = str((source or {}).get("critical_path_type") or "").strip()
    if is_tabular_source:
        criticality_basis = ((source or {}).get("criticality_basis")
                             if criticality_available else "not available in source")
    elif cptype == "CT_TotFloat":
        criticality_basis = "total float"
    elif cptype:
        criticality_basis = cptype
    else:
        criticality_basis = "Horizun critical flag"
    threshold_hours = _num((source or {}).get("critical_float_threshold_hours"))
    hpd = _num((source or {}).get("hours_per_day"))
    criticality_threshold_days = (threshold_hours / hpd
                                  if threshold_hours is not None and hpd else None)

    type_counts = (source or {}).get("task_type_counts") or {}
    loe_count = int(type_counts.get("TT_LOE", 0) or type_counts.get("Level of Effort", 0) or 0)
    summary_count = sum(1 for r in act_rows if r.get("is_summary"))
    milestone_count = sum(1 for r in act_rows if r.get("is_milestone"))
    resource_assignment_count = (int((source or {}).get("resource_assignment_count") or 0)
                                 if is_tabular_source else _count_assignments_local(project_id))
    resource_basis = ("source resource-assignment column" if is_tabular_source and
                      (source or {}).get("resource_values_available") else "Horizun resources_query")

    reference_context = inspect_project_references(project_id, source) if is_tabular_source else None

    source_public = None
    if source:
        source_public = {k: source.get(k) for k in (
            "format", "source_guarded", "project_resolution", "ambiguous_project",
            "project_id", "project_code", "task_count", "wbs_count", "task_type_counts",
            "forecast_columns", "forecast_values_available", "forecast_finish", "forecast_basis",
            "planned_start", "planned_finish", "project_planned_start", "must_finish_by",
            "schedule_finish", "data_date", "baseline_assigned", "baseline_id", "baseline_basis",
            "baseline_values_available", "baseline_start", "baseline_finish",
            "baseline_coverage_count", "baseline_coverage_total", "baseline_equals_planned_count",
            "critical_path_type", "critical_float_threshold_hours", "hours_per_day",
            "criticality_available", "criticality_basis", "progress_available", "progress_basis",
            "source_progress_pct", "status_counts", "resource_assignment_count",
            "resource_label_count", "calendar_labels", "relationship_type_values_available",
            "lag_values_available", "duplicate_sibling_affected_ids", "milestone_duration_uids",
            "milestone_resource_uids") if k in source}

    db.insert("schedule_snapshots", {
        "id": snapshot_id, "project_id": project_id, "file_id": file_id,
        "job_id": job_id, "revision": revision, "source_path": schedule_path,
        "project_name": info.get("name") or info.get("title") or (source or {}).get("project_code"),
        "data_date": status_date, "status_date": status_date,
        "planned_start": planned_start, "planned_finish": planned_finish,
        "forecast_finish": forecast_finish,
        "baseline_start": baseline_start, "baseline_finish": baseline_finish,
        "baseline_present": 1 if baseline_present else 0,
        "baseline_coverage_count": int((source or {}).get("baseline_coverage_count") or 0),
        "must_finish_by": must_finish_by,
        "forecast_basis": forecast_basis, "baseline_basis": baseline_basis,
        "criticality_basis": criticality_basis,
        "criticality_available": 1 if criticality_available else 0,
        "criticality_threshold_days": criticality_threshold_days,
        "overdue_evaluable": 1 if overdue_evaluable else 0,
        "completed_late_evaluable": 1 if completed_late_evaluable else 0,
        "progress_available": 1 if progress_available else 0,
        "progress_basis": progress_basis,
        "resource_assignment_count": resource_assignment_count,
        "resource_basis": resource_basis,
        "task_count": len(act_rows), "wbs_count": int((source or {}).get("wbs_count") or 0),
        "summary_activity_count": summary_count, "loe_count": loe_count,
        "milestone_count": milestone_count,
        "relationship_count": len(seen), "resource_count": len(resources),
        "critical_count": crit, "late_count": overdue,
        "overdue_count": overdue, "completed_late_count": completed_late,
        "percent_complete": overall, "health_score": _health_score(qa),
        "capabilities_json": db.jdumps(caps),
        "info_json": db.jdumps({"info": info, "source": source_public,
                                 "reference_context": reference_context,
                                 "analyze": _slim(analyze), "qa": {
            "checks": qa.get("checks"), "passed": qa.get("passed"),
            "failed": qa.get("failed"), "notEvaluated": qa.get("notEvaluated"),
            "notes": qa.get("notes"), "semanticGuard": qa.get("vedaSemanticGuard"),
        }, "baseline": {"present": baseline_present, "basis": baseline_basis,
                         "project": bc.get("project")}}),
        "is_current": 1,
    })

    revision_changes = _record_revision_changes(
        project_id, snapshot_id, revision, previous_activities, act_rows)
    lineage_changes = _record_activity_lineage(
        project_id, revision, previous_activities, act_rows)
    if revision > 1:
        step("schedule_revision_compared",
             str(revision_changes["added"]) + " added, " +
             str(revision_changes["removed"]) + " removed, " +
             str(revision_changes["updated"]) + " updated")

    return {
        "snapshot_id": snapshot_id, "revision": revision,
        "tasks": len(act_rows), "wbs": int((source or {}).get("wbs_count") or 0),
        "relationships": len(seen), "resources": len(resources),
        "milestones": milestone_count,
        "critical": crit, "late": overdue, "overdue": overdue,
        "completed_late": completed_late,
        "qa_failed": qa.get("failed"), "qa_checks": qa.get("checks"),
        "baseline_present": baseline_present,
        "project_name": info.get("name") or (source or {}).get("project_code"),
        "planned_start": planned_start,
        "forecast_finish": forecast_finish,
        "status_date": status_date,
        "percent_complete": overall,
        "revision_changes": revision_changes, "activity_lineage": lineage_changes,
    }


_REVISION_FIELDS = (
    "display_id", "name", "wbs", "parent_uid", "is_summary", "is_milestone",
    "status", "start", "finish", "actual_start", "actual_finish",
    "duration_days", "remaining_days", "percent_complete", "constraint_type",
    "constraint_date", "deadline", "baseline_start", "baseline_finish",
)


def _record_activity_lineage(project_id: str, revision: int, before_rows: list, after_rows: list) -> dict:
    """Record stable identity and conservative rename/split/merge hypotheses.

    This does not rewrite history.  It only preserves an auditable bridge between
    the activity identity that existed when old evidence was created and the
    identity exposed by the new schedule revision.
    """
    out={"same_uid":0,"renamed_or_rekeyed":0,"split_candidate":0,"merge_candidate":0}
    if revision <= 1 or not before_rows:
        return out
    db.ex("DELETE FROM activity_lineage WHERE project_id=? AND to_revision=?",[project_id,revision])
    before={int(r["uid"]):r for r in before_rows if r.get("uid") is not None}
    after={int(r["uid"]):r for r in after_rows if r.get("uid") is not None}
    for uid in sorted(set(before)&set(after)):
        a,b=before[uid],after[uid]
        basis=[]
        if a.get("display_id")==b.get("display_id"): basis.append("display_id_stable")
        if a.get("name")==b.get("name"): basis.append("name_stable")
        db.insert("activity_lineage",{"project_id":project_id,"from_revision":revision-1,"to_revision":revision,
                  "from_uid":uid,"to_uid":uid,"from_display_id":a.get("display_id"),"to_display_id":b.get("display_id"),
                  "relation":"same_uid","score":1.0,"basis":";".join(basis) or "stable_horizun_uid"})
        out["same_uid"]+=1

    old=[r for u,r in before.items() if u not in after]
    new=[r for u,r in after.items() if u not in before]
    import re as _re
    def toks(v): return {x for x in _re.findall(r"[a-z0-9]+",str(v or "").lower()) if len(x)>2}
    def sim(a,b):
        score=0.0; reasons=[]
        da=str(a.get("display_id") or "").lower(); dbid=str(b.get("display_id") or "").lower()
        if da and dbid and da==dbid: score+=.65; reasons.append("display_id_exact")
        an,bn=toks(a.get("name")),toks(b.get("name"));
        if an and bn:
            j=len(an&bn)/max(1,len(an|bn)); score+=.48*j
            if j>=.6: reasons.append("name_similarity")
        aw,bw=toks(a.get("wbs")),toks(b.get("wbs"))
        if aw and bw:
            j=len(aw&bw)/max(1,len(aw|bw)); score+=.22*j
            if j>=.6: reasons.append("wbs_similarity")
        return min(1.0,score),reasons
    matrix={(int(a["uid"]),int(b["uid"])):sim(a,b) for a in old for b in new}
    # One-to-one high-confidence rekeys/renames.
    used_old=set(); used_new=set()
    pairs=sorted(((sc,ou,nu,rs) for (ou,nu),(sc,rs) in matrix.items()),reverse=True)
    for sc,ou,nu,rs in pairs:
        if sc < .72 or ou in used_old or nu in used_new: continue
        a,b=before[ou],after[nu]
        db.insert("activity_lineage",{"project_id":project_id,"from_revision":revision-1,"to_revision":revision,
                  "from_uid":ou,"to_uid":nu,"from_display_id":a.get("display_id"),"to_display_id":b.get("display_id"),
                  "relation":"renamed_or_rekeyed","score":round(sc,4),"basis":";".join(rs)})
        used_old.add(ou); used_new.add(nu); out["renamed_or_rekeyed"]+=1
    # Ambiguous one-to-many / many-to-one remain hypotheses and require planner review.
    for a in old:
        ou=int(a["uid"]); matches=[(nu,sc,rs) for (x,nu),(sc,rs) in matrix.items() if x==ou and sc>=.58 and nu not in used_new]
        if len(matches)>=2:
            for nu,sc,rs in sorted(matches,key=lambda z:-z[1])[:4]:
                b=after[nu]
                db.insert("activity_lineage",{"project_id":project_id,"from_revision":revision-1,"to_revision":revision,
                          "from_uid":ou,"to_uid":nu,"from_display_id":a.get("display_id"),"to_display_id":b.get("display_id"),
                          "relation":"split_candidate","score":round(sc,4),"basis":";".join(rs)})
                out["split_candidate"]+=1
    for b in new:
        nu=int(b["uid"]); matches=[(ou,sc,rs) for (ou,x),(sc,rs) in matrix.items() if x==nu and sc>=.58 and ou not in used_old]
        if len(matches)>=2:
            for ou,sc,rs in sorted(matches,key=lambda z:-z[1])[:4]:
                a=before[ou]
                db.insert("activity_lineage",{"project_id":project_id,"from_revision":revision-1,"to_revision":revision,
                          "from_uid":ou,"to_uid":nu,"from_display_id":a.get("display_id"),"to_display_id":b.get("display_id"),
                          "relation":"merge_candidate","score":round(sc,4),"basis":";".join(rs)})
                out["merge_candidate"]+=1
    return out


def _record_revision_changes(project_id: str, snapshot_id: str, revision: int,
                             before_rows: list, after_rows: list) -> dict:
    """Persist an activity-level revision delta keyed by Horizun stable uid."""
    counts = {"added": 0, "removed": 0, "updated": 0}
    if revision <= 1 or not before_rows:
        return counts

    def keyed(rows):
        return {str(r.get("uid")): r for r in rows if r.get("uid") is not None}

    before = keyed(before_rows)
    after = keyed(after_rows)
    db.ex("DELETE FROM schedule_revision_changes WHERE snapshot_id=?", [snapshot_id])

    def slim(r):
        if not r:
            return None
        return {"uid": r.get("uid"), **{k: r.get(k) for k in _REVISION_FIELDS}}

    for key in sorted(set(before) | set(after), key=lambda x: (len(x), x)):
        old, new = before.get(key), after.get(key)
        if old is None:
            change_type, changed = "added", list(_REVISION_FIELDS)
            row = new
        elif new is None:
            change_type, changed = "removed", list(_REVISION_FIELDS)
            row = old
        else:
            changed = [k for k in _REVISION_FIELDS if old.get(k) != new.get(k)]
            if not changed:
                continue
            change_type, row = "updated", new
        counts[change_type] += 1
        db.insert("schedule_revision_changes", {
            "project_id": project_id, "snapshot_id": snapshot_id,
            "revision": revision, "activity_uid": row.get("uid"),
            "display_id": row.get("display_id"), "activity_name": row.get("name"),
            "change_type": change_type, "changed_fields_json": db.jdumps(changed),
            "before_json": db.jdumps(slim(old)) if old else None,
            "after_json": db.jdumps(slim(new)) if new else None,
        })
    return counts


def _ev_rows(res: dict):
    p = res.get("project")
    if isinstance(p, dict):
        yield p, "project", None
    for b in res.get("byBranch") or []:
        if isinstance(b, dict):
            yield b, "branch", b.get("label")


def _s(v: Any) -> str | None:
    return None if v is None else str(v)


def _slim(a: dict) -> dict:
    """Keep the analysis summary small; detail already lives in tables."""
    out = {}
    for k, v in (a or {}).items():
        if isinstance(v, dict):
            out[k] = {kk: vv for kk, vv in v.items() if not isinstance(vv, list)}
            lists = {kk: len(vv) for kk, vv in v.items() if isinstance(vv, list)}
            if lists:
                out[k]["_counts"] = lists
        elif isinstance(v, list):
            out[k] = {"_count": len(v)}
        else:
            out[k] = v
    return out


def _daydiff(a: Any, b: Any) -> float | None:
    from datetime import datetime
    if not a or not b:
        return None
    try:
        da = datetime.fromisoformat(str(a).replace("Z", ""))
        dbb = datetime.fromisoformat(str(b).replace("Z", ""))
        return round((da - dbb).total_seconds() / 86400.0, 2)
    except Exception:
        return None


def _baseline_finish(rows: list) -> str | None:
    vals = [r["baseline_finish"] for r in rows if r.get("baseline_finish")]
    return _iso(max(vals)) if vals else None


def _health_score(qa: dict) -> float | None:
    checks = qa.get("checks")
    if not checks:
        return None
    passed = qa.get("passed") or 0
    not_evaluated = qa.get("notEvaluated")
    if not_evaluated is None:
        not_evaluated = qa.get("not_evaluated") or 0
    evaluated = max(0, int(checks) - int(not_evaluated or 0))
    if not evaluated:
        return None
    # A check that cannot be evaluated is reported separately; it must never
    # count as a pass, but it also must not depress the pass rate as though it
    # had failed.
    return round(100.0 * passed / evaluated, 1)


_QA_TITLES = {
    "dcma_01_logic": "Missing logic",
    "dcma_02_leads": "Leads (negative lag)",
    "dcma_03_lags": "Lags",
    "dcma_04_relationship_types": "Relationship types",
    "dcma_05_hard_constraints": "Hard constraints",
    "dcma_06_high_float": "High float",
    "dcma_07_negative_float": "Negative float",
    "dcma_08_high_duration": "High duration",
    "dcma_09_invalid_dates": "Invalid dates",
    "dcma_10_resources": "Unresourced work",
    "dcma_11_missed_tasks": "Missed baseline tasks",
    "dcma_12_critical_path_test": "Critical path test",
    "dcma_13_cpli": "Critical path length index",
    "dcma_14_bei": "Baseline execution index",
}


def _qa_title(rule: Any) -> str:
    if not rule:
        return "Schedule check"
    return _QA_TITLES.get(str(rule), str(rule).replace("_", " ").title())


def _qa_category(rule: Any) -> str:
    r = str(rule or "")
    if r.startswith("dcma"):
        return "DCMA 14-point"
    return "Horizun rule"


def _build_wbs(project_id: str, snapshot_id: str, rows: list, by_uid: dict,
               source: dict | None = None) -> None:
    """Persist WBS hierarchy without confusing WBS nodes with activities.

    For XER, PROJWBS is authoritative for hierarchy. A TASK whose activity type
    is WBS Summary remains a real activity, but a PROJWBS row is never counted as
    an activity. Other formats retain the adapter-derived summary fallback.
    """
    db.ex("DELETE FROM wbs_nodes WHERE project_id=?", [project_id])

    source_nodes = (source or {}).get("wbs_nodes") or []
    task_to_wbs = (source or {}).get("task_to_wbs") or {}
    if source_nodes and task_to_wbs:
        nodes_by_id = {str(n.get("wbs_id")): n for n in source_nodes
                       if n.get("wbs_id") is not None}
        children: dict[str, list[str]] = {}
        for wid, n in nodes_by_id.items():
            parent = str(n.get("parent_wbs_id") or "")
            if parent:
                children.setdefault(parent, []).append(wid)

        path_memo: dict[str, list[str]] = {}
        def wbs_path_parts(wid: str, trail: set[str] | None = None) -> list[str]:
            if wid in path_memo: return path_memo[wid]
            trail=set(trail or ())
            if wid in trail: return []
            trail.add(wid)
            n=nodes_by_id.get(wid) or {}
            parent=str(n.get("parent_wbs_id") or "")
            prefix=wbs_path_parts(parent,trail) if parent and parent in nodes_by_id else []
            label=str(n.get("name") or n.get("code") or wid)
            path_memo[wid]=prefix+[label]
            return path_memo[wid]

        def mapped_wbs_id(r: dict) -> str:
            # XER source identity is often Activity ID while Horizun uid is an
            # internal runtime identity.  Try both; never silently discard WBS.
            return str(task_to_wbs.get(str(r.get("uid"))) or
                       task_to_wbs.get(str(r.get("display_id"))) or "")

        memo_desc: dict[str, set[str]] = {}
        def descendants(wid: str, trail: set[str] | None = None) -> set[str]:
            if wid in memo_desc:
                return memo_desc[wid]
            trail = set(trail or ())
            if wid in trail:
                return {wid}
            trail.add(wid)
            out = {wid}
            for child in children.get(wid, []):
                out.update(descendants(child, trail))
            memo_desc[wid] = out
            return out

        # Rollups intentionally exclude WBS Summary activities from the workload
        # aggregates to avoid double-counting; they remain visible as activities.
        leaf_rows = [r for r in rows if not r.get("is_summary")]
        for wid, n in nodes_by_id.items():
            covered = descendants(wid)
            kids = [r for r in leaf_rows if mapped_wbs_id(r) in covered]
            starts = [k["start"] for k in kids if k.get("start")]
            finishes = [k["finish"] for k in kids if k.get("finish")]
            tot = sum((k.get("duration_days") or 1) for k in kids) or 1
            pc = (sum((k.get("percent_complete") or 0) *
                      (k.get("duration_days") or 1) for k in kids) / tot) if kids else 0
            db.insert("wbs_nodes", {
                "project_id": project_id, "snapshot_id": snapshot_id,
                "code": n.get("code") or wid, "name": n.get("name") or wid,
                "parent_code": n.get("parent_code"), "level": n.get("level") or 1,
                "uid": int(wid) if wid.isdigit() else None,
                "start": min(starts) if starts else None,
                "finish": max(finishes) if finishes else None,
                "percent_complete": round(pc, 1),
                "activity_count": len(kids),
                "critical_count": (sum(1 for k in kids if k.get("critical"))
                                   if (source or {}).get("criticality_available") else None),
                "late_count": (sum(1 for k in kids if k.get("status") != "complete" and
                                  k.get("finish") and (source or {}).get("data_date") and
                                  _iso(k.get("finish")) < _iso((source or {}).get("data_date")))
                               if (source or {}).get("data_date") else None),
                "provenance": ("SOURCE_FILE" if (source or {}).get("format") in
                               ("csv", "tsv", "xlsx", "xlsm") else "MCP_FACT"),
            })
        for r in rows:
            wid=mapped_wbs_id(r)
            n=nodes_by_id.get(wid) or {}
            parts=wbs_path_parts(wid) if wid else []
            code=n.get("code") or r.get("wbs")
            patch={"wbs_name": n.get("name") or (parts[-1] if parts else None),
                   "wbs_path": " > ".join(parts) if parts else None}
            if not r.get("wbs") and code: patch["wbs"]=code
            db.update("activities", r["id"], patch)
            r.update({k:v for k,v in patch.items() if v is not None})
        return

    # Non-XER / adapter fallback: summary rows describe the hierarchy.
    summaries = [r for r in rows if r["is_summary"]]
    leaves = [r for r in rows if not r["is_summary"]]
    for s in summaries:
        code = s.get("wbs") or ""
        kids = [l for l in leaves
                if (l.get("wbs") or "").startswith(code + ".") or
                l.get("parent_uid") == s["uid"]]
        if not kids:
            kids = [l for l in leaves if l.get("parent_uid") == s["uid"]]
        parent = None
        if code and "." in code:
            parent = code.rsplit(".", 1)[0]
        starts = [k["start"] for k in kids if k.get("start")]
        finishes = [k["finish"] for k in kids if k.get("finish")]
        tot = sum((k.get("duration_days") or 1) for k in kids) or 1
        pc = sum((k.get("percent_complete") or 0) * (k.get("duration_days") or 1)
                 for k in kids) / tot
        db.insert("wbs_nodes", {
            "project_id": project_id, "snapshot_id": snapshot_id,
            "code": code or str(s["uid"]), "name": s["name"],
            "parent_code": parent, "level": s.get("outline_level") or 1,
            "uid": s["uid"],
            "start": min(starts) if starts else s.get("start"),
            "finish": max(finishes) if finishes else s.get("finish"),
            "percent_complete": round(pc, 1),
            "activity_count": len(kids),
            "critical_count": sum(1 for k in kids if k["critical"]),
            "late_count": sum(1 for k in kids
                              if (k.get("finish_variance_days") or 0) > 0),
            "provenance": "MCP_FACT",
        })

    # Resolve readable paths for fallback formats from the WBS code hierarchy.
    nodes={str(x.get("code") or ""):x for x in db.q("SELECT code,name,parent_code FROM wbs_nodes WHERE project_id=?",[project_id])}
    def parts(code: str) -> list[str]:
        out=[]; seen=set(); cur=str(code or "")
        while cur and cur not in seen:
            seen.add(cur); n=nodes.get(cur)
            if n:
                out.append(str(n.get("name") or cur)); cur=str(n.get("parent_code") or "")
            elif "." in cur:
                out.append(cur.rsplit(".",1)[-1]); cur=cur.rsplit(".",1)[0]
            else:
                out.append(cur); break
        return list(reversed(out))
    for r in rows:
        ps=parts(str(r.get("wbs") or ""))
        patch={"wbs_name": ps[-1] if ps else None, "wbs_path": " > ".join(ps) if ps else None}
        db.update("activities",r["id"],patch); r.update({k:v for k,v in patch.items() if v is not None})


def _build_eps(project_id: str, info: dict, path: str) -> None:
    """spec 17: only store EPS when the source genuinely carries one."""
    db.ex("DELETE FROM eps_nodes WHERE project_id=?", [project_id])
    ext = os.path.splitext(path)[1].lower()
    eps = info.get("eps") or info.get("epsNodes")
    if isinstance(eps, list) and eps:
        for n in eps:
            db.insert("eps_nodes", {
                "project_id": project_id, "code": n.get("code"), "name": n.get("name"),
                "parent_code": n.get("parentCode"), "level": n.get("level"),
                "source": "primavera", "provenance": "MCP_FACT",
            })
        return
    if ext in (".xer", ".pmxml"):
        # Primavera source but no EPS surfaced by the runtime - say so, invent nothing.
        return
    return
