"""VEDA durable state.

Rule (spec 4): durable state belongs to VEDA. The reasoning provider
conversation memory is never the only copy of anything that matters.
"""
from __future__ import annotations

import contextlib
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
  wbs TEXT, wbs_name TEXT, wbs_path TEXT, outline_level INTEGER,
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
  asset_tags_json TEXT,
  location_tags_json TEXT,
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
  event_type TEXT, action_type TEXT, event_state TEXT, event_confidence REAL,
  asset_tags_json TEXT, location_tags_json TEXT,
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
  retrieval_score REAL, rank_score REAL, calibrated_probability REAL,
  calibration_mode TEXT, calibration_is_empirical INTEGER DEFAULT 0, calibration_model_version TEXT,
  feature_json TEXT, policy_json TEXT, prediction_set_json TEXT,
  policy_decision TEXT, recommended_uid INTEGER, committed_uid INTEGER,
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

-- Canonical execution events preserve institutional memory independently of
-- whatever activity IDs/descriptions a later schedule revision happens to use.
CREATE TABLE IF NOT EXISTS execution_events (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  canonical_key TEXT,
  activity_uid INTEGER,
  action_type TEXT, event_state TEXT, event_date TEXT,
  observed_progress REAL, remaining_days REAL, quantity REAL, unit TEXT,
  confidence REAL, state TEXT DEFAULT 'observed',
  source_count INTEGER DEFAULT 0,
  provenance TEXT DEFAULT 'DERIVED',
  created_at REAL, updated_at REAL
);
CREATE INDEX IF NOT EXISTS ix_exec_event_project ON execution_events(project_id, activity_uid, event_date);

CREATE TABLE IF NOT EXISTS execution_event_sources (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  execution_event_id TEXT NOT NULL,
  evidence_id TEXT NOT NULL,
  source_file TEXT, locator TEXT, source_trust REAL,
  created_at REAL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_exec_event_source ON execution_event_sources(execution_event_id, evidence_id);

-- A field capture is the user-confirmed envelope around one observation. Its
-- client id makes mobile/offline retries idempotent; media remains in the
-- immutable files store and only ids/metadata live here.
CREATE TABLE IF NOT EXISTS field_captures (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  client_capture_id TEXT NOT NULL,
  status TEXT DEFAULT 'confirmed',
  occurred_at TEXT,
  event_state TEXT,
  language TEXT DEFAULT 'en',
  reporter TEXT,
  original_text TEXT,
  confirmed_text TEXT NOT NULL,
  activity_uid INTEGER,
  activity_display_id TEXT,
  activity_name TEXT,
  observed_progress REAL,
  remaining_days REAL,
  location_label TEXT,
  latitude REAL,
  longitude REAL,
  location_accuracy_m REAL,
  location_source TEXT,
  media_file_ids_json TEXT,
  evidence_id TEXT,
  execution_event_id TEXT,
  proposal_ids_json TEXT,
  sync_source TEXT DEFAULT 'online',
  created_at REAL, updated_at REAL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_field_capture_client
  ON field_captures(project_id, client_capture_id);
CREATE INDEX IF NOT EXISTS ix_field_capture_project
  ON field_captures(project_id, created_at DESC);

-- Activity identity across schedule revisions.  Stable UIDs are strongest;
-- rename/split/merge hypotheses remain explicit and auditable.
CREATE TABLE IF NOT EXISTS activity_lineage (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  from_revision INTEGER, to_revision INTEGER,
  from_uid INTEGER, to_uid INTEGER,
  from_display_id TEXT, to_display_id TEXT,
  relation TEXT, score REAL, basis TEXT,
  created_at REAL
);
CREATE INDEX IF NOT EXISTS ix_activity_lineage_project ON activity_lineage(project_id, from_revision, to_revision);

CREATE TABLE IF NOT EXISTS retrieval_documents (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  activity_uid INTEGER NOT NULL,
  fingerprint TEXT,
  search_text TEXT,
  embedding_model TEXT,
  embedding_dim INTEGER,
  embedding_blob BLOB,
  sparse_json TEXT,
  metadata_json TEXT,
  updated_at REAL,
  created_at REAL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_retrieval_doc_activity
  ON retrieval_documents(project_id, activity_uid);
CREATE INDEX IF NOT EXISTS ix_retrieval_doc_project
  ON retrieval_documents(project_id);

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
  proposal_group_id TEXT,
  source_event_id TEXT,
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

-- Hot-path indexes for the control-room header and the resolver loop.  Every
-- one of these backs a COUNT/lookup that used to force a full table scan on
-- each dashboard refresh or each candidate scored.
CREATE INDEX IF NOT EXISTS ix_issues_project ON issues(project_id, status);
CREATE INDEX IF NOT EXISTS ix_risks_project ON risks(project_id, status);
CREATE INDEX IF NOT EXISTS ix_prop_project ON proposals(project_id, approval_state);
CREATE INDEX IF NOT EXISTS ix_qa_project ON qa_findings(project_id, status);
CREATE INDEX IF NOT EXISTS ix_ms_project ON milestones(project_id);
CREATE INDEX IF NOT EXISTS ix_wbs_project ON wbs_nodes(project_id);
CREATE INDEX IF NOT EXISTS ix_res_project ON resources(project_id);
CREATE INDEX IF NOT EXISTS ix_asg_project ON assignments(project_id);
CREATE INDEX IF NOT EXISTS ix_art_project ON artifacts(project_id, kind, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_ev_project_file ON evidence(project_id, file_id);
CREATE INDEX IF NOT EXISTS ix_ev_project_date ON evidence(project_id, date);
CREATE INDEX IF NOT EXISTS ix_evl_project_rel ON evidence_links(project_id, relation, is_candidate);
CREATE INDEX IF NOT EXISTS ix_aa_project ON agent_activity(project_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_earned_project ON earned_value(project_id, scope, created_at DESC);
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
        # WAL + synchronous=NORMAL is the standard durable-but-fast pairing: a
        # commit still survives an application crash, only an OS/power loss can
        # cost the last transactions.  With synchronous=FULL every single row
        # write in the resolver loop paid an fsync, which dominated analysis
        # latency far more than any model did.
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA cache_size=-32000")       # ~32 MB page cache
        conn.execute("PRAGMA mmap_size=268435456")     # 256 MB, best-effort
        conn.execute("PRAGMA wal_autocheckpoint=2000")
        _local.conn = conn
    return conn


@contextlib.contextmanager
def transaction():
    """Group many writes into one commit.

    ``ex``/``insert``/``update`` normally commit per statement so a crash never
    leaves a half-written analysis.  Inside this block they defer to a single
    commit at the end, which is what turns a per-row resolver write burst into
    one durable transaction.  Nesting is safe; only the outermost block commits.
    """
    depth = getattr(_local, "batch_depth", 0)
    _local.batch_depth = depth + 1
    conn = connect()
    try:
        yield conn
    except BaseException:
        _local.batch_depth = depth
        if depth == 0:
            with contextlib.suppress(Exception):
                conn.rollback()
        raise
    else:
        _local.batch_depth = depth
        if depth == 0:
            conn.commit()


def _autocommit(conn: sqlite3.Connection) -> None:
    if not getattr(_local, "batch_depth", 0):
        conn.commit()


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
    # Hybrid retrieval/entity-resolution fields (v0.2).
    acols = {r[1] for r in conn.execute("PRAGMA table_info(activities)").fetchall()}
    for name, ddl in (
        ("wbs_path", "ALTER TABLE activities ADD COLUMN wbs_path TEXT"),
        ("asset_tags_json", "ALTER TABLE activities ADD COLUMN asset_tags_json TEXT"),
        ("location_tags_json", "ALTER TABLE activities ADD COLUMN location_tags_json TEXT"),
    ):
        if name not in acols:
            conn.execute(ddl)

    ecols = {r[1] for r in conn.execute("PRAGMA table_info(evidence)").fetchall()}
    for name, ddl in (
        ("event_type", "ALTER TABLE evidence ADD COLUMN event_type TEXT"),
        ("action_type", "ALTER TABLE evidence ADD COLUMN action_type TEXT"),
        ("event_state", "ALTER TABLE evidence ADD COLUMN event_state TEXT"),
        ("event_confidence", "ALTER TABLE evidence ADD COLUMN event_confidence REAL"),
        ("asset_tags_json", "ALTER TABLE evidence ADD COLUMN asset_tags_json TEXT"),
        ("location_tags_json", "ALTER TABLE evidence ADD COLUMN location_tags_json TEXT"),
    ):
        if name not in ecols:
            conn.execute(ddl)

    lcols = {r[1] for r in conn.execute("PRAGMA table_info(evidence_links)").fetchall()}
    if "review_id" not in lcols:
        conn.execute("ALTER TABLE evidence_links ADD COLUMN review_id TEXT")
    for name, ddl in (
        ("retrieval_score", "ALTER TABLE evidence_links ADD COLUMN retrieval_score REAL"),
        ("rank_score", "ALTER TABLE evidence_links ADD COLUMN rank_score REAL"),
        ("calibrated_probability", "ALTER TABLE evidence_links ADD COLUMN calibrated_probability REAL"),
        ("calibration_mode", "ALTER TABLE evidence_links ADD COLUMN calibration_mode TEXT"),
        ("calibration_is_empirical", "ALTER TABLE evidence_links ADD COLUMN calibration_is_empirical INTEGER DEFAULT 0"),
        ("calibration_model_version", "ALTER TABLE evidence_links ADD COLUMN calibration_model_version TEXT"),
        ("feature_json", "ALTER TABLE evidence_links ADD COLUMN feature_json TEXT"),
        ("policy_json", "ALTER TABLE evidence_links ADD COLUMN policy_json TEXT"),
        ("prediction_set_json", "ALTER TABLE evidence_links ADD COLUMN prediction_set_json TEXT"),
        ("policy_decision", "ALTER TABLE evidence_links ADD COLUMN policy_decision TEXT"),
        ("recommended_uid", "ALTER TABLE evidence_links ADD COLUMN recommended_uid INTEGER"),
        ("committed_uid", "ALTER TABLE evidence_links ADD COLUMN committed_uid INTEGER"),
    ):
        if name not in lcols:
            conn.execute(ddl)

    rdcols = {r[1] for r in conn.execute("PRAGMA table_info(retrieval_documents)").fetchall()}
    if "sparse_json" not in rdcols:
        conn.execute("ALTER TABLE retrieval_documents ADD COLUMN sparse_json TEXT")

    xcols = {r[1] for r in conn.execute("PRAGMA table_info(execution_events)").fetchall()}
    if "remaining_days" not in xcols:
        conn.execute("ALTER TABLE execution_events ADD COLUMN remaining_days REAL")

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
        ("proposal_group_id", "ALTER TABLE proposals ADD COLUMN proposal_group_id TEXT"),
        ("source_event_id", "ALTER TABLE proposals ADD COLUMN source_event_id TEXT"),
    ):
        if name not in pcols:
            conn.execute(ddl)
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_proposal_event_field "
                 "ON proposals(project_id, source_event_id, target_uid, field) "
                 "WHERE source_event_id IS NOT NULL")
    conn.commit()
    # Keep the query planner's statistics current.  Without this a database that
    # grew from empty keeps planning COUNTs as if every table were tiny.
    with contextlib.suppress(Exception):
        conn.execute("ANALYZE")
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
    _autocommit(conn)
    return cur


def exmany(sql: str, seq: list) -> None:
    if not seq:
        return
    conn = connect()
    conn.executemany(sql, seq)
    _autocommit(conn)


def insertmany(table: str, rows: list) -> list:
    """Insert many homogeneous rows in one prepared statement + one commit.

    Falls back to per-row ``insert`` when the rows do not share a column set, so
    callers never have to reason about which shape they built.
    """
    if not rows:
        return []
    cols_ok = table_cols(table)
    prepared, ids = [], []
    keys = None
    for row in rows:
        clean = {k: v for k, v in row.items() if k in cols_ok and v is not None}
        clean.setdefault("id", new_id())
        if "created_at" in cols_ok and "created_at" not in clean:
            clean["created_at"] = now()
        if keys is None:
            keys = list(clean)
        elif list(clean) != keys:
            # Mixed shapes: nothing has been executed yet, so discard the
            # partially prepared batch and insert every row individually.
            return [insert(table, pending) for pending in rows]
        prepared.append([clean[k] for k in keys])
        ids.append(clean["id"])
    exmany("INSERT OR REPLACE INTO " + table + " (" + ",".join(keys) + ") VALUES (" +
           ",".join("?" for _ in keys) + ")", prepared)
    return ids


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


_PROBE_CACHE: dict = {}
PROBE_TTL = 0.5


def cached_probe(key, loader, ttl: float = PROBE_TTL):
    """Memoise a cheap "has this changed?" query for a fraction of a second.

    The revision-scoped caches in the resolver ask this once per candidate
    scored, which turned a free cache check into tens of thousands of SQLite
    round trips per analysis. The window is short enough that a write landing
    mid-batch is still picked up almost immediately, and every explicit cache
    invalidation clears it outright.
    """
    stamp = time.monotonic()
    hit = _PROBE_CACHE.get(key)
    if hit is not None and (stamp - hit[0]) < ttl:
        return hit[1]
    value = loader()
    _PROBE_CACHE[key] = (stamp, value)
    return value


def clear_probe_cache() -> None:
    _PROBE_CACHE.clear()


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
