"""Document decomposition: a document is a container, not an observation.

One uploaded report (Daily Construction Report, Daily Progress Report, site
diary, look-ahead, issue register, ...) carries many heterogeneous observations:
activity-progress rows, manpower counts, equipment usage, weather, look-ahead
targets, issues/blockers, metadata and sign-off.  Treating the whole page as a
single "evidence record" and matching it to one schedule activity is the bug
this module exists to remove.

Pipeline implemented here (stages 1-5 of the required architecture)::

    FILE -> TEXT ACQUISITION -> DOCUMENT CLASSIFICATION
         -> STRUCTURE / SECTION EXTRACTION -> ATOMIC OBSERVATION EXTRACTION
         -> OBSERVATION-TYPE ROUTING TAG

Nothing here resolves an observation against a schedule activity.  Resolution is
downstream, per observation, and only for observation types that are eligible
(see ``ACTIVITY_RESOLVABLE`` and ``pipeline.linking``).

No project-specific names, ids or rules live in this module.  Section headings,
column synonyms and document signals are generic construction-reporting
vocabulary.
"""
from __future__ import annotations

import hashlib
import os
import re
from typing import Any

from . import dates

# --------------------------------------------------------------- observation types
OBS_ACTIVITY_PROGRESS = "activity_progress"
OBS_MANPOWER = "manpower"
OBS_EQUIPMENT = "equipment"
OBS_WEATHER = "weather"
OBS_ISSUE = "issue"
OBS_TARGET = "target"
OBS_REPORT_METADATA = "report_metadata"
OBS_SIGNOFF = "signoff"
OBS_GENERAL = "general"

# Only these observation types are handed to the schedule activity resolver.
ACTIVITY_RESOLVABLE = frozenset({OBS_ACTIVITY_PROGRESS, OBS_GENERAL})

# Evidence.state assigned at extraction time by observation type.
STATE_BY_TYPE = {
    OBS_ACTIVITY_PROGRESS: "new",
    OBS_GENERAL: "new",
    OBS_ISSUE: "issue",
    OBS_MANPOWER: "context",
    OBS_EQUIPMENT: "context",
    OBS_WEATHER: "context",
    OBS_TARGET: "context",
    OBS_REPORT_METADATA: "context",
    OBS_SIGNOFF: "context",
}

# --------------------------------------------------------------- document types
DOC_DAILY_CONSTRUCTION_REPORT = "DAILY_CONSTRUCTION_REPORT"
DOC_DAILY_PROGRESS_REPORT = "DAILY_PROGRESS_REPORT"
DOC_SITE_DIARY = "SITE_DIARY"
DOC_EXCEL_PROGRESS_REGISTER = "EXCEL_PROGRESS_REGISTER"
DOC_ISSUE_REGISTER = "ISSUE_REGISTER"
DOC_RESOURCE_REPORT = "RESOURCE_REPORT"
DOC_WEEKLY_REPORT = "WEEKLY_REPORT"
DOC_UNKNOWN = "UNKNOWN"

MIN_USABLE_CHARS = int(os.getenv("VEDA_MIN_EXTRACT_CHARS", "48"))

_PAGE_MARK = re.compile(r"\[page\s+(\d+)\]", re.I)


class ExtractionRequired(RuntimeError):
    """Raised when a document yielded no usable text (image-only / failed OCR).

    The caller must record file ``extract_state = 'extraction_required'`` and
    must NOT run the activity resolver on placeholder text.
    """

    def __init__(self, reason: str, detail: str | None = None):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


# ============================================================ 1. TEXT ACQUISITION
def strip_page_markers(text: str) -> tuple[str, list[tuple[int, str]]]:
    """Split ``[page N]`` marked text into (clean_text, [(page_no, page_text)])."""
    if not text:
        return "", []
    parts = _PAGE_MARK.split(text)
    pages: list[tuple[int, str]] = []
    if len(parts) == 1:
        body = parts[0].strip()
        return body, ([(1, body)] if body else [])
    # parts == [pre, num, chunk, num, chunk, ...]
    lead = parts[0].strip()
    if lead:
        pages.append((1, lead))
    it = iter(parts[1:])
    for num, chunk in zip(it, it):
        try:
            page_no = int(num)
        except (TypeError, ValueError):
            page_no = len(pages) + 1
        pages.append((page_no, (chunk or "").strip()))
    clean = "\n\n".join(p[1] for p in pages if p[1]).strip()
    return clean, [p for p in pages if p[1]]


def acquire_text(f: dict) -> dict:
    """Stage 1: obtain usable text, or declare EXTRACTION_REQUIRED.

    Native extraction (with the adaptive OCR fallback already inside
    ``extract.read_text``) is attempted first.  A result that is empty, only
    ``[page N]`` placeholders, or below the minimum meaningful length is *not*
    passed downstream.
    """
    from . import extract  # local import: extract imports documents

    path = f["stored_path"]
    ext = (f.get("ext") or "").lower()
    method = "pdf_text" if ext == ".pdf" else ("ocr" if ext in extract.IMAGE else "text")
    # Only rendered formats (PDF / scanned image) can fail extraction silently
    # and need the render->OCR fallback; a text/CSV/DOCX file with any content
    # is genuine text, never "extraction required".
    rendered = ext == ".pdf" or ext in extract.IMAGE
    raw = extract.read_text(path, ext) or ""
    clean, pages = strip_page_markers(raw)
    meaningful = re.sub(r"\s+", "", clean)
    if rendered and "[page" in raw.lower() and not clean:
        raise ExtractionRequired("extraction_placeholder_only",
                                 "only page placeholders were extracted; the "
                                 "document is image-only or extraction failed")
    if rendered and len(meaningful) < MIN_USABLE_CHARS:
        raise ExtractionRequired(
            "no_usable_text",
            f"native extraction produced {len(meaningful)} usable character(s); "
            "render the pages and OCR them, then re-run the same pipeline")
    if not meaningful:
        raise ExtractionRequired("empty_document", "no extractable text at all")
    return {"text": clean, "pages": pages or [(1, clean)], "method": method,
            "confidence": 0.9 if method != "ocr" else 0.6, "raw": raw}


# ============================================================ 2. CLASSIFICATION
# (document_type, weight, [signal regexes]) - generic construction vocabulary.
_DOC_SIGNALS: list[tuple[str, float, list[str]]] = [
    (DOC_DAILY_CONSTRUCTION_REPORT, 3.0, [
        r"daily\s+construction\s+report", r"\bd\.?c\.?r\.?\b"]),
    (DOC_DAILY_PROGRESS_REPORT, 3.0, [
        r"daily\s+progress\s+report", r"\bd\.?p\.?r\.?\b"]),
    (DOC_SITE_DIARY, 3.0, [r"site\s+diary", r"site\s+day\s*book", r"engineer'?s\s+diary"]),
    (DOC_WEEKLY_REPORT, 2.5, [r"weekly\s+(?:site\s+)?report", r"weekly\s+progress"]),
    (DOC_ISSUE_REGISTER, 2.5, [r"issue\s+register", r"ncr\s+log", r"risk\s+register",
                               r"site\s+instruction\s+log"]),
    (DOC_RESOURCE_REPORT, 2.0, [r"resource\s+report", r"manpower\s+histogram",
                                r"labou?r\s+report"]),
    (DOC_DAILY_CONSTRUCTION_REPORT, 1.0, [
        r"work\s+progress", r"manpower", r"\bequipment\b", r"weather"]),
    (DOC_DAILY_PROGRESS_REPORT, 0.7, [
        r"planned\s+today", r"achieved\s+today", r"cumulative", r"plan\s+next\s+day"]),
]


def classify_document(text: str, filename: str | None = None) -> dict:
    blob = (str(filename or "") + "\n" + (text or "")).lower()
    scores: dict[str, float] = {}
    hits: dict[str, list[str]] = {}
    for doc_type, weight, patterns in _DOC_SIGNALS:
        for pat in patterns:
            if re.search(pat, blob):
                scores[doc_type] = scores.get(doc_type, 0.0) + weight
                hits.setdefault(doc_type, []).append(pat)
    if not scores:
        return {"document_type": DOC_UNKNOWN, "confidence": 0.2, "signals": []}
    best = max(scores, key=scores.get)
    total = sum(scores.values()) or 1.0
    return {"document_type": best,
            "confidence": round(min(0.98, 0.4 + scores[best] / (total + 1.5)), 3),
            "signals": hits.get(best, [])}


# ============================================================ 3. SECTION EXTRACTION
# (section_type, heading regex).  Order matters: more specific first.
_SECTION_RULES: list[tuple[str, re.Pattern]] = [
    ("work_progress", re.compile(
        r"^(?:\d+[.)]\s*)?(work\s+progress|progress\s+of\s+work|works?\s+done|"
        r"physical\s+progress|activit(?:y|ies)\s+progress|progress\s+status|"
        r"execution\s+summary|daily\s+progress)\b", re.I)),
    ("manpower", re.compile(
        r"^(?:\d+[.)]\s*)?(man\s*power|manpower\s+deployment|labou?r\s+deployment|"
        r"labou?r\s+report|labou?r\s+strength|workforce|deployment\s+of\s+labou?r)\b", re.I)),
    ("equipment", re.compile(
        r"^(?:\d+[.)]\s*)?(equipment|plant\s*(?:&|and)?\s*machinery|machinery|"
        r"plant\s+deployment|equipment\s+deployment|tools?\s*(?:&|and)?\s*plant)\b", re.I)),
    ("target", re.compile(
        r"^(?:\d+[.)]\s*)?(anticipated\s+activit(?:y|ies)|planned\s+(?:activit(?:y|ies)|work|"
        r"for\s+(?:tomorrow|next\s+day))|next\s+day\s+plan|look[\s-]*ahead|target(?:s|\s+for\s+"
        r"tomorrow)?|programme\s+for\s+tomorrow|tomorrow'?s?\s+plan)\b", re.I)),
    ("issue", re.compile(
        r"^(?:\d+[.)]\s*)?(critical\s+concerns?(?:\s*/?\s*issues?)?|issues?(?:\s*(?:&|and|/)\s*"
        r"concerns?)?|concerns?|blockers?|constraints?|hold\s+points?|delays?\s*(?:&|and)?\s*"
        r"disruptions?|risks?\s*(?:&|and)\s*issues?|obstructions?)\b", re.I)),
    ("weather", re.compile(r"^(?:\d+[.)]\s*)?(weather(?:\s+conditions?)?|site\s+conditions?)\b", re.I)),
    ("signoff", re.compile(
        r"^(?:\d+[.)]\s*)?(sign[\s-]*off|approvals?|verification|prepared\s*(?:&|and)?\s*"
        r"approved|distribution)\b", re.I)),
]


def _match_heading(line: str) -> "str | None":
    stripped = line.strip().rstrip(":").strip()
    if not stripped or len(stripped) > 64:
        return None
    # A heading is a standalone label, not a "key: value" metadata line.  If the
    # line carries a colon with real content after it (e.g. "Weather: clear"),
    # it is data, not a section boundary.
    if ":" in line.strip().rstrip(":"):
        return None
    for section_type, pattern in _SECTION_RULES:
        m = pattern.match(stripped)
        if not m:
            continue
        tail = stripped[m.end():].strip()
        # The heading keyword must be essentially the whole line.
        if not tail or re.fullmatch(r"[-:/&.\s]*", tail):
            return section_type
    return None


def segment(pages: list[tuple[int, str]]) -> list[dict]:
    """Stage 3: split the document into typed sections.

    The block before the first recognised heading is ``report_metadata``.
    """
    sections: list[dict] = []
    current = {"section": "report_metadata", "heading": None, "page": pages[0][0] if pages else 1,
               "lines": []}
    for page_no, page_text in pages:
        for raw_line in page_text.splitlines():
            heading = _match_heading(raw_line)
            if heading:
                if current["lines"]:
                    sections.append(current)
                current = {"section": heading, "heading": raw_line.strip(),
                           "page": page_no, "lines": []}
                continue
            current["lines"].append((page_no, raw_line))
    if current["lines"] or not sections:
        sections.append(current)
    for s in sections:
        s["body"] = "\n".join(ln for _, ln in s["lines"]).strip()
        s["page"] = s["lines"][0][0] if s["lines"] else s["page"]
    return sections


# ============================================================ 4. ATOMIC OBSERVATIONS
_ZONE_RE = re.compile(
    r"\b((?:zone|area|sector|block|grid(?:line)?|level|floor|wing|bay|building|tower)\s*[-#]?\s*"
    r"[A-Za-z0-9]+(?:\s*[-/]\s*[A-Za-z0-9]+)?)\b", re.I)
_UNIT_TRAIL = re.compile(
    r"[\s(\[]((?:sq\.?\s*)?m2|m\^?2|sqm|(?:cu\.?\s*)?m3|m\^?3|cum|rmt|r\.?m|lm|"
    r"nos?|no\.?|each|ea|kg|t(?:on(?:ne)?s?)?|ltr|l|m|mm|km|pcs?|units?|"
    r"points?|joints?|coats?)[\s)\]]*$", re.I)

# header token -> canonical progress field
_PROGRESS_COLUMNS: dict[str, tuple[str, ...]] = {
    "description": ("description", "activity", "activities", "work", "work description",
                    "description of work", "item", "task", "scope", "particulars",
                    "activity description", "work item", "element", "trade / activity"),
    "location": ("location", "zone", "area", "grid", "gridline", "block", "level",
                 "floor", "sector", "wing", "chainage", "position", "structure"),
    "unit": ("unit", "uom", "units", "u/m", "u.o.m", "measure"),
    "total_qty": ("total qty", "total quantity", "total", "scope qty", "boq qty",
                  "contract qty", "total scope", "total quantum", "overall qty",
                  "planned quantity", "planned qty total"),
    "planned_today": ("planned today", "plan today", "today plan", "planned qty",
                      "plan for the day", "planned", "target today", "plan qty today",
                      "day plan", "planned for today", "today target"),
    "achieved_today": ("achieved today", "actual today", "today achieved", "progress today",
                       "done today", "achieved", "actual qty today", "qty today",
                       "executed today", "today actual", "achieved qty", "todays progress",
                       "progress for the day", "actual progress"),
    "plan_next_day": ("plan next day", "next day plan", "tomorrow plan", "plan for tomorrow",
                      "next day", "look ahead qty", "planned next day", "plan for next day",
                      "next day target"),
    "cumulative_qty": ("cumulative", "cum qty", "cumulative achieved", "to date",
                       "cumulative to date", "cumulative qty", "total achieved",
                       "cum achieved", "cumulative progress", "progress to date",
                       "cum. achieved", "cumulative quantity"),
    "percent_complete": ("%", "percent", "% complete", "percent complete", "progress %",
                         "completion", "% age", "% complete to date", "pct", "%complete",
                         "progress percent", "overall %"),
}
_NUMERIC_PROGRESS_FIELDS = ("total_qty", "planned_today", "achieved_today",
                            "plan_next_day", "cumulative_qty", "percent_complete")

_ISSUE_COLUMNS: dict[str, tuple[str, ...]] = {
    "description": ("description", "issue", "concern", "detail", "details", "subject",
                    "particulars", "nature of issue", "problem", "matter"),
    "reference": ("reference", "ref", "ref no", "reference no", "document", "document no",
                  "drawing", "drawing no", "letter no", "rfi", "rfi no", "si no",
                  "ncr no", "correspondence", "transmittal"),
    "raised": ("raised", "date raised", "raised on", "date", "reported", "reported on",
               "logged", "issue date", "identified on"),
    "work_affected": ("work affected", "affected work", "affected activity", "impact",
                      "activity affected", "impacted work", "affected scope",
                      "work impacted", "affected activities", "impacted activity"),
    "plan_start": ("plan start", "planned start", "planned start date", "target start",
                   "scheduled start", "affected start", "activity plan start"),
}

_MANPOWER_COLUMNS: dict[str, tuple[str, ...]] = {
    "trade": ("trade", "designation", "category", "labour", "labor", "skill",
              "resource", "description", "manpower", "role", "worker"),
    "count": ("count", "nos", "no", "number", "qty", "quantity", "strength",
              "headcount", "total", "deployed", "manpower"),
}
_EQUIPMENT_COLUMNS: dict[str, tuple[str, ...]] = {
    "equipment": ("equipment", "plant", "machinery", "description", "resource",
                  "item", "type", "asset"),
    "count": ("count", "nos", "no", "number", "qty", "quantity", "deployed", "units"),
    "hours": ("hours", "hrs", "working hours", "run hours", "operating hours", "usage"),
}


def _norm_header(v: str) -> str:
    return re.sub(r"[^a-z0-9%]+", " ", str(v or "").lower()).strip()


def _num(v) -> "float | None":
    """Parse a number; blank / dash / 'n/a' stay None (never invented as 0)."""
    if v is None:
        return None
    s = str(v).strip()
    if not s or s.lower() in {"-", "--", "n/a", "na", "nil", "tbd", "tba", "x"}:
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", s.replace(",", ""))
    return float(m.group(0)) if m else None


def _looks_tabular(lines: list[str]) -> bool:
    body_lines = [ln for ln in lines if ln.strip()]
    if len(body_lines) < 2:
        return False
    delim = sum(1 for ln in body_lines if "|" in ln or "\t" in ln
                or re.search(r"\S {2,}\S", ln))
    return delim >= max(2, len(body_lines) // 2)


def _split_cells(line: str) -> list[str]:
    if "|" in line:
        return [c.strip() for c in line.split("|")]
    if "\t" in line:
        return [c.strip() for c in line.split("\t")]
    return [c.strip() for c in re.split(r"\s{2,}", line.strip())]


def _column_map(header_cells: list[str], vocab: dict[str, tuple[str, ...]]) -> dict[str, int]:
    normed = [_norm_header(c) for c in header_cells]
    out: dict[str, int] = {}
    for field, names in vocab.items():
        exact = {n for n in names}
        for i, h in enumerate(normed):
            if h and h in exact:
                out.setdefault(field, i)
        if field not in out:
            for i, h in enumerate(normed):
                if h and any(n in h or h in n for n in names):
                    out.setdefault(field, i)
                    break
    return out


def _find_location(text: str) -> "str | None":
    m = _ZONE_RE.search(str(text or ""))
    if not m:
        return None
    loc = re.sub(r"\s+", " ", m.group(1)).strip()
    return loc[:1].upper() + loc[1:]


def _trailing_unit(text: str) -> "str | None":
    m = _UNIT_TRAIL.search(str(text or "").strip())
    return m.group(1).lower() if m else None


def _obs_key(file_sha: str, page: int, section: str, row_index, content: str) -> str:
    norm = re.sub(r"\s+", " ", str(content or "").lower()).strip()
    seed = f"{file_sha}|{page}|{section}|{row_index}|{norm}"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32]


def _base_observation(project_id: str, f: dict, *, section: str, page: int,
                      row_index, obs_type: str, raw_text: str,
                      locator: str, provenance: str, method: str,
                      confidence: float) -> dict:
    return {
        "project_id": project_id, "file_id": f["id"],
        "source_file": f.get("filename"), "locator": locator,
        "observation_type": obs_type, "section": section,
        "row_index": row_index if isinstance(row_index, int) else None,
        "raw_text": raw_text[:2000],
        "extraction_method": method, "extraction_confidence": round(confidence, 3),
        "provenance": provenance, "security_state": f.get("security_state", "clean"),
        "state": STATE_BY_TYPE.get(obs_type, "context"),
        "observation_key": _obs_key(f.get("sha256") or f.get("id") or "", page,
                                    section, row_index, raw_text),
    }


# ---- section parsers -------------------------------------------------------
def _parse_metadata(project_id, f, section, doc_type, context_dates, method):
    body = section["body"]
    if not body.strip():
        return []
    kv: dict[str, str] = {}
    for line in body.splitlines():
        m = re.match(r"\s*([A-Za-z][\w /&().-]{1,40}?)\s*[:\-]\s*(.+?)\s*$", line)
        if m:
            kv[m.group(1).strip().lower()] = m.group(2).strip()
    date_raw = next((v for k, v in kv.items() if k in (
        "date", "report date", "dcr date", "dpr date", "reporting date",
        "day", "doc date")), None)
    di = dates.interpret(date_raw, context_dates) if date_raw else None
    obs = _base_observation(project_id, f, section="report_metadata",
                            page=section["page"], row_index=None,
                            obs_type=OBS_REPORT_METADATA, raw_text=body,
                            locator=f"page {section['page']} · report metadata",
                            provenance=_provenance(f), method=method, confidence=0.9)
    obs.update({
        "description": "; ".join(f"{k}: {v}" for k, v in list(kv.items())[:12]) or body[:400],
        "author": next((v for k, v in kv.items() if k in (
            "prepared by", "reported by", "author", "engineer", "site engineer")), None),
        "contractor": next((v for k, v in kv.items() if k in (
            "contractor", "subcontractor", "agency", "firm")), None),
        "document_type": doc_type,
        "raw_values_json": _jdumps(kv),
        "raw_date": (di or {}).get("raw"),
        "date": (di or {}).get("normalized"),
        "date_interpretations_json": _jdumps(di) if di else None,
    })
    out = [obs]
    weather = next((v for k, v in kv.items() if k in ("weather", "weather conditions",
                                                      "site conditions")), None)
    if weather:
        w = _base_observation(project_id, f, section="report_metadata",
                              page=section["page"], row_index=None,
                              obs_type=OBS_WEATHER, raw_text=f"Weather: {weather}",
                              locator=f"page {section['page']} · weather",
                              provenance=_provenance(f), method=method, confidence=0.8)
        w.update({"description": f"Weather: {weather}", "date": (di or {}).get("normalized"),
                  "raw_values_json": _jdumps({"weather": weather})})
        out.append(w)
    return out


def _parse_work_progress(project_id, f, section, report_date, method):
    lines = [ln for _, ln in section["lines"]]
    text_lines = [ln for ln in lines if ln.strip()]
    out: list[dict] = []
    if not text_lines:
        return out
    tabular = _looks_tabular(text_lines)
    col_map: dict[str, int] = {}
    data_lines: list[tuple[int, str]] = []
    if tabular:
        header_cells = _split_cells(text_lines[0])
        col_map = _column_map(header_cells, _PROGRESS_COLUMNS)
        data_lines = [(i + 2, ln) for i, ln in enumerate(text_lines[1:])]
        if "description" not in col_map:
            col_map["description"] = 0
    else:
        data_lines = [(i + 1, ln) for i, ln in enumerate(text_lines)]

    for row_index, line in data_lines:
        cells = _split_cells(line) if tabular else [line]
        if tabular and not any(c for c in cells):
            continue

        def cell(field: str) -> str:
            idx = col_map.get(field)
            if idx is None or idx >= len(cells):
                return ""
            return cells[idx].strip()

        desc = cell("description") if tabular else line.strip()
        desc = re.sub(r"\s+", " ", desc).strip(" .-|")
        if not desc or len(desc) < 3 or re.fullmatch(r"[\d.,%/\s-]+", desc):
            continue
        if re.match(r"^(total|sub[\s-]?total|grand\s+total|s\.?\s?no\.?|sr\.?\s?no\.?)\b",
                    desc, re.I):
            continue

        location = cell("location") or _find_location(line) or _find_location(desc)
        unit = cell("unit") or _trailing_unit(desc)
        values = {fld: _num(cell(fld)) for fld in _NUMERIC_PROGRESS_FIELDS} if tabular \
            else {fld: None for fld in _NUMERIC_PROGRESS_FIELDS}
        pct = values.get("percent_complete")
        # A percent is only asserted when the source states one. Blank stays None.
        raw_values = {k: v for k, v in values.items()}
        raw_values["unit"] = unit
        raw_values["location"] = location

        obs = _base_observation(
            project_id, f, section="work_progress", page=section["page"],
            row_index=row_index, obs_type=OBS_ACTIVITY_PROGRESS, raw_text=line,
            locator=f"page {section['page']} · work progress · row {row_index}",
            provenance=_provenance(f), method=method,
            confidence=0.86 if tabular else 0.6)
        obs.update({
            "date": report_date,
            "description": desc[:900],
            "location": location or None,
            "unit": (unit or None),
            "quantity": values.get("achieved_today"),
            "observed_progress": pct,
            "activity_description": desc[:900],
            "raw_values_json": _jdumps(raw_values),
        })
        out.append(obs)
    return out


def _parse_resource(project_id, f, section, obs_type, vocab, report_date, method):
    lines = [ln for _, ln in section["lines"] if ln.strip()]
    out: list[dict] = []
    if not lines:
        return out
    tabular = _looks_tabular(lines)
    col_map: dict[str, int] = {}
    rows: list[tuple[int, str]] = []
    if tabular:
        col_map = _column_map(_split_cells(lines[0]), vocab)
        rows = [(i + 2, ln) for i, ln in enumerate(lines[1:])]
    else:
        rows = [(i + 1, ln) for i, ln in enumerate(lines)]
    label_field = "trade" if obs_type == OBS_MANPOWER else "equipment"
    for row_index, line in rows:
        cells = _split_cells(line) if tabular else [line]

        def cell(field):
            idx = col_map.get(field)
            return cells[idx].strip() if idx is not None and idx < len(cells) else ""

        label = cell(label_field) if tabular else re.split(r"[:\-]|\s{2,}", line)[0].strip()
        label = re.sub(r"\s+", " ", label).strip(" .-|")
        if not label or re.fullmatch(r"[\d.,%/\s-]+", label):
            continue
        count = _num(cell("count")) if tabular else _num(line)
        hours = _num(cell("hours")) if (tabular and obs_type == OBS_EQUIPMENT) else None
        obs = _base_observation(
            project_id, f, section=section["section"], page=section["page"],
            row_index=row_index, obs_type=obs_type, raw_text=line,
            locator=f"page {section['page']} · {section['section']} · row {row_index}",
            provenance=_provenance(f), method=method, confidence=0.8)
        obs.update({
            "date": report_date,
            "description": (f"{label}: {count:g}" if count is not None else label)[:400],
            "crew": label if obs_type == OBS_MANPOWER else None,
            "quantity": count,
            "raw_values_json": _jdumps({"label": label, "count": count, "hours": hours}),
        })
        out.append(obs)
    return out


def _parse_targets(project_id, f, section, context_dates, method):
    lines = [ln for _, ln in section["lines"] if ln.strip()]
    out: list[dict] = []
    tabular = _looks_tabular(lines)
    rows = lines[1:] if tabular else lines
    start = 2 if tabular else 1
    for i, line in enumerate(rows, start=start):
        text = re.sub(r"\s+", " ", line).strip(" .-|")
        if not text or len(text) < 4 or re.fullmatch(r"[\d.,%/\s-]+", text):
            continue
        planned = None
        m = re.search(r"(?:planned|target(?:ed)?|scheduled|expected)\s*(?:for|on|:)?\s*"
                      r"([0-3]?\d[\s./\-][A-Za-z0-9]{2,9}[\s./\-]\d{2,4}|\d{4}-\d{2}-\d{2})",
                      text, re.I)
        if m:
            planned = dates.interpret(m.group(1), context_dates).get("normalized")
        obs = _base_observation(
            project_id, f, section="target", page=section["page"], row_index=i,
            obs_type=OBS_TARGET, raw_text=line,
            locator=f"page {section['page']} · anticipated / target · row {i}",
            provenance=_provenance(f), method=method, confidence=0.7)
        obs.update({
            "description": text[:900],
            "location": _find_location(text) or None,
            "raw_values_json": _jdumps({"planned_start": planned, "text": text}),
        })
        out.append(obs)
    return out


def _parse_issues(project_id, f, section, context_dates, method):
    lines = [ln for _, ln in section["lines"] if ln.strip()]
    out: list[dict] = []
    if not lines:
        return out
    tabular = _looks_tabular(lines)
    col_map: dict[str, int] = {}
    rows: list[tuple[int, str]] = []
    if tabular:
        col_map = _column_map(_split_cells(lines[0]), _ISSUE_COLUMNS)
        rows = [(i + 2, ln) for i, ln in enumerate(lines[1:])]
        if "description" not in col_map:
            col_map["description"] = 0
    else:
        rows = [(i + 1, ln) for i, ln in enumerate(lines)]

    for row_index, line in rows:
        cells = _split_cells(line) if tabular else [line]

        def cell(field):
            idx = col_map.get(field)
            return cells[idx].strip() if idx is not None and idx < len(cells) else ""

        desc = cell("description") if tabular else line.strip()
        desc = re.sub(r"\s+", " ", desc).strip(" .-|")
        if not desc or len(desc) < 5 or re.fullmatch(r"[\d.,%/\s-]+", desc):
            continue
        reference = cell("reference") or _first(re.findall(
            r"\b(?:[A-Z]{1,4}[-/]?\d{2,}[-/A-Z0-9]*|F\d{3,}[-/][A-Z0-9-]+)\b", line))
        raised_raw = cell("raised") or _first(re.findall(
            r"\b[0-3]?\d[\s./\-][A-Za-z]{3,9}[\s./\-]\d{2,4}\b", line))
        di = dates.interpret(raised_raw, context_dates) if raised_raw else None
        work_affected = cell("work_affected") or None
        plan_start_raw = cell("plan_start") or None
        plan_start = dates.interpret(plan_start_raw, context_dates).get("normalized") \
            if plan_start_raw else None
        location = _find_location(work_affected or "") or _find_location(desc)

        obs = _base_observation(
            project_id, f, section="issue", page=section["page"], row_index=row_index,
            obs_type=OBS_ISSUE, raw_text=line,
            locator=f"page {section['page']} · critical concern / issues · row {row_index}",
            provenance=_provenance(f), method=method, confidence=0.82)
        obs.update({
            "description": desc[:900],
            "date": (di or {}).get("normalized"),
            "raw_date": (di or {}).get("raw"),
            "date_interpretations_json": _jdumps(di) if di else None,
            "location": location or None,
            "discipline": None,
            "raw_values_json": _jdumps({
                "reference": reference, "raised_raw": raised_raw,
                "work_affected": work_affected, "plan_start_raw": plan_start_raw,
                "plan_start": plan_start}),
        })
        out.append(obs)
    return out


def _parse_generic(project_id, f, section, context_dates, method):
    """Fallback: unstructured prose -> one observation per paragraph/line."""
    body = section["body"]
    blocks = [b.strip() for b in re.split(r"\n\s*\n", body) if len(b.strip()) > 12]
    if not blocks:
        blocks = [ln.strip() for ln in body.splitlines() if len(ln.strip()) > 12]
    if not blocks and body.strip():
        blocks = [body.strip()]
    out: list[dict] = []
    for i, block in enumerate(blocks, start=1):
        first_date = _first(re.findall(
            r"\d{4}-\d{2}-\d{2}|[0-3]?\d[\s./\-][A-Za-z0-9]{2,9}[\s./\-]\d{2,4}", block))
        di = dates.interpret(first_date, context_dates) if first_date else None
        obs = _base_observation(
            project_id, f, section=section["section"], page=section["page"], row_index=i,
            obs_type=OBS_GENERAL, raw_text=block,
            locator=f"page {section['page']} · {section['section']} · block {i}",
            provenance=_provenance(f), method=method, confidence=0.5)
        obs.update({
            "description": block[:900],
            "date": (di or {}).get("normalized"),
            "raw_date": (di or {}).get("raw"),
            "date_interpretations_json": _jdumps(di) if di else None,
            "location": _find_location(block) or None,
        })
        out.append(obs)
    return out


# ============================================================ ORCHESTRATION
def decompose(project_id: str, f: dict, job_id: str | None = None) -> dict:
    """Full document -> typed atomic observations.

    Raises ``ExtractionRequired`` when no usable text could be obtained.
    """
    acq = acquire_text(f)
    text, pages, method = acq["text"], acq["pages"], acq["method"]
    doc_class = classify_document(text, f.get("filename"))
    doc_type = doc_class["document_type"]
    sections = segment(pages)

    # Temporal context for date disambiguation: every unambiguous date in the
    # document plus the project schedule window.
    context_dates = _document_context_dates(text) + _project_context_dates(project_id)

    report_date = _report_date(sections, context_dates)

    observations: list[dict] = []
    for section in sections:
        kind = section["section"]
        if kind == "report_metadata":
            observations += _parse_metadata(project_id, f, section, doc_type,
                                            context_dates, method)
        elif kind == "work_progress":
            observations += _parse_work_progress(project_id, f, section, report_date, method)
        elif kind == "manpower":
            observations += _parse_resource(project_id, f, section, OBS_MANPOWER,
                                            _MANPOWER_COLUMNS, report_date, method)
        elif kind == "equipment":
            observations += _parse_resource(project_id, f, section, OBS_EQUIPMENT,
                                            _EQUIPMENT_COLUMNS, report_date, method)
        elif kind == "target":
            observations += _parse_targets(project_id, f, section, context_dates, method)
        elif kind == "issue":
            observations += _parse_issues(project_id, f, section, context_dates, method)
        elif kind == "signoff":
            observations += _parse_signoff(project_id, f, section, method)
        elif kind == "weather":
            observations += _parse_generic(project_id, f, section, context_dates, method)
        else:
            observations += _parse_generic(project_id, f, section, context_dates, method)

    # A recognised report that produced no activity-progress or issue rows is a
    # structural-extraction failure, not "nothing to report".
    resolvable = [o for o in observations
                  if o.get("observation_type") in (OBS_ACTIVITY_PROGRESS, OBS_ISSUE)]
    if doc_type != DOC_UNKNOWN and not resolvable and len(observations) <= 1:
        raise ExtractionRequired(
            "structure_unusable",
            f"classified as {doc_type} but no work-progress or issue rows could be "
            "parsed from the extracted text")

    for o in observations:
        o.setdefault("document_type", doc_type)
        o["job_id"] = job_id

    summary: dict[str, int] = {}
    for o in observations:
        summary[o["observation_type"]] = summary.get(o["observation_type"], 0) + 1

    return {"usable": True, "document_type": doc_type,
            "document_confidence": doc_class["confidence"],
            "document_signals": doc_class["signals"],
            "text_method": method, "page_count": len(pages),
            "observations": observations, "section_summary": summary,
            "section_types": [s["section"] for s in sections]}


def _parse_signoff(project_id, f, section, method):
    body = section["body"]
    if not body.strip():
        return []
    kv: dict[str, str] = {}
    for m in re.finditer(r"(prepared by|checked by|reviewed by|approved by|verified by|"
                         r"received by|distribution)\s*[:\-]?\s*([A-Za-z][\w .,'&/-]{1,60})",
                         body, re.I):
        kv[m.group(1).lower()] = m.group(2).strip()
    obs = _base_observation(project_id, f, section="signoff", page=section["page"],
                            row_index=None, obs_type=OBS_SIGNOFF, raw_text=body,
                            locator=f"page {section['page']} · sign-off",
                            provenance=_provenance(f), method=method, confidence=0.8)
    obs.update({"description": body[:400],
                "raw_values_json": _jdumps(kv or {"text": body[:400]})})
    return [obs]


# ============================================================ helpers
def _provenance(f: dict) -> str:
    return "HUMAN_INPUT" if f.get("source_mode") in (
        "field_note", "whatsapp", "change_request") else "SOURCE_FILE"


def _jdumps(obj: Any) -> str:
    from .. import db
    return db.jdumps(obj)


def _first(seq):
    for x in seq or []:
        if x:
            return x
    return None


def _document_context_dates(text: str) -> list[str]:
    """Unambiguous dates present in the document, used to rank ambiguous ones."""
    out: list[str] = []
    for m in re.findall(r"\b[0-3]?\d[\s./\-][A-Za-z]{3,9}[\s./\-]\d{2,4}\b", text or ""):
        iso = dates.best_iso(m)
        if iso:
            out.append(iso)
    for m in re.findall(r"\b\d{4}-\d{2}-\d{2}\b", text or ""):
        out.append(m)
    return out


def _project_context_dates(project_id: str) -> list[str]:
    from .. import db
    rows = db.q("SELECT planned_start, planned_finish, data_date, status_date "
                "FROM schedule_snapshots WHERE project_id=? AND is_current=1 "
                "ORDER BY created_at DESC LIMIT 1", [project_id])
    out: list[str] = []
    for r in rows:
        for v in r.values():
            if v:
                out.append(str(v).split("T")[0])
    act = db.q("SELECT MIN(start) a, MAX(finish) b FROM activities WHERE project_id=?",
               [project_id])
    for r in act:
        for v in r.values():
            if v:
                out.append(str(v).split("T")[0])
    return out


def _report_date(sections: list[dict], context_dates: list[str]) -> "str | None":
    for section in sections:
        if section["section"] != "report_metadata":
            continue
        for line in section["body"].splitlines():
            m = re.match(r"\s*(?:date|report date|dcr date|dpr date|reporting date|day)\s*"
                         r"[:\-]\s*(.+?)\s*$", line, re.I)
            if m:
                return dates.interpret(m.group(1).strip(), context_dates).get("normalized")
    return None
