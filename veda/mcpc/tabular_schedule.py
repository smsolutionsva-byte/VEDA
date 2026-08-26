"""Conservative tabular schedule detection + MSPDI adaptation.

CSV/XLSX project schedules are common operator interchange formats. Horizun owns
schedule machinery, so VEDA converts a confidently schedule-shaped table to a
minimal Microsoft Project XML interchange file before opening it in Horizun.
The original file remains immutable and authoritative for provenance.
"""
from __future__ import annotations

import csv
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from xml.etree.ElementTree import Element, SubElement, ElementTree, register_namespace

SUPPORTED = {".csv", ".tsv", ".xlsx", ".xlsm"}

ALIASES = {
    "id": {"id", "uid", "unique id", "unique_id", "activity id", "activity_id", "activity code", "activity_code", "task id", "task_id"},
    "name": {"name", "task name", "task_name", "activity name", "activity_name", "description", "activity description", "activity_description"},
    "start": {"start", "start date", "start_date", "planned start", "planned_start", "baseline start", "baseline_start", "target start", "target_start"},
    "finish": {"finish", "finish date", "finish_date", "end", "end date", "end_date", "planned finish", "planned_finish", "baseline finish", "baseline_finish", "target finish", "target_finish"},
    "actual_start": {"actual start", "actual_start", "actualstart"},
    "actual_finish": {"actual finish", "actual_finish", "actualfinish"},
    "pct": {"% complete", "percent complete", "percent_complete", "pct complete", "pct_complete", "progress", "physical %", "physical_percent"},
    "wbs": {"wbs", "wbs path", "wbs_path", "outline number", "outline_number", "outline", "parent wbs", "parent_wbs"},
    "level": {"outline level", "outline_level", "level", "wbs level", "wbs_level"},
    "pred": {"predecessors", "predecessor", "pred", "preds", "predecessor ids", "predecessor_ids"},
    "summary": {"summary", "is summary", "is_summary"},
    "milestone": {"milestone", "is milestone", "is_milestone"},
    "duration": {"duration", "duration days", "duration_days"},
    "data_date": {"data date", "data_date", "status date", "status_date", "as of", "as_of"},
    "forecast_finish": {"forecast finish", "forecast_finish", "current finish", "current_finish", "remaining early finish", "remaining_early_finish"},
}

NEGATIVE_NAME_HINTS = (
    "milestone_register", "milestone register", "resource_allocation", "resource allocation",
    "calendar_def", "calendar definition", "dictionary", "earned_value", "earned value",
    "delay_analysis", "delay analysis", "import_template", "import template", "update_template",
)
SCHEDULE_NAME_HINTS = ("schedule", "programme", "program", "baseline", "master plan", "lookahead", "look-ahead")
ALT_HINTS = ("extended", "extension", "recovery", "alternate", "alternative", "draft", "what-if", "whatif")


def _norm(v: Any) -> str:
    s = str(v or "").strip().casefold().replace("\n", " ")
    s = re.sub(r"[\-_]+", "_", s)
    s = re.sub(r"\s+", " ", s)
    return s


def _read_tables(path: str, ext: str) -> list[tuple[str, list[str], list[list[Any]]]]:
    ext = ext.lower()
    if ext in (".csv", ".tsv"):
        with open(path, "r", encoding="utf-8-sig", errors="replace", newline="") as f:
            sample = f.read(8192); f.seek(0)
            delim = "\t" if ext == ".tsv" else ","
            if ext == ".csv":
                try: delim = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
                except Exception: pass
            rows = list(csv.reader(f, delimiter=delim))
        if not rows: return []
        return [("(csv)", rows[0], rows[1:])]
    if ext in (".xlsx", ".xlsm"):
        from openpyxl import load_workbook
        wb = load_workbook(path, read_only=True, data_only=True)
        out = []
        try:
            for ws in wb.worksheets:
                rows = []
                for r in ws.iter_rows(values_only=True):
                    vals = list(r)
                    if any(str(v or "").strip() for v in vals): rows.append(vals)
                    if len(rows) >= 100000: break
                if rows: out.append((ws.title, [str(v or "") for v in rows[0]], rows[1:]))
        finally:
            wb.close()
        return out
    return []


def _mapping(headers: list[Any]) -> dict[str, int]:
    hs = [_norm(h) for h in headers]
    out: dict[str, int] = {}
    for role, aliases in ALIASES.items():
        norms = {_norm(a) for a in aliases}
        for i, h in enumerate(hs):
            if h in norms:
                out[role] = i; break
    return out


def inspect(path: str, relative_path: str | None = None) -> dict:
    ext = os.path.splitext(path)[1].lower()
    if ext not in SUPPORTED:
        return {"candidate": False, "format": ext.lstrip(".")}
    display = (relative_path or os.path.basename(path)).replace("\\", "/")
    lowname = display.casefold()
    if any(x in lowname for x in NEGATIVE_NAME_HINTS):
        return {"candidate": False, "format": ext.lstrip("."), "reason": "known supporting/reference table"}
    best = None
    for sheet, headers, rows in _read_tables(path, ext):
        mp = _mapping(headers)
        core = sum(1 for k in ("id", "name", "start", "finish") if k in mp)
        dates = sum(1 for k in ("start", "finish") if k in mp)
        structure = sum(1 for k in ("wbs", "level", "pred") if k in mp)
        name_hint = any(x in lowname or x in sheet.casefold() for x in SCHEDULE_NAME_HINTS)
        # High precision: all four core roles, or a named schedule with name + both dates
        # and at least one structural schedule field. Never classify from filename alone.
        candidate = core == 4 or (name_hint and "name" in mp and dates == 2 and structure >= 1)
        score = core * 20 + dates * 5 + structure * 4 + (8 if name_hint else 0) + min(len(rows), 200) / 200
        rec = {"candidate": candidate, "format": ext.lstrip("."), "sheet": sheet,
               "headers": headers, "mapping": mp, "row_count": len(rows), "score": score,
               "relative_path": display, "alternate_hint": any(x in lowname for x in ALT_HINTS)}
        if best is None or rec["score"] > best["score"]: best = rec
    return best or {"candidate": False, "format": ext.lstrip("."), "reason": "empty tabular file"}


def _parse_dt(v: Any) -> datetime | None:
    if isinstance(v, datetime): return v
    s = str(v or "").strip()
    if not s: return None
    s2 = s.replace("Z", "+00:00")
    for cand in (s2, s2.replace(" ", "T", 1)):
        try: return datetime.fromisoformat(cand).replace(tzinfo=None)
        except Exception: pass
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%m/%d/%Y", "%d-%b-%Y", "%d-%b-%y"):
        try: return datetime.strptime(s, fmt)
        except Exception: pass
    return None


def _val(row: list[Any], mp: dict[str, int], role: str) -> Any:
    i = mp.get(role)
    return row[i] if i is not None and i < len(row) else None


def _bool(v: Any) -> bool:
    return str(v or "").strip().casefold() in {"1", "true", "yes", "y", "x"}


def _pct(v: Any) -> int:
    try:
        x = float(str(v or "0").strip().replace("%", ""))
        if 0 <= x <= 1 and "%" not in str(v): x *= 100
        return max(0, min(100, round(x)))
    except Exception: return 0


def _pred_tokens(v: Any) -> list[str]:
    s = str(v or "").strip()
    if not s: return []
    out = []
    for tok in re.split(r"[;,|]+", s):
        tok = tok.strip()
        # MSP-style tokens can be 12FS+2d; retain only the identifier prefix.
        tok = re.sub(r"(?i)(FS|SS|FF|SF).*$", "", tok).strip()
        if tok: out.append(tok)
    return out


def prepare_mspdi(path: str, cache_dir: str | None = None, relative_path: str | None = None) -> tuple[str, dict]:
    meta = inspect(path, relative_path)
    if not meta.get("candidate"):
        raise ValueError("tabular file is not confidently schedule-shaped")
    ext = os.path.splitext(path)[1].lower()
    tables = _read_tables(path, ext)
    table = next((x for x in tables if x[0] == meta.get("sheet")), tables[0])
    sheet, headers, rows = table
    mp = _mapping(headers)
    clean_rows = [r for r in rows if str(_val(r, mp, "name") or "").strip()]
    ids = []
    for i, r in enumerate(clean_rows, 1):
        sid = str(_val(r, mp, "id") or i).strip()
        ids.append(sid)
    uid_by_id = {sid: i + 1 for i, sid in enumerate(ids)}

    register_namespace("", "http://schemas.microsoft.com/project")
    ns = "{http://schemas.microsoft.com/project}"
    root = Element(ns + "Project")
    SubElement(root, ns + "SaveVersion").text = "14"
    SubElement(root, ns + "Name").text = os.path.basename(path)
    dts = []
    for r in clean_rows:
        for role in ("start", "finish"):
            d = _parse_dt(_val(r, mp, role))
            if d: dts.append(d)
    if dts:
        SubElement(root, ns + "StartDate").text = min(dts).isoformat(timespec="seconds")
        SubElement(root, ns + "FinishDate").text = max(dts).isoformat(timespec="seconds")
    SubElement(root, ns + "ScheduleFromStart").text = "1"
    tasks_el = SubElement(root, ns + "Tasks")
    by_uid = {}
    task_by_id = {}
    task_to_wbs = {}
    wbs_paths: set[str] = set()
    planned_starts: list[datetime] = []
    planned_finishes: list[datetime] = []
    forecast_finishes: list[datetime] = []
    data_dates: list[datetime] = []
    for idx, r in enumerate(clean_rows, 1):
        sid = ids[idx - 1]; uid = uid_by_id[sid]
        name = str(_val(r, mp, "name") or sid).strip()
        start = _parse_dt(_val(r, mp, "start")); finish = _parse_dt(_val(r, mp, "finish"))
        actual_start = _parse_dt(_val(r, mp, "actual_start")); actual_finish = _parse_dt(_val(r, mp, "actual_finish"))
        forecast_finish = _parse_dt(_val(r, mp, "forecast_finish"))
        data_date = _parse_dt(_val(r, mp, "data_date"))
        if start: planned_starts.append(start)
        if finish: planned_finishes.append(finish)
        if forecast_finish: forecast_finishes.append(forecast_finish)
        if data_date: data_dates.append(data_date)
        wbs = str(_val(r, mp, "wbs") or "").strip()
        try: level = int(float(str(_val(r, mp, "level") or "")))
        except Exception: level = max(1, len([x for x in re.split(r"[./\\>]", wbs) if x])) if wbs else 1
        milestone = _bool(_val(r, mp, "milestone")) or bool(start and finish and start == finish)
        summary = _bool(_val(r, mp, "summary"))
        t = SubElement(tasks_el, ns + "Task")
        for tag, value in (("UID", uid), ("ID", idx), ("Name", name), ("Type", 1), ("IsNull", 0),
                           ("WBS", wbs or sid), ("OutlineNumber", wbs or str(idx)), ("OutlineLevel", level),
                           ("Milestone", 1 if milestone else 0), ("Summary", 1 if summary else 0),
                           ("PercentComplete", _pct(_val(r, mp, "pct")))):
            SubElement(t, ns + tag).text = str(value)
        if start: SubElement(t, ns + "Start").text = start.isoformat(timespec="seconds")
        if finish: SubElement(t, ns + "Finish").text = finish.isoformat(timespec="seconds")
        if actual_start: SubElement(t, ns + "ActualStart").text = actual_start.isoformat(timespec="seconds")
        if actual_finish: SubElement(t, ns + "ActualFinish").text = actual_finish.isoformat(timespec="seconds")
        if start and finish:
            hours = max(0.0, (finish - start).total_seconds() / 3600.0)
            SubElement(t, ns + "Duration").text = f"PT{hours:.3f}H0M0S"
            SubElement(t, ns + "DurationFormat").text = "7"
        for pred in _pred_tokens(_val(r, mp, "pred")):
            puid = uid_by_id.get(pred)
            if not puid: continue
            pl = SubElement(t, ns + "PredecessorLink")
            SubElement(pl, ns + "PredecessorUID").text = str(puid)
            SubElement(pl, ns + "Type").text = "1"  # finish-to-start
            SubElement(pl, ns + "CrossProject").text = "0"
            SubElement(pl, ns + "LinkLag").text = "0"
            SubElement(pl, ns + "LagFormat").text = "7"
        by_uid[str(uid)] = {"source_id": sid, "name": name, "wbs": wbs, "outline_level": level,
                            "summary": summary, "milestone": milestone}
        task_by_id[str(uid)] = {"task_id": str(uid), "source_id": sid, "task_type": "TT_WBS" if summary else ("TT_Mile" if milestone else "TT_Task"),
                                "target_start_date": start.isoformat(sep=" ") if start else "",
                                "target_end_date": finish.isoformat(sep=" ") if finish else ""}
        if wbs:
            wbs_paths.add(wbs)
            task_to_wbs[str(uid)] = wbs
    # Build a stable path-based WBS manifest. Prefix paths are included even if
    # no activity sits directly on the parent node.
    all_wbs: set[str] = set()
    for path_value in wbs_paths:
        parts = [x for x in re.split(r"[./\\>]", path_value) if x]
        for i in range(1, len(parts)+1): all_wbs.add(".".join(parts[:i]))
    wbs_nodes = []
    for code in sorted(all_wbs, key=lambda x: (x.count("."), x)):
        parent = code.rsplit(".", 1)[0] if "." in code else None
        wbs_nodes.append({"wbs_id": code, "parent_wbs_id": parent, "code": code,
                          "short_code": code.rsplit(".",1)[-1], "name": code.rsplit(".",1)[-1],
                          "parent_code": parent, "level": code.count(".")+1, "project_node": False})
    outdir = Path(cache_dir or (str(Path(path).parent / ".veda-adapted")))
    outdir.mkdir(parents=True, exist_ok=True)
    out = outdir / (Path(path).stem + ".mspdi.xml")
    ElementTree(root).write(out, encoding="utf-8", xml_declaration=True)
    meta.update({"canonical_path": str(out), "by_uid": by_uid, "activity_count": len(clean_rows),
                 "source_guarded": True, "task_ids": list(by_uid), "task_by_id": task_by_id,
                 "task_to_wbs": task_to_wbs, "wbs_nodes": wbs_nodes, "wbs_count": len(wbs_nodes),
                 "planned_start": min(planned_starts).date().isoformat() if planned_starts else None,
                 "planned_finish": max(planned_finishes).date().isoformat() if planned_finishes else None,
                 "forecast_finish": max(forecast_finishes).date().isoformat() if forecast_finishes else None,
                 "forecast_basis": "tabular forecast/current finish column" if forecast_finishes else "not available in source",
                 "data_date": max(data_dates).date().isoformat() if data_dates else None,
                 "baseline_assigned": False, "baseline_basis": "tabular planned/reference dates",
                 "format": ext.lstrip("."), "project_resolution": "single_tabular_schedule"})
    return str(out), meta
