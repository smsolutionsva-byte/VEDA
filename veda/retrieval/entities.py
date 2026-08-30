"""Engineering entity normalization used by extraction and schedule retrieval.

Construction/oil & gas reports are unusually rich in identifiers (equipment,
line, instrument, spool, drawing, cable, etc.).  Exact identifier agreement is
therefore treated as a first-class signal instead of asking embeddings to infer
what is already an explicit key in the source text.
"""
from __future__ import annotations

import functools
import json
import re
from typing import Any, Iterable

# Common engineering tag prefixes.  The generic regex below still captures
# unknown owner-specific codes when they contain separators; this prefix list
# mainly allows compact tags such as P104A / V203 without creating too many
# false positives from ordinary words.
_PREFIXES = {
    "P", "PU", "PMP", "V", "TK", "T", "E", "HX", "C", "K", "COMP", "FAN",
    "XV", "PV", "FV", "LV", "HV", "MOV", "SDV", "ESDV", "BDV", "PSV",
    "PT", "PI", "PIT", "TT", "TI", "TIT", "LT", "LI", "LIT", "FT", "FI",
    "FIT", "LS", "PS", "TS", "JB", "MCC", "PCC", "DB", "UPS", "TR", "XFMR",
    "CB", "CT", "PTX", "SP", "SPL", "ISO", "PID", "PFD", "DWG", "DRG",
    "CABLE", "CBL", "LOOP", "IP", "FC", "FDN", "FOUND", "LINE", "L", "RACK", "BAY",
}

# Prefixes that strongly indicate document/control identifiers.  We preserve
# them because daily reports often cite an isometric/drawing rather than the
# equipment itself, and those references can still resolve a schedule activity.
_DOC_PREFIXES = {"ISO", "PID", "PFD", "DWG", "DRG", "NCR", "RFI", "ITP", "MIR", "MRN"}


_ASSET_CLASS = {
    "P": "pump", "PU": "pump", "PMP": "pump",
    "V": "vessel", "TK": "tank", "T": "tank",
    "E": "heat_exchanger", "HX": "heat_exchanger",
    "C": "compressor", "K": "compressor", "COMP": "compressor", "FAN": "fan",
    "XV": "valve", "PV": "valve", "FV": "valve", "LV": "valve", "HV": "valve",
    "MOV": "valve", "SDV": "valve", "ESDV": "valve", "BDV": "valve", "PSV": "valve",
    "PT": "instrument", "PI": "instrument", "PIT": "instrument", "TT": "instrument",
    "TI": "instrument", "TIT": "instrument", "LT": "instrument", "LI": "instrument",
    "LIT": "instrument", "FT": "instrument", "FI": "instrument", "FIT": "instrument",
    "LS": "instrument", "PS": "instrument", "TS": "instrument",
    "JB": "junction_box", "MCC": "motor_control_center", "PCC": "power_control_center",
    "DB": "distribution_board", "UPS": "ups", "TR": "transformer", "XFMR": "transformer",
    "CB": "circuit_breaker", "CABLE": "cable", "CBL": "cable", "LOOP": "instrument_loop", "IP": "instrument_package",
    "SP": "spool", "SPL": "spool", "FDN": "foundation", "FOUND": "foundation",
    "LINE": "process_line", "L": "process_line", "RACK": "rack", "BAY": "bay",
}

# Tokens that frequently resemble compact tags but are not assets.
_TAG_STOP = {
    "AREA1", "AREA2", "UNIT1", "UNIT2", "PHASE1", "PHASE2", "DAY1", "DAY2",
    "WEEK1", "WEEK2", "SHIFT1", "SHIFT2", "REV1", "REV2", "L1", "L2", "L3",
    "L4", "L5", "L6", "WBS1", "WBS2",
}

# Tag with at least one separator, e.g. P-101A, 24-P-1043-A1, PT-402, ISO-101-03.
_SEPARATED = re.compile(
    r"(?<![A-Z0-9])([A-Z0-9]{1,8}(?:\s*[-_/.:]\s*[A-Z0-9]{1,12}){1,6})(?![A-Z0-9])",
    re.I,
)
# Compact known-prefix tag, e.g. P104A, V203, PT402, JB303.
_COMPACT = re.compile(r"\b([A-Z]{1,6})(\d{2,7}[A-Z]?(?:[A-Z0-9]{0,3})?)\b", re.I)
# Known-prefix notation with spaces, e.g. `PT 402`, `CBL 4401`,
# `ISO 24P1043 003`.  Restricting to known prefixes avoids promoting ordinary
# prose such as "AREA A" to an equipment identity.
_SPACED_PREFIX = re.compile(r"(?=\b([A-Z]{1,6})\s+([A-Z0-9]{2,16})\b)", re.I)
_SPACED_DOC = re.compile(r"(?=\b(ISO|PID|PFD|DWG|DRG)\s+([A-Z0-9]{2,16})\s+([A-Z0-9]{1,8})\b)", re.I)
_LINE_SPACED = re.compile(r"\b(\d{1,3})\s+([A-Z]{1,5})\s+(\d{2,7})\s+([A-Z]\d{0,3})\b", re.I)
_LINE_COMPACT = re.compile(r"\b(\d{1,3})([A-Z]{1,5})(\d{2,7})([A-Z]\d{0,3})\b", re.I)
# Common line-number form that starts with nominal bore, including 24\"-P-1043-A1.
_LINE = re.compile(
    r"\b(\d{1,3}(?:\.\d+)?\s*(?:\"|IN|INCH)?\s*[-/]\s*[A-Z]{1,5}\s*[-/]\s*\d{2,7}(?:\s*[-/]\s*[A-Z0-9]{1,10}){0,4})\b",
    re.I,
)


def _canon_tag(value: str) -> str:
    s = str(value or "").upper().strip()
    s = s.replace("–", "-").replace("—", "-")
    s = re.sub(r"\s+", "", s)
    s = re.sub(r"[^A-Z0-9/_:.-]+", "", s)
    s = re.sub(r"[-_/.:]{2,}", "-", s)
    return s.strip("-_/.: ")


def tag_aliases(tag: str) -> set[str]:
    """Canonical + punctuation-free aliases for owner/contractor notation drift."""
    c = _canon_tag(tag)
    if not c:
        return set()
    compact = re.sub(r"[-_/.:]", "", c)
    return {c, compact} if compact and compact != c else {c}


def ocr_probable_aliases(tag: str) -> set[str]:
    """Conservative OCR aliases, kept separate from safe notation aliases.

    We only substitute visually-confusable characters next to digits and only
    generate single-edit alternatives.  These aliases are evidence, never
    canonical identity; `P-101A` must never collapse into `P-101B`.
    """
    c=_canon_tag(tag)
    if not c: return set()
    out=set()
    pairs={"O":"0","I":"1","L":"1","S":"5","B":"8"}
    chars=list(c)
    for i,ch in enumerate(chars):
        rep=pairs.get(ch)
        if not rep: continue
        left=chars[i-1].isdigit() if i>0 else False
        right=chars[i+1].isdigit() if i+1<len(chars) else False
        if left or right:
            v=chars.copy(); v[i]=rep; out.update(tag_aliases("".join(v)))
    # reverse confusion is only allowed inside a numeric run adjacent to letters.
    rev={"0":"O","1":"I","5":"S","8":"B"}
    for i,ch in enumerate(chars):
        rep=rev.get(ch)
        if not rep: continue
        if (i>0 and chars[i-1].isalpha()) or (i+1<len(chars) and chars[i+1].isalpha()):
            v=chars.copy(); v[i]=rep; out.update(tag_aliases("".join(v)))
    return out - tag_aliases(c)


def _asset_class(tag: str) -> str | None:
    c=_canon_tag(tag)
    head=re.split(r"[-_/.:\d]", c, 1)[0]
    if c[:1].isdigit() and ("-P-" in c or "/P/" in c): return "process_line"
    return _ASSET_CLASS.get(head)


def _tag_type(tag: str) -> str:
    c = _canon_tag(tag)
    head = re.split(r"[-_/.:\d]", c, 1)[0]
    if head in _DOC_PREFIXES:
        return "document"
    if head in {"PT", "PI", "PIT", "TT", "TI", "TIT", "LT", "LI", "LIT", "FT", "FI", "FIT", "LS", "PS", "TS"}:
        return "instrument"
    if head in {"MCC", "PCC", "DB", "UPS", "CB", "CT", "XFMR", "TR", "JB", "CABLE", "CBL"}:
        return "electrical"
    if head in {"SP", "SPL"}:
        return "spool"
    if c[:1].isdigit() and ("-P-" in c or "/P/" in c):
        return "line"
    return "asset"


def extract_asset_tags(*texts: Any, custom: Any = None) -> list[dict]:
    """Extract normalized engineering identifiers with conservative typing.

    `custom` may be a Primavera/MSP custom-field dictionary.  Only values under
    identifier-looking keys are promoted, avoiding accidental ingestion of every
    custom value as an asset.
    """
    blob = " ".join(str(t) for t in texts if t not in (None, ""))
    found: dict[str, dict] = {}

    def add(raw: str, typ: str | None = None, source: str = "text") -> None:
        c = _canon_tag(raw)
        if len(c) < 3 or len(c) > 64 or c in _TAG_STOP:
            return
        if re.fullmatch(r"\d+(?:[-/.]\d+)+", c):  # dates / decimal-like values
            return
        if not any(ch.isdigit() for ch in c):
            return
        found.setdefault(c, {"tag": c, "type": typ or _tag_type(c), "class": _asset_class(c),
                             "source": source, "aliases": sorted(tag_aliases(c)),
                             "ocr_aliases": sorted(ocr_probable_aliases(c))})

    for m in _LINE.finditer(blob.upper()):
        add(m.group(1), "line")
    for m in _LINE_SPACED.finditer(blob.upper()):
        add("-".join(m.groups()), "line")
    for m in _LINE_COMPACT.finditer(blob.upper()):
        add("-".join(m.groups()), "line")
    for m in _SPACED_DOC.finditer(blob.upper()):
        add("-".join(m.groups()), "document")
    for m in _SPACED_PREFIX.finditer(blob.upper()):
        prefix = m.group(1).upper()
        if prefix in _PREFIXES and prefix not in {"LINE","CABLE","RACK","BAY"} and any(ch.isdigit() for ch in m.group(2)):
            add(prefix + "-" + m.group(2))
    for m in _SEPARATED.finditer(blob.upper()):
        raw = m.group(1)
        # Ignore simple calendar dates and chainages (12+400 is not matched).
        if re.fullmatch(r"\d{1,4}[-/.]\d{1,4}(?:[-/.]\d{1,4})?", raw.replace(" ", "")):
            continue
        add(raw)
    for m in _COMPACT.finditer(blob.upper()):
        prefix, tail = m.group(1).upper(), m.group(2).upper()
        if prefix in _PREFIXES:
            add(prefix + "-" + tail)

    if custom:
        if isinstance(custom, str):
            try:
                custom = json.loads(custom)
            except Exception:
                custom = None
        key_pat = re.compile(
            r"tag|asset|equipment|equip|line(?:_?no)?|spool|loop|cable|drawing|dwg|iso|pid|p&id|system|subsystem|package|work_?pack",
            re.I,
        )

        def walk(obj: Any, key: str = "") -> None:
            if isinstance(obj, dict):
                for k, v in obj.items():
                    walk(v, str(k))
            elif isinstance(obj, (list, tuple, set)):
                for v in obj:
                    walk(v, key)
            elif key_pat.search(key) and obj not in (None, ""):
                sval = str(obj)
                # Let text extraction normalize multiple values in one field.
                before = len(found)
                for m in _LINE.finditer(sval.upper()):
                    add(m.group(1), "line", "custom")
                for m in _SEPARATED.finditer(sval.upper()):
                    add(m.group(1), source="custom")
                for m in _COMPACT.finditer(sval.upper()):
                    if m.group(1).upper() in _PREFIXES:
                        add(m.group(1) + m.group(2), source="custom")
                # Some custom fields contain a bare owner code with no known prefix.
                if len(found) == before and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{2,40}", sval):
                    add(sval, source="custom")

        walk(custom)

    return sorted(found.values(), key=lambda x: (x["type"], x["tag"]))


def asset_alias_set(items: Iterable[Any]) -> set[str]:
    out: set[str] = set()
    for item in items or ():
        tag = item.get("tag") if isinstance(item, dict) else str(item)
        out.update(tag_aliases(tag))
    return out


def asset_ocr_alias_set(items: Iterable[Any]) -> set[str]:
    out: set[str]=set()
    for item in items or ():
        if isinstance(item, dict) and item.get("ocr_aliases"):
            out.update(str(x) for x in item.get("ocr_aliases") or [])
        else:
            out.update(ocr_probable_aliases(item.get("tag") if isinstance(item,dict) else str(item)))
    return out


# Richer location ontology than the original `area/unit/spread` regex.  Tokens
# are intentionally hierarchical so exact rack/bay matches can coexist with a
# broader unit/area match.
_LOCATION_PATTERNS = (
    ("spread", r"\bspread\s*[-:#]?\s*([a-z0-9]+)"),
    ("section", r"\bsection\s*[-:#]?\s*([a-z0-9]+)"),
    ("zone", r"\bzone\s*[-:#]?\s*([a-z0-9]+)"),
    ("area", r"\barea\s*[-:#]?\s*([a-z0-9]+)"),
    ("unit", r"\bunit\s*[-:#]?\s*([a-z0-9]+)"),
    ("train", r"\btrain\s*[-:#]?\s*([a-z0-9]+)"),
    ("block", r"\bblock\s*[-:#]?\s*([a-z0-9]+)"),
    # Capture `Pipe Rack PR-02` as rack:02 rather than rack:pr, and never
    # misread ordinary words beginning with `pr` (e.g. "process") as a rack.
    ("rack", r"\b(?:pipe\s*)?rack\s*[-:#]?\s*(?:pr\s*[-:#]?\s*)?([a-z0-9]+)"),
    ("rack", r"\bpr[-:#]\s*([a-z0-9]{1,6})\b"),
    ("rack", r"\bpr\s+([a-z0-9]{1,6})\b"),
    ("rack", r"\bpr(\d{1,6})\b"),
    ("bay", r"\bbay\s*[-:#]?\s*([a-z0-9]+)"),
    ("building", r"\b(?:building|bldg)\s*[-:#]?\s*([a-z0-9]+)"),
    ("floor", r"\b(?:floor|level)\s*[-:#]?\s*([a-z0-9]+)"),
    ("grid", r"\b(?:grid|gridline)\s*[-:#]?\s*([a-z0-9]+(?:[/.-][a-z0-9]+)?)"),
    ("elevation", r"\b(?:elevation|elev|el)\s*[-:=]?\s*([+_-]?[a-z0-9.]+)"),
    ("substation", r"\bsubstation\s*[-:#]?\s*([a-z0-9]+)"),
    ("station", r"\bstation\s*[-:#]?\s*([a-z0-9]+)"),
    ("wellpad", r"\b(?:well\s*pad|wellpad)\s*[-:#]?\s*([a-z0-9]+)"),
    ("tankfarm", r"\b(?:tank\s*farm|tankfarm)\s*[-:#]?\s*([a-z0-9]+)?"),
)
_DIRECTION = re.compile(r"\b(north(?:ern)?|south(?:ern)?|east(?:ern)?|west(?:ern)?|ne|nw|se|sw)\b", re.I)
_SHORT_SITE = re.compile(r"\b(ps-?\d+|sv-?\d+|mlv-?\d+)\b", re.I)


def extract_location_tags(*texts: Any) -> list[str]:
    """Hierarchical location tags for a set of text/metadata fragments.

    Every candidate scored asks this about the same activity path and the same
    evidence text, so plain-text calls are memoised. Structured metadata is not
    hashable and takes the uncached path.
    """
    if all(t is None or isinstance(t, str) for t in texts):
        return list(_location_tags_cached(texts))
    return _extract_location_tags(*texts)


@functools.lru_cache(maxsize=32768)
def _location_tags_cached(texts: tuple) -> tuple:
    return tuple(_extract_location_tags(*texts))


def _extract_location_tags(*texts: Any) -> list[str]:
    # Preserve key names when custom/raw metadata is structured. Turning
    # {"Area": "B", "Pipe Rack": "PR-02"} into a bare dict string loses
    # exactly the semantics location filtering needs.
    chunks: list[str] = []
    location_key = re.compile(r"location|area|zone|unit|train|block|rack|bay|building|floor|level|grid|substation|station|well.?pad|tank.?farm|spread|section|elevation", re.I)
    def flatten(obj: Any, key: str = "") -> None:
        if isinstance(obj, dict):
            for k, v in obj.items(): flatten(v, str(k))
        elif isinstance(obj, (list, tuple, set)):
            for v in obj: flatten(v, key)
        elif obj not in (None, ""):
            if key and location_key.search(key): chunks.append(f"{key} {obj}")
            elif not key: chunks.append(str(obj))
    for t in texts:
        if isinstance(t, (dict, list, tuple, set)): flatten(t)
        elif t not in (None, ""): chunks.append(str(t))
    blob = " ".join(chunks).lower()
    out: set[str] = set()
    for typ, pat in _LOCATION_PATTERNS:
        for m in re.finditer(pat, blob, re.I):
            val = (m.group(1) if m.lastindex else "") or ""
            val = re.sub(r"[^a-z0-9]+", "", val.lower())
            out.add(typ + (":" + val if val else ""))
    for m in _SHORT_SITE.finditer(blob):
        out.add("site:" + m.group(1).lower().replace("-", ""))
    for m in _DIRECTION.finditer(blob):
        d = m.group(1).lower()
        d = {"northern": "north", "southern": "south", "eastern": "east", "western": "west"}.get(d, d)
        out.add("direction:" + d)
    return sorted(out)


_EVENT_ALIASES = {
    "start": ("started", "commenced", "mobilized", "mobilised", "began", "begin"),
    "finish": ("completed", "complete", "finished", "done", "closed out", "closed-out"),
    "erection": ("erect", "erected", "erection", "installed", "installation", "placed"),
    "fabrication": ("fabricat", "shop fabrication", "prefabricat"),
    "fitup": ("fit-up", "fitup", "fit up"),
    "welding": ("weld", "welding", "golden weld"),
    "ndt": ("ndt", "radiograph", "radiography", " rt ", " ut ", "mpi", "dpi", "aut"),
    "hydrotest": ("hydrotest", "hydro test", "pressure test", "hydrotesting"),
    "excavation": ("excavat", "trench"),
    "concrete": ("concrete", "pour", "cast", "foundation"),
    "cable_pull": ("cable pull", "cable laid", "cable laying"),
    "termination": ("terminat", "glanding"),
    "calibration": ("calibrat",),
    "alignment": ("align", "alignment"),
    "commissioning": ("commission", "pre-commission", "precommission"),
    "inspection": ("inspect", "inspection", "approved", "accepted"),
    "delivery": ("delivered", "received at site", "material received", "dispatch"),
}


def event_types(text: Any) -> list[str]:
    t = " " + str(text or "").lower() + " "
    out = []
    for event, aliases in _EVENT_ALIASES.items():
        if any(a in t for a in aliases):
            out.append(event)
    return out


def primary_event_type(text: Any) -> str | None:
    evs = event_types(text)
    # Domain action is more identifying than generic started/completed.
    for e in evs:
        if e not in {"start", "finish"}:
            return e
    return evs[0] if evs else None
