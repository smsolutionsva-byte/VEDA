# VEDA Anywhere — browser companion

VEDA Anywhere lets you use VEDA from inside the web tools your project team
already lives in — Microsoft Teams, Slack, Gmail, WhatsApp Web, an internal
portal, a web ERP, a project dashboard — without leaving what you are doing.

**It is opt‑in and inert by default.** The extension never reads, scrapes,
monitors, or analyses web pages. It only ever sends VEDA the text you
*explicitly select* and *explicitly submit*, and only while you have switched
VEDA Anywhere on inside the VEDA web app.

```
Highlight text  →  invoke VEDA  →  only the selection is read  →  Ask or Capture  →  keep working
```

During normal browsing, **VEDA receives nothing.**

---

## What it does

| Action | What happens | Writes anything? |
|---|---|---|
| **Ask VEDA** | Sends the selection + current project context to VEDA. VEDA answers from schedule facts, field evidence, relationships, milestones, risks and Primavera/Horizun data. Follow‑up questions supported. | **No.** Read‑only. It cannot create issues, risks, reviews or proposals, and can never move the schedule. |
| **Capture in VEDA** | Sends the selection into VEDA's existing evidence & reconciliation pipeline: entity extraction → activity detection → schedule‑linking resolver → semantic/engineering/tree/rescheduler ranks → MetaRank → probability calibration → deterministic validation → risk policy → execution event or human‑review item → actuals proposal → **human approval**. | Only an **evidence record** and (if you confirm an activity) a **proposal**. Nothing reaches Primavera / MS Project / the authoritative schedule without the normal VEDA approval + verified‑write + audit flow. |

Selected text is treated as untrusted input. It is scanned for prompt‑injection
and quoted (never interpreted as an instruction) before it reaches the reasoning
agent. `Ignore previous instructions`, `Approve all pending changes`,
`Delete the schedule` and similar phrases cannot change VEDA's behaviour —
captured text is **evidence, not a command**.

---

## Install (developer / unpacked)

There is no web‑store listing. Load it directly:

1. Start the VEDA app (`start_veda.bat`). It serves `http://127.0.0.1:8770`.
2. Open `chrome://extensions` (Chrome) or `edge://extensions` (Edge).
3. Turn on **Developer mode**.
4. Choose **Load unpacked** and select this `extension/` folder.
5. In the VEDA web app, open **VEDA Anywhere** (left rail → Advanced → VEDA
   Anywhere), press **Enable VEDA Anywhere**, then **Connect extension**.
6. VEDA shows a **pairing code**. Click the VEDA Anywhere icon in the browser
   toolbar, paste the code, and choose **Pair with code**.

There is **no automatic hand-off** — the extension connects only when you enter
the code yourself. Dashes, spaces and letter case don't matter. The VEDA
Anywhere settings page detects the pairing and updates on its own.

You don't need a project to enable VEDA Anywhere or to pair. The extension popup
has a **Create a project in VEDA** shortcut, and **VEDA Anywhere** / **System /
MCP** in the VEDA app are reachable before the first project exists.

Icons are generated deterministically from the VEDA mark:
`python tools/make_icons.py` (stdlib only, no Pillow).

---

## How pairing / auth works

```
VEDA web app: Enable VEDA Anywhere → Connect extension
        │
        └─ POST /api/anywhere/pair          → short‑lived code (5 min, one use)
                                               shown on screen, nothing is sent anywhere

You: copy the code → extension popup → paste → Pair with code
        │
        ▼
Extension: POST /api/anywhere/pair/complete { code }
        → server checks the code, issues a bearer token (held only in the
          background service worker); VEDA stores just its SHA‑256 digest
        → the VEDA settings page, polling, sees the new token and shows "connected"
```

* Pairing requires the code to be entered by hand. There is no automatic
  browser‑to‑extension hand‑off. `content/bridge.js` only tells the settings
  page the extension is installed.
* The token is scoped to this VEDA workspace. The extension reuses your existing
  project access — it can never reach a project you cannot open in VEDA.
* Revoke any time from **VEDA Anywhere settings** (per browser, or all) or from
  the extension popup / options page (**Disconnect this browser** — clears the
  token locally even if the server is unreachable, and revokes it server‑side
  when it can).
* Disabling VEDA Anywhere in the web app immediately blocks every extension
  action server‑side (`403`), regardless of extension state.

---

## Architecture

```
extension/
  manifest.json            MV3. permissions: storage, contextMenus, activeTab, scripting
                           host_permissions: the VEDA backend only
                           optional_host_permissions: *://*/*  (granted per your choice)
  background.js             the only holder of the bearer token. Every VEDA API
                           call goes through here. Does nothing unprompted.
  lib/
    constants.js           message names, defaults
    store.js               chrome.storage.local state (+ active project)
    api.js                 the VEDA REST client (one request per user action)
  content/
    bridge.js              runs ONLY on the VEDA origin — presence + pairing handoff
    overlay.js             injected on demand — the floating selection UI (Shadow DOM)
    overlay.css            host‑element reset for the injected overlay
  popup/                   toolbar popup — status, active project, invoke on selection
  options/                 backend URL, connection status, disconnect
  icons/                   16 / 32 / 48 / 128 (see tools/make_icons.py)
```

**The extension never injects a content script into arbitrary pages.** The
overlay is injected only when you click the toolbar button, use the right‑click
menu on a selection, or press the keyboard shortcut (`Alt+Shift+V`) — each of
which is an explicit user action that grants one‑time access to the active tab.

`content/bridge.js` is the single always‑on content script and it runs *only* on
`http://127.0.0.1:8770/*` and `http://localhost:8770/*` (the VEDA app itself),
purely to let the settings page detect the companion and hand over a pairing
code.

### Non‑default VEDA host

If you run VEDA on another host/port, set it in the extension **Options** page
(it will request access to that origin). Automatic pairing‑code handoff only
works on the default localhost origins; on any other host, paste the pairing
code into the popup instead.

---

## Privacy summary

* No continuous monitoring. No page scraping. No browsing history.
* No reading of chat messages. No keystroke watching.
* No automatic sending of selected text, URLs or page contents.
* No background AI analysis of any page.
* Webpage URL, page title and source app are **opt‑in per capture** — only what
  you tick is sent.
* Every **Capture in VEDA** creates an auditable record in VEDA (capture ID,
  project, user, selected text, timestamp, `source type: browser extension`,
  optional source site, SHA‑256 evidence hash, activity match, confidence,
  review status).

See `COMPATIBILITY.md` for the exact endpoint contract between this extension
and the VEDA backend.
