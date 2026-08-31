"""Ambiguous date interpretation that never overwrites the raw source value.

A construction document is full of dates written in locale-specific and
shorthand forms: ``10.03.2017``, ``4-Oct-17``, ``21/09/17``.  Silently picking
one calendar order (the old behaviour) destroys evidence.  This module keeps the
raw string, produces every calendar-valid interpretation, and ranks them using
whatever temporal context the caller can supply (other dates in the same
document, the project schedule window).  The raw value is always preserved.
"""
from __future__ import annotations

import re
from datetime import date

_MONTHS = {m: i for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"), start=1)}

_ISO = re.compile(r"^\s*(\d{4})-(\d{1,2})-(\d{1,2})(?:[ T].*)?$")
_NUMERIC = re.compile(r"^\s*(\d{1,4})\s*[./\-]\s*(\d{1,2})\s*[./\-]\s*(\d{1,4})\s*$")
_DMON = re.compile(r"^\s*(\d{1,2})[\s./\-]+([A-Za-z]{3,9})\.?[\s./\-,]+(\d{2,4})\s*$")
_MOND = re.compile(r"^\s*([A-Za-z]{3,9})\.?[\s./\-]+(\d{1,2})(?:st|nd|rd|th)?[\s./\-,]+(\d{2,4})\s*$")

# How close (in days) an interpretation must sit to a known context date before
# that agreement is treated as meaningful corroboration.
_CONTEXT_WINDOW_DAYS = 150


def _yr(y: int) -> int:
    if y >= 100:
        return y
    return 2000 + y if y <= 69 else 1900 + y


def _mk(y: int, m: int, d: int):
    try:
        return date(_yr(y), m, d)
    except ValueError:
        return None


def _band(p: float) -> str:
    return "high" if p >= 0.8 else "medium" if p >= 0.5 else "low"


def _candidates(raw: str) -> list[tuple]:
    """Return [(date, format_label, base_plausibility, basis)] for a raw string."""
    out: list[tuple] = []
    m = _ISO.match(raw)
    if m:
        dt = _mk(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if dt:
            out.append((dt, "YYYY-MM-DD", 0.99, "unambiguous ISO-8601 order"))
        return out

    m = _DMON.match(raw)
    if m and m.group(2).lower()[:3] in _MONTHS:
        dt = _mk(int(m.group(3)), _MONTHS[m.group(2).lower()[:3]], int(m.group(1)))
        if dt:
            out.append((dt, "DD-Mon-YYYY", 0.97, "alphabetic month name fixes the order"))
        return out

    m = _MOND.match(raw)
    if m and m.group(1).lower()[:3] in _MONTHS:
        dt = _mk(int(m.group(3)), _MONTHS[m.group(1).lower()[:3]], int(m.group(2)))
        if dt:
            out.append((dt, "Mon-DD-YYYY", 0.97, "alphabetic month name fixes the order"))
        return out

    m = _NUMERIC.match(raw)
    if m:
        a, b, c = int(m.group(1)), int(m.group(2)), int(m.group(3))
        variants: list[tuple] = []
        if c > 31:                       # trailing year: dd?mm?yyyy
            variants.append((_mk(c, b, a), "DD.MM.YYYY", a, b))
            variants.append((_mk(c, a, b), "MM.DD.YYYY", b, a))
        if a > 31:                       # leading year: yyyy?mm?dd
            variants.append((_mk(a, b, c), "YYYY-MM-DD", c, b))
            variants.append((_mk(a, c, b), "YYYY-DD-MM", b, c))
        seen: set[str] = set()
        for dt, label, day_field, month_field in variants:
            if not dt or dt.isoformat() in seen:
                continue
            seen.add(dt.isoformat())
            forced = day_field > 12 >= month_field
            out.append((dt, label,
                        0.9 if forced else 0.5,
                        "day field exceeds 12 so the order is forced" if forced
                        else "numeric date with an ambiguous day/month order"))
    return out


def _coerce(value) -> "date | None":
    if isinstance(value, date):
        return value
    parsed = _candidates(str(value or "").strip())
    return parsed[0][0] if parsed else None


def interpret(raw, context_dates=None) -> dict:
    """Interpret ``raw`` without ever discarding it.

    Returns::

        {
          "raw": "10.03.2017",              # verbatim, never mutated
          "normalized": "2017-10-03",       # best interpretation (or None)
          "date_format_interpretation": "MM.DD.YYYY",
          "confidence": "high|medium|low",
          "reason": "...",
          "ambiguous": True,
          "interpretations": [{"iso","format","plausibility","basis"}, ...]
        }
    """
    raw_s = "" if raw is None else str(raw).strip()
    result = {"raw": raw_s or None, "normalized": None,
              "date_format_interpretation": None, "confidence": None,
              "reason": None, "ambiguous": False, "interpretations": []}
    if not raw_s:
        return result

    ctx = [d for d in (_coerce(c) for c in (context_dates or [])) if d]
    cands = _candidates(raw_s)
    if not cands:
        result["reason"] = "no recognisable date pattern"
        return result

    ranked: list[dict] = []
    for dt, label, base, basis in cands:
        plausibility = base
        note = basis
        if ctx:
            nearest = min(abs((dt - c).days) for c in ctx)
            if nearest <= _CONTEXT_WINDOW_DAYS:
                plausibility = min(0.99, base + 0.4 * (1 - nearest / _CONTEXT_WINDOW_DAYS))
                note = basis + f"; within {nearest}d of other project dates"
            else:
                plausibility = max(0.05, base - 0.25)
                note = basis + f"; {nearest}d from the nearest project date"
        if dt > date.today():
            plausibility = min(plausibility, 0.15)
            note += "; interpretation lies in the future"
        ranked.append({"iso": dt.isoformat(), "format": label,
                       "plausibility": round(plausibility, 3), "basis": note})

    ranked.sort(key=lambda r: -r["plausibility"])
    deduped: list[dict] = []
    seen: set[str] = set()
    for item in ranked:
        if item["iso"] in seen:
            continue
        seen.add(item["iso"])
        deduped.append(item)

    best = deduped[0]
    result["interpretations"] = deduped
    result["normalized"] = best["iso"]
    result["date_format_interpretation"] = best["format"]
    result["confidence"] = _band(best["plausibility"])
    result["ambiguous"] = len(deduped) > 1
    if len(deduped) > 1:
        result["reason"] = (f"{best['format']} preferred over {deduped[1]['format']}: "
                            f"{best['basis']}.")
    else:
        result["reason"] = best["basis"] + "."
    return result


def best_iso(raw, context_dates=None) -> "str | None":
    """Convenience: the preferred ISO interpretation only."""
    return interpret(raw, context_dates).get("normalized")
