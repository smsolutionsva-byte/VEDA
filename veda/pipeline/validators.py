"""Deterministic validators (spec 45).

Nothing the model infers becomes a stored association or a schedule change
until these rules have run. They are plain code with plain reasons, so a
reviewer can see exactly why something passed, warned or failed.

Each validator returns:
    {"name", "result": pass|warn|fail, "message", "detail"}
"""
from __future__ import annotations
import os

import re
from datetime import date, datetime, timedelta
from typing import Any

from .. import db

PASS, WARN, FAIL = "pass", "warn", "fail"

# Sources whose word carries different weight (spec 45: source trust).
SOURCE_TRUST = {
    "qaqc": 0.95, "ncr": 0.95, "ndt": 0.9, "welding_register": 0.9,
    "dpr": 0.8, "survey": 0.85, "material": 0.75, "site_report": 0.7,
    "instruction": 0.8, "chat": 0.35, "transcript": 0.4, "unknown": 0.5,
}


def _r(name: str, result: str, message: str, /, **detail) -> dict:
    # Positional-only: a check may legitimately carry detail keys called
    # "name" or "result", which would otherwise collide with these parameters.
    return {"name": name, "result": result, "message": message, "detail": detail}


def _d(v: Any):
    if not v:
        return None
    s = str(v).split("T")[0]
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def source_class(filename: str | None, description: str | None = None) -> str:
    blob = ((filename or "") + " " + (description or "")).lower()
    if "ncr" in blob or "qaqc" in blob or "qa_qc" in blob:
        return "ncr"
    if "ndt" in blob or "radiograph" in blob:
        return "ndt"
    if "weld" in blob and "register" in blob:
        return "welding_register"
    if "dpr" in blob or "daily" in blob:
        return "dpr"
    if "chat" in blob or "whatsapp" in blob:
        return "chat"
    if "transcript" in blob or "minutes" in blob:
        return "transcript"
    if "material" in blob or "mrn" in blob:
        return "material"
    if "instruction" in blob or "si_" in blob:
        return "instruction"
    if "report" in blob:
        return "site_report"
    if "survey" in blob:
        return "survey"
    return "unknown"


# ------------------------------------------------------- token helpers
_CH = re.compile(r"(\d{1,3})\s*\+\s*(\d{3})")


def chainage_values(text: str | None) -> list:
    """'12+400' -> 12400 metres. Returns every chainage found."""
    if not text:
        return []
    return [int(a) * 1000 + int(b) for a, b in _CH.findall(str(text))]


def chainage_window(text: str | None) -> tuple:
    """Extract a (low, high) window from an activity name such as
    'Spread A (CH 0+000 to 12+000)'."""
    vals = chainage_values(text)
    if len(vals) >= 2:
        return min(vals), max(vals)
    if len(vals) == 1:
        return vals[0], vals[0]
    return (None, None)


def location_tokens(text: str | None) -> set:
    if not text:
        return set()
    t = str(text).lower()
    out = set()
    for m in re.finditer(r"spread\s*([a-z0-9]+)", t):
        out.add("spread:" + m.group(1))
    for m in re.finditer(r"\b(ps-?\d+|sv-?\d+|mlv-?\d+)\b", t):
        out.add(m.group(1).replace("-", ""))
    for m in re.finditer(r"\b(section|zone|area|unit)\s*([a-z0-9]+)", t):
        out.add(m.group(1) + ":" + m.group(2))
    return out


DISCIPLINE_ALIASES = {
    "welding": {"weld", "welding", "fit-up", "fitup"},
    "ndt": {"ndt", "rt", "radiography", "radiograph", "aut", "ut", "mpi", "dpi"},
    "coating": {"coating", "coat", "wrapping", "fbe", "holiday"},
    "trenching": {"trench", "trenching", "excavation", "excavate"},
    "stringing": {"stringing", "string", "haul"},
    "bending": {"bending", "bend"},
    "lowering-in": {"lowering", "lower", "lowering-in"},
    "backfilling": {"backfill", "backfilling", "reinstatement"},
    "hydrotest": {"hydrotest", "hydro", "pressure test", "testing"},
    "civil": {"civil", "foundation", "concrete", "grading", "road"},
    "e&i": {"e&i", "electrical", "instrument", "instrumentation"},
    "hdd": {"hdd", "drilling", "bore", "crossing"},
    "tie-in": {"tie-in", "tie in", "golden weld"},
    "commissioning": {"commissioning", "precommissioning", "pre-commissioning"},
}


def discipline_key(text: str | None) -> str | None:
    if not text:
        return None
    t = str(text).lower()
    for key, words in DISCIPLINE_ALIASES.items():
        if any(w in t for w in words):
            return key
    return None


MAJOR_DISCIPLINE_ALIASES = {
    "instrumentation": {"instrumentation", "instrument", "loop check", "calibration", "transmitter", "analyzer", "junction box", "jb ", "pt-", "tt-", "lt-", "ft-"},
    "electrical": {"electrical", "cable", "mcc", "pcc", "switchgear", "transformer", "earthing", "grounding", "termination", "glanding"},
    "piping": {"piping", "pipe", "spool", "line ", "fit-up", "fitup", "weld", "hydrotest", "flushing", "tie-in", "isometric", " iso-"},
    "rotating_equipment": {"rotating", "pump", "compressor", "turbine", "fan", "blower", "alignment", "coupling"},
    "static_equipment": {"static equipment", "vessel", "column", "drum", "tank", "heat exchanger", "exchanger", "reactor"},
    "structural": {"structural", "steel structure", "structural steel", "platform", "pipe rack", "rack steel"},
    "civil": {"civil", "foundation", "concrete", "rebar", "reinforcement", "formwork", "shuttering", "excavation", "backfill", "grading", "road"},
    "hse": {"hse", "safety", "permit to work", "ptw", "toolbox talk", "incident", "near miss", "hazard", "scaffold inspection"},
    "commissioning": {"commissioning", "precommissioning", "pre-commissioning", "startup", "start-up"},
}


def major_discipline_key(text: str | None) -> str | None:
    if not text:
        return None
    t = " " + str(text).lower() + " "
    for key, words in MAJOR_DISCIPLINE_ALIASES.items():
        if any(w in t for w in words):
            return key
    return None


# =====================================================================
#  Evidence -> activity association validators
# =====================================================================
def validate_link(evidence: dict, activity: dict | None, *,
                  project_id: str, status_date: str | None = None,
                  all_links: list | None = None) -> dict:
    """Run the full validator suite for one candidate association."""
    checks: list = []

    # --- activity exists -------------------------------------------------
    if activity is None:
        checks.append(_r("activity_exists", FAIL,
                         "No activity with that uid exists in this project."))
        return _summarise(checks)
    checks.append(_r("activity_exists", PASS,
                     "Activity uid " + str(activity.get("uid")) + " exists.",
                     uid=activity.get("uid"), name=activity.get("name")))

    if activity.get("is_summary"):
        checks.append(_r("activity_is_leaf", WARN,
                         "Target is a summary/WBS row; evidence normally belongs "
                         "to a work activity."))

    # --- progress range ---------------------------------------------------
    op = evidence.get("observed_progress")
    if op is None:
        checks.append(_r("progress_range", PASS, "No observed progress asserted."))
    elif 0 <= float(op) <= 100:
        checks.append(_r("progress_range", PASS,
                         "Observed progress " + str(op) + "% is in range."))
    else:
        checks.append(_r("progress_range", FAIL,
                         "Observed progress " + str(op) + "% is outside 0-100."))

    # --- date validity ----------------------------------------------------
    ed = _d(evidence.get("date"))
    if evidence.get("date") and ed is None:
        checks.append(_r("date_validity", FAIL,
                         "Evidence date '" + str(evidence.get("date")) +
                         "' is not a valid date."))
    elif ed is None:
        checks.append(_r("date_validity", WARN, "Evidence carries no date."))
    else:
        future = date.today() + timedelta(days=1)
        if ed > future:
            checks.append(_r("date_validity", FAIL,
                             "Evidence date " + ed.isoformat() + " is in the future."))
        else:
            checks.append(_r("date_validity", PASS,
                             "Evidence date " + ed.isoformat() + " is valid."))

    # --- date ordering ----------------------------------------------------
    a_start = _d(activity.get("actual_start") or activity.get("start"))
    a_fin = _d(activity.get("actual_finish") or activity.get("finish"))
    if ed and a_start and a_fin:
        grace = timedelta(days=10)
        if a_start - grace <= ed <= a_fin + grace:
            checks.append(_r("date_ordering", PASS,
                             "Evidence date falls within the activity window."))
        elif ed < a_start - grace:
            checks.append(_r("date_ordering", WARN,
                             "Evidence dated " + ed.isoformat() + " predates the "
                             "activity window starting " + a_start.isoformat() + ".",
                             days_before=(a_start - ed).days))
        else:
            checks.append(_r("date_ordering", WARN,
                             "Evidence dated " + ed.isoformat() + " falls after the "
                             "activity window ending " + a_fin.isoformat() + ".",
                             days_after=(ed - a_fin).days))
    else:
        checks.append(_r("date_ordering", PASS,
                         "Not enough dates to order; skipped."))

    # --- location compatibility ------------------------------------------
    ev_loc = location_tokens(
        " ".join(str(evidence.get(k) or "") for k in ("location", "description")))
    act_loc = location_tokens(
        " ".join(str(activity.get(k) or "") for k in ("name", "wbs_name")))
    if ev_loc and act_loc:
        if ev_loc & act_loc:
            checks.append(_r("location_compatibility", PASS,
                             "Location tokens agree: " +
                             ", ".join(sorted(ev_loc & act_loc)) + ".",
                             shared=sorted(ev_loc & act_loc)))
        else:
            checks.append(_r("location_compatibility", FAIL,
                             "Location conflict: evidence says " +
                             ", ".join(sorted(ev_loc)) + " but the activity is " +
                             ", ".join(sorted(act_loc)) + ".",
                             evidence=sorted(ev_loc), activity=sorted(act_loc)))
    else:
        checks.append(_r("location_compatibility", WARN if not ev_loc else PASS,
                         "No comparable location on both sides." if not ev_loc
                         else "Activity carries no location token."))

    # --- chainage compatibility -------------------------------------------
    ev_ch = chainage_values(str(evidence.get("chainage") or "") + " " +
                            str(evidence.get("description") or ""))
    lo, hi = chainage_window(activity.get("name"))
    if ev_ch and lo is not None and hi is not None and hi > lo:
        inside = [c for c in ev_ch if lo - 500 <= c <= hi + 500]
        if inside:
            checks.append(_r("chainage_compatibility", PASS,
                             "Chainage " + _fmt_ch(inside[0]) + " lies within " +
                             _fmt_ch(lo) + " to " + _fmt_ch(hi) + ".",
                             value=inside[0], window=[lo, hi]))
        else:
            checks.append(_r("chainage_compatibility", FAIL,
                             "Chainage " + _fmt_ch(ev_ch[0]) + " lies outside the "
                             "activity range " + _fmt_ch(lo) + " to " +
                             _fmt_ch(hi) + ".",
                             value=ev_ch[0], window=[lo, hi]))
    else:
        checks.append(_r("chainage_compatibility", PASS,
                         "No comparable chainage on both sides; skipped."))

    # --- discipline compatibility -----------------------------------------
    ev_disc = discipline_key(evidence.get("discipline")) or \
        discipline_key(evidence.get("description"))
    act_disc = discipline_key(activity.get("name"))
    if ev_disc and act_disc:
        if ev_disc == act_disc:
            checks.append(_r("discipline_compatibility", PASS,
                             "Both are " + ev_disc + "."))
        else:
            checks.append(_r("discipline_compatibility", FAIL,
                             "Discipline conflict: evidence is " + ev_disc +
                             ", activity is " + act_disc + ".",
                             evidence=ev_disc, activity=act_disc))
    else:
        checks.append(_r("discipline_compatibility", WARN,
                         "Discipline could not be determined on both sides."))

    # --- duplicate detection ----------------------------------------------
    # Text equality is *not* enough to call two site observations duplicates.
    # The same physical event can legitimately be repeated in a DPR, diary,
    # supervisor voice note, or another contractor sheet; those observations
    # should corroborate a canonical execution event instead of one being
    # silently discarded.  We only call a row a source-level duplicate when
    # we have a stable provenance locator (file + row/page/cell) and an earlier
    # record with the same provenance key.
    src = str(evidence.get("source_file") or "").strip()
    locator = str(evidence.get("locator") or "").strip()
    dup = None
    if src and locator:
        created = float(evidence.get("created_at") or 0.0)
        dup = db.q1(
            "SELECT id, source_file, locator FROM evidence "
            "WHERE project_id=? AND id<>? AND source_file=? AND locator=? "
            "AND (COALESCE(created_at,0) < ? OR "
            "(COALESCE(created_at,0)=? AND id < ?)) "
            "ORDER BY COALESCE(created_at,0), id LIMIT 1",
            [project_id, evidence.get("id"), src, locator, created, created,
             evidence.get("id")])
    if dup:
        checks.append(_r("duplicate_detection", WARN,
                         "The same source locator was already ingested (" +
                         str(dup.get("source_file")) + " " +
                         str(dup.get("locator")) + ").", duplicate_of=dup["id"],
                         basis="same_provenance_locator"))
    else:
        msg = ("No provenance-level duplicate found." if src and locator else
               "No stable source locator is available; text similarity alone is "
               "not treated as a duplicate.")
        checks.append(_r("duplicate_detection", PASS, msg))

    # --- historical detection (spec 39) -----------------------------------
    sd = _d(status_date)
    historical_days = max(1, int(os.getenv("VEDA_HISTORICAL_DAYS", "90")))
    if ed and sd and ed < sd - timedelta(days=historical_days):
        checks.append(_r("historical_detection", WARN,
                         "Evidence is " + str((sd - ed).days) + " days older than "
                         "the data date; treat as historical, not current progress.",
                         days_old=(sd - ed).days))
    elif activity.get("status") == "complete" and ed and a_fin and ed > a_fin:
        checks.append(_r("historical_detection", WARN,
                         "Activity is already complete; this cannot advance it."))
    else:
        checks.append(_r("historical_detection", PASS, "Evidence is current."))

    # --- negation detection ------------------------------------------------
    desc = str(evidence.get("description") or "").lower()
    neg = [w for w in ("not started", "no progress", "cancelled", "postponed",
                       "on hold", "suspended", "stopped", "nil progress",
                       "no work", "stood down", "not commenced", "deferred")
           if w in desc]
    if neg:
        checks.append(_r("negation_detection", WARN,
                         "Text reports the absence of work (" + ", ".join(neg) +
                         "); it must not be read as progress.", phrases=neg))
    else:
        checks.append(_r("negation_detection", PASS, "No negation detected."))

    # --- source trust --------------------------------------------------------
    cls = source_class(evidence.get("source_file"), evidence.get("description"))
    trust = SOURCE_TRUST.get(cls, 0.5)
    checks.append(_r("source_trust", PASS if trust >= 0.5 else WARN,
                     "Source classified as " + cls + " (trust " + str(trust) + ").",
                     source_class=cls, trust=trust))

    # --- progress regression (spec 39) --------------------------------------
    official = activity.get("percent_complete")
    if op is not None and official is not None and float(op) < float(official) - 5:
        checks.append(_r("progress_regression", WARN,
                         "Observed " + str(op) + "% is below the official " +
                         str(official) + "%. Recorded as an observation only; "
                         "official progress is not reduced.",
                         observed=op, official=official))
    else:
        checks.append(_r("progress_regression", PASS, "No regression implied."))

    # --- source trust vs security -------------------------------------------
    if evidence.get("security_state") in ("suspicious", "quarantined"):
        checks.append(_r("document_trust", FAIL,
                         "Source document is " + str(evidence.get("security_state")) +
                         "; it cannot be accepted without security review."))
    else:
        checks.append(_r("document_trust", PASS, "Source document is clean."))

    return _summarise(checks)


def _fmt_ch(v: int) -> str:
    return str(v // 1000) + "+" + str(v % 1000).zfill(3)


def _summarise(checks: list) -> dict:
    fails = [c for c in checks if c["result"] == FAIL]
    warns = [c for c in checks if c["result"] == WARN]
    result = FAIL if fails else (WARN if warns else PASS)
    return {
        "result": result,
        "checks": checks,
        "failed": [c["name"] for c in fails],
        "warned": [c["name"] for c in warns],
        "summary": (str(len(checks) - len(fails) - len(warns)) + " passed, " +
                    str(len(warns)) + " warned, " + str(len(fails)) + " failed"),
    }


# =====================================================================
#  Change-proposal validators
# =====================================================================
WRITABLE_FIELDS = {
    "percentComplete", "actualStart", "actualFinish", "start", "finish",
    "duration", "deadline", "notes", "name", "constraintType", "constraintDate",
}
CREATE_WRITABLE_FIELDS = WRITABLE_FIELDS | {
    "milestone", "active", "cost", "custom",
}


def validate_proposal(proposal: dict, activity: dict | None, *,
                      project_id: str, approved: bool = False,
                      capabilities: dict | None = None) -> dict:
    checks: list = []
    caps = capabilities or {}
    operation = str(proposal.get("operation") or "update").lower()
    payload = db.jloads(proposal.get("payload_json"), {}) or {}

    if operation not in {"update", "create", "delete"}:
        checks.append(_r("operation", FAIL,
                         "Unsupported task operation '" + operation + "'."))
        return _summarise(checks)
    checks.append(_r("operation", PASS, "Task operation is " + operation + "."))

    if operation == "create":
        fields = payload.get("task_fields") or {}
        name = str(fields.get("name") or proposal.get("target_name") or "").strip()
        checks.append(_r("task_name", PASS if name else FAIL,
                         "New task name is present." if name else
                         "A create proposal needs a task name."))
        unknown = sorted(set(fields) - CREATE_WRITABLE_FIELDS)
        checks.append(_r("write_scope", PASS if not unknown else FAIL,
                         "Create fields are within the permitted task scope." if not unknown
                         else "Unsupported create fields: " + ", ".join(unknown) + "."))
        parent_uid = payload.get("parent_uid")
        if parent_uid is not None:
            parent = db.q1("SELECT uid,name FROM activities WHERE project_id=? AND uid=?",
                           [project_id, parent_uid])
            checks.append(_r("parent_exists", PASS if parent else FAIL,
                             ("Parent task '" + str((parent or {}).get("name")) + "' exists.")
                             if parent else "No task exists with parent uid " +
                             str(parent_uid) + "."))
        else:
            checks.append(_r("parent_exists", PASS,
                             "No parent uid requested; task will be created at project level."))
    else:
        if activity is None:
            checks.append(_r("activity_exists", FAIL,
                             "Proposal targets uid " + str(proposal.get("target_uid")) +
                             ", which does not exist."))
            return _summarise(checks)
        checks.append(_r("activity_exists", PASS,
                         "Target activity '" + str(activity.get("name")) + "' exists."))

        if operation == "delete":
            children = (db.q1("SELECT COUNT(*) c FROM activities WHERE project_id=? "
                              "AND parent_uid=?",
                              [project_id, proposal.get("target_uid")]) or {}).get("c", 0)
            if children:
                checks.append(_r("delete_scope", FAIL,
                                 "Refusing to delete a summary/parent task with " +
                                 str(children) + " child task(s). Upload a revised schedule "
                                 "or remove children explicitly so the scope is visible."))
            else:
                checks.append(_r("delete_scope", PASS,
                                 "Target has no child tasks; delete scope is one task."))
        else:
            field = proposal.get("field")
            if field not in WRITABLE_FIELDS:
                checks.append(_r("write_scope", FAIL,
                                 "Field '" + str(field) + "' is outside the permitted write "
                                 "scope " + ", ".join(sorted(WRITABLE_FIELDS)) + "."))
            else:
                checks.append(_r("write_scope", PASS,
                                 "Field '" + str(field) + "' is writable."))

            val = proposal.get("proposed_value")
            if field == "percentComplete":
                try:
                    pct = float(str(val).replace("%", "").strip())
                    if 0 <= pct <= 100:
                        checks.append(_r("progress_range", PASS,
                                         "Proposed progress " + str(pct) + "% is in range."))
                    else:
                        checks.append(_r("progress_range", FAIL,
                                         "Proposed progress " + str(pct) + "% is out of range."))
                    official = activity.get("percent_complete")
                    if official is not None and pct < float(official) - 0.01:
                        checks.append(_r("progress_regression", FAIL,
                                         "Proposal would reduce progress from " +
                                         str(official) + "% to " + str(pct) + "%. Progress "
                                         "regression requires explicit human authority.",
                                         official=official, proposed=pct))
                    else:
                        checks.append(_r("progress_regression", PASS,
                                         "No progress regression."))
                except (TypeError, ValueError):
                    checks.append(_r("progress_range", FAIL,
                                     "Proposed value '" + str(val) + "' is not a number."))
            elif field in ("actualStart", "actualFinish", "start", "finish",
                           "deadline", "constraintDate"):
                dv = _d(val)
                if dv is None:
                    checks.append(_r("date_validity", FAIL,
                                     "Proposed value '" + str(val) + "' is not a date "
                                     "(expected yyyy-MM-dd)."))
                else:
                    checks.append(_r("date_validity", PASS,
                                     "Proposed date " + dv.isoformat() + " parses."))
                    st = _d(activity.get("actual_start") or activity.get("start"))
                    if field == "actualFinish" and st and dv < st:
                        checks.append(_r("date_ordering", FAIL,
                                         "Proposed finish " + dv.isoformat() +
                                         " precedes the start " + st.isoformat() + "."))
                    else:
                        checks.append(_r("date_ordering", PASS,
                                         "Date ordering is consistent."))
                    if dv > date.today() + timedelta(days=1) and field.startswith("actual"):
                        checks.append(_r("date_validity_future", FAIL,
                                         "An actual date cannot be in the future."))
            else:
                checks.append(_r("value_present", PASS if str(val or "").strip() else FAIL,
                                 "Proposed value is present." if str(val or "").strip()
                                 else "Proposed value is empty."))

    # --- evidence backing ---------------------------------------------------
    ev_ids = db.jloads(proposal.get("evidence_ids_json"), []) or []
    if not ev_ids:
        checks.append(_r("evidence_backing", WARN,
                         "No evidence is cited for this change."))
    else:
        rows = db.q("SELECT id, state, security_state, source_file FROM evidence "
                    "WHERE id IN (" + ",".join("?" for _ in ev_ids) + ")", ev_ids)
        bad = [r for r in rows if r.get("security_state") in
               ("suspicious", "quarantined")]
        missing = len(ev_ids) - len(rows)
        if bad:
            checks.append(_r("evidence_backing", FAIL,
                             "Cited evidence comes from a flagged document: " +
                             ", ".join(str(b.get("source_file")) for b in bad) + "."))
        elif missing > 0:
            checks.append(_r("evidence_backing", FAIL,
                             str(missing) + " cited evidence id(s) do not exist."))
        else:
            trust = max((SOURCE_TRUST.get(
                source_class(r.get("source_file")), 0.5) for r in rows), default=0.5)
            checks.append(_r("evidence_backing", PASS if trust >= 0.5 else WARN,
                             str(len(rows)) + " evidence item(s) cited, best source "
                             "trust " + str(round(trust, 2)) + ".", trust=trust))

    # --- approval presence (spec 45) ----------------------------------------
    if approved:
        checks.append(_r("approval_presence", PASS,
                         "Human approval is recorded."))
    else:
        checks.append(_r("approval_presence", WARN,
                         "Not yet approved. A write cannot proceed until a human "
                         "approves this proposal."))

    # --- capability check ----------------------------------------------------
    if caps and not caps.get("dry_run_simulation", True):
        checks.append(_r("dry_run_capability", FAIL,
                         "Horizun reports dry-run simulation is unavailable, so this "
                         "change cannot be safely previewed."))
    else:
        checks.append(_r("dry_run_capability", PASS,
                         "Dry-run simulation is available."))

    return _summarise(checks)
