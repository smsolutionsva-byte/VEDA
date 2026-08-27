"""Tree-aware WBS context features.

WBS is a hierarchy, not prose.  Identical activity names under different units,
areas or systems must be disambiguated using ancestry rather than cosine
similarity over one flattened string.
"""
from __future__ import annotations

import re
from typing import Any

from ..retrieval.entities import extract_location_tags

STOP = {"project", "works", "work", "construction", "engineering", "package", "activity", "activities"}


def _norm_token(v: Any) -> str:
    s = re.sub(r"[^a-z0-9]+", "", str(v or "").lower())
    return s


def path_segments(act: dict) -> list[str]:
    # Human-readable path is preferred; WBS codes are used as an additional view.
    raw = str(act.get("wbs_path") or act.get("wbs_name") or "")
    segs = [x.strip() for x in re.split(r"\s*>\s*|\s*\|\s*|\s*/\s*", raw) if x.strip()]
    if not segs and act.get("wbs"):
        segs = [x.strip() for x in re.split(r"[.>]", str(act.get("wbs"))) if x.strip()]
    return segs


def code_segments(act: dict) -> list[str]:
    return [x for x in re.split(r"[.>/_-]+", str(act.get("wbs") or "").lower()) if x]


def evidence_tokens(ev: dict) -> set[str]:
    out: set[str] = set()
    text = " ".join(str(ev.get(k) or "") for k in ("description", "location", "discipline", "contractor", "crew"))
    for token in re.findall(r"[A-Za-z]+\d*|\d+[A-Za-z]+", text.lower()):
        n = _norm_token(token)
        if len(n) >= 2 and n not in STOP:
            out.add(n)
    for loc in extract_location_tags(ev.get("location"), ev.get("description"), ev.get("raw_json")):
        out.add(_norm_token(loc))
        if ":" in loc:
            typ, val = loc.split(":", 1)
            out.update({_norm_token(typ), _norm_token(val), _norm_token(typ + val)})
    return {x for x in out if x}


def _segment_tokens(seg: str) -> set[str]:
    vals = {_norm_token(x) for x in re.findall(r"[A-Za-z]+\d*|\d+[A-Za-z]+", seg)}
    return {x for x in vals if len(x) >= 2 and x not in STOP}


def features(ev: dict, act: dict) -> dict:
    e = evidence_tokens(ev)
    segs = path_segments(act)
    csegs = code_segments(act)
    seg_tok = [_segment_tokens(s) for s in segs]
    all_tok = set().union(*seg_tok) if seg_tok else set()

    exact_hits = e & all_tok
    path_overlap = len(exact_hits) / max(1, min(len(e), 8)) if e else 0.0
    # Do not reward a candidate merely for having a deeper path.  The previous
    # `[:-1]` logic made "... > Mechanical > Phase 2" score *higher* than
    # "... > Mechanical" because Mechanical changed from leaf to ancestor.
    hierarchy_hits = sum(1 for toks in seg_tok if e & toks)
    ancestor_ratio = hierarchy_hits / max(1, min(len(seg_tok), 6)) if seg_tok else 0.0

    # Explicit location hierarchy is particularly discriminative for OIL/EPC data.
    ev_locs = set(extract_location_tags(ev.get("location"), ev.get("description"), ev.get("raw_json")))
    path_locs = set(extract_location_tags(" > ".join(segs), act.get("wbs_name"), act.get("name")))
    loc_inter = ev_locs & path_locs
    loc_conflict = False
    if ev_locs and path_locs and not loc_inter:
        # Only call it a conflict when the same hierarchical type exists on both sides.
        by_type_ev = {x.split(":",1)[0]: x for x in ev_locs if ":" in x}
        by_type_act = {x.split(":",1)[0]: x for x in path_locs if ":" in x}
        loc_conflict = any(t in by_type_act and by_type_ev[t] != by_type_act[t] for t in by_type_ev)

    # Longest matching leading WBS-code prefix can be learned from source metadata
    # if the evidence itself carries a WBS code in raw fields.
    raw = ev.get("raw_json")
    raw_s = str(raw or "")
    m = re.search(r"(?:wbs|work\s*breakdown)[^A-Za-z0-9]{0,6}([A-Za-z0-9_.\-/]+)", raw_s, re.I)
    exact_code = 0.0
    code_prefix = 0.0
    if m and csegs:
        qsegs = [x for x in re.split(r"[.>/_-]+", m.group(1).lower()) if x]
        same = 0
        for a, b in zip(qsegs, csegs):
            if _norm_token(a) != _norm_token(b):
                break
            same += 1
        code_prefix = same / max(1, len(qsegs))
        exact_code = 1.0 if qsegs == csegs else 0.0

    score = 0.20
    score += 0.28 * min(1.0, path_overlap * 2.0)
    score += 0.22 * min(1.0, ancestor_ratio)
    score += 0.22 if loc_inter else 0.0
    score += 0.25 * exact_code + 0.12 * code_prefix
    if loc_conflict:
        score -= 0.42
    score = max(0.0, min(1.0, score))
    return {
        "score": score,
        "path_overlap": min(1.0, path_overlap),
        "ancestor_match": min(1.0, ancestor_ratio),
        "location_match": 1.0 if loc_inter else 0.0,
        "location_conflict": 1.0 if loc_conflict else 0.0,
        "exact_code": exact_code,
        "code_prefix": code_prefix,
        "matched_tokens": sorted(exact_hits)[:10],
        "path": " > ".join(segs),
    }
