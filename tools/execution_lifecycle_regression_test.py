#!/usr/bin/env python3
"""Regression coverage for live run stages and project hand-off cancellation."""
from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
from pathlib import Path


tmp = Path(tempfile.mkdtemp(prefix="veda-lifecycle-"))
os.environ["VEDA_DATA_DIR"] = str(tmp)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from veda import db, jobs  # noqa: E402
from veda.pipeline import linking  # noqa: E402
from veda.retrieval import engine as retrieval_engine  # noqa: E402
from veda.resolution import rescheduler  # noqa: E402


def wait_for(predicate, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


db.init_db()

# The resolver must expose durable, bounded progress stages even when there are
# no candidates. This keeps the UI truthful without depending on animation time.
resolver_pid = db.insert("projects", {
    "name": "Resolver stages", "status": "active",
    "created_at": db.now(), "updated_at": db.now(),
})
evidence_id = db.insert("evidence", {
    "project_id": resolver_pid, "source_file": "field.txt",
    "description": "Pipe support installed in Area A", "state": "new",
    "security_state": "clean", "created_at": db.now(),
})
evidence = db.q1("SELECT * FROM evidence WHERE id=?", [evidence_id])
phases: list[str] = []
checkpoints = 0
original_index = retrieval_engine.index_project
original_search = retrieval_engine.hybrid_search


def check() -> None:
    global checkpoints
    checkpoints += 1


try:
    retrieval_engine.index_project = lambda *args, **kwargs: {
        "activities": 0, "indexed": 0, "embedding_backend": "test",
    }
    retrieval_engine.hybrid_search = lambda *args, **kwargs: {
        "candidates": [], "diagnostics": {},
    }
    linking.link_evidence(
        resolver_pid, evidence_rows=[evidence], raise_reviews=False,
        progress=lambda phase, label, detail=None: phases.append(phase),
        cancel_check=check,
    )
finally:
    retrieval_engine.index_project = original_index
    retrieval_engine.hybrid_search = original_search

assert phases == [
    "resolver_indexing", "resolver_experts", "resolver_ranking",
    "resolver_validating",
], phases
assert checkpoints >= 4, checkpoints

# Rescheduler cancellation is allowed to escape immediately rather than being
# converted into an expert failure and leaving the worker occupied.
class SyntheticCancel(RuntimeError):
    pass


try:
    rescheduler.standalone_rank(
        resolver_pid, {"description": "cancel me"},
        cancel_check=lambda: (_ for _ in ()).throw(SyntheticCancel("stop")),
    )
    raise AssertionError("rescheduler swallowed cancellation")
except SyntheticCancel:
    pass

# Deleting the current project must release the single worker so activated work
# for a newly created project does not remain queued behind the deleted run.
old_pid = db.insert("projects", {
    "name": "Old", "status": "active", "created_at": db.now(),
    "updated_at": db.now(),
})
new_pid = db.insert("projects", {
    "name": "New", "status": "active", "created_at": db.now(),
    "updated_at": db.now(),
})
old_started = threading.Event()
original_run_analysis = jobs._run_analysis


def cancellable_analysis(job_id: str, project_id: str, payload: dict) -> dict:
    if project_id == old_pid:
        old_started.set()
        while True:
            jobs._raise_if_cancelled(job_id)
            time.sleep(0.01)
    jobs.step(job_id, project_id, "associations_validated", "New project completed")
    return {"project_id": project_id}


jobs._run_analysis = cancellable_analysis
try:
    jobs.start_worker()
    jobs.activate_project(old_pid)
    old_job = jobs.create_job(old_pid, "analysis")
    jobs.enqueue(old_job, priority=True)
    assert old_started.wait(2.0), "old job never started"

    deleted = jobs.delete_project(old_pid)
    assert deleted.get("cleanup_pending") is True, deleted
    jobs.activate_project(new_pid)
    new_job = jobs.create_job(new_pid, "analysis")
    jobs.enqueue(new_job, priority=True)

    assert wait_for(lambda: (db.q1("SELECT status FROM jobs WHERE id=?", [new_job])
                             or {}).get("status") == "done"), \
        "new project remained queued behind cancelled work"
    assert wait_for(lambda: db.q1("SELECT id FROM projects WHERE id=?", [old_pid])
                    is None), "deleted project was not purged after worker release"
finally:
    jobs._run_analysis = original_run_analysis

print("execution lifecycle regression test: ok")
