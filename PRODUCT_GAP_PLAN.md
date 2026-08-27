# VEDA product gap and delivery plan

## Product thesis

VEDA should be the schedule ground-truth layer between field reality and the
authoritative planning system. Its differentiator is not schedule authoring. It
is the conversion of heterogeneous site evidence into validated, explainable,
schedule-linked execution events.

The repository already contains unusually strong foundations for that thesis:

- multi-source intake, adaptive extraction and source quarantine;
- engineering-aware entity resolution with four expert rankers;
- calibrated confidence kept separate from ranking scores;
- clustered human review and reusable human corrections;
- canonical execution events and activity identity across revisions;
- schedule proposals gated by validation, dry-run, approval and verified writes;
- provenance and append-only audit history.

## Current product gaps

| Priority | Gap | Why it matters | Current state |
|---|---|---|---|
| P0 | Explainable planner review inbox | This is the core field-to-schedule decision workflow and the clearest product differentiator. | First slice implemented: evidence, candidates, reasons, contradictions, confidence basis and governed action are shown together. |
| P0 | Field-first capture | Supervisors still need a Files page or pasted text. The intended workflow is a fast mobile report with voice, photo, location, offline queue and confirmation. | Missing. |
| P0 | Actuals proposal generation | Validated execution events exist, but the product does not yet consistently translate them into Actual Start, Actual Finish, Remaining Duration or Percent Complete proposals. | Partial infrastructure; incomplete end-to-end policy. |
| P0 | Primavera adapter | Horizun/MS Project revision writes are implemented, but OIL's target system needs a real P6 REST/SyncService adapter with environment-safe simulation. | Missing. |
| P1 | Exception-driven control room | The current overview is factually rigorous but dominated by technical schedule cards. A manager needs freshness, slippage, missing reports, conflicts and decisions first. | Partial. |
| P1 | Conflict and duplicate workbench | Validators and source hashing exist, but planners need a dedicated workflow for conflicting dates, duplicate execution events and multi-activity statements. | Partial. |
| P1 | Reporting freshness and SLA | There is no clear reporting-latency model by discipline, contractor, area or source. | Missing. |
| P1 | Role and permission model | Field reporters, planners, approvers, contracts users and administrators currently share one local interface and hard-coded actor labels. | Missing. |
| P1 | Operational metrics | Matching benchmarks exist offline, but the product does not show precision-at-threshold, automation rate, false auto-link rate, time-to-review or report-to-link latency. | Missing in product. |
| P2 | Cross-project knowledge | Canonical events exist per project, but reusable organization terminology, duration benchmarks, delay patterns and lessons learned are not yet a product surface. | Foundation only. |
| P2 | Enterprise integrations | Email, SharePoint/document systems, ERP, notifications and identity providers are not connected. | Missing. |
| P2 | Claims/evidence timeline | Audit exists, but contracts teams need a chronological, exportable evidence package per activity, delay or claim. | Partial foundation. |
| P3 | Visual reality capture | Photo/BIM/360-degree inference can complement text evidence but should follow the textual field-to-schedule MVP. | Deferred intentionally. |

## Target experiences

### 1. Capture — site supervisor and engineer

- one primary action: speak, type, photograph or attach;
- show the interpreted action, asset, location, date, quantity and delay cause;
- show the likely activity in plain field language;
- let the person confirm, correct or leave unmatched;
- work offline and show sync status explicitly.

### 2. Review Inbox — planner and project controls

- organize work by exception: match, conflict, security, failure and governed change;
- show field evidence beside schedule candidates;
- explain positive and conflicting signals;
- label empirical calibration separately from cold-start estimates;
- confirm identity without implying schedule mutation;
- send actuals through validation, dry-run, approval and verification.

### 3. Control Room — PM and management

- show what needs intervention, not total record counts;
- prioritize critical-path impact, field-versus-schedule variance, reporting
  staleness, unplanned work and unresolved conflicts;
- provide drill-through to evidence and responsible discipline/contractor;
- keep detailed schedule tables available as secondary expert tools.

### 4. Knowledge and Audit — PMO, contracts and future projects

- preserve canonical execution events independently of changing activity IDs;
- learn organization and contractor terminology from reviewed corrections;
- compare planned versus actual duration with context and delay cause;
- export activity/claim timelines with source, actor, decision and write verification.

## Delivery sequence

### Phase 1 — trusted reconciliation MVP

1. Complete the explainable Review Inbox and keyboard-efficient review flow.
2. Add an installable mobile capture route with text/photo first, then local speech-to-text.
3. Convert confirmed start/progress/finish events into governed actuals proposals.
4. Add a simulated P6 adapter contract and mapping tests using synthetic data.
5. Add precision-at-threshold, review time and ingestion-to-link latency telemetry.

Exit criteria:

- a DPR, spreadsheet row or field note becomes a structured execution event;
- top candidates and reasons are visible;
- ambiguous evidence produces no automatic schedule update;
- a confirmed event creates a dry-runnable actuals proposal;
- every action is attributable and reversible.

### Phase 2 — operational pilot

1. Offline capture queue, media compression and sync recovery.
2. Project roles, WBS-scoped permissions and configurable approval policy.
3. Dedicated conflict, duplicate and multi-match workflows.
4. Reporting freshness by contractor, discipline and area.
5. Real P6 REST/SyncService read adapter and isolated write sandbox.

Exit criteria:

- field users can report under poor connectivity;
- planners review only exceptions;
- approvers see old value, proposed value, source evidence and simulated impact;
- pilot activity actuals can round-trip through a non-production P6 environment.

### Phase 3 — control and learning

1. Exception-driven management control room.
2. Cross-project terminology and correction memory with tenant boundaries.
3. Planned-versus-actual duration and recurring delay-cause analytics.
4. Claims-ready activity and delay evidence timelines.
5. Portfolio views and project health comparisons.

### Phase 4 — enterprise scale

1. SSO, fine-grained authorization, retention policy and deployment hardening.
2. Email/document management and notification integrations.
3. Production P6 change-window, locking, retry and reconciliation controls.
4. Model monitoring, drift detection and organization-specific calibration.
5. Optional BIM/photo/360-degree evidence adapters.

## UX decisions grounded in current products

- Oracle P6 already uses a status-update approval queue with pending/held/approved
  history. VEDA should preserve that governance while adding semantic identity
  resolution before the update exists.
- InEight proves the value of mobile field logs, quantities, photos and sign-off,
  but its workflow starts from predefined work packages. VEDA's capture must also
  accept legacy reports that were never structured against a package.
- Planlab validates live collaboration, permissions, change history and P6
  integration around the schedule. VEDA should keep schedule collaboration as an
  integration boundary and own the evidence-to-actuals trust layer.
- Procore validates low-friction mobile daily capture and searchable historical
  logs. VEDA should make capture equally easy while adding activity reconciliation.

Official references:

- Oracle P6 Team Member status review: https://docs.oracle.com/cd/F88966_01/p6help/en/51331.htm
- Oracle P6 REST activities: https://docs.oracle.com/en/industries/construction-engineering/primavera-p6-project/26/rest-api/rest-endpoints.html
- Oracle P6 SyncService: https://docs.oracle.com/en/industries/construction-engineering/primavera-p6-project/26/rest-api/api-syncservice.html
- InEight Plan & Progress: https://ineight.com/products/ineight-plan-and-progress/
- Planlab collaboration: https://www.planlab.ai/collaboration
- Procore Daily Log: https://www.procore.com/quality-safety/daily-log

## First implementation slice

The initial change deliberately targets the planner's magic moment rather than
adding another dashboard:

- navigation is reorganized around Operate, Field Truth, Schedule, Project Data
  and Advanced tools;
- Needs Attention becomes Review Inbox;
- inbox filters separate match decisions, governed schedule changes, source
  security and processing failures;
- each match review shows field quotations beside schedule candidates;
- each candidate shows activity ID, WBS, dates, status, ranking/calibration label,
  supporting signals and contradictions;
- the UI states explicitly that confirming identity does not write to the schedule.

## Judge-ready execution experience

The second implementation slice turns waiting time into an auditable product
demonstration rather than a generic spinner:

- the shell now supports polished light and dark themes, follows the operating
  system on first use, and remembers an explicit user choice;
- source ingestion shows the real intake contract—batch transfer, integrity and
  security checks, immutable storage and run creation;
- the analysis screen presents the production resolver architecture from field
  observation through semantic retrieval, the four-expert candidate union,
  LambdaMART MetaRank and governed downstream controls;
- node state is derived from persisted job/activity rows delivered through the
  existing project event stream; no invented percentage or chain-of-thought is
  displayed;
- the schedule-write boundary is visually distinct and remains guarded even
  after analysis completes because analysis completion is not write approval;
- the detailed activity and Horizun call logs remain available as secondary
  execution evidence.

The visual behavior follows AWS Step Functions' execution-graph convention of
showing real node status and selectable execution detail, Carbon's distinction
between productive and expressive motion, and Carbon/Material guidance for
layered light and dark surfaces. Motion is disabled for reduced-motion users.

Additional official references:

- AWS execution graph: https://docs.aws.amazon.com/step-functions/latest/dg/concepts-view-execution-details.html
- AWS Workflow Studio: https://docs.aws.amazon.com/step-functions/latest/dg/workflow-studio.html
- Carbon motion: https://carbondesignsystem.com/elements/motion/overview/
- Carbon themes: https://carbondesignsystem.com/elements/themes/code/
- Material dark theme: https://design.google/library/material-design-dark-theme
