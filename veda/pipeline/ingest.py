"""File intake: store, hash, classify, scan (spec 6, 12, 56)."""
from __future__ import annotations

import hashlib
import os
import re
import shutil
from pathlib import Path

from .. import audit, config, db
from . import security

_SAFE = re.compile(r"[^A-Za-z0-9._ \-()+]")


def safe_name(name: str) -> str:
    base = os.path.basename(str(name or "upload")).strip()
    base = _SAFE.sub("_", base)
    return base[:180] or "upload"


def sha256_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 256), b""):
            h.update(chunk)
    return h.hexdigest()


def classify(ext: str) -> str:
    ext = ext.lower()
    if ext in config.SCHEDULE_EXTS:
        return "schedule"
    if ext in config.EVIDENCE_EXTS:
        return "evidence"
    return "unknown"


def _looks_like_schedule_xml(path: str) -> bool:
    """.xml is ambiguous: MSPDI is a schedule, arbitrary XML is not."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            head = f.read(4000)
    except Exception:
        return False
    return ("<Project" in head and "mspdi" in head.lower()) or \
           "schemas.microsoft.com/project" in head.lower() or \
           "<APIBusinessObjects" in head


def store_upload(project_id: str, filename: str, data: bytes,
                 content_type: str | None = None, uploaded_by: str = "human") -> dict:
    """Persist one uploaded file with provenance, then classify and scan it.

    The stored copy is the source document and is never modified in place
    (spec 12). Revisions and outputs are written elsewhere.
    """
    pdir = config.project_dir(project_id)
    name = safe_name(filename)
    dest = pdir / "files" / name
    stem, ext = os.path.splitext(name)
    n = 1
    while dest.exists():
        dest = pdir / "files" / (stem + "_" + str(n) + ext)
        n += 1
    dest.write_bytes(data)

    ext = ext.lower()
    kind = classify(ext)
    if ext == ".xml":
        kind = "schedule" if _looks_like_schedule_xml(str(dest)) else "evidence"

    digest = sha256_of(str(dest))
    dup = db.q1("SELECT id, filename FROM files WHERE project_id=? AND sha256=?",
                [project_id, digest])

    sec = {"state": "clean", "note": None, "findings": []}
    if kind != "schedule":
        from . import extract
        try:
            text = extract.full_text(str(dest), ext)
            sec = security.scan(text)
        except Exception:
            sec = {"state": "clean", "note": None, "findings": []}

    fid = db.insert("files", {
        "project_id": project_id, "filename": dest.name, "stored_path": str(dest),
        "ext": ext, "size_bytes": dest.stat().st_size, "sha256": digest,
        "kind": kind, "content_type": content_type, "uploaded_by": uploaded_by,
        "security_state": sec["state"],
        "security_notes": sec.get("note"),
        "extract_state": "pending",
    })

    audit.record(project_id, actor=uploaded_by, actor_type="human",
                 action="file_uploaded", source="website",
                 entity_type="file", entity_id=fid,
                 new_value=dest.name, result="stored",
                 detail={"sha256": digest, "kind": kind, "bytes": dest.stat().st_size,
                         "security_state": sec["state"],
                         "duplicate_of": (dup or {}).get("id")})

    if sec["state"] != "clean":
        from .. import reviews as reviews_mod
        reviews_mod.create(
            project_id=project_id, kind="security_review",
            title="Suspicious content in " + dest.name,
            question=("This uploaded document contains text that tries to instruct "
                      "the analysis system rather than report project facts. VEDA "
                      "has treated it as data only and withheld it from the agent. "
                      "How should it be handled?"),
            detail=sec.get("note"),
            options=["Quarantine permanently (recommended)",
                     "Release for analysis as data only",
                     "Delete the file"],
            entity_type="file", entity_id=fid, priority="high",
            extra={"findings": sec.get("findings", [])[:10]})
        audit.record(project_id, actor="system", actor_type="system",
                     action="file_quarantined", source="security_scan",
                     entity_type="file", entity_id=fid,
                     new_value=sec["state"], result=sec.get("note"))

    return {"id": fid, "filename": dest.name, "path": str(dest), "ext": ext,
            "kind": kind, "sha256": digest, "size_bytes": dest.stat().st_size,
            "security_state": sec["state"], "duplicate_of": (dup or {}).get("id")}


def revision_path(project_id: str, original: str, suffix: str = "rev") -> Path:
    """Where a modified copy goes. The original is never overwritten (spec 12)."""
    pdir = config.project_dir(project_id)
    stem = Path(original).stem
    n = 1
    while True:
        cand = pdir / "revisions" / (stem + "_" + suffix + str(n) + ".xml")
        if not cand.exists():
            return cand
        n += 1


def copy_for_edit(project_id: str, source_path: str, suffix: str = "rev") -> str:
    dest = revision_path(project_id, source_path, suffix)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, dest)
    return str(dest)
