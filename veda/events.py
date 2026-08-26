"""VEDA event bus (spec 5).

The website talks to the backend; the backend raises events; the agent wakes on
those events. Nothing polls the filesystem. Events are durable rows first and
in-process notifications second, so a crash mid-flight loses no trigger.
"""
from __future__ import annotations

import queue
import threading
from typing import Any, Callable

from . import db

# spec 5 - the vocabulary the platform reacts to
DATASET_UPLOADED = "dataset_uploaded"
FILES_ADDED = "files_added"
ANALYSIS_REQUESTED = "analysis_requested"
REVIEW_ANSWERED = "review_answered"
REVIEW_APPROVED = "review_approved"
REVIEW_REJECTED = "review_rejected"
SCHEDULE_CHANGED = "schedule_changed"
REPROCESS_REQUESTED = "reprocess_requested"
USER_QUESTION = "user_question"

WAKE_EVENTS = {
    DATASET_UPLOADED, FILES_ADDED, ANALYSIS_REQUESTED, REVIEW_ANSWERED,
    REVIEW_APPROVED, REVIEW_REJECTED, SCHEDULE_CHANGED, REPROCESS_REQUESTED,
    USER_QUESTION,
}

_handlers: list = []
_streams: list = []
_lock = threading.RLock()


def on_event(fn: Callable[[dict], None]) -> None:
    """Register a backend handler (the job orchestrator uses this)."""
    with _lock:
        _handlers.append(fn)


def emit(type_: str, project_id: str | None = None, payload: dict | None = None,
         source: str = "backend") -> dict:
    ev = {
        "id": db.new_id("ev_"),
        "project_id": project_id,
        "type": type_,
        "payload_json": db.jdumps(payload or {}),
        "source": source,
        "consumed": 0,
        "created_at": db.now(),
    }
    db.insert("events", ev)
    rec = dict(ev)
    rec["payload"] = payload or {}

    with _lock:
        handlers = list(_handlers)
        streams = list(_streams)
    for fn in handlers:
        try:
            fn(rec)
        except Exception:
            pass
    for q in streams:
        try:
            q.put_nowait(rec)
        except Exception:
            pass
    return rec


def mark_consumed(event_id: str) -> None:
    db.ex("UPDATE events SET consumed=1 WHERE id=?", [event_id])


# ------------------------------------------------------------ live streaming
class Stream:
    """A bounded fan-out queue used by the dashboard's SSE endpoint."""

    def __init__(self, project_id: str | None = None, maxsize: int = 500):
        self.project_id = project_id
        self.q: queue.Queue = queue.Queue(maxsize=maxsize)

    def put_nowait(self, rec: dict) -> None:
        if self.project_id and rec.get("project_id") not in (None, self.project_id):
            return
        try:
            self.q.put_nowait(rec)
        except queue.Full:
            try:
                self.q.get_nowait()
                self.q.put_nowait(rec)
            except Exception:
                pass

    def get(self, timeout: float = 1.0):
        try:
            return self.q.get(timeout=timeout)
        except queue.Empty:
            return None

    def close(self) -> None:
        with _lock:
            if self in _streams:
                _streams.remove(self)


def open_stream(project_id: str | None = None) -> Stream:
    s = Stream(project_id)
    with _lock:
        _streams.append(s)
    return s


def recent(project_id: str | None = None, limit: int = 100) -> list:
    if project_id:
        rows = db.q("SELECT * FROM events WHERE project_id=? "
                    "ORDER BY created_at DESC LIMIT ?", [project_id, limit])
    else:
        rows = db.q("SELECT * FROM events ORDER BY created_at DESC LIMIT ?", [limit])
    for r in rows:
        r["payload"] = db.jloads(r.pop("payload_json", None), {})
    return rows


def notify_ui(project_id: str, kind: str, data: dict | None = None) -> None:
    """Push a UI refresh hint without creating a durable workflow event."""
    rec = {"id": db.new_id("ui_"), "project_id": project_id, "type": "ui:" + kind,
           "payload": data or {}, "source": "backend", "created_at": db.now()}
    with _lock:
        streams = list(_streams)
    for q in streams:
        try:
            q.put_nowait(rec)
        except Exception:
            pass
