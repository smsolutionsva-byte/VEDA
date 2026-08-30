import { MSG, EXTENSION_VERSION } from '../lib/constants.js';
import { clearAuth } from '../lib/store.js';

const main = document.getElementById('pw-main');
const statePill = document.getElementById('pw-state');
document.getElementById('pw-version').textContent = 'v' + EXTENSION_VERSION;
document.getElementById('pw-settings').addEventListener('click', () => {
  openApp('#anywhere');
});

let STATE = null;
let busy = false;

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

function openApp(hash) {
  send({ type: MSG.OPEN_APP, hash: hash === undefined ? '#anywhere' : hash });
  window.close();
}

function elem(tag, props, ...children) {
  const n = document.createElement(tag);
  Object.assign(n, props || {});
  for (const c of children) {
    if (c == null) continue;
    n.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
  }
  return n;
}

function setPill(text, cls) {
  statePill.textContent = text;
  statePill.className = 'pw-pill' + (cls ? ' ' + cls : '');
}

function clearMain() { main.textContent = ''; }

async function load() {
  const got = await send({ type: MSG.SESSION_GET });
  if (!got || !got.ok) { renderUnreachable(); return; }
  STATE = got.state;
  render();
  const fresh = await send({ type: MSG.SESSION_REFRESH });
  if (fresh && fresh.ok && fresh.state) { STATE = fresh.state; render(); }
  else if (fresh && fresh.reason === 'revoked') { STATE = { ...STATE, connected: false }; render(); }
}

function render() {
  clearMain();
  if (!STATE) return renderUnreachable();
  if (!STATE.connected) return renderNotConnected();
  if (!STATE.enabled) return renderDisabled();
  const projects = STATE.projects || [];
  if (!projects.length) return renderNoProject();
  return renderReady();
}

function renderUnreachable() {
  setPill('offline', 'bad');
  clearMain();
  const retry = elem('button', { className: 'pw-btn' }, 'Retry');
  retry.addEventListener('click', load);
  main.append(
    note('bad', strong('VEDA is not reachable.'), ' Start the VEDA desktop app, then Retry.'),
    retry,
  );
}

function renderNotConnected() {
  setPill('not connected', 'warn');
  clearMain();

  const codeInput = elem('input', {
    type: 'text', id: 'pw-code', placeholder: 'VEDA-XXXX-XXXX',
    autocomplete: 'off', spellcheck: false, maxLength: 20,
  });
  codeInput.addEventListener('input', () => {
    const p = codeInput.selectionStart;
    codeInput.value = codeInput.value.toUpperCase();
    try { codeInput.setSelectionRange(p, p); } catch (_) {}
  });

  const pairBtn = elem('button', { className: 'pw-btn primary' }, 'Pair with code');
  const status = elem('div');

  pairBtn.addEventListener('click', async () => {
    const code = (codeInput.value || '').trim();
    if (code.replace(/[\s-]/g, '').length < 8) { codeInput.focus(); return; }
    pairBtn.disabled = true;
    pairBtn.textContent = 'Pairing…';
    status.replaceChildren();
    const res = await send({ type: MSG.PAIR, code });
    if (res && res.ok) {
      setPill('connecting', 'warn');
      status.replaceChildren(note('ok', strong('Paired.'), ' Loading your workspace…'));
      setTimeout(load, 500);
    } else {
      pairBtn.disabled = false;
      pairBtn.textContent = 'Pair with code';
      status.replaceChildren(note('bad', (res && res.error) || 'Pairing failed.'));
    }
  });
  codeInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') pairBtn.click(); });

  const openBtn = elem('button', { className: 'pw-btn ghost' }, 'Open VEDA Anywhere settings');
  openBtn.addEventListener('click', () => openApp('#anywhere'));

  main.append(
    elem('ol', { className: 'pw-steps' },
      elem('li', {}, 'In the VEDA app, open ', elem('b', {}, 'VEDA Anywhere'), ' → ',
        elem('b', {}, 'Enable'), ' → ', elem('b', {}, 'Connect extension')),
      elem('li', {}, 'Copy the pairing code it shows'),
      elem('li', {}, 'Paste it below and choose ', elem('b', {}, 'Pair with code'))),
    elem('label', { className: 'pw-field' }, elem('span', {}, 'Pairing code'), codeInput),
    pairBtn,
    status,
    openBtn,
  );
  codeInput.focus();
}

function renderDisabled() {
  setPill('disabled', 'warn');
  clearMain();
  const openBtn = elem('button', { className: 'pw-btn primary' }, 'Open VEDA Anywhere settings');
  openBtn.addEventListener('click', () => openApp('#anywhere'));
  main.append(
    note('warn', strong('VEDA Anywhere is disabled.'),
      ' No page interaction happens while it is off. Enable it in the VEDA app to use Ask and Capture.'),
    accountBlock(),
    openBtn,
    disconnectButton(),
  );
}

function renderNoProject() {
  setPill('no project', 'warn');
  clearMain();
  const createBtn = elem('button', { className: 'pw-btn primary' },
    elem('span', { className: 'i' }, '＋'), 'Create a project in VEDA');
  createBtn.addEventListener('click', () => openApp('#new-project'));
  const openBtn = elem('button', { className: 'pw-btn ghost' }, 'Open VEDA');
  openBtn.addEventListener('click', () => openApp(''));
  main.append(
    note('warn', strong('No project yet.'),
      ' Ask VEDA and Capture in VEDA need a project. Create one, then reopen this popup.'),
    createBtn,
    openBtn,
    accountBlock(),
    disconnectButton(),
  );
}

function renderReady() {
  setPill('active', 'ok');
  clearMain();

  const projects = STATE.projects || [];
  const activeId = STATE.activeProjectId || STATE.defaultProjectId || projects[0].id;

  const select = elem('select', { id: 'pw-project' });
  for (const p of projects) {
    const opt = elem('option', { value: p.id }, p.name);
    if (p.id === activeId) opt.selected = true;
    select.appendChild(opt);
  }
  select.addEventListener('change', async () => {
    STATE.activeProjectId = select.value;
    await send({ type: MSG.SET_ACTIVE_PROJECT, projectId: select.value });
  });

  const askBtn = elem('button', { className: 'pw-btn' },
    elem('span', { className: 'i' }, '✦'), 'Ask VEDA about selection');
  const capBtn = elem('button', { className: 'pw-btn amber' },
    elem('span', { className: 'i' }, '＋'), 'Capture selection in VEDA');
  askBtn.addEventListener('click', () => invoke('ask'));
  capBtn.addEventListener('click', () => invoke('capture'));

  const selHint = elem('div', { className: 'pw-note' },
    'Select text on the current page first. VEDA only ever receives the exact text you send.');

  const newProj = elem('button', { className: 'pw-btn ghost sm' }, '+ New project in VEDA');
  newProj.addEventListener('click', () => openApp('#new-project'));

  main.append(
    elem('label', { className: 'pw-field' },
      elem('span', {}, 'Active project'), select),
    elem('div', { className: 'pw-actions' }, askBtn, capBtn),
    selHint,
    newProj,
    accountBlock(),
    disconnectButton(),
  );
}

async function invoke(mode) {
  const gotSel = await send({ type: MSG.GET_SELECTION });
  const text = gotSel && gotSel.ok && gotSel.selection ? (gotSel.selection.text || '').trim() : '';
  if (!text) {
    const n = main.querySelector('.pw-note');
    if (n) n.replaceWith(note('warn', strong('No text selected.'),
      ' Highlight a sentence on the page, then click again.'));
    return;
  }
  await send({ type: MSG.OPEN_OVERLAY, mode });
  window.close();
}

function accountBlock() {
  const acct = STATE.account || {};
  const dl = elem('dl', { className: 'pw-kv' });
  dl.append(
    elem('dt', {}, 'Workspace'), elem('dd', {}, acct.workspace || 'VEDA'),
    elem('dt', {}, 'Host'), elem('dd', {}, acct.host || (STATE.baseUrl || '').replace(/^https?:\/\//, '')),
  );
  if (STATE.serverVersion) dl.append(elem('dt', {}, 'VEDA'), elem('dd', {}, STATE.serverVersion));
  return elem('div', { className: 'pw-block' }, elem('h2', {}, 'Connected to'), dl);
}

function disconnectButton() {
  const b = elem('button', { className: 'pw-btn ghost' }, 'Disconnect this browser');
  b.addEventListener('click', async () => {
    if (busy) return;
    busy = true;
    b.disabled = true;
    b.textContent = 'Disconnecting…';
    // Ask the background to revoke the token server-side and clear local auth.
    // Give it a bounded window; if the worker doesn't answer, clear locally so
    // the extension is disconnected no matter what.
    const res = await Promise.race([
      send({ type: MSG.DISCONNECT }),
      new Promise((r) => setTimeout(() => r({ ok: false, timeout: true }), 2500)),
    ]);
    if (!res || !res.ok) {
      try { await clearAuth(); } catch (_) {}
    }
    STATE = { connected: false, baseUrl: (STATE && STATE.baseUrl) || null };
    busy = false;
    render();
    load();
  });
  return b;
}

function note(kind, ...children) {
  return elem('div', { className: 'pw-note' + (kind ? ' ' + kind : '') }, ...children);
}
function strong(text) { return elem('b', {}, text); }

chrome.runtime.onMessage.addListener((message) => {
  if (message && message.type === MSG.STATE_CHANGED && !busy) load();
});

load();
