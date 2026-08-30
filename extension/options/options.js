import { MSG, EXTENSION_VERSION, DEFAULT_BASE_URL } from '../lib/constants.js';
import { getState, setState, clearAuth } from '../lib/store.js';

const statePill = document.getElementById('ow-state');
const baseInput = document.getElementById('ow-base');
const baseStatus = document.getElementById('ow-base-status');
const conn = document.getElementById('ow-conn');
document.getElementById('ow-version').textContent = 'VEDA Anywhere v' + EXTENSION_VERSION;

document.getElementById('ow-open-settings').addEventListener('click', () => {
  send({ type: MSG.OPEN_APP, hash: '#anywhere' });
});

function send(message) {
  return new Promise((resolve) => {
    try {
      chrome.runtime.sendMessage(message, (res) => {
        resolve(chrome.runtime.lastError ? { ok: false, error: chrome.runtime.lastError.message } : (res || {}));
      });
    } catch (err) {
      resolve({ ok: false, error: String(err) });
    }
  });
}

function normaliseUrl(value) {
  let v = String(value || '').trim();
  if (!v) return '';
  if (!/^https?:\/\//i.test(v)) v = 'http://' + v;
  try {
    const u = new URL(v);
    return u.origin;
  } catch (_) {
    return '';
  }
}

function setNote(target, kind, text) {
  target.textContent = '';
  const n = document.createElement('div');
  n.className = 'ow-note' + (kind ? ' ' + kind : '');
  n.textContent = text;
  target.appendChild(n);
}

async function refresh() {
  const state = await getState();
  baseInput.value = state.baseUrl || DEFAULT_BASE_URL;

  const got = await send({ type: MSG.SESSION_GET });
  const s = got && got.ok ? got.state : null;

  conn.textContent = '';
  if (!s) {
    statePill.textContent = 'unknown';
    statePill.className = 'ow-pill';
    return;
  }
  if (!s.connected) {
    statePill.textContent = 'not connected';
    statePill.className = 'ow-pill warn';
    setNote(conn, 'warn', 'No browser paired. Open VEDA Anywhere settings in the VEDA app and choose “Connect extension”.');
    return;
  }
  statePill.textContent = s.enabled ? 'active' : 'connected · disabled';
  statePill.className = 'ow-pill ' + (s.enabled ? 'ok' : 'warn');

  const dl = document.createElement('dl');
  dl.className = 'ow-kv';
  const add = (k, v) => {
    const dt = document.createElement('dt'); dt.textContent = k;
    const dd = document.createElement('dd'); dd.textContent = v;
    dl.append(dt, dd);
  };
  add('Workspace', (s.account && s.account.workspace) || 'VEDA');
  add('Host', (s.account && s.account.host) || (s.baseUrl || '').replace(/^https?:\/\//, ''));
  add('Projects', String((s.projects || []).length));
  if (s.serverVersion) add('VEDA version', s.serverVersion);
  conn.appendChild(dl);

  const disconnect = document.createElement('button');
  disconnect.className = 'ow-btn danger';
  disconnect.textContent = 'Disconnect this browser';
  disconnect.style.marginTop = '12px';
  disconnect.addEventListener('click', async () => {
    disconnect.disabled = true;
    disconnect.textContent = 'Disconnecting…';
    const res = await Promise.race([
      send({ type: MSG.DISCONNECT }),
      new Promise((r) => setTimeout(() => r({ ok: false, timeout: true }), 2500)),
    ]);
    if (!res || !res.ok) {
      try { await clearAuth(); } catch (_) {}
    }
    refresh();
  });
  conn.appendChild(disconnect);
}

document.getElementById('ow-save-base').addEventListener('click', async () => {
  const origin = normaliseUrl(baseInput.value);
  if (!origin) { setNote(baseStatus, 'bad', 'Enter a valid URL, e.g. http://127.0.0.1:8770'); return; }
  const pattern = origin + '/*';
  let granted = true;
  try {
    granted = await chrome.permissions.request({ origins: [pattern] });
  } catch (err) {
    setNote(baseStatus, 'bad', 'Could not request access: ' + err.message);
    return;
  }
  if (!granted) { setNote(baseStatus, 'warn', 'Access to ' + origin + ' was not granted.'); return; }
  await setState({ baseUrl: origin });
  setNote(baseStatus, 'ok', 'Saved. VEDA backend is now ' + origin + '.');
  refresh();
});

document.getElementById('ow-reset-base').addEventListener('click', async () => {
  await setState({ baseUrl: DEFAULT_BASE_URL });
  baseInput.value = DEFAULT_BASE_URL;
  setNote(baseStatus, 'ok', 'Reset to ' + DEFAULT_BASE_URL + '.');
  refresh();
});

chrome.runtime.onMessage.addListener((message) => {
  if (message && message.type === MSG.STATE_CHANGED) refresh();
});

refresh();
