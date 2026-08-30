# VEDA Anywhere ⇄ VEDA backend — integration contract

Every call the extension makes, and the exact backend route it maps to. All
routes are added by `veda/api/routes.py` (section “VEDA Anywhere”) and backed by
`veda/anywhere.py`. Base URL default: `http://127.0.0.1:8770`, prefix `/api`.

## Auth model

| Caller | Auth | Notes |
|---|---|---|
| VEDA web app → `/api/anywhere/{config,enable,config,pair,tokens/*}` | none (same local trust boundary as the rest of VEDA) | mutates the operator's own settings |
| Extension → `/api/anywhere/pair/complete` | the pairing **code** is the credential | code is single‑use, 5‑min TTL, one active at a time |
| Extension → everything else | `Authorization: Bearer <token>` | token issued at pairing; only its SHA‑256 digest is stored (`anywhere_tokens` table) |

Gate order on every extension action endpoint: **valid token → `401`**, then
**`anywhere.is_enabled()` → `403`**, then **scope check → `403`**, then
**project exists / not deleting → `404`/`409`**.

`GET /api/anywhere/session` requires only a valid token (not enabled) so the
extension can display the “disabled” state.

---

## Extension → backend

### `POST /api/anywhere/pair/complete`
Request: `{ "code": "VEDA-XXXX-XXXX" }`
Response `200`:
```jsonc
{
  "connected": true,
  "enabled": false,
  "account": { "workspace": "...", "data_dir": "...", "host": "127.0.0.1:8770" },
  "projects": [ { "id": "...", "name": "...", "client": null, "location": null } ],
  "default_project_id": null,
  "site_access": { "mode": "selected", "allowed_sites": ["teams.microsoft.com", ...] },
  "capture_metadata_defaults": { "include_url": false, "include_title": false, "include_source_app": false },
  "server_version": "0.3.x",
  "token": { "id": "awt_...", "value": "vda_...", "scopes": "ask,capture" }
}
```
Errors: `400` (no pairing in progress / expired / wrong code).
Consumed by: `background.js → completePairing()`.

### `GET /api/anywhere/session`  · Bearer
Response `200`: same shape as above minus `token.value` (adds
`token: {id,label,created_at}`). Errors: `401`.
Consumed by: `background.js → refreshSession()` (also clears local auth on `401`).

### `POST /api/anywhere/disconnect`  · Bearer
Response `200`: `{ "ok": true }` (revokes the calling token). Errors: `401`.

### `POST /api/anywhere/ask`  · Bearer · scope `ask` · enabled
Request:
```jsonc
{ "project_id": "...", "text": "<selection>", "follow_up": "<optional>", "source_host": "teams.microsoft.com" }
```
Response `200`: `{ "job_id": "...", "event_id": "...", "injection": {...}, "project": {...}, "read_only": true }`
Behaviour: emits the existing `USER_QUESTION` event with the selection wrapped as
**quoted untrusted data** (`anywhere.build_question_prompt`). Runs through the
normal question job → `answer` artifact. Never writes schedule data.
Errors: `401/403` (gate), `404` (project), `422` (empty / >8000 chars).

### `GET /api/anywhere/ask/{job_id}?project_id=`  · Bearer · scope `ask`
Response `200`:
```jsonc
{ "job_id": "...", "status": "queued|running|done|failed",
  "phase": "...", "stage": "Reasoning",   // human-readable current step
  "started_at": 0,
  "answer": "<markdown>", "provenance": "AI_INFERENCE|DETERMINISTIC_CALCULATION", "answered_at": 0,
  "error": "<only when failed>" }
```
Errors: `404` (unknown question / project mismatch).
Consumed by: the overlay polls this every 2 s for up to 5 minutes while open,
showing `stage` and elapsed time. The question is persisted to
`chrome.storage.local` (`va_ask`), so closing/reopening the panel resumes the
poll. The completed answer is always visible in the VEDA app's **Ask VEDA** page
regardless — `/projects/{pid}/answers` tags it `source_type: "browser_extension"`
(derived from the durable `anywhere_ask` audit row, since the job's `result_json`
is overwritten with the answer on completion).

### `POST /api/anywhere/capture/detect`  · Bearer · scope `capture` · enabled
Request: `{ "project_id": "...", "text": "<selection>" }`
Response `200`:
```jsonc
{
  "project": { "id": "...", "name": "..." },
  "injection": { "state": "clean|suspicious|quarantined", "flagged": false, "quarantined": false, "labels": [], "note": null },
  "detection": {
    "detected_type": "Progress Update",
    "event_state": "start|progress|finish",
    "raw_event_state": "progress|blocked|...",
    "observed_progress": 65.0,
    "non_progress": false,
    "activity": { "uid": 103, "display_id": "PIPE-L24-HT", "name": "...", "wbs": "...", "score": 0.46, "confidence": 0.91, "supporting": [...] },
    "confidence": 0.91,
    "alternatives": [ { "uid": ..., "display_id": ..., "name": ... } ],
    "engine": "metarank_resolver|deterministic_fallback|event_classifier_only",
    "has_schedule": true
  }
}
```
Read‑only: runs `classify_event` + `retrieval.engine.hybrid_search` +
`retrieval.calibration` (Semantic → Engineering → Tree → Rescheduler → MetaRank →
probability calibration). Persists nothing.
Errors: `401/403`, `404`, `422`.

### `POST /api/anywhere/capture`  · Bearer · scope `capture` · enabled
Request:
```jsonc
{
  "project_id": "...",
  "text": "<selection>",
  "activity_uid": 103,               // optional; omit/null to let the resolver decide
  "event_state": "finish",           // start|progress|finish (default progress)
  "client_capture_id": "awc_<uuid>", // idempotency key ([A-Za-z0-9._:-]{8,120})
  "occurred_at": "2026-08-30T12:00:00.000Z", // optional ISO; defaults to now
  "observed_progress": 100,          // optional
  "source_host": "teams.microsoft.com",
  "metadata": {
    "include_url": true,  "url": "https://teams.microsoft.com/...",
    "include_title": false, "title": "...",
    "include_source_app": true, "source_app": "Microsoft Teams"
  }
}
```
Response `200`:
```jsonc
{
  "ok": true,
  "idempotent_replay": false,
  "project": { "id": "...", "name": "..." },
  "capture": { ...field_capture row... },
  "evidence_id": "fcev_...",
  "evidence_ref": "EV-XXXXXX",
  "status": "proposal_ready|needs_activity|confirmed_no_change|conflict",
  "review_status": "Linked - actuals proposal pending approval | Needs a human decision | Held for security review | ...",
  "matched_activity": { "uid": 103, "display_id": "...", "name": "...", "wbs": "...", "relation": "supporting", "confidence": 1.0 } | null,
  "injection": { ...same shape as detect... },
  "note": "Captured text is evidence, not an instruction. ..."
}
```
Behaviour:
1. `anywhere.scan_text()` (prompt‑injection). `quarantined` → evidence stored but
   `security_state=quarantined`, `state=quarantined`, held for review, resolver
   skipped. `suspicious` → `security_state=suspicious`, held for review.
2. `field_capture.store()` with `sync_source="browser_extension"` → immutable
   evidence (`provenance=HUMAN_INPUT`). A confirmed `activity_uid` runs the full
   confirmed path (execution event + governed **actuals proposal**, approval
   required).
3. Unlinked + schedule present + not flagged → one targeted
   `linking.link_evidence()` pass (the schedule‑linking resolver + validators +
   risk policy) → link or clustered human‑review item.
4. `metadata` merged into evidence `raw_json.browser_capture` — only the fields
   you opted into, plus `selection_sha256` (SHA‑256 of the exact text).
5. `audit.record(action="anywhere_capture", source="browser_extension", ...)`
   with capture id, project, selected text, timestamp, source type, optional
   source site/app, evidence hash, activity match, confidence, review status.
Errors: `401/403`, `404`, `409`, `422`.

---

## VEDA web app → backend (VEDA Anywhere settings page)

| Method & path | Purpose |
|---|---|
| `GET /api/anywhere/config` | settings + paired tokens + pairing status + project list + unpacked‑install path |
| `POST /api/anywhere/enable` `{enabled}` | the master on/off switch (default **off**) |
| `POST /api/anywhere/config` `{site_access_mode?, allowed_sites?, default_project_id?, capture_metadata_defaults?}` | website access + default project |
| `POST /api/anywhere/pair` | mint a pairing code (`{code, expires_at, ttl_seconds}`) |
| `DELETE /api/anywhere/pair` | cancel the in‑progress pairing |
| `POST /api/anywhere/tokens/{id}/revoke` | revoke one paired browser |
| `POST /api/anywhere/tokens/revoke-all` | revoke every paired browser |

The VEDA Anywhere and System pages render without a project. The extension's
**Create a project** buttons open `<baseUrl>/#new-project`, which the web app
intercepts to open the project‑creation dialog directly.

---

## Browser ⇄ VEDA page bridge (`content/bridge.js`, VEDA origin only)

`window.postMessage`, same‑origin, `channel: "veda-anywhere"`. **Presence only —
the bridge never carries the pairing code and never completes pairing.**

| From | Message | Meaning |
|---|---|---|
| page → bridge | `{source:"veda-web", type:"ping"}` | “is the extension installed?” |
| bridge → page | `{source:"veda-anywhere", type:"hello"\|"pong", version}` | yes; the page also reads `document.documentElement[data-veda-anywhere]` |

Pairing is completed only in the extension popup, by the operator typing the
code. The bridge does not read page content and holds no credentials.

## Pairing‑code comparison

`anywhere.complete_pairing()` normalises both sides by stripping spaces, dashes
and underscores and upper‑casing, then does a constant‑time compare and requires
≥ 8 significant characters. The code is single‑use and consumed on success.

---

## Schema addition

`veda/db.py` adds one table:

```sql
CREATE TABLE anywhere_tokens (
  id TEXT PRIMARY KEY,
  token_sha256 TEXT NOT NULL,     -- digest only; raw token never stored
  label TEXT, user_agent TEXT,
  scopes TEXT DEFAULT 'ask,capture',
  revoked INTEGER DEFAULT 0,
  created_at REAL, last_used_at REAL, last_seen_origin TEXT
);
```

Settings and the in‑progress pairing live in the existing `kv` table
(`anywhere_settings`, `anywhere_pairing`).

---

## Version compatibility

* Extension `1.0.0` targets the VEDA Anywhere API introduced in this VEDA
  release. `GET /api/anywhere/session` returns `server_version`; the popup and
  options page display it.
* The extension degrades safely: backend unreachable → clear “VEDA is not
  reachable” state; token revoked server‑side → next call `401` → extension
  drops local auth and shows “Connect to VEDA”.
