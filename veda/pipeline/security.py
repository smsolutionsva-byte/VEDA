"""Uploaded documents are untrusted DATA (spec 56).

A construction document has no legitimate reason to address the system that is
reading it. When one does, VEDA quarantines it and raises a security_review
rather than silently trusting or silently discarding it.
"""
from __future__ import annotations

import re

# Patterns that indicate a document is trying to steer the reader rather than
# report site facts. Kept explicit so a reviewer can see exactly what fired.
PATTERNS = [
    (r"ignore\s+(all\s+)?(previous|prior|above|earlier)\s+instructions?",
     "instruction override", "critical"),
    (r"disregard\s+(all\s+)?(previous|prior|above|earlier|your)\s+"
     r"(instructions?|rules?|prompt)", "instruction override", "critical"),
    (r"\bsystem\s*(message|prompt)\s*[:\-]", "forged system message", "critical"),
    (r"</?\s*(system|assistant|user)\s*>", "forged role tag", "critical"),
    (r"\byou\s+are\s+now\s+in\s+\w+\s+mode\b", "mode switch attempt", "critical"),
    (r"approve\s+(every|all)\s+(pending\s+)?(change|proposal|request)",
     "approval coercion", "critical"),
    (r"\b(delete|drop|wipe|erase)\s+(the\s+)?"
     r"(schedule|baseline|database|project|audit)", "destructive instruction",
     "critical"),
    (r"set\s+(every|all)\s+activit(y|ies)\s+to\s+100",
     "progress falsification", "critical"),
    (r"do\s+not\s+(report|tell|inform|mention)\s+(this|it)?\s*(to\s+)?"
     r"(the\s+)?(user|human|operator)", "concealment instruction", "critical"),
    (r"without\s+(human\s+)?(review|approval|confirmation)",
     "approval bypass", "high"),
    (r"\breply\s+only\s+with\b", "output hijack", "high"),
    (r"\b(bypass|skip|disable)\s+(the\s+)?(validation|validator|check|"
     r"security|permission)", "control bypass", "high"),
    (r"\bexfiltrat|\bsend\s+.{0,30}\bto\s+https?://", "exfiltration attempt",
     "critical"),
]

_COMPILED = [(re.compile(p, re.I), label, sev) for p, label, sev in PATTERNS]

SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}


def scan(text: str, *, max_chars: int = 400_000) -> dict:
    """Scan document text. Returns state, findings and a human-readable note."""
    if not text:
        return {"state": "clean", "findings": [], "note": None}
    sample = text[:max_chars]
    findings = []
    for rx, label, sev in _COMPILED:
        for m in rx.finditer(sample):
            start = max(0, m.start() - 70)
            end = min(len(sample), m.end() + 70)
            findings.append({
                "label": label,
                "severity": sev,
                "match": m.group(0)[:160],
                "excerpt": sample[start:end].replace("\n", " ").strip()[:300],
                "offset": m.start(),
            })
            break  # one hit per pattern is enough to justify review

    if not findings:
        return {"state": "clean", "findings": [], "note": None}

    worst = max(SEVERITY_RANK.get(f["severity"], 1) for f in findings)
    state = "quarantined" if worst >= 4 else "suspicious"
    labels = sorted({f["label"] for f in findings})
    note = ("Document contains " + str(len(findings)) + " pattern(s) that attempt to "
            "instruct the reader rather than report project facts: " +
            ", ".join(labels) + ". Treated as data only.")
    return {"state": state, "findings": findings, "note": note}


def sanitize_for_display(text: str, limit: int = 4000) -> str:
    """Neutralise role tags so flagged content is safe to render in the UI."""
    out = text[:limit]
    out = re.sub(r"<\s*/?\s*(system|assistant|user)\s*>", "[role-tag-removed]",
                 out, flags=re.I)
    return out
