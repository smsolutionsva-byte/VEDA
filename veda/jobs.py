"""Job orchestration: events wake the agent, VEDA keeps the state (spec 5-7).

A single worker thread runs jobs in order. That keeps SQLite writes and the
Horizun session simple to reason about, and a construction project does not
need more concurrency than this. Failure never loses work: files, project,
reviews and previous results all survive, and the job can be retried (spec 57).
"""
from __future__ import annotations

import asyncio
import queue
import threading
import traceback
from typing import Any

from . import audit, config, db, events, reviews
from .agent import registry, schemas
from .agent.prompts import SYSTEM, analysis_prompt, question_prompt, resume_prompt
from .mcpc import McpError, horizun, schedule_ops
from .pipeline import deterministic, extract, linking, proposals

_queue: "queue.Queue[str]" = queue.Queue()
_worker: threading.Thread | None = None
_started = False
_current: dict = {"job_id": None}


# ----------------------------------------------------------------- job records
def create_job(project_id: str, kind: str, trigger_event_id: str | None = None,
               payload: dict | None = None) -> str:
    jid = db.insert("jobs", {
        "project_id": project_id, "kind": kind, "status": "queued",
        "phase": "queued", "progress": 0.0,
        "trigger_event_id": trigger_event_id,
        "provider": registry.active_provider_name(),
        "result_json": db.jdumps({"input": payload or {}}),
    })
    audit.record(project_id, actor="system", actor_type="system",
                 action="job_created", job_id=jid, entity_type="job",
                 entity_id=jid, new_value=kind, result="queued")
    events.notify_ui(project_id, "jobs_changed", {"job_id": jid})
    return jid


def step(job_id: str, project_id: str, name: str, label: str,
         state: str = "success", detail: str | None = None) -> None:
    """Safe, high-level agent progress (spec 50). No chain-of-thought."""
    db.insert("agent_activity", {
        "project_id": project_id, "job_id": job_id, "step": name,
        "label": label, "state": state, "detail": detail,
    })
    db.update("jobs", job_id, {"phase": name})
    events.notify_ui(project_id, "activity", {"job_id": job_id, "step": name,
                                              "label": label, "state": state})


def _finish(job_id: str, project_id: str, status: str, error: str | None = None,
            result: dict | None = None) -> None:
    patch: dict = {"status": status, "finished_at": db.now(), "progress": 1.0}
    if error:
        patch["error"] = error[:4000]
    if result is not None:
        patch["result_json"] = db.jdumps(result)
    db.update("jobs", job_id, patch)
    audit.record(project_id, actor="system", actor_type="system",
                 action="job_" + status, job_id=job_id, entity_type="job",
                 entity_id=job_id, result=error or status)
    events.notify_ui(project_id, "jobs_changed", {"job_id": job_id,
                                                  "status": status})


# --------------------------------------------------------------- event wiring
def handle_event(ev: dict) -> None:
    """Wake the platform on a backend event. Never polls (spec 5)."""
    etype = ev.get("type")
    project_id = ev.get("project_id")
    if not project_id or etype not in events.WAKE_EVENTS:
        return
    payload = ev.get("payload") or {}

    if etype in (events.DATASET_UPLOADED, events.FILES_ADDED,
                 events.ANALYSIS_REQUESTED, events.REPROCESS_REQUESTED):
        enqueue(create_job(project_id, "analysis", ev.get("id"), payload))
    elif etype in (events.REVIEW_ANSWERED, events.REVIEW_APPROVED,
                   events.REVIEW_REJECTED):
        enqueue(create_job(project_id, "resume_review", ev.get("id"), payload))
    elif etype == events.USER_QUESTION:
        enqueue(create_job(project_id, "question", ev.get("id"), payload))
    elif etype == events.SCHEDULE_CHANGED:
        enqueue(create_job(project_id, "resnapshot", ev.get("id"), payload))


def enqueue(job_id: str) -> None:
    _queue.put(job_id)


def start_worker() -> None:
    global _worker, _started
    if _started:
        return
    _started = True
    events.on_event(handle_event)
    _worker = threading.Thread(target=_loop, daemon=True, name="veda-jobs")
    _worker.start()


def _loop() -> None:
    while True:
        job_id = _queue.get()
        try:
            _run(job_id)
        except Exception:
            job = db.q1("SELECT * FROM jobs WHERE id=?", [job_id]) or {}
            _finish(job_id, job.get("project_id", ""), "failed",
                    traceback.format_exc()[-3000:])
        finally:
            _current["job_id"] = None
            _queue.task_done()


def current_job() -> str | None:
    return _current.get("job_id")


# ------------------------------------------------------------------- the work
def _run(job_id: str) -> None:
    job = db.q1("SELECT * FROM jobs WHERE id=?", [job_id])
    if not job or job.get("status") in ("cancelled", "done"):
        return
    project_id = job["project_id"]
    _current["job_id"] = job_id
    db.update("jobs", job_id, {
        "status": "running", "started_at": db.now(), "error": None,
        "attempts": (job.get("attempts") or 0) + 1,
        "provider": registry.active_provider_name(),
    })
    events.notify_ui(project_id, "jobs_changed", {"job_id": job_id})

    payload = (db.jloads(job.get("result_json"), {}) or {}).get("input", {})
    kind = job["kind"]
    try:
        if kind == "analysis":
            result = _run_analysis(job_id, project_id, payload)
        elif kind == "resume_review":
            result = _run_resume(job_id, project_id, payload)
        elif kind == "question":
            result = _run_question(job_id, project_id, payload)
        elif kind == "resnapshot":
            result = _run_resnapshot(job_id, project_id, payload)
        else:
            raise ValueError("unknown job kind: " + kind)
    except McpError as exc:
        step(job_id, project_id, "mcp_failed", "Horizun call failed", "failed",
             str(exc))
        _finish(job_id, project_id, "failed", "Horizun MCP: " + str(exc))
        return
    except Exception as exc:  # noqa: BLE001
        step(job_id, project_id, "job_failed", type(exc).__name__, "failed",
             str(exc)[:500])
        _finish(job_id, project_id, "failed",
                type(exc).__name__ + ": " + str(exc) + "\n" +
                traceback.format_exc()[-2000:])
        return

    open_reviews = db.q1("SELECT COUNT(*) c FROM reviews WHERE project_id=? "
                         "AND status='open'", [project_id]) or {}
    status = "awaiting_review" if open_reviews.get("c") else "done"
    _finish(job_id, project_id, status, None, result)
    events.notify_ui(project_id, "refresh", {"job_id": job_id})


# ------------------------------------------------------------------ analysis
def _run_analysis(job_id: str, project_id: str, payload: dict) -> dict:
    project = db.q1("SELECT * FROM projects WHERE id=?", [project_id]) or {}
    step(job_id, project_id, "files_received", "Files received")

    # ---- 1. Horizun capability matrix (spec 8) --------------------------
    try:
        health = horizun.health(project_id=project_id, job_id=job_id)
        caps = health.get("capabilities", {})
        step(job_id, project_id, "mcp_health",
             "Horizun ready on the " + str(health.get("backend")) + " backend",
             "success",
             ", ".join(k for k, v in caps.items() if v))
    except McpError as exc:
        step(job_id, project_id, "mcp_health", "Horizun unavailable", "failed",
             str(exc))
        raise

    # ---- 2. schedule snapshot (spec 15) ---------------------------------
    sched = db.q1("SELECT * FROM files WHERE project_id=? AND kind='schedule' "
                  "ORDER BY created_at DESC LIMIT 1", [project_id])
    snap_summary: dict = {}
    if sched:
        step(job_id, project_id, "schedule_detected",
             "Schedule detected: " + str(sched["filename"]))
        db.update("projects", project_id, {"schedule_file_id": sched["id"],
                                           "updated_at": db.now()})
        snap_summary = schedule_ops.collect_snapshot(
            project_id, proposals.current_schedule_path(project_id) or
            sched["stored_path"],
            job_id=job_id, file_id=sched["id"],
            progress=lambda n, l, s: step(job_id, project_id, n, l, s))
        db.update("files", sched["id"], {"extract_state": "done"})
    else:
        step(job_id, project_id, "schedule_detected",
             "No schedule file uploaded yet", "failed")

    # ---- 3. evidence extraction (spec 33, 34) ---------------------------
    ev_files = db.q("SELECT * FROM files WHERE project_id=? AND kind='evidence' "
                    "AND extract_state IN ('pending','failed')", [project_id])
    total_ev = 0
    for f in ev_files:
        if f.get("security_state") == "quarantined":
            db.update("files", f["id"], {"extract_state": "skipped",
                                         "extract_error": "quarantined"})
            step(job_id, project_id, "evidence_quarantined",
                 "Withheld " + str(f["filename"]) + " - content tries to instruct "
                 "the system", "failed")
            continue
        try:
            rows = extract.extract_evidence(project_id, f, job_id)
            db.ex("DELETE FROM evidence WHERE file_id=?", [f["id"]])
            for r in rows:
                db.insert("evidence", r)
            db.update("files", f["id"], {"extract_state": "done",
                                         "extract_error": None})
            total_ev += len(rows)
        except Exception as exc:  # noqa: BLE001
            db.update("files", f["id"], {"extract_state": "failed",
                                         "extract_error": str(exc)[:500]})
    if ev_files:
        step(job_id, project_id, "evidence_processed",
             str(total_ev) + " evidence records extracted from " +
             str(len(ev_files)) + " document(s)")

    # ---- 4. reasoning (spec 7 - VEDA invokes the agent itself) ----------
    files = db.q("SELECT id, filename, kind, size_bytes, security_state FROM files "
                 "WHERE project_id=?", [project_id])
    ev_sample = db.q("SELECT id, date, discipline, crew, location, chainage, "
                     "description FROM evidence WHERE project_id=? "
                     "ORDER BY date DESC LIMIT 40", [project_id])
    snap = db.q1("SELECT * FROM schedule_snapshots WHERE project_id=? "
                 "AND is_current=1 ORDER BY created_at DESC LIMIT 1", [project_id])
    answers = db.q("SELECT title, answer FROM reviews WHERE project_id=? "
                   "AND status IN ('answered','approved') ORDER BY answered_at DESC "
                   "LIMIT 20", [project_id])
    prompt = analysis_prompt(project, snap, files, ev_sample,
                             reviews.open_for(project_id), answers)

    result, used = _invoke_agent(job_id, project_id, prompt)

    # ---- 5. persist, validate, link (spec 35, 43, 45) -------------------
    applied = apply_result(project_id, job_id, result, source=used)
    return {"snapshot": snap_summary, "evidence_extracted": total_ev,
            "provider": used, **applied}


def _invoke_agent(job_id: str, project_id: str, prompt: str,
                  resume_external: str | None = None) -> tuple:
    """Run the configured provider; fall back to rules if it cannot run."""
    provider_name = registry.active_provider_name()
    provider = registry.get_provider(provider_name)
    step(job_id, project_id, "agent_invoked",
         "Waking " + registry.LABELS.get(provider_name, provider_name))

    health = _await(provider.health())
    if not health.get("ok"):
        step(job_id, project_id, "agent_unavailable",
             registry.LABELS.get(provider_name, provider_name) + " unavailable",
             "failed", str(health.get("error"))[:300])
        if not config.ALLOW_DETERMINISTIC_FALLBACK:
            raise RuntimeError("reasoning provider unavailable: " +
                               str(health.get("error")))
        step(job_id, project_id, "fallback_analysis",
             "Running VEDA's rule-based analyser instead")
        return deterministic.analyse(project_id), "deterministic"

    sess_row = None
    resume_session = None
    if resume_external:
        from .agent.base import AgentSession
        sess_row = db.q1("SELECT * FROM agent_sessions WHERE id=?",
                         [resume_external])
        if sess_row:
            resume_session = AgentSession(
                session_id=sess_row["id"], external_id=sess_row.get("external_id"),
                provider=sess_row["provider"], model=sess_row.get("model"),
                meta={"project_id": project_id, "job_id": job_id})

    def on_event(ev) -> None:
        if ev.kind == "tool_call":
            step(job_id, project_id, "tool_call", ev.label, "success")
        elif ev.kind == "error":
            step(job_id, project_id, "agent_error", ev.label[:200], "failed")
        elif ev.kind == "status":
            step(job_id, project_id, ev.step or "agent_status", ev.label)

    run = _await(provider.run(
        project_id=project_id, job_id=job_id, prompt=prompt, system=SYSTEM,
        schema=schemas.json_schema(), workspace=str(config.DATA_DIR),
        resume=resume_session, on_event=on_event))

    sid = run.external_id or db.new_id("sess_")
    if sess_row:
        db.update("agent_sessions", sess_row["id"], {
            "turns": (sess_row.get("turns") or 0) + run.turns,
            "cost_usd": (sess_row.get("cost_usd") or 0) + run.cost_usd,
            "updated_at": db.now(),
            "external_id": run.external_id or sess_row.get("external_id")})
        session_id = sess_row["id"]
    else:
        session_id = db.insert("agent_sessions", {
            "project_id": project_id, "job_id": job_id, "provider": provider_name,
            "external_id": sid, "model": run.events and None or None,
            "turns": run.turns, "cost_usd": run.cost_usd,
            "status": "active", "updated_at": db.now()})
    db.update("jobs", job_id, {"agent_session_id": session_id})

    if not run.ok and not run.text:
        step(job_id, project_id, "agent_failed", "Agent produced no result",
             "failed", (run.error or "")[:400])
        if not config.ALLOW_DETERMINISTIC_FALLBACK:
            raise RuntimeError("agent failed: " + str(run.error))
        return deterministic.analyse(project_id), "deterministic"

    outcome = schemas.parse_agent_result(run.structured or run.text)
    if not outcome.ok:
        # spec 43: reject malformed output safely and keep the evidence of it.
        step(job_id, project_id, "structured_output_rejected",
             "Agent output did not validate", "failed", str(outcome.error)[:400])
        db.insert("artifacts", {
            "project_id": project_id, "job_id": job_id, "kind": "rejected_output",
            "title": "Rejected agent output", "format": "text",
            "description": str(outcome.error)[:2000],
            "provenance": "AI_INFERENCE"})
        reviews.create(
            project_id=project_id, kind="failed_validation", job_id=job_id,
            title="Agent returned output VEDA could not read",
            question=("The reasoning provider returned a result that did not match "
                      "VEDA's structured schema, so nothing from it was applied. "
                      "Retry the analysis, or continue with what is already "
                      "stored?"),
            detail=str(outcome.error)[:1000],
            options=["Retry analysis", "Continue without it"], priority="high")
        if not config.ALLOW_DETERMINISTIC_FALLBACK:
            raise RuntimeError("structured output rejected")
        return deterministic.analyse(project_id), "deterministic"

    if outcome.dropped:
        step(job_id, project_id, "structured_output_partial",
             str(outcome.dropped) + " malformed row(s) dropped from agent output",
             "failed", "; ".join(outcome.drop_reasons)[:1000])
    step(job_id, project_id, "output_ready", "Structured result received")
    return outcome.result, provider_name


def _await(coro):
    """Run a coroutine from the worker thread."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        try:
            loop.close()
        except Exception:
            pass


# ----------------------------------------------------- persisting the result
def apply_result(project_id: str, job_id: str, result: schemas.AgentResult,
                 source: str = "agent") -> dict:
    """Persist a validated agent result and run the deterministic gates."""
    actor_type = "agent" if source != "deterministic" else "system"
    prov_default = "AI_INFERENCE" if source != "deterministic" \
        else "DETERMINISTIC_CALCULATION"

    ref_to_id: dict = {}
    for e in result.evidence:
        existing = db.q1("SELECT id FROM evidence WHERE project_id=? AND id=?",
                         [project_id, e.ref])
        if existing:
            ref_to_id[e.ref] = e.ref
            patch = {}
            if e.observed_progress is not None:
                patch["observed_progress"] = e.observed_progress
            if e.discipline:
                patch["discipline"] = e.discipline
            if e.chainage:
                patch["chainage"] = e.chainage
            if patch:
                db.update("evidence", e.ref, patch)
            continue
        new_id = db.insert("evidence", {
            "project_id": project_id, "job_id": job_id,
            "source_file": e.source_file, "locator": e.locator, "date": e.date,
            "author": e.author, "contractor": e.contractor, "crew": e.crew,
            "discipline": e.discipline, "location": e.location,
            "chainage": e.chainage, "quantity": e.quantity, "unit": e.unit,
            "description": e.description,
            "observed_progress": e.observed_progress,
            "confidence": e.confidence, "state": "new",
            "provenance": e.provenance})
        ref_to_id[e.ref] = new_id

    # Candidate links from the model, keyed by the evidence row they cite.
    agent_links: dict = {}
    for l in result.evidence_links:
        eid = ref_to_id.get(l.evidence_ref, l.evidence_ref)
        if not db.q1("SELECT id FROM evidence WHERE id=? AND project_id=?",
                     [eid, project_id]):
            continue
        agent_links.setdefault(eid, []).append({
            "activity_uid": l.activity_uid, "confidence": l.confidence,
            "relation": l.relation,
            "supporting_signals": l.supporting_signals,
            "conflicting_signals": l.conflicting_signals})

    link_stats = linking.link_evidence(project_id, job_id=job_id,
                                       agent_links=agent_links)

    # ---- issues and risks, kept distinct (spec 32) ----------------------
    n_issues = 0
    for i in result.issues:
        if db.q1("SELECT id FROM issues WHERE project_id=? AND title=?",
                 [project_id, i.title]):
            continue
        db.insert("issues", {
            "project_id": project_id, "job_id": job_id, "ref": i.ref,
            "title": i.title, "description": i.description, "source": i.source,
            "status": i.status, "priority": i.priority, "severity": i.severity,
            "owner": i.owner, "date": i.date,
            "target_resolution": i.target_resolution,
            "activity_uids_json": db.jdumps(i.activity_uids), "wbs": i.wbs,
            "schedule_impact_days": i.schedule_impact_days,
            "schedule_impact_note": i.schedule_impact_note,
            "evidence_ids_json": db.jdumps(
                [ref_to_id.get(r, r) for r in i.evidence_refs]),
            "confidence": i.confidence,
            "provenance": i.provenance or prov_default,
            "updated_at": db.now()})
        n_issues += 1

    n_risks = 0
    for r in result.risks:
        if db.q1("SELECT id FROM risks WHERE project_id=? AND title=?",
                 [project_id, r.title]):
            continue
        db.insert("risks", {
            "project_id": project_id, "job_id": job_id, "ref": r.ref,
            "title": r.title, "description": r.description, "category": r.category,
            "probability": r.probability, "impact": r.impact,
            "rating": r.rating or _rating(r.probability, r.impact),
            "score": _score(r.probability, r.impact),
            "owner": r.owner, "status": r.status, "mitigation": r.mitigation,
            "trigger": r.trigger,
            "activity_uids_json": db.jdumps(r.activity_uids), "wbs": r.wbs,
            "schedule_impact_days": r.schedule_impact_days,
            "critical_path_relevance": r.critical_path_relevance,
            "evidence_ids_json": db.jdumps(
                [ref_to_id.get(x, x) for x in r.evidence_refs]),
            "confidence": r.confidence,
            "provenance": r.provenance or prov_default,
            "updated_at": db.now()})
        n_risks += 1

    # ---- review questions the model raised (spec 40, 41) ----------------
    n_reviews = 0
    for q in result.review_questions:
        ids = [ref_to_id.get(r, r) for r in q.affected_evidence_refs]
        reviews.create(project_id=project_id, kind=q.kind, title=q.title,
                       question=q.question, detail=q.detail,
                       options=q.options, cluster_key=q.cluster_key,
                       affected_ids=ids, entity_type=q.entity_type,
                       entity_id=q.entity_id, priority=q.priority, job_id=job_id)
        n_reviews += 1

    # ---- change proposals: validated, then dry-run (spec 46, 47) --------
    n_props = 0
    for p in result.change_proposals:
        pid = proposals.create(
            project_id, target_uid=p.target_uid, field=p.field,
            proposed_value=p.proposed_value, reason=p.reason,
            target_type=p.target_type, target_name=p.target_name,
            evidence_ids=[ref_to_id.get(r, r) for r in p.evidence_refs],
            confidence=p.confidence, job_id=job_id,
            provenance=p.provenance or prov_default)
        try:
            proposals.dry_run(pid, job_id=job_id)
        except Exception as exc:  # noqa: BLE001
            db.update("proposals", pid, {
                "dryrun_state": "failed",
                "dryrun_json": db.jdumps({"error": str(exc)})})
        n_props += 1
    if n_props:
        step(job_id, project_id, "dry_run_complete",
             str(n_props) + " proposal(s) dry-run against a throwaway copy")

    # ---- artifacts -------------------------------------------------------
    for a in result.artifacts:
        path = None
        if a.content:
            out = config.project_dir(project_id) / "outputs"
            out.mkdir(parents=True, exist_ok=True)
            ext = {"markdown": ".md", "json": ".json", "csv": ".csv",
                   "text": ".txt"}.get(a.format, ".txt")
            fp = out / (db.new_id("art_") + ext)
            fp.write_text(a.content, encoding="utf-8")
            path = str(fp)
        db.insert("artifacts", {
            "project_id": project_id, "job_id": job_id, "kind": a.kind,
            "title": a.title, "path": path, "format": a.format,
            "size_bytes": len(a.content or "") or None,
            "description": a.description,
            "provenance": prov_default})

    if result.summary:
        db.insert("artifacts", {
            "project_id": project_id, "job_id": job_id, "kind": "summary",
            "title": "Analysis summary", "format": "markdown",
            "description": result.summary[:4000], "provenance": prov_default})

    audit.record(project_id, actor=source, actor_type=actor_type,
                 action="analysis_applied", job_id=job_id, entity_type="job",
                 entity_id=job_id, result="ok",
                 detail={"issues": n_issues, "risks": n_risks,
                         "reviews": n_reviews, "proposals": n_props,
                         "links": link_stats})

    step(job_id, project_id, "associations_validated",
         "Evidence validated: " + ", ".join(
             str(v) + " " + k for k, v in link_stats["stats"].items() if v))
    if link_stats["clusters"]:
        step(job_id, project_id, "human_review_required",
             str(link_stats["clusters"]) + " clustered question(s) need a human "
             "answer")

    events.notify_ui(project_id, "refresh", {"job_id": job_id})
    return {"issues": n_issues, "risks": n_risks, "reviews": n_reviews,
            "proposals": n_props, "links": link_stats,
            "summary": result.summary[:2000]}


_P = {"low": 0.2, "medium": 0.5, "high": 0.8, "very high": 0.95, "very low": 0.1}


def _score(p: str, i: str) -> float:
    return round(_P.get(str(p).lower(), 0.5) * _P.get(str(i).lower(), 0.5), 3)


def _rating(p: str, i: str) -> str:
    s = _score(p, i)
    if s >= 0.6:
        return "high"
    if s >= 0.25:
        return "medium"
    return "low"


# ------------------------------------------------------------------- resume
def _run_resume(job_id: str, project_id: str, payload: dict) -> dict:
    """A human answered; reprocess exactly what that unblocks (spec 42)."""
    review_id = payload.get("review_id")
    review = None
    if review_id:
        rows = [r for r in reviews.all_for(project_id) if r["id"] == review_id]
        review = rows[0] if rows else None
    if review is None:
        return {"note": "review not found"}

    step(job_id, project_id, "review_answered",
         "Human answered: " + str(review.get("title")))

    # Approvals of a proposal execute the verified write (spec 47, 48).
    if review.get("entity_type") == "proposal" and review.get("entity_id"):
        pid = review["entity_id"]
        approved = review.get("status") == "approved"
        proposals.approve(pid, approved_by=review.get("answered_by") or "human",
                          approve_it=approved)
        if approved:
            step(job_id, project_id, "verified_write",
                 "Applying approved change to a revision copy")
            res = proposals.execute(pid, job_id=job_id, actor="human")
            step(job_id, project_id, "verified_write",
                 "Write " + str(res.get("verification")),
                 "success" if res.get("ok") else "failed")
            return {"proposal": pid, **res}
        return {"proposal": pid, "approved": False}

    if review.get("entity_type") == "file" and review.get("entity_id"):
        return _apply_security_answer(job_id, project_id, review)

    # Clustered clarification: apply the answer to every affected record.
    applied = linking.apply_cluster_answer(project_id, review, job_id)
    step(job_id, project_id, "records_reprocessed",
         str(applied.get("reprocessed", 0)) + " record(s) reprocessed from one "
         "answer")

    affected = []
    ids = review.get("affected_ids") or []
    if ids:
        affected = db.q("SELECT id, date, crew, description FROM evidence "
                        "WHERE id IN (" + ",".join("?" for _ in ids) + ") LIMIT 30",
                        ids)

    sess = db.q1("SELECT id FROM agent_sessions WHERE project_id=? "
                 "ORDER BY created_at DESC LIMIT 1", [project_id])
    prompt = resume_prompt([review], affected)
    result, used = _invoke_agent(job_id, project_id, prompt,
                                 resume_external=(sess or {}).get("id"))
    out = apply_result(project_id, job_id, result, source=used)
    return {"reprocessed": applied, "provider": used, **out}


def _apply_security_answer(job_id: str, project_id: str, review: dict) -> dict:
    fid = review["entity_id"]
    answer = (review.get("answer") or "").lower()
    f = db.q1("SELECT * FROM files WHERE id=?", [fid])
    if not f:
        return {"note": "file not found"}
    if "release" in answer:
        db.update("files", fid, {"security_state": "clean",
                                 "extract_state": "pending"})
        audit.record(project_id, actor=review.get("answered_by") or "human",
                     actor_type="human", action="file_released", job_id=job_id,
                     entity_type="file", entity_id=fid,
                     previous_value=f.get("security_state"), new_value="clean",
                     approval=review.get("answered_by"),
                     result="released for analysis as data only")
        step(job_id, project_id, "security_resolved",
             "File released as data only: " + str(f["filename"]))
        events.emit(events.REPROCESS_REQUESTED, project_id, {"file_id": fid},
                    source="human")
        return {"file": fid, "action": "released"}
    if "delete" in answer:
        try:
            import os
            os.remove(f["stored_path"])
        except Exception:
            pass
        db.ex("DELETE FROM evidence WHERE file_id=?", [fid])
        db.ex("DELETE FROM files WHERE id=?", [fid])
        audit.record(project_id, actor=review.get("answered_by") or "human",
                     actor_type="human", action="file_deleted", job_id=job_id,
                     entity_type="file", entity_id=fid,
                     previous_value=f.get("filename"), result="deleted on request",
                     approval=review.get("answered_by"))
        return {"file": fid, "action": "deleted"}
    db.update("files", fid, {"security_state": "quarantined"})
    step(job_id, project_id, "security_resolved",
         "File remains quarantined: " + str(f["filename"]))
    return {"file": fid, "action": "quarantined"}


# ----------------------------------------------------------------- question
def _run_question(job_id: str, project_id: str, payload: dict) -> dict:
    question = payload.get("question") or ""
    project = db.q1("SELECT * FROM projects WHERE id=?", [project_id]) or {}
    snap = db.q1("SELECT * FROM schedule_snapshots WHERE project_id=? "
                 "AND is_current=1 ORDER BY created_at DESC LIMIT 1", [project_id])
    step(job_id, project_id, "question_received", "Question received")
    prompt = question_prompt(question, project, snap)
    result, used = _invoke_agent(job_id, project_id, prompt)

    answer = result.summary or "No grounded answer could be produced."
    db.insert("artifacts", {
        "project_id": project_id, "job_id": job_id, "kind": "answer",
        "title": question[:180] or "Project question", "format": "markdown",
        "description": answer[:4000],
        "provenance": "AI_INFERENCE" if used != "deterministic"
        else "DETERMINISTIC_CALCULATION"})
    audit.record(project_id, actor="human", actor_type="human",
                 action="question_asked", job_id=job_id, new_value=question[:500],
                 result="answered")
    step(job_id, project_id, "output_ready", "Answer ready")
    return {"question": question, "answer": answer, "provider": used,
            "findings": [f.model_dump() for f in result.schedule_findings]}


# --------------------------------------------------------------- resnapshot
def _run_resnapshot(job_id: str, project_id: str, payload: dict) -> dict:
    """Re-harvest after a verified write (spec 13 - recalculate only when needed)."""
    path = payload.get("path") or proposals.current_schedule_path(project_id)
    if not path:
        return {"note": "no schedule to re-read"}
    step(job_id, project_id, "schedule_reopened", "Re-reading the updated schedule")
    schedule_ops.forget_handles()
    summary = schedule_ops.collect_snapshot(
        project_id, path, job_id=job_id,
        progress=lambda n, l, s: step(job_id, project_id, n, l, s))
    linking.rebuild_observed_progress(project_id)
    return {"snapshot": summary}
