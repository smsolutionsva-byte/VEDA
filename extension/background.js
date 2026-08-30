/* VEDA Anywhere - background service worker.

   This is the only place that holds the VEDA bearer token. The popup and the
   on-page overlay never see it: they ask the worker to perform an action, the
   worker calls VEDA, and returns the result.

   The worker does nothing on its own. It reacts only to:
     - the operator clicking the toolbar icon / context menu / keyboard command
     - a pairing code handed over from the VEDA web app
     - the popup or overlay asking it to do one specific thing
*/
import { MSG, EXTENSION_VERSION } from './lib/constants.js';
import { getState, setState, clearAuth, resolveActiveProjectId } from './lib/store.js';
import { api, VedaApiError } from './lib/api.js';

const CONTEXT_ASK = 'veda-ask';
const CONTEXT_CAPTURE = 'veda-capture';

// --------------------------------------------------------------------------- //
//  Lifecycle                                                                   //
// --------------------------------------------------------------------------- //

chrome.runtime.onInstalled.addListener(() => {
  rebuildContextMenus();
});
chrome.runtime.onStartup.addListener(() => {
  rebuildContextMenus();
});

function rebuildContextMenus() {
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create({
      id: CONTEXT_ASK,
      title: 'Ask VEDA about "%s"',
      contexts: ['selection'],
    });
    chrome.contextMenus.create({
      id: CONTEXT_CAPTURE,
      title: 'Capture "%s" in VEDA',
      contexts: ['selection'],
    });
  });
}

chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (!tab || !tab.id) return;
  const mode = info.menuItemId === CONTEXT_CAPTURE ? 'capture' : 'ask';
  openOverlay(tab.id, mode).catch((err) => console.warn('[VEDA] overlay', err));
});

chrome.commands.onCommand.addListener((command) => {
  if (command !== 'invoke-veda') return;
  chrome.tabs.query({ active: true, currentWindow: true }).then(([tab]) => {
    if (tab && tab.id) openOverlay(tab.id, 'menu').catch((err) => console.warn('[VEDA] overlay', err));
  });
});

// --------------------------------------------------------------------------- //
//  Overlay injection (explicit, on-demand only)                                //
// --------------------------------------------------------------------------- //

async function openOverlay(tabId, mode) {
  try {
    await chrome.scripting.insertCSS({ target: { tabId }, files: ['content/overlay.css'] });
  } catch (_) { /* already inserted, or restricted page */ }
  try {
    await chrome.scripting.executeScript({ target: { tabId }, files: ['content/overlay.js'] });
  } catch (err) {
    // Restricted pages (chrome://, the Web Store, PDF viewer) cannot be scripted.
    throw err;
  }
  try {
    await chrome.tabs.sendMessage(tabId, { type: MSG.OPEN_OVERLAY, mode });
  } catch (_) { /* overlay will pick up mode from its own init */ }
}

// --------------------------------------------------------------------------- //
//  Pairing + session                                                           //
// --------------------------------------------------------------------------- //

async function completePairing(code) {
  const state = await getState();
  const result = await api.completePairing(state.baseUrl, String(code || '').trim());
  const token = result.token && result.token.value;
  if (!token) throw new VedaApiError('Pairing did not return a token.', 0, {});
  await setState({
    token,
    tokenId: (result.token && result.token.id) || null,
    account: result.account || null,
    enabled: Boolean(result.enabled),
    projects: result.projects || [],
    defaultProjectId: result.default_project_id || null,
    activeProjectId: result.default_project_id || (result.projects && result.projects[0] && result.projects[0].id) || null,
    siteAccess: result.site_access || { mode: 'selected', allowed_sites: [] },
    captureMetadataDefaults: result.capture_metadata_defaults ||
      { include_url: false, include_title: false, include_source_app: false },
    serverVersion: result.server_version || null,
    lastSync: Date.now(),
  });
  broadcastStateChanged();
  return { ok: true };
}

async function refreshSession() {
  const state = await getState();
  if (!state.token) return { ok: false, reason: 'not_connected' };
  try {
    const s = await api.session(state.baseUrl, state.token);
    const projects = s.projects || [];
    const ids = new Set(projects.map((p) => p.id));
    await setState({
      account: s.account || null,
      enabled: Boolean(s.enabled),
      projects,
      defaultProjectId: s.default_project_id || null,
      activeProjectId: ids.has(state.activeProjectId) ? state.activeProjectId
        : (s.default_project_id || (projects[0] && projects[0].id) || null),
      siteAccess: s.site_access || state.siteAccess,
      captureMetadataDefaults: s.capture_metadata_defaults || state.captureMetadataDefaults,
      serverVersion: s.server_version || null,
      lastSync: Date.now(),
    });
    broadcastStateChanged();
    return { ok: true };
  } catch (err) {
    if (err instanceof VedaApiError && err.status === 401) {
      await clearAuth();
      broadcastStateChanged();
      return { ok: false, reason: 'revoked' };
    }
    return { ok: false, reason: 'unreachable', error: err.message };
  }
}

async function disconnect() {
  const { baseUrl, token } = await getState();
  // Clear local auth FIRST so the extension is disconnected even if the server
  // is unreachable or the service worker is torn down mid-request.
  await clearAuth();
  broadcastStateChanged();
  if (token) {
    // Revoke the token server-side, best effort - the local disconnect stands
    // regardless of the outcome.
    api.disconnect(baseUrl, token).catch(() => {});
  }
  return { ok: true, disconnected: true };
}

function broadcastStateChanged() {
  try {
    chrome.runtime.sendMessage({ type: MSG.STATE_CHANGED }).catch(() => {});
  } catch (_) { /* no receivers */ }
}

// --------------------------------------------------------------------------- //
//  Ask VEDA (read-only)                                                        //
// --------------------------------------------------------------------------- //

// Start the question and return immediately. The overlay drives polling via
// ASK_POLL so each service-worker invocation stays short (MV3-friendly).
async function runAsk({ projectId, text, followUp, sourceHost }) {
  const state = await requireConnectedEnabled();
  const pid = projectId || resolveActiveProjectId(state);
  if (!pid) throw new VedaApiError('Choose a VEDA project first.', 0, {});
  const started = await api.ask(state.baseUrl, state.token, {
    project_id: pid,
    text,
    follow_up: followUp || null,
    source_host: sourceHost || null,
  });
  return { ok: true, jobId: started.job_id, injection: started.injection, projectId: pid };
}

async function pollAsk({ jobId, projectId }) {
  const state = await getState();
  if (!state.token) return { ok: false, error: 'not connected' };
  const status = await api.askStatus(state.baseUrl, state.token, jobId, projectId);
  return { ok: true, ...status };
}

// --------------------------------------------------------------------------- //
//  Capture in VEDA                                                             //
// --------------------------------------------------------------------------- //

async function runDetect({ projectId, text }) {
  const state = await requireConnectedEnabled();
  const pid = projectId || resolveActiveProjectId(state);
  if (!pid) throw new VedaApiError('Choose a VEDA project first.', 0, {});
  const result = await api.detect(state.baseUrl, state.token, { project_id: pid, text });
  return { ok: true, ...result, projectId: pid };
}

async function runCapture(payload) {
  const state = await requireConnectedEnabled();
  const pid = payload.projectId || resolveActiveProjectId(state);
  if (!pid) throw new VedaApiError('Choose a VEDA project first.', 0, {});
  const result = await api.capture(state.baseUrl, state.token, {
    project_id: pid,
    text: payload.text,
    activity_uid: payload.activityUid || null,
    event_state: payload.eventState || 'progress',
    client_capture_id: payload.clientCaptureId,
    occurred_at: payload.occurredAt || null,
    observed_progress: payload.observedProgress ?? null,
    source_host: payload.sourceHost || null,
    metadata: {
      include_url: Boolean(payload.metadata && payload.metadata.include_url),
      include_title: Boolean(payload.metadata && payload.metadata.include_title),
      include_source_app: Boolean(payload.metadata && payload.metadata.include_source_app),
      url: payload.metadata && payload.metadata.url,
      title: payload.metadata && payload.metadata.title,
      source_app: payload.metadata && payload.metadata.source_app,
    },
  });
  return { ok: true, ...result, projectId: pid };
}

// --------------------------------------------------------------------------- //
//  Helpers                                                                     //
// --------------------------------------------------------------------------- //

async function requireConnectedEnabled() {
  const state = await getState();
  if (!state.token) throw new VedaApiError('Connect VEDA Anywhere first.', 401, {});
  if (!state.enabled) {
    // Re-check the server in case it was just toggled on.
    const r = await refreshSession();
    const fresh = await getState();
    if (!fresh.enabled) {
      throw new VedaApiError('VEDA Anywhere is disabled. Enable it in the VEDA app.', 403,
        { reason: r.reason });
    }
    return fresh;
  }
  return state;
}

async function getActiveSelection(tabId) {
  try {
    const [{ result } = {}] = await chrome.scripting.executeScript({
      target: { tabId },
      func: () => {
        const sel = window.getSelection();
        return {
          text: sel ? String(sel.toString()) : '',
          url: location.href,
          host: location.host,
          title: document.title,
        };
      },
    });
    return result || { text: '', url: '', host: '', title: '' };
  } catch (_) {
    return { text: '', url: '', host: '', title: '' };
  }
}

// --------------------------------------------------------------------------- //
//  Message router                                                              //
// --------------------------------------------------------------------------- //

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  handleMessage(message, sender).then(sendResponse).catch((err) => {
    sendResponse({ ok: false, error: err && err.message ? err.message : String(err),
      status: err && err.status, data: err && err.data });
  });
  return true; // async
});

async function handleMessage(message, sender) {
  switch (message && message.type) {
    case MSG.PAIR:
      return completePairing(message.code);
    case MSG.SESSION_GET: {
      const state = await getState();
      return { ok: true, state: redactState(state) };
    }
    case MSG.SESSION_REFRESH:
      await refreshSession();
      return { ok: true, state: redactState(await getState()) };
    case MSG.SET_ACTIVE_PROJECT:
      await setState({ activeProjectId: message.projectId || null });
      broadcastStateChanged();
      return { ok: true };
    case MSG.DISCONNECT:
      return disconnect();
    case MSG.ASK:
      return runAsk(message.payload || {});
    case MSG.ASK_POLL:
      return pollAsk({ jobId: message.jobId, projectId: message.projectId });
    case MSG.DETECT:
      return runDetect(message.payload || {});
    case MSG.CAPTURE:
      return runCapture(message.payload || {});
    case MSG.GET_SELECTION: {
      const tabId = (sender.tab && sender.tab.id) ||
        (await chrome.tabs.query({ active: true, currentWindow: true }))[0]?.id;
      if (!tabId) return { ok: false, error: 'no active tab' };
      return { ok: true, selection: await getActiveSelection(tabId) };
    }
    case MSG.OPEN_OVERLAY: {
      const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
      if (!tab || !tab.id) return { ok: false, error: 'no active tab' };
      await openOverlay(tab.id, message.mode || 'menu');
      return { ok: true };
    }
    case MSG.OPEN_APP: {
      const state = await getState();
      const base = state.baseUrl.replace(/\/+$/, '');
      const hash = message.hash === undefined ? '#anywhere' : String(message.hash);
      const url = base + '/' + hash;
      // Reuse an existing VEDA tab if there is one, rather than piling up tabs.
      let existing = [];
      try { existing = await chrome.tabs.query({ url: base + '/*' }); } catch (_) {}
      if (existing.length && existing[0].id != null) {
        await chrome.tabs.update(existing[0].id, { url, active: true });
        if (existing[0].windowId != null) {
          try { await chrome.windows.update(existing[0].windowId, { focused: true }); } catch (_) {}
        }
      } else {
        await chrome.tabs.create({ url });
      }
      return { ok: true };
    }
    default:
      return { ok: false, error: 'unknown message: ' + (message && message.type) };
  }
}

// Never expose the raw token outside the worker.
function redactState(state) {
  const { token, ...rest } = state;
  return { ...rest, connected: Boolean(token), extensionVersion: EXTENSION_VERSION };
}
