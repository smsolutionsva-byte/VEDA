# VEDA

**Agent-Native Construction Project Intelligence Platform**

VEDA connects a local website, an AI reasoning agent, the Horizun MS Project MCP
server, construction schedules, field evidence, human review, validation,
schedule simulation, safe updates and audit history.

```
User → VEDA Website → VEDA Backend → Agent Bridge → Gemini OR Claude
                                          ↓
                            Horizun MCP + VEDA tools
                                          ↓
                        Structured Agent Result → VEDA Backend
                                          ↓
                        Website / Human Review / Outputs
```

## Responsibility model

| Component        | Owns                                              |
|------------------|---------------------------------------------------|
| Gemini / Claude  | reasoning                                         |
| Horizun MCP      | schedule machinery (CPM, DCMA, EV, dry-run)       |
| VEDA Backend     | persistence, workflow, validation                 |
| VEDA Website     | the human control plane                           |
| Human            | ambiguity resolution and consequential approval   |

VEDA never re-implements schedule machinery, and never presents an AI inference
as a schedule fact.

---

## Quick start

```bat
start_veda.bat
```

The script creates `.venv`, installs dependencies, warns about anything missing,
and opens <http://127.0.0.1:8770>.

### Prerequisites

| Requirement | Install | Needed for |
|---|---|---|
| Python 3.10+ | python.org | everything |
| Horizun MCP | `dotnet tool install -g HorizunMsProjectMcp` | schedule analysis |
| Claude Code | `npm install -g @anthropic-ai/claude-code` | reasoning (default) |
| Gemini key | set `GEMINI_API_KEY` | reasoning (alternative) |

Both providers are optional. Without either, VEDA still runs its rule-based
analyser and every finding is stamped `DETERMINISTIC_CALCULATION` rather than
being passed off as inference.

### Try it with the sample project

```bat
.venv\Scripts\python.exe tools\make_sample_data.py
```

Builds a 56-activity cross-country pipeline schedule (through Horizun itself, so
it is a genuine schedule file) plus the paperwork a real project produces: DPRs,
a welding register, an NDT/NCR log, material receipts, a weekly site report, a
site chat export — and one hostile document used to exercise the untrusted-data
rules.

Then in the website: **New project → Files → Upload** everything in
`sample_data\`. The agent wakes on its own.

---

## How it works

### Events wake the agent (no polling)

```
upload → files stored, hashed, scanned → dataset_uploaded
       → analysis job → agent wakes → Horizun + VEDA tools
       → structured result → validated → database → dashboard
```

Backend events: `dataset_uploaded`, `files_added`, `analysis_requested`,
`review_answered`, `review_approved`, `review_rejected`, `schedule_changed`,
`reprocess_requested`, `user_question`.

You never open Claude Code or Antigravity yourself.

### Provenance is the product

Every important fact declares where it came from, and the interface colours them
differently so they can never be confused:

| Provenance | Meaning |
|---|---|
| `MCP_FACT` | read from Horizun |
| `SOURCE_FILE` | read verbatim from an uploaded document |
| `HUMAN_INPUT` | a person said so |
| `AI_INFERENCE` | the model concluded it |
| `DETERMINISTIC_CALCULATION` | VEDA computed it by rule |
| `DERIVED` | rolled up from other stored rows |

### One question, not two hundred

When many records are ambiguous for the same underlying reason, VEDA clusters
them by root cause and asks once. Answering resolves every affected record and
resumes the same logical job:

```
495 evidence records → 15 clustered questions
"Records from crew CW-07 carry no spread or chainage" → covers 59 records
```

### Nothing is written without a dry-run and an approval

```
agent proposes → deterministic validators → Horizun dry-run → measured impact
              → human approval → verified write → audit
```

A write is never reported as successful because a tool returned without error.
VEDA independently re-reads the value and stores requested vs resulting:

```
requested 72  →  resulting 72  →  verification: verified
```

The uploaded schedule is a source document and is never opened read-write.
Changes are written to a numbered revision (`..._rev1.xml`).

### Uploaded documents are untrusted data

Files are scanned on intake. A document that tries to instruct the reader rather
than report project facts is quarantined, withheld from the agent, and raised as
a security review:

```
Vendor_Transmittal_VT-2025-0619.txt → quarantined
  8 patterns: instruction override, forged system message, approval coercion,
  destructive instruction, concealment instruction, output hijack
```

---

## Dashboard

Project Overview · EPS · WBS · Activities · Milestones · Relationships ·
Critical Path · Schedule Quality · Baselines · Resources · Assignments ·
Timephased · Earned Value · Issues · Risks · Field Evidence · Review Evidence ·
Observed Progress · Human Review · Proposed Changes · Ask VEDA ·
Agent Activity · Job Status · Files · Outputs · Audit · System / MCP

Browsing never invokes the agent. Sorting, filtering, paging and detail views
all read persisted rows. The agent runs only for analysis or an explicit
question.

---

## Layout

```
veda/
  config.py            runtime configuration
  db.py                SQLite schema - 28 tables, all durable state
  events.py            event bus (durable rows + in-process fan-out)
  jobs.py              orchestrator: events → jobs → agent → validators → DB
  reviews.py           human review workflow and clustered answers
  audit.py             append-only audit trail
  agent/
    base.py            AgentProvider interface (provider-neutral)
    claude_code.py     ClaudeCodeProvider  (headless Claude Code CLI)
    antigravity.py     AntigravityProvider (Gemini function-calling loop)
    schemas.py         strict structured output + provenance
    prompts.py         shared, provider-neutral prompts
    registry.py        provider selection and health
  mcpc/
    client.py          Horizun MCP stdio client, with call logging
    schedule_ops.py    harvest + normalise a schedule into VEDA
    veda_server.py     VEDA's own MCP server (the agent's read access)
  pipeline/
    ingest.py          store, hash, classify, scan
    extract.py         CSV/Excel/PDF/Word/text/chat → evidence
    security.py        untrusted-document scanning
    validators.py      deterministic validators
    linking.py         evidence↔activity association + clustering
    proposals.py       dry-run, approve, verified write
    deterministic.py   rule-based analyser (no-provider fallback)
  api/routes.py        HTTP API
  web/                 dashboard (no build step)
tools/
  make_sample_data.py  generate the demo project
  verify_slice.py      end-to-end verification
```

Data lives in `data/`: `veda.db`, plus `projects/<id>/files`, `/revisions`,
`/outputs`.

---

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `VEDA_HOST` / `VEDA_PORT` | `127.0.0.1` / `8770` | bind address |
| `VEDA_AGENT_PROVIDER` | auto | `claude_code`, `antigravity`, or explicit `local_antigravity` bridge |
| `VEDA_CLAUDE_MODEL` | `sonnet` | Claude Code model |
| `GEMINI_API_KEY` | — | enables Antigravity/Gemini |
| `VEDA_HORIZUN_CMD` | auto-detected | Horizun executable |
| `VEDA_ALLOW_FALLBACK` | `1` | rule-based analysis when no provider |
| `VEDA_AGENT_CLAIM_TIMEOUT` | `30` | seconds an unclaimed local-Antigravity inbox job may block the worker |
| `VEDA_DATA_DIR` | `./data` | storage root |

---

## Verify

```bat
.venv\Scripts\python.exe tools\verify_slice.py
```

Runs the real path end to end and prints the agent steps, the MCP calls, the
populated tables, the evidence states, the clustered questions, the issues and
risks with their provenance, and the security outcome.

## Not required

No Ollama, Qdrant, Chroma, LangGraph, Kubernetes or distributed infrastructure.
Retrieval-augmented search over the document corpus is a possible future
addition, not a dependency.
