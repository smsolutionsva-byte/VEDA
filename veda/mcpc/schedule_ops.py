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

from .. import db
from .client import McpError, horizun

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

    handle = open_schedule(schedule_path, "readonly", project_id, job_id)
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
    step("activities_loaded", str(len(tasks)) + " activities loaded")

    db.ex("DELETE FROM activities WHERE project_id=?", [project_id])
    act_rows = []
    by_uid = {}
    for t in tasks:
        uid = t.get("uid")
        if uid is None:
            continue
        by_uid[uid] = t
        pct = _num(t.get("percentComplete")) or 0.0
        actual_finish = t.get("actualFinish")
        if actual_finish:
            status = "complete"
        elif t.get("actualStart") or pct > 0:
            status = "in_progress"
        else:
            status = "not_started"
        bstart, bfin = t.get("baselineStart"), t.get("baselineFinish")
        act_rows.append({
            "id": db.new_id("act_"), "project_id": project_id,
            "snapshot_id": snapshot_id,
            "uid": uid, "display_id": str(t.get("id") or uid),
            "name": t.get("name"),
            "wbs": t.get("wbs"), "outline_level": t.get("outlineLevel"),
            "parent_uid": t.get("parentUid"),
            "is_summary": 1 if t.get("summary") else 0,
            "is_milestone": 1 if t.get("milestone") else 0,
            "status": status,
            "start": _dt(t.get("start")), "finish": _dt(t.get("finish")),
            "actual_start": _dt(t.get("actualStart")),
            "actual_finish": _dt(actual_finish),
            "early_start": _dt(t.get("earlyStart")),
            "early_finish": _dt(t.get("earlyFinish")),
            "late_start": _dt(t.get("lateStart")),
            "late_finish": _dt(t.get("lateFinish")),
            "duration_days": _dur_days(t.get("duration")),
            "remaining_days": _dur_days(t.get("remainingDuration")),
            "percent_complete": pct,
            "total_float_days": _num(t.get("totalFloatDays")),
            "free_float_days": _num(t.get("freeFloatDays")),
            "critical": 1 if t.get("critical") else 0,
            "calendar": t.get("calendar"),
            "constraint_type": t.get("constraintType"),
            "constraint_date": _dt(t.get("constraintDate")),
            "deadline": _dt(t.get("deadline")),
            "baseline_start": _dt(bstart), "baseline_finish": _dt(bfin),
            "baseline_duration_days": _dur_days(t.get("baselineDuration")),
            "cost": _num(t.get("cost")), "work_hours": _num(t.get("workHours")),
            "resource_names": t.get("resourceNames") or t.get("resources"),
            "custom_json": db.jdumps(t.get("custom")) if t.get("custom") else None,
            "notes": t.get("notes"),
            "provenance": "MCP_FACT",
        })

    for r in act_rows:
        bf, fin = r.get("baseline_finish"), r.get("finish")
        r["finish_variance_days"] = _daydiff(fin, bf)
        r["start_variance_days"] = _daydiff(r.get("start"), r.get("baseline_start"))
        if r.get("duration_days") is not None and \
           r.get("baseline_duration_days") is not None:
            r["duration_variance_days"] = round(
                r["duration_days"] - r["baseline_duration_days"], 2)
    for r in act_rows:
        db.insert("activities", r)

    # ---- relationships -------------------------------------------------
    links = page_all("links_query", {"handle": handle, "direction": "both"},
                     project_id=project_id, job_id=job_id)
    db.ex("DELETE FROM relationships WHERE project_id=?", [project_id])
    seen = set()
    for l in links:
        a, b = l.get("fromUid"), l.get("toUid")
        if a is None or b is None or (a, b, l.get("type")) in seen:
            continue
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
    resources = page_all("resources_query",
                         {"handle": handle, "includeAssignments": True},
                         project_id=project_id, job_id=job_id, limit=200)
    db.ex("DELETE FROM resources WHERE project_id=?", [project_id])
    db.ex("DELETE FROM assignments WHERE project_id=?", [project_id])
    for r in resources:
        assigns = r.get("assignments") or []
        db.insert("resources", {
            "project_id": project_id, "snapshot_id": snapshot_id,
            "uid": r.get("uid"), "name": r.get("name"), "type": r.get("type"),
            "calendar": r.get("calendar"), "max_units": _num(r.get("maxUnits")),
            "standard_rate": _num(r.get("standardRate")),
            "work_hours": _num(r.get("workHours")), "cost": _num(r.get("cost")),
            "overallocated": 1 if r.get("overallocated") else 0,
            "peak_units": _num(r.get("peakUnits")),
            "assignment_count": len(assigns),
            "provenance": "MCP_FACT",
        })
        for a in assigns:
            db.insert("assignments", {
                "project_id": project_id, "snapshot_id": snapshot_id,
                "task_uid": a.get("taskUid"), "resource_uid": a.get("resourceUid"),
                "task_name": a.get("taskName"), "resource_name": a.get("resourceName"),
                "units": _num(a.get("units")),
                "work_hours": _num(a.get("workHours")),
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
            "forecast_date": _dt(m.get("finish")) or r["finish"],
            "actual_date": r["actual_finish"], "deadline": r["deadline"],
            "variance_days": _num(m.get("slipDays")) if m.get("slipDays") is not None
            else r.get("finish_variance_days"),
            "status": m.get("status") or r["status"],
            "critical": r["critical"],
            "total_float_days": r["total_float_days"],
            "provenance": "MCP_FACT",
        })

    # ---- WBS rollup (spec 18) ------------------------------------------
    _build_wbs(project_id, snapshot_id, act_rows, by_uid)

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
                    "provenance": "MCP_FACT",
                })
            step("schedule_quality_assessed",
                 str(res.get("failed", 0)) + " of " + str(res.get("checks", 0)) +
                 " DCMA checks failed")

    # ---- baseline / earned value (spec 24, 28) -------------------------
    bc = {}
    ok, res = horizun.try_call("baseline_compare", {"handle": handle, "byBranch": True},
                               project_id=project_id, job_id=job_id, timeout=300)
    if ok and isinstance(res, dict) and res.get("baselinePresent"):
        bc = res
        db.ex("DELETE FROM earned_value WHERE project_id=?", [project_id])
        basis = "Horizun baseline_compare, measure=" + \
                str((res.get("project") or {}).get("measure", "unknown")) + \
                ", baseline " + str(res.get("baselineNumber", 0))
        for scope_row, scope, key in _ev_rows(res):
            db.insert("earned_value", {
                "project_id": project_id, "snapshot_id": snapshot_id,
                "scope": scope, "scope_key": key,
                "status_date": _iso(res.get("statusDate") or info.get("statusDate")),
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
    crit = sum(1 for r in leaves if r["critical"])
    status_date = _iso(info.get("statusDate"))
    late = sum(1 for r in leaves
               if r["status"] != "complete" and status_date and r.get("finish")
               and _iso(r["finish"]) < status_date)
    pct = (bc.get("project") or {})
    overall = None
    if pct.get("bac"):
        overall = round(100.0 * (_num(pct.get("bcwp")) or 0) / _num(pct["bac"]), 1)
    if overall is None and leaves:
        durs = [(r.get("duration_days") or 0) for r in leaves]
        tot = sum(durs) or len(leaves)
        overall = round(sum((r.get("percent_complete") or 0) *
                            ((r.get("duration_days") or 1)) for r in leaves) / (tot or 1), 1)

    db.insert("schedule_snapshots", {
        "id": snapshot_id, "project_id": project_id, "file_id": file_id,
        "job_id": job_id, "revision": revision, "source_path": schedule_path,
        "project_name": info.get("name") or info.get("title"),
        "data_date": status_date, "status_date": status_date,
        "planned_start": _iso(info.get("startDate")),
        "planned_finish": _iso(info.get("finishDate")),
        "forecast_finish": _iso(info.get("finishDate")),
        "baseline_finish": _baseline_finish(act_rows),
        "task_count": len(act_rows), "milestone_count": info.get("milestones"),
        "relationship_count": len(seen), "resource_count": len(resources),
        "critical_count": crit, "late_count": late,
        "percent_complete": overall,
        "health_score": _health_score(qa),
        "capabilities_json": db.jdumps(caps),
        "info_json": db.jdumps({"info": info, "analyze": _slim(analyze), "qa": {
            "checks": qa.get("checks"), "passed": qa.get("passed"),
            "failed": qa.get("failed"), "notEvaluated": qa.get("notEvaluated"),
            "notes": qa.get("notes"),
        }, "baseline": {"present": bool(bc), "project": bc.get("project")}}),
        "is_current": 1,
    })

    revision_changes = _record_revision_changes(
        project_id, snapshot_id, revision, previous_activities, act_rows)
    if revision > 1:
        step("schedule_revision_compared",
             str(revision_changes["added"]) + " added, " +
             str(revision_changes["removed"]) + " removed, " +
             str(revision_changes["updated"]) + " updated")

    return {
        "snapshot_id": snapshot_id, "revision": revision,
        "tasks": len(act_rows), "relationships": len(seen),
        "resources": len(resources), "milestones": info.get("milestones"),
        "critical": crit, "late": late,
        "qa_failed": qa.get("failed"), "qa_checks": qa.get("checks"),
        "baseline_present": bool(bc),
        "project_name": info.get("name"),
        "planned_start": _iso(info.get("startDate")),
        "forecast_finish": _iso(info.get("finishDate")),
        "status_date": status_date,
        "percent_complete": overall,
        "revision_changes": revision_changes,
    }


_REVISION_FIELDS = (
    "display_id", "name", "wbs", "parent_uid", "is_summary", "is_milestone",
    "status", "start", "finish", "actual_start", "actual_finish",
    "duration_days", "remaining_days", "percent_complete", "constraint_type",
    "constraint_date", "deadline", "baseline_start", "baseline_finish",
)


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
    return round(100.0 * passed / checks, 1)


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


def _build_wbs(project_id: str, snapshot_id: str, rows: list, by_uid: dict) -> None:
    db.ex("DELETE FROM wbs_nodes WHERE project_id=?", [project_id])
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
