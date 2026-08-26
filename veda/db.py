"""VEDA durable state.

Rule (spec 4): durable state belongs to VEDA. The reasoning provider
conversation memory is never the only copy of anything that matters.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from typing import Any, Iterable

from . import config

_local = threading.local()

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS projects (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  client TEXT, location TEXT, description TEXT,
  status TEXT DEFAULT 'active',
  agent_provider TEXT,
  schedule_file_id TEXT,
  horizun_handle TEXT,
  created_at REAL, updated_at REAL
);

CREATE TABLE IF NOT EXISTS files (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  filename TEXT NOT NULL,
  stored_path TEXT NOT NULL,
  ext TEXT, size_bytes INTEGER,
  sha256 TEXT,
  kind TEXT,
  content_type TEXT,
  uploaded_by TEXT DEFAULT 'human',
  security_state TEXT DEFAULT 'clean',
  security_notes TEXT,
  extract_state TEXT DEFAULT 'pending',
  extract_error TEXT,
  batch_id TEXT,
  source_mode TEXT DEFAULT 'file',
  relative_path TEXT,
  duplicate_of TEXT,
  created_at REAL
);
CREATE INDEX IF NOT EXISTS ix_files_project ON files(project_id);
-- ix_files_batch is created in init_db after forward migration adds batch_id.

CREATE TABLE IF NOT EXISTS ingestion_batches (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  source TEXT DEFAULT 'website',
  status TEXT DEFAULT 'stored',
  file_count INTEGER DEFAULT 0,
  duplicate_count INTEGER DEFAULT 0,
  schedule_count INTEGER DEFAULT 0,
  evidence_count INTEGER DEFAULT 0,
  note TEXT,
  created_at REAL
);
CREATE INDEX IF NOT EXISTS ix_batches_project ON ingestion_batches(project_id, created_at DESC);

CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  kind TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'queued',
  phase TEXT,
  progress REAL DEFAULT 0,
  trigger_event_id TEXT,
  agent_session_id TEXT,
  provider TEXT,
  error TEXT,
  result_json TEXT,
  attempts INTEGER DEFAULT 0,
  created_at REAL, started_at REAL, finished_at REAL
);
CREATE INDEX IF NOT EXISTS ix_jobs_project ON jobs(project_id, created_at DESC);

CREATE TABLE IF NOT EXISTS agent_sessions (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  job_id TEXT,
  provider TEXT NOT NULL,
  external_id TEXT,
  status TEXT DEFAULT 'active',
  model TEXT,
  turns INTEGER DEFAULT 0,
  cost_usd REAL DEFAULT 0,
  created_at REAL, updated_at REAL
);

CREATE TABLE IF NOT EXISTS events (
  id TEXT PRIMARY KEY,
  project_id TEXT,
  type TEXT NOT NULL,
  payload_json TEXT,
  source TEXT,
  consumed INTEGER DEFAULT 0,
  created_at REAL
);
CREATE INDEX IF NOT EXISTS ix_events_project ON events(project_id, created_at DESC);

CREATE TABLE IF NOT EXISTS schedule_snapshots (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  file_id TEXT, job_id TEXT,
  revision INTEGER DEFAULT 1,
  source_path TEXT,
  project_name TEXT, data_date TEXT, status_date TEXT,
  planned_start TEXT, planned_finish TEXT, forecast_finish TEXT,
  baseline_start TEXT, baseline_finish TEXT, must_finish_by TEXT,
  forecast_basis TEXT, baseline_basis TEXT, criticality_basis TEXT,
  criticality_threshold_days REAL,
  baseline_present INTEGER, baseline_coverage_count INTEGER,
  criticality_available INTEGER, overdue_evaluable INTEGER,
  completed_late_evaluable INTEGER, progress_available INTEGER,
  progress_basis TEXT, resource_assignment_count INTEGER, resource_basis TEXT,
  task_count INTEGER, wbs_count INTEGER, summary_activity_count INTEGER,
  loe_count INTEGER, milestone_count INTEGER, relationship_count INTEGER,
  resource_count INTEGER, critical_count INTEGER, late_count INTEGER,
  overdue_count INTEGER, completed_late_count INTEGER,
  percent_complete REAL,
  health_score REAL,
  capabilities_json TEXT,
  info_json TEXT,
  is_current INTEGER DEFAULT 1,
  created_at REAL
);
CREATE INDEX IF NOT EXISTS ix_snap_project ON schedule_snapshots(project_id);

CREATE TABLE IF NOT EXISTS schedule_revision_changes (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  snapshot_id TEXT,
  revision INTEGER,
  activity_uid INTEGER,
  display_id TEXT,
  activity_name TEXT,
  change_type TEXT NOT NULL,
  changed_fields_json TEXT,
  before_json TEXT,
  after_json TEXT,
  created_at REAL
);
CREATE INDEX IF NOT EXISTS ix_sched_changes_project
  ON schedule_revision_changes(project_id, revision, change_type);

CREATE TABLE IF NOT EXISTS activities (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  snapshot_id TEXT,
  uid INTEGER,
  display_id TEXT,
  name TEXT,
  wbs TEXT, wbs_name TEXT, outline_level INTEGER,
  parent_uid INTEGER,
  is_summary INTEGER DEFAULT 0,
  is_milestone INTEGER DEFAULT 0,
  status TEXT,
  start TEXT, finish TEXT,
  actual_start TEXT, actual_finish TEXT,
  early_start TEXT, early_finish TEXT, late_start TEXT, late_finish TEXT,
  duration_days REAL, remaining_days REAL,
  percent_complete REAL,
  total_float_days REAL, free_float_days REAL,
  critical INTEGER DEFAULT 0,
  calendar TEXT,
  constraint_type TEXT, constraint_date TEXT, deadline TEXT,
  baseline_start TEXT, baseline_finish TEXT, baseline_duration_days REAL,
  start_variance_days REAL, finish_variance_days REAL, duration_variance_days REAL,
  cost REAL, work_hours REAL,
  resource_names TEXT,
  custom_json TEXT,
  notes TEXT,
  provenance TEXT DEFAULT 'MCP_FACT',
  created_at REAL
);
CREATE INDEX IF NOT EXISTS ix_act_project ON activities(project_id);
CREATE UNIQUE INDEX IF NOT EXISTS ux_act_uid ON activities(project_id, uid);

CREATE TABLE IF NOT EXISTS relationships (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  snapshot_id TEXT,
  pred_uid INTEGER, succ_uid INTEGER,
  pred_name TEXT, succ_name TEXT,
  type TEXT,
  lag_days REAL,
  driving INTEGER,
  provenance TEXT DEFAULT 'MCP_FACT',
  created_at REAL
);
CREATE INDEX IF NOT EXISTS ix_rel_project ON relationships(project_id);

CREATE TABLE IF NOT EXISTS resources (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  snapshot_id TEXT,
  uid INTEGER, name TEXT, type TEXT,
  calendar TEXT, max_units REAL, standard_rate REAL,
  work_hours REAL, cost REAL,
  overallocated INTEGER DEFAULT 0,
  overallocated_days INTEGER DEFAULT 0,
  peak_units REAL,
  assignment_count INTEGER DEFAULT 0,
  provenance TEXT DEFAULT 'MCP_FACT',
  created_at REAL
);

CREATE TABLE IF NOT EXISTS assignments (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  snapshot_id TEXT,
  task_uid INTEGER, resource_uid INTEGER,
  task_name TEXT, resource_name TEXT,
  units REAL, work_hours REAL, actual_work_hours REAL, remaining_work_hours REAL,
  cost REAL, actual_cost REAL,
  start TEXT, finish TEXT,
  provenance TEXT DEFAULT 'MCP_FACT',
  created_at REAL
);

CREATE TABLE IF NOT EXISTS timephased (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  snapshot_id TEXT,
  measure TEXT, granularity TEXT,
  period TEXT, task_uid INTEGER, resource_uid INTEGER,
  value REAL, cumulative REAL,
  provenance TEXT DEFAULT 'MCP_FACT'
);
CREATE INDEX IF NOT EXISTS ix_tp_project ON timephased(project_id, measure);

CREATE TABLE IF NOT EXISTS earned_value (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  snapshot_id TEXT,
  scope TEXT DEFAULT 'project',
  scope_key TEXT,
  status_date TEXT,
  pv REAL, ev REAL, ac REAL,
  sv REAL, cv REAL, spi REAL, cpi REAL, eac REAL, bac REAL, tcpi REAL,
  basis TEXT,
  provenance TEXT DEFAULT 'MCP_FACT',
  created_at REAL
);

CREATE TABLE IF NOT EXISTS qa_findings (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  snapshot_id TEXT,
  code TEXT, category TEXT, title TEXT, detail TEXT,
  severity TEXT, status TEXT,
  threshold TEXT, actual TEXT,
  count INTEGER, total INTEGER, percent REAL,
  task_uids_json TEXT,
  provenance TEXT DEFAULT 'MCP_FACT',
  created_at REAL
);

CREATE TABLE IF NOT EXISTS milestones (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  snapshot_id TEXT,
  uid INTEGER, display_id TEXT, name TEXT,
  planned_date TEXT, baseline_date TEXT, forecast_date TEXT, actual_date TEXT,
  deadline TEXT,
  variance_days REAL, status TEXT, critical INTEGER DEFAULT 0,
  total_float_days REAL,
  provenance TEXT DEFAULT 'MCP_FACT',
  created_at REAL
);

CREATE TABLE IF NOT EXISTS wbs_nodes (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  snapshot_id TEXT,
  code TEXT, name TEXT, parent_code TEXT, level INTEGER,
  uid INTEGER,
  start TEXT, finish TEXT, percent_complete REAL,
  activity_count INTEGER, critical_count INTEGER, late_count INTEGER,
  provenance TEXT DEFAULT 'MCP_FACT',
  created_at REAL
);

CREATE TABLE IF NOT EXISTS eps_nodes (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  code TEXT, name TEXT, parent_code TEXT, level INTEGER,
  source TEXT,
  provenance TEXT DEFAULT 'MCP_FACT',
  created_at REAL
);

CREATE TABLE IF NOT EXISTS evidence (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  file_id TEXT, job_id TEXT,
  source_file TEXT, locator TEXT,
  date TEXT, author TEXT, contractor TEXT, crew TEXT,
  discipline TEXT, location TEXT, chainage TEXT,
  quantity REAL, unit TEXT,
  description TEXT,
  observed_progress REAL,
  confidence REAL,
  state TEXT DEFAULT 'new',
  security_state TEXT DEFAULT 'clean',
  raw_json TEXT,
  provenance TEXT DEFAULT 'SOURCE_FILE',
  created_at REAL
);
CREATE INDEX IF NOT EXISTS ix_ev_project ON evidence(project_id, state);

CREATE TABLE IF NOT EXISTS evidence_links (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  evidence_id TEXT NOT NULL,
  activity_uid INTEGER,
  activity_name TEXT,
  confidence REAL,
  relation TEXT DEFAULT 'supporting',
  supporting_signals TEXT,
  conflicting_signals TEXT,
  validator_result TEXT,
  validator_json TEXT,
  human_decision TEXT,
  review_id TEXT,
  decided_by TEXT, decided_at REAL,
  is_candidate INTEGER DEFAULT 0,
  provenance TEXT DEFAULT 'AI_INFERENCE',
  created_at REAL
);
CREATE INDEX IF NOT EXISTS ix_evl_ev ON evidence_links(evidence_id);
CREATE INDEX IF NOT EXISTS ix_evl_act ON evidence_links(project_id, activity_uid);

CREATE TABLE IF NOT EXISTS observed_progress (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  activity_uid INTEGER,
  official_percent REAL,
  observed_percent REAL,
  delta REAL,
  evidence_count INTEGER,
  as_of TEXT,
  basis TEXT,
  provenance TEXT DEFAULT 'DERIVED',
  updated_at REAL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_op ON observed_progress(project_id, activity_uid);

CREATE TABLE IF NOT EXISTS issues (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  job_id TEXT,
  ref TEXT,
  title TEXT, description TEXT,
  source TEXT, status TEXT DEFAULT 'open',
  priority TEXT, severity TEXT, owner TEXT,
  date TEXT, target_resolution TEXT,
  activity_uids_json TEXT, wbs TEXT,
  schedule_impact_days REAL, schedule_impact_note TEXT,
  evidence_ids_json TEXT,
  confidence REAL,
  provenance TEXT DEFAULT 'AI_INFERENCE',
  review_state TEXT DEFAULT 'unconfirmed',
  created_at REAL, updated_at REAL
);

CREATE TABLE IF NOT EXISTS risks (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  job_id TEXT,
  ref TEXT,
  title TEXT, description TEXT, category TEXT,
  probability TEXT, impact TEXT, rating TEXT, score REAL,
  owner TEXT, status TEXT DEFAULT 'open',
  mitigation TEXT, trigger TEXT,
  activity_uids_json TEXT, wbs TEXT,
  schedule_impact_days REAL, critical_path_relevance TEXT,
  evidence_ids_json TEXT,
  confidence REAL,
  provenance TEXT DEFAULT 'AI_INFERENCE',
  review_state TEXT DEFAULT 'unconfirmed',
  created_at REAL, updated_at REAL
);

CREATE TABLE IF NOT EXISTS reviews (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  job_id TEXT,
  kind TEXT,
  title TEXT, question TEXT, detail TEXT,
  options_json TEXT,
  cluster_key TEXT,
  affected_count INTEGER DEFAULT 1,
  affected_ids_json TEXT,
  entity_type TEXT, entity_id TEXT,
  priority TEXT DEFAULT 'normal',
  status TEXT DEFAULT 'open',
  answer TEXT, answer_json TEXT,
  answered_by TEXT, answered_at REAL,
  schedule_revision INTEGER, schedule_snapshot_id TEXT,
  resolution_effect_json TEXT,
  created_at REAL
);
CREATE INDEX IF NOT EXISTS ix_rev_project ON reviews(project_id, status);

CREATE TABLE IF NOT EXISTS proposals (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  job_id TEXT,
  target_type TEXT,
  operation TEXT DEFAULT 'update',
  target_uid INTEGER, target_name TEXT, field TEXT,
  payload_json TEXT,
  current_value TEXT, proposed_value TEXT,
  reason TEXT,
  evidence_ids_json TEXT,
  confidence REAL,
  validation_state TEXT DEFAULT 'pending',
  validation_json TEXT,
  dryrun_state TEXT DEFAULT 'not_run',
  dryrun_json TEXT,
  impact_tasks_moved INTEGER, impact_finish_before TEXT, impact_finish_after TEXT,
  impact_critical_change INTEGER, impact_negative_float INTEGER,
  approval_state TEXT DEFAULT 'pending',
  approved_by TEXT, approved_at REAL,
  execution_state TEXT DEFAULT 'not_executed',
  executed_at REAL,
  verification_state TEXT DEFAULT 'not_verified',
  requested_value TEXT, resulting_value TEXT,
  verified_fields_json TEXT, rejected_fields_json TEXT,
  output_path TEXT,
  provenance TEXT DEFAULT 'AI_INFERENCE',
  created_at REAL, updated_at REAL
);

CREATE TABLE IF NOT EXISTS artifacts (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  job_id TEXT,
  kind TEXT, title TEXT, path TEXT, format TEXT,
  size_bytes INTEGER, sha256 TEXT,
  description TEXT,
  provenance TEXT DEFAULT 'DERIVED',
  created_at REAL
);

CREATE TABLE IF NOT EXISTS audit (
  id TEXT PRIMARY KEY,
  project_id TEXT,
  job_id TEXT,
  actor TEXT, actor_type TEXT,
  action TEXT, tool TEXT, source TEXT,
  entity_type TEXT, entity_id TEXT,
  previous_value TEXT, new_value TEXT,
  approval TEXT, verification TEXT,
  result TEXT, detail_json TEXT,
  created_at REAL
);
CREATE INDEX IF NOT EXISTS ix_audit_project ON audit(project_id, created_at DESC);

CREATE TABLE IF NOT EXISTS agent_activity (
  id TEXT PRIMARY KEY,
  project_id TEXT, job_id TEXT,
  step TEXT, label TEXT, state TEXT,
  detail TEXT,
  created_at REAL
);
CREATE INDEX IF NOT EXISTS ix_aa_job ON agent_activity(job_id, created_at);

CREATE TABLE IF NOT EXISTS mcp_calls (
  id TEXT PRIMARY KEY,
  project_id TEXT, job_id TEXT,
  server TEXT, tool TEXT,
  args_json TEXT,
  state TEXT, error TEXT,
  duration_ms REAL,
  summary TEXT,
  created_at REAL
);
CREATE INDEX IF NOT EXISTS ix_mcp_project ON mcp_calls(project_id, created_at DESC);

CREATE TABLE IF NOT EXISTS kv (
  k TEXT PRIMARY KEY, v TEXT, updated_at REAL
);

CREATE TABLE IF NOT EXISTS agent_inbox (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  job_id TEXT NOT NULL,
  prompt TEXT NOT NULL,
  system_prompt TEXT,
  schema_json TEXT,
  status TEXT DEFAULT 'pending',
  created_at REAL, claimed_at REAL, finished_at REAL
);
CREATE INDEX IF NOT EXISTS ix_inbox_status ON agent_inbox(status, created_at);

CREATE TABLE IF NOT EXISTS agent_outbox (
  id TEXT PRIMARY KEY,
  inbox_id TEXT NOT NULL,
  project_id TEXT NOT NULL,
  job_id TEXT NOT NULL,
  result_json TEXT,
  error TEXT,
  events_json TEXT,
  created_at REAL
);
CREATE INDEX IF NOT EXISTS ix_outbox_inbox ON agent_outbox(inbox_id);
"""


def connect() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)
    if conn is None:
        config.ensure_dirs()
        conn = sqlite3.connect(str(config.DB_PATH), check_same_thread=False, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=30000")
        _local.conn = conn
    return conn


def init_db() -> None:
    config.ensure_dirs()
    conn = connect()
    conn.executescript(SCHEMA)
    # Lightweight forward migrations for existing v0.1.x databases. SQLite
    # CREATE TABLE IF NOT EXISTS does not add new columns to an old table.
    cols = {r[1] for r in conn.execute("PRAGMA table_info(files)").fetchall()}
    for name, ddl in (
        ("batch_id", "ALTER TABLE files ADD COLUMN batch_id TEXT"),
        ("source_mode", "ALTER TABLE files ADD COLUMN source_mode TEXT DEFAULT 'file'"),
        ("duplicate_of", "ALTER TABLE files ADD COLUMN duplicate_of TEXT"),
        ("relative_path", "ALTER TABLE files ADD COLUMN relative_path TEXT"),
    ):
        if name not in cols:
            conn.execute(ddl)
    conn.execute("CREATE INDEX IF NOT EXISTS ix_files_batch ON files(batch_id)")

    # Source-semantic schedule fields added after v0.1.2.  These keep WBS nodes,
    # forecast provenance and the two different meanings of "late" separate.
    scols = {r[1] for r in conn.execute(
        "PRAGMA table_info(schedule_snapshots)").fetchall()}
    for name, ddl in (
        ("must_finish_by", "ALTER TABLE schedule_snapshots ADD COLUMN must_finish_by TEXT"),
        ("forecast_basis", "ALTER TABLE schedule_snapshots ADD COLUMN forecast_basis TEXT"),
        ("baseline_basis", "ALTER TABLE schedule_snapshots ADD COLUMN baseline_basis TEXT"),
        ("criticality_basis", "ALTER TABLE schedule_snapshots ADD COLUMN criticality_basis TEXT"),
        ("criticality_threshold_days", "ALTER TABLE schedule_snapshots ADD COLUMN criticality_threshold_days REAL"),
        ("wbs_count", "ALTER TABLE schedule_snapshots ADD COLUMN wbs_count INTEGER"),
        ("summary_activity_count", "ALTER TABLE schedule_snapshots ADD COLUMN summary_activity_count INTEGER"),
        ("loe_count", "ALTER TABLE schedule_snapshots ADD COLUMN loe_count INTEGER"),
        ("overdue_count", "ALTER TABLE schedule_snapshots ADD COLUMN overdue_count INTEGER"),
        ("completed_late_count", "ALTER TABLE schedule_snapshots ADD COLUMN completed_late_count INTEGER"),
        ("baseline_start", "ALTER TABLE schedule_snapshots ADD COLUMN baseline_start TEXT"),
        ("baseline_present", "ALTER TABLE schedule_snapshots ADD COLUMN baseline_present INTEGER"),
        ("baseline_coverage_count", "ALTER TABLE schedule_snapshots ADD COLUMN baseline_coverage_count INTEGER"),
        ("criticality_available", "ALTER TABLE schedule_snapshots ADD COLUMN criticality_available INTEGER"),
        ("overdue_evaluable", "ALTER TABLE schedule_snapshots ADD COLUMN overdue_evaluable INTEGER"),
        ("completed_late_evaluable", "ALTER TABLE schedule_snapshots ADD COLUMN completed_late_evaluable INTEGER"),
        ("progress_available", "ALTER TABLE schedule_snapshots ADD COLUMN progress_available INTEGER"),
        ("progress_basis", "ALTER TABLE schedule_snapshots ADD COLUMN progress_basis TEXT"),
        ("resource_assignment_count", "ALTER TABLE schedule_snapshots ADD COLUMN resource_assignment_count INTEGER"),
        ("resource_basis", "ALTER TABLE schedule_snapshots ADD COLUMN resource_basis TEXT"),
    ):
        if name not in scols:
            conn.execute(ddl)

    # Smooth-workflow review/link provenance. Human decisions are scoped to the
    # schedule revision they were made against, and evidence links retain the
    # originating review so a deliberate correction can be reversed safely.
    rcols = {r[1] for r in conn.execute("PRAGMA table_info(reviews)").fetchall()}
    for name, ddl in (
        ("schedule_revision", "ALTER TABLE reviews ADD COLUMN schedule_revision INTEGER"),
        ("schedule_snapshot_id", "ALTER TABLE reviews ADD COLUMN schedule_snapshot_id TEXT"),
        ("resolution_effect_json", "ALTER TABLE reviews ADD COLUMN resolution_effect_json TEXT"),
    ):
        if name not in rcols:
            conn.execute(ddl)
    lcols = {r[1] for r in conn.execute("PRAGMA table_info(evidence_links)").fetchall()}
    if "review_id" not in lcols:
        conn.execute("ALTER TABLE evidence_links ADD COLUMN review_id TEXT")

    # Legacy workflow migration: human attention is no longer a job status.
    # Analysis that had already finished but was labelled awaiting_review is
    # terminal work; the open review rows continue to represent the decision.
    conn.execute("UPDATE jobs SET status='done', phase=CASE WHEN phase='awaiting_review' "
                 "THEN 'done' ELSE phase END, finished_at=COALESCE(finished_at, ?) "
                 "WHERE status='awaiting_review'", (now(),))

    # v0.1.2 proposals can represent task create/delete as well as field updates.
    pcols = {r[1] for r in conn.execute("PRAGMA table_info(proposals)").fetchall()}
    for name, ddl in (
        ("operation", "ALTER TABLE proposals ADD COLUMN operation TEXT DEFAULT 'update'"),
        ("payload_json", "ALTER TABLE proposals ADD COLUMN payload_json TEXT"),
    ):
        if name not in pcols:
            conn.execute(ddl)
    conn.commit()
    _COLS_CACHE.clear()


def new_id(prefix: str = "") -> str:
    u = uuid.uuid4().hex[:16]
    return prefix + u if prefix else u


def now() -> float:
    return time.time()


def q(sql: str, params: Iterable = ()) -> list:
    cur = connect().execute(sql, tuple(params))
    return [dict(r) for r in cur.fetchall()]


def q1(sql: str, params: Iterable = ()):
    rows = q(sql, params)
    return rows[0] if rows else None


def ex(sql: str, params: Iterable = ()):
    conn = connect()
    cur = conn.execute(sql, tuple(params))
    conn.commit()
    return cur


def exmany(sql: str, seq: list) -> None:
    if not seq:
        return
    conn = connect()
    conn.executemany(sql, seq)
    conn.commit()


_COLS_CACHE: dict = {}


def table_cols(table: str) -> set:
    if table not in _COLS_CACHE:
        _COLS_CACHE[table] = {c["name"] for c in q("PRAGMA table_info(" + table + ")")}
    return _COLS_CACHE[table]


def insert(table: str, row: dict) -> str:
    cols_ok = table_cols(table)
    row = {k: v for k, v in row.items() if k in cols_ok and v is not None}
    row.setdefault("id", new_id())
    if "created_at" in cols_ok and "created_at" not in row:
        row["created_at"] = now()
    cols = ",".join(row)
    ph = ",".join("?" for _ in row)
    ex("INSERT OR REPLACE INTO " + table + " (" + cols + ") VALUES (" + ph + ")",
       list(row.values()))
    return row["id"]


def update(table: str, id_: str, row: dict) -> None:
    cols_ok = table_cols(table)
    row = {k: v for k, v in row.items() if k in cols_ok and k != "id"}
    if not row:
        return
    sets = ",".join(k + "=?" for k in row)
    ex("UPDATE " + table + " SET " + sets + " WHERE id=?", list(row.values()) + [id_])


def jloads(s: Any, default=None):
    if s in (None, "", b""):
        return default
    if isinstance(s, (dict, list)):
        return s
    try:
        return json.loads(s)
    except Exception:
        return default


def jdumps(o: Any) -> str:
    return json.dumps(o, ensure_ascii=False, default=str)
