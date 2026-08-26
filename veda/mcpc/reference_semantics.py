"""Read-only consistency checks between a selected tabular schedule and nearby
project-control reference tables.

These checks never coerce names or mutate the schedule.  They only report exact
key coverage so a planner can resolve aliases deliberately instead of VEDA
silently guessing (for example ``6-Day`` vs ``6_Day_Standard``).
"""
from __future__ import annotations

import csv
import os
import re
from typing import Any

from .. import db


REFERENCE_FILES = {
    "activity_code_dictionary.csv": "activity_codes",
    "calendar_definitions.csv": "calendars",
    "milestone_register.csv": "milestones",
    "resource_allocation_master.csv": "resources",
    "wbs_dictionary.csv": "wbs",
}


def _read_csv(path: str) -> list[dict[str, str]]:
    try:
        with open(path, "r", encoding="utf-8-sig", errors="replace", newline="") as f:
            return [dict(r) for r in csv.DictReader(f)]
    except Exception:
        return []


def _split_ids(value: Any) -> list[str]:
    return [x.strip() for x in re.split(r"[;,|]+", str(value or "")) if x.strip()]


def inspect_project_references(project_id: str, source: dict | None) -> dict:
    """Return exact, source-grounded diagnostics for known control tables."""
    source = source or {}
    rows = db.q(
        "SELECT filename, relative_path, stored_path FROM files "
        "WHERE project_id=? AND security_state='clean'", [project_id])
    by_name: dict[str, str] = {}
    for row in rows:
        path = row.get("stored_path")
        if not path or not os.path.isfile(path):
            continue
        base = os.path.basename(str(row.get("filename") or path)).casefold()
        if base in REFERENCE_FILES:
            by_name[base] = path

    parsed = {kind: _read_csv(path) for name, kind in REFERENCE_FILES.items()
              if (path := by_name.get(name))}

    task_by_id = source.get("task_by_id") or {}
    source_activity_ids = {str(v.get("source_id") or "").strip()
                           for v in task_by_id.values() if str(v.get("source_id") or "").strip()}
    resource_labels = {str(x).strip() for x in (source.get("resource_labels") or []) if str(x).strip()}
    calendar_labels = {str(x).strip() for x in (source.get("calendar_labels") or []) if str(x).strip()}

    resource_rows = parsed.get("resources", [])
    resource_names = {str(r.get("Resource_Name") or "").strip() for r in resource_rows
                      if str(r.get("Resource_Name") or "").strip()}
    resource_ids = {str(r.get("Resource_ID") or "").strip() for r in resource_rows
                    if str(r.get("Resource_ID") or "").strip()}
    resource_exact = sorted(resource_labels & (resource_names | resource_ids))
    resource_unresolved = sorted(resource_labels - (resource_names | resource_ids))

    cal_rows = parsed.get("calendars", [])
    calendar_names = {str(r.get("Calendar_Name") or "").strip() for r in cal_rows
                      if str(r.get("Calendar_Name") or "").strip()}
    calendar_exact = sorted(calendar_labels & calendar_names)
    calendar_unresolved = sorted(calendar_labels - calendar_names)

    ms_rows = parsed.get("milestones", [])
    linked_ids: list[str] = []
    for r in ms_rows:
        linked_ids.extend(_split_ids(r.get("Linked_Activity_IDs")))
    # Treat repeated links as separate register references for row-level coverage,
    # but also expose the unique set for diagnostics.
    linked_unique = sorted(set(linked_ids))
    linked_resolved = sorted(set(linked_unique) & source_activity_ids)
    linked_unresolved = sorted(set(linked_unique) - source_activity_ids)

    wbs_rows = parsed.get("wbs", [])
    code_rows = parsed.get("activity_codes", [])
    reference_record_count = sum(len(v) for v in parsed.values())

    warnings: list[dict[str, Any]] = []
    if resource_unresolved:
        warnings.append({
            "code": "RESOURCE_MASTER_UNRESOLVED",
            "severity": "warning",
            "summary": (f"{len(resource_unresolved)} of {len(resource_labels)} unique schedule resource "
                        "labels do not exactly match the resource master; alias/mapping review required."),
            "values": resource_unresolved,
        })
    if calendar_unresolved:
        warnings.append({
            "code": "CALENDAR_MASTER_UNRESOLVED",
            "severity": "warning",
            "summary": (f"{len(calendar_unresolved)} schedule calendar label(s) do not exactly match "
                        "calendar_definitions.csv; calendar mapping must be confirmed before relying on "
                        "calendar-sensitive CPM calculations."),
            "values": calendar_unresolved,
        })
    if linked_unresolved:
        warnings.append({
            "code": "MILESTONE_LINK_UNRESOLVED",
            "severity": "warning",
            "summary": (f"{len(linked_unresolved)} of {len(linked_unique)} unique milestone-register "
                        "activity links do not resolve to the selected schedule revision."),
            "values": linked_unresolved,
        })
    if wbs_rows and int(source.get("wbs_count") or 0) != len(wbs_rows):
        warnings.append({
            "code": "WBS_REFERENCE_COVERAGE_DIFFERS",
            "severity": "info",
            "summary": (f"The selected schedule contains {int(source.get('wbs_count') or 0)} active WBS "
                        f"nodes while WBS_dictionary.csv contains {len(wbs_rows)} reference definitions; "
                        "the sets are retained separately rather than merged by name."),
            "values": [],
        })

    return {
        "reference_files_found": sorted(by_name),
        "reference_record_count": reference_record_count,
        "activity_code_count": len(code_rows),
        "calendar_definition_count": len(cal_rows),
        "milestone_register_count": len(ms_rows),
        "resource_master_count": len(resource_rows),
        "wbs_dictionary_count": len(wbs_rows),
        "resource_schedule_label_count": len(resource_labels),
        "resource_exact_match_count": len(resource_exact),
        "resource_unresolved_count": len(resource_unresolved),
        "resource_exact_matches": resource_exact,
        "resource_unresolved_labels": resource_unresolved,
        "calendar_schedule_label_count": len(calendar_labels),
        "calendar_exact_match_count": len(calendar_exact),
        "calendar_unresolved_count": len(calendar_unresolved),
        "calendar_exact_matches": calendar_exact,
        "calendar_unresolved_labels": calendar_unresolved,
        "milestone_link_count": len(linked_unique),
        "milestone_links_resolved_count": len(linked_resolved),
        "milestone_links_unresolved_count": len(linked_unresolved),
        "milestone_links_resolved": linked_resolved,
        "milestone_links_unresolved": linked_unresolved,
        "warnings": warnings,
    }


__all__ = ["inspect_project_references"]
