# VEDA field-to-Primavera execution plan

## Outcome

VEDA should become the governed translation layer between what a field person
observed and what a planner may approve into the authoritative schedule. It
should not become a second schedule editor or a second system of record.

The shortest credible product loop is:

```text
voice / photo / text / location
            ↓
human-confirmed field event
            ↓
explicit or reviewed activity identity
            ↓
canonical execution event
            ↓
idempotent actuals proposal bundle
            ↓
validators → impact simulation → planner approval
            ↓
P6 sandbox write → independent re-read → evidence package
```

This sequence is deliberate. Oracle P6 already supports activity updates and
external-system synchronization; VEDA's product value is the evidence,
identity, policy and approval layer before that write, not replacement of P6.

## What this build slice now supplies

- **Workspace-first navigation:** Capture, Files, Edit/proposed changes and
  Review Inbox are the first items at the top-left. Dense schedule tables remain
  available as expert tools rather than dominating the primary workflow.
- **Mobile field capture:** started/progress/finished event, voice recording,
  camera/gallery media, typed text, permission-based coordinates, manual area,
  activity search, date/time, reporter and BCP-47 language tag.
- **Multilingual confirmation:** browser speech recognition is only a draft
  convenience. The audio remains evidence and the reporter must confirm the
  exact text that VEDA may use.
- **Offline recovery:** an IndexedDB outbox stores the capture and Blob media;
  online recovery is mandatory and Background Sync is used only where the
  browser supports it. A client-generated id makes retries idempotent.
- **Server authority:** confirmed envelopes are stored in SQLite and media in
  the immutable project file store. Browser state stops being authoritative as
  soon as the server acknowledges the capture.
- **Governed actuals:** a confirmed event becomes a canonical execution event
  and an idempotent proposal group. No capture endpoint can write a schedule.
- **P6 adapter boundary:** Release 26 Activity API mapping, OAuth client
  credentials, sandbox-only environment gate, explicit P6 project allow-list,
  activity ObjectId mapping and duration-unit conversion gates. It is inert
  until configured.

## Actuals proposal policy

| Confirmed event | Proposal(s) | Important rule |
|---|---|---|
| Start | `ActualStart = observed date` | If an official actual start already differs, hold a conflict. Never overwrite it. |
| Progress | `DurationPercentComplete = confirmed %` | A lower value than official progress is a conflict, not a regression. |
| Progress with explicit remaining work | `RemainingDuration = confirmed working days` | Never derive remaining duration mechanically from percent complete. Calendar conversion happens at the adapter boundary. |
| Finish | `ActualFinish = observed date`, `DurationPercentComplete = 100`, `RemainingDuration = 0` | One evidence/event group produces three reviewable proposals. They share provenance but remain independently validated. |
| Narrative progress without a number | Evidence and execution event only | Do not fabricate a percent or remaining duration. |
| Event without an activity | `needs_activity` field capture | Preserve it safely; no proposal exists until identity is resolved. |

Every proposal is unique by project, canonical event, activity and field. Mobile
retries, service-worker retries and duplicate taps therefore cannot create a
second actuals update.

## P0 delivery path

### 1. Field capture — harden the implemented slice

Next tasks:

1. Add client-side photo resizing with original retention policy configurable by
   project; do not destroy evidentiary originals by default.
2. Add a project language pack and terminology hints for optional server-side
   transcription. Keep the current confirm-before-use gate.
3. Add a `needs_activity` queue with activity search in the Review Inbox so a
   planner can resolve unmatched field captures without starting a full agent
   run.
4. Add resumable/chunked media transfer for recordings beyond the current
   bounded capture envelope.
5. Encrypt deployed offline storage or prevent sensitive capture on unmanaged
   devices according to the organization's device policy.

Exit criteria:

- a reporter can complete the core flow one-handed at a 360 px viewport;
- capture succeeds offline, survives a reload, and syncs exactly once;
- microphone and location are requested only after the relevant user action;
- original audio/photo, original transcript and confirmed wording remain
  distinguishable;
- a missing activity or ambiguous identity cannot create a proposal.

### 2. Actuals proposal engine — harden the implemented slice

Next tasks:

1. Add proposal-group approval so a finish bundle is reviewed atomically while
   retaining field-level validation and audit.
2. Add explicit conflict records for date disagreement, progress regression,
   duplicate-but-not-identical events and mutually inconsistent sources.
3. Read the P6 activity's PercentCompleteType before choosing duration versus
   physical percent; support ActivityStep proposals when weighted steps govern
   PhysicalPercentComplete.
4. Support ActivityPeriodActual proposals only where the project's financial
   period governance permits them.
5. Re-read the P6 activity after a sandbox update and compare every requested
   field before marking the proposal verified.

Exit criteria:

- start, progress and finish policy tests cover missing, equal, advancing and
  conflicting official values;
- no proposal is created from an unconfirmed transcript;
- every proposal cites at least one evidence id and one canonical event id;
- an approval is attributable to a role and a person;
- a tool HTTP 2xx is not treated as success until independent verification.

### 3. Primavera sandbox adapter

Roll out in four gates:

1. **Contract tests:** synthetic Activity objects and exact VEDA→P6 field
   mappings. No network.
2. **Read-only sandbox:** OAuth and ObjectId mapping; compare P6 values with the
   imported VEDA snapshot.
3. **Controlled write:** one allow-listed sandbox ProjectObjectId, one activity,
   one approved proposal, then independent re-read and audit.
4. **Synchronization mode:** use SyncService for externally synchronized
   projects/batches after idempotency, locking, status-date and partial-failure
   rules are proven with Oracle.

Required configuration before the first write:

- a sandbox base URL and OAuth client with least privilege;
- explicit ProjectObjectId allow-list;
- verified mapping from VEDA activity UID to P6 Activity ObjectId;
- project calendar conversion for duration values;
- nominated planner/approver identities and a rollback/reconciliation runbook.

Production remains disabled until sandbox round-trip evidence is signed off.

## P1 — operational pilot

### Conflict and duplicate workbench

Create one exception surface with four lanes:

- **conflicting actuals:** official versus observed date/progress;
- **possible duplicate:** same activity/state/date with different wording or
  media, with merge and “separate event” decisions;
- **multi-task statement:** split one source into child observations while
  retaining the source envelope;
- **unplanned work:** create a planning request, never silently invent a P6
  activity.

The workbench should show sources on the left, official schedule state in the
middle and the governed action on the right. Keyboard actions are useful for
planners; mobile capture should not expose this density.

### Reporting freshness

Model expected reporting cadence by contractor, discipline, area and shift.
Show:

- last confirmed field event and median report-to-link latency;
- expected versus received updates in the current reporting window;
- completeness of activity, location, reporter, event state and quantitative
  actuals;
- stale critical-path work first, with “not expected to report” distinct from
  “missing.”

### Roles and approvals

Introduce server-side authorization, not hidden buttons:

| Role | Core permission |
|---|---|
| Field reporter | create/view own captures; correct before planner decision |
| Planner | resolve identity, edit proposal values/reasons, run simulations |
| Approver | approve/reject within project/WBS scope; cannot alter evidence |
| Contracts | read/export evidence and decision timelines; no schedule write |
| Administrator | identity, project policy, connectors and retention |

Support separation of duties for high-risk projects: the proposal editor and
final approver must be different people.

### Operational AI metrics

Put operational metrics beside workflow health, not in a generic “AI” page:

- precision at the active automation threshold, based only on held-out or
  post-decision labels;
- false-link and human-correction rate by discipline/source;
- median/p90 review time and report-to-link latency;
- automatic, confirmed, deferred and unresolved rates;
- calibration coverage, with empirical and cold-start estimates separated;
- drift alerts when project terminology or error mix moves materially.

Never tune a threshold using the same decisions used to report its precision.

## P2 — defensibility and enterprise scale

### Institutional knowledge

Create tenant-scoped, versioned knowledge stores for terminology aliases,
reviewed identity corrections, contextual duration benchmarks, delay causes and
lessons learned. Do not pool raw project evidence across clients. Every reused
rule needs source project, reviewer, confidence, validity dates and reversal.

### Claims timeline

Generate an immutable package per activity/delay/claim containing:

1. original media/document hash and source locator;
2. extracted and confirmed text;
3. activity candidates, decision and actor;
4. canonical events in event-time order;
5. official value before, proposed value, validation and simulation;
6. approval/rejection and P6 request/response;
7. independent verification and resulting schedule revision.

Export PDF for human review plus JSON/CSV and original sources for machine and
legal discovery. A PDF alone is not the evidentiary archive.

### Enterprise connectors

Sequence connectors by value and control risk:

1. SSO/SCIM and project/WBS claims;
2. SharePoint/document intake with source version and retention metadata;
3. email ingestion with thread/message identity and attachment hashes;
4. notifications for assigned exceptions and approval SLA breaches;
5. ERP read models for cost/resource context, then narrowly governed writes.

Each connector needs idempotency keys, cursors/checkpoints, deletion policy,
tenant isolation, rate-limit recovery and a visible last-success/last-error
state.

## UI and accessibility rules

- Keep Capture, Files, Edit/proposed changes and Review Inbox in the first
  top-left navigation group; the user's current task should be visible without
  opening “Advanced.”
- Use a mobile drawer instead of deleting navigation at narrow widths.
- Keep primary capture targets at least 44 px where practical; WCAG 2.2's
  normative Target Size minimum is 24×24 CSS px, but gloves and site movement
  justify the larger product target.
- Respect `prefers-reduced-motion`; motion may communicate progress but must not
  be required to understand state.
- Preserve clear focus, visible light-theme outlines, programmatic labels and
  page/part language.
- Separate four states in plain language: saved on device, syncing, synced to
  VEDA and proposed to the planner. “Synced” must never imply “written to P6.”

## Primary references

- [Oracle P6 Release 26 REST endpoints](https://docs.oracle.com/en/industries/construction-engineering/primavera-p6-project/26/rest-api/rest-endpoints.html)
- [Oracle P6 Activity update API](https://docs.oracle.com/en/industries/construction-engineering/primavera-p6-project/26/rest-api/op-activity-put.html)
- [Oracle P6 SyncService](https://docs.oracle.com/en/industries/construction-engineering/primavera-p6-project/26/rest-api/api-syncservice.html)
- [Oracle P6 ActivityPeriodActual API](https://docs.oracle.com/en/industries/construction-engineering/primavera-p6-project/26/rest-api/api-activityperiodactual.html)
- [Oracle P6 ActivityStep API](https://docs.oracle.com/en/industries/construction-engineering/primavera-p6-project/26/rest-api/api-activitystep.html)
- [Oracle P6 pending ActivityUpdate fields](https://docs.oracle.com/cd/G48897_01/English/Integration_Documentation/p6_eppm_api_reference/com/primavera/integration/client/bo/object/ActivityUpdate.html)
- [MDN: installable PWAs](https://developer.mozilla.org/en-US/docs/Web/Progressive_web_apps/Guides/Making_PWAs_installable)
- [MDN: IndexedDB](https://developer.mozilla.org/en-US/docs/Web/API/IndexedDB_API/Using_IndexedDB)
- [MDN: Background Sync](https://developer.mozilla.org/en-US/docs/Web/API/Background_Synchronization_API)
- [MDN: MediaRecorder](https://developer.mozilla.org/en-US/docs/Web/API/MediaRecorder)
- [MDN: Geolocation](https://developer.mozilla.org/en-US/docs/Web/API/Geolocation_API)
- [MDN: media capture attribute](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Attributes/capture)
- [MDN: Web Speech API](https://developer.mozilla.org/en-US/docs/Web/API/Web_Speech_API/Using_the_Web_Speech_API)
- [W3C: WCAG 2.2 new criteria](https://www.w3.org/WAI/standards-guidelines/wcag/new-in-22/)
- [W3C: WCAG 2.2 applied to mobile](https://www.w3.org/TR/wcag2mobile-22/)
