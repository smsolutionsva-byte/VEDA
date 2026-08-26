"""File intake: store, hash, classify, scan (spec 6, 12, 56)."""
from __future__ import annotations

import hashlib
import os
import re
import shutil
from datetime import datetime
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


def _classify_stored(path: str, ext: str, relative_path: str | None = None) -> tuple[str, dict | None]:
    """Classify from both format and content.

    CSV/XLSX are ambiguous in construction projects: they can be DPR evidence,
    trackers, or an exported schedule.  Only promote a tabular file when its
    column structure is confidently schedule-shaped; filenames alone never do it.
    """
    ext = ext.lower()
    if ext == ".xml":
        return ("schedule" if _looks_like_schedule_xml(path) else "evidence"), None
    if ext in config.SCHEDULE_EXTS:
        return "schedule", None
    if ext in {".csv", ".tsv", ".xlsx", ".xlsm"}:
        try:
            from ..mcpc import tabular_schedule
            meta = tabular_schedule.inspect(path, relative_path)
            if meta.get("candidate"):
                return "schedule", meta
        except Exception:
            pass
        return "evidence", None
    if ext in config.EVIDENCE_EXTS:
        return "evidence", None
    # Extensionless XER occasionally appears in exported project folders.
    try:
        with open(path, "rb") as fh:
            head = fh.read(65536)
        text = head.decode("utf-8-sig", errors="ignore")
        if text.startswith("ERMHDR") and "%T\tPROJECT" in text and "%T\tTASK" in text:
            return "schedule", {"detected_as": "xer_content"}
        if "<Project" in text and ("mspdi" in text.lower() or "schemas.microsoft.com/project" in text.lower()):
            return "schedule", {"detected_as": "mspdi_content"}
    except Exception:
        pass
    return "unknown", None


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
                 content_type: str | None = None, uploaded_by: str = "human",
                 batch_id: str | None = None, source_mode: str = "file",
                 trusted_human: bool = False, relative_path: str | None = None) -> dict:
    """Persist one source immutably, classify it, and security-scan evidence.

    v0.1.2 makes ingestion idempotent per project: identical bytes already in
    the project are not stored/extracted twice. The caller still receives a
    duplicate result so a batch can report what happened.
    """
    pdir = config.project_dir(project_id)
    name = safe_name(filename)
    rel = str(relative_path or filename or name).replace("\\", "/").lstrip("/")[:1000]
    files_dir = pdir / "files"

    # Hash before allocating the final immutable path. This means repeated
    # drag/drop, paste or browser retries do not create duplicate evidence.
    digest = hashlib.sha256(data).hexdigest()
    dup = db.q1("SELECT id, filename, stored_path, ext, kind, size_bytes, "
                "security_state FROM files WHERE project_id=? AND sha256=? "
                "ORDER BY created_at ASC LIMIT 1", [project_id, digest])
    if dup:
        audit.record(project_id, actor=uploaded_by, actor_type="human",
                     action="duplicate_upload_skipped", source="website",
                     entity_type="file", entity_id=dup["id"],
                     new_value=name, result="skipped",
                     detail={"sha256": digest, "duplicate_of": dup["id"],
                             "batch_id": batch_id, "source_mode": source_mode,
                         "relative_path": rel})
        return {"id": dup["id"], "filename": dup["filename"],
                "path": dup.get("stored_path"), "ext": dup.get("ext"),
                "kind": dup.get("kind"), "sha256": digest,
                "size_bytes": dup.get("size_bytes") or len(data),
                "security_state": dup.get("security_state") or "clean",
                "duplicate_of": dup["id"], "skipped": True,
                "source_mode": source_mode, "batch_id": batch_id,
                "relative_path": rel}

    dest = files_dir / name
    stem, ext = os.path.splitext(name)
    n = 1
    while dest.exists():
        dest = files_dir / (stem + "_" + str(n) + ext)
        n += 1
    dest.write_bytes(data)

    ext = ext.lower()
    kind, candidate_meta = _classify_stored(str(dest), ext, rel)

    sec = {"state": "clean", "note": None, "findings": []}
    # Deliberate operator text is an instruction/evidence source by design. It
    # must not be quarantined merely for containing words such as update/delete.
    # It is still constrained downstream by proposal approval + dry-run rules.
    if kind != "schedule" and not trusted_human:
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
        "security_state": sec["state"], "security_notes": sec.get("note"),
        "extract_state": "pending", "batch_id": batch_id,
        "source_mode": source_mode or "file", "relative_path": rel,
    })

    audit.record(project_id, actor=uploaded_by, actor_type="human",
                 action="file_uploaded", source="website",
                 entity_type="file", entity_id=fid,
                 new_value=dest.name, result="stored",
                 detail={"sha256": digest, "kind": kind,
                         "bytes": dest.stat().st_size,
                         "security_state": sec["state"],
                         "batch_id": batch_id, "source_mode": source_mode,
                         "relative_path": rel})

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
                     "Release for analysis as data only", "Delete the file"],
            entity_type="file", entity_id=fid, priority="high",
            extra={"findings": sec.get("findings", [])[:10]})
        audit.record(project_id, actor="system", actor_type="system",
                     action="file_quarantined", source="security_scan",
                     entity_type="file", entity_id=fid,
                     new_value=sec["state"], result=sec.get("note"))

    return {"id": fid, "filename": dest.name, "path": str(dest), "ext": ext,
            "kind": kind, "sha256": digest, "size_bytes": dest.stat().st_size,
            "security_state": sec["state"], "duplicate_of": None,
            "skipped": False, "source_mode": source_mode, "batch_id": batch_id,
            "relative_path": rel, "schedule_candidate": candidate_meta}


def store_text_input(project_id: str, text: str, source_mode: str = "field_note",
                     title: str | None = None, batch_id: str | None = None,
                     uploaded_by: str = "human") -> dict:
    """Turn pasted/operator text into an immutable, citable project source."""
    mode = source_mode if source_mode in {"field_note", "whatsapp", "change_request"} \
        else "field_note"
    clean_title = safe_name((title or mode.replace("_", " ").title()).strip())
    if not clean_title.lower().endswith(".txt"):
        clean_title += ".txt"
    # Timestamp keeps separate operator notes readable in the file list; byte
    # hashing still deduplicates exact repeated pastes.
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    stem, ext = os.path.splitext(clean_title)
    filename = f"{stem}_{stamp}{ext}"
    return store_upload(project_id, filename, text.encode("utf-8"), "text/plain",
                        uploaded_by=uploaded_by, batch_id=batch_id,
                        source_mode=mode, trusted_human=True)


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
