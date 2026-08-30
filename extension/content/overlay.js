/* VEDA Anywhere - on-page selection UI.

   Injected only when the operator explicitly invokes VEDA (toolbar popup,
   right-click menu, or keyboard command). It reads the CURRENT text selection
   once, shows a small floating panel, and does nothing else. It never observes
   the page, never re-reads the selection on its own, and never sends anything
   to VEDA until the operator picks an action.

   The panel is draggable (grab the header) and stays fully inside the viewport,
   with the action bar always visible. An Ask VEDA question keeps working even
   if you close the panel - the answer is always in Ask VEDA in the VEDA app,
   and reopening the panel resumes the conversation.
*/
(() => {
  'use strict';

  if (window.__vedaAnywhereOverlay) {
    window.__vedaAnywhereOverlay.reopen();
    return;
  }

  const MSG = {
    SESSION_GET: 'veda:session:get',
    SESSION_REFRESH: 'veda:session:refresh',
    SET_ACTIVE_PROJECT: 'veda:project:set',
    ASK: 'veda:ask',
    ASK_POLL: 'veda:ask:poll',
    DETECT: 'veda:detect',
    CAPTURE: 'veda:capture',
    OPEN_APP: 'veda:app:open',
    OPEN_OVERLAY: 'veda:overlay:open',
    STATE_CHANGED: 'veda:state:changed',
  };

  const APP_NAMES = {
    'teams.microsoft.com': 'Microsoft Teams',
    'slack.com': 'Slack', 'app.slack.com': 'Slack',
    'web.whatsapp.com': 'WhatsApp Web',
    'mail.google.com': 'Gmail',
    'outlook.office.com': 'Outlook', 'outlook.office365.com': 'Outlook',
    'discord.com': 'Discord',
  };

  const ASK_POLL_MS = 2000;
  const ASK_MAX_MS = 5 * 60 * 1000;      // keep polling this long while open
  const ASK_RESUME_MS = 30 * 60 * 1000;  // resume a persisted conversation this recent
  const PANEL_KEY = 'va_panel';
  const ASK_KEY = 'va_ask';

  function send(message) {
    return new Promise((resolve) => {
      try {
        chrome.runtime.sendMessage(message, (res) => {
          resolve(chrome.runtime.lastError
            ? { ok: false, error: chrome.runtime.lastError.message }
            : (res || { ok: false, error: 'no response' }));
        });
      } catch (err) {
        resolve({ ok: false, error: String(err) });
      }
    });
  }

  const storeGet = (key) => new Promise((resolve) => {
    try { chrome.storage.local.get(key, (r) => resolve((r || {})[key])); }
    catch (_) { resolve(undefined); }
  });
  const storeSet = (key, value) => new Promise((resolve) => {
    try { chrome.storage.local.set({ [key]: value }, () => resolve()); }
    catch (_) { resolve(); }
  });
  const storeDel = (key) => new Promise((resolve) => {
    try { chrome.storage.local.remove(key, () => resolve()); }
    catch (_) { resolve(); }
  });

  const esc = (s) => String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');

  const fmtClock = (ms) => {
    const s = Math.max(0, Math.round(ms / 1000));
    return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0');
  };

  // Stable, non-reversible key so re-capturing the identical selection in the
  // same project de-duplicates instead of creating a second evidence record.
  function stableKey(parts) {
    const str = parts.join('|');
    let h = 5381;
    for (let i = 0; i < str.length; i += 1) h = ((h << 5) + h + str.charCodeAt(i)) >>> 0;
    let h2 = 52711;
    for (let i = str.length - 1; i >= 0; i -= 1) h2 = ((h2 << 5) + h2 + str.charCodeAt(i)) >>> 0;
    return 'awc_' + h.toString(36) + h2.toString(36);
  }

  // ----------------------------------------------------------------- state
  const V = {
    mode: 'menu',
    selection: '',
    rect: null,
    session: null,
    projectId: null,
    host: location.host,
    url: location.href,
    title: document.title,
    sourceApp: APP_NAMES[location.host] || location.host,
    thread: [],
    detection: null,
    injection: null,
    busy: false,
    ask: null,          // { jobId, startedAt } while a question is in flight
    pos: null,          // { left, top } persisted panel position
    width: 380,
  };

  // ----------------------------------------------------------------- shadow UI
  const hostEl = document.createElement('div');
  hostEl.id = 'veda-anywhere-root';
  const shadow = hostEl.attachShadow({ mode: 'open' });
  shadow.innerHTML = '<style>' + STYLES() + '</style><div class="va-anchor"></div>';
  (document.documentElement || document.body).appendChild(hostEl);
  const anchor = shadow.querySelector('.va-anchor');

  function STYLES() {
    return [
      ':host { all: initial; }',
      '* { box-sizing: border-box; }',
      '.va-anchor { position: fixed; inset: 0; z-index: 2147483647; pointer-events: none;',
      "  font-family: -apple-system, 'Segoe UI', Roboto, system-ui, sans-serif;",
      '  font-size: 13px; line-height: 1.45; color: #E9ECF2; }',
      '.va-anchor > * { pointer-events: auto; }',
      ".va-mono { font-family: ui-monospace, 'Cascadia Mono', Consolas, monospace; font-variant-numeric: tabular-nums; }",

      /* floating selection pill */
      '.va-pop { position: fixed; width: max-content; max-width: 360px;',
      '  background: linear-gradient(180deg, #161B22, #0F1319);',
      '  border: 1px solid #3D4757; border-top: 2px solid #45C8E8;',
      '  box-shadow: 0 0 0 1px rgba(0,0,0,.35), 0 18px 50px -12px rgba(0,0,0,.7), 0 2px 8px rgba(0,0,0,.4);',
      '  animation: va-in .13s cubic-bezier(.2,.7,.3,1); }',
      '@keyframes va-in { from { opacity: 0; transform: translateY(5px) scale(.98); } }',
      '.va-pill { display: flex; align-items: stretch; }',
      '.va-pill .va-mark { display: flex; align-items: center; padding: 0 10px 0 12px;',
      "  font: 700 11px/1 -apple-system, 'Segoe UI', sans-serif; letter-spacing: .18em;",
      '  color: #E9ECF2; border-right: 1px solid #232935; background: rgba(69,200,232,.05); }',
      '.va-pill button { appearance: none; border: 0; background: transparent; color: #E9ECF2;',
      '  font: inherit; font-size: 12.5px; padding: 10px 14px; cursor: pointer; display: flex;',
      '  align-items: center; gap: 7px; white-space: nowrap; transition: background .1s; }',
      '.va-pill button:hover { background: rgba(69,200,232,.14); }',
      '.va-pill button + button { border-left: 1px solid #232935; }',
      '.va-pill .va-i { color: #45C8E8; font-style: normal; font-size: 13px; }',
      '.va-pill .va-cap .va-i { color: #FFB020; }',
      '.va-pill .va-cap:hover { background: rgba(255,176,32,.14); }',

      /* draggable panel: header + scrolling body + always-visible footer */
      '.va-panel { position: fixed; display: flex; flex-direction: column;',
      '  width: var(--va-w, 380px); max-width: calc(100vw - 16px); max-height: calc(100vh - 16px);',
      '  background: linear-gradient(180deg, #161B22, #0F1319);',
      '  border: 1px solid #3D4757; border-top: 2px solid #45C8E8;',
      '  box-shadow: 0 0 0 1px rgba(0,0,0,.4), 0 24px 60px -12px rgba(0,0,0,.75);',
      '  animation: va-in .13s cubic-bezier(.2,.7,.3,1); }',
      '.va-head { flex: none; display: flex; align-items: center; gap: 8px; padding: 9px 8px 9px 12px;',
      '  border-bottom: 1px solid #232935; background: linear-gradient(180deg, #1A1F28, #14181F);',
      '  cursor: grab; user-select: none; touch-action: none; }',
      '.va-head:active { cursor: grabbing; }',
      '.va-head .va-brand { font-weight: 700; letter-spacing: .22em; font-size: 12px; }',
      "  .va-head .va-tag { font: 500 9px/1 ui-monospace, Consolas, monospace; text-transform: uppercase;",
      '  letter-spacing: .1em; color: #45C8E8; border: 1px solid rgba(69,200,232,.4); padding: 3px 6px; }',
      '.va-head .va-cap-tag { color: #FFB020; border-color: rgba(255,176,32,.4); }',
      '.va-head .va-neutral-tag { color: #97A1B2; border-color: #3D4757; }',
      '.va-head .va-spacer { flex: 1; }',
      '.va-head .va-grip { color: #4A5464; font-size: 12px; letter-spacing: -2px; margin-right: 2px; }',
      '.va-x { border: 0; background: transparent; color: #97A1B2; cursor: pointer; font-size: 17px;',
      '  line-height: 1; padding: 3px 6px; }',
      '.va-x:hover { color: #E9ECF2; }',

      '.va-body { flex: 1 1 auto; min-height: 0; padding: 12px; overflow-y: auto; overflow-x: hidden; }',
      '.va-body::-webkit-scrollbar { width: 9px; }',
      '.va-body::-webkit-scrollbar-thumb { background: #2F3745; border: 2px solid #0F1319; }',

      '.va-actions { flex: none; display: flex; gap: 8px; align-items: center; flex-wrap: wrap;',
      '  padding: 10px 11px; border-top: 1px solid #232935; background: #0F1319; }',
      '.va-actions .va-spacer { flex: 1; }',

      '.va-resize { position: absolute; right: 0; bottom: 0; width: 16px; height: 16px;',
      '  cursor: nwse-resize; background:', "  linear-gradient(135deg, transparent 45%, #3D4757 45%, #3D4757 55%, transparent 55%, transparent 70%, #3D4757 70%, #3D4757 80%, transparent 80%); }",

      /* shared bits */
      '.va-selq { border-left: 2px solid #45C8E8; padding: 6px 9px; margin: 0 0 10px;',
      '  background: #0E1218; color: #B9C2D0; font-size: 12px; max-height: 96px; overflow-y: auto; white-space: pre-wrap; }',
      '.va-selq.va-cap { border-left-color: #FFB020; }',
      '.va-row { display: flex; align-items: center; gap: 8px; margin-bottom: 9px; }',
      '.va-row label { font: 500 9.5px/1 ui-monospace, Consolas, monospace; text-transform: uppercase;',
      '  letter-spacing: .13em; color: #616B7C; flex: none; }',
      'select, input[type=text], textarea { appearance: none; width: 100%; background: #0C1015; color: #E9ECF2;',
      '  border: 1px solid #2F3745; padding: 7px 8px; font: inherit; font-size: 12.5px; }',
      'select { cursor: pointer; }',
      'textarea { resize: none; min-height: 40px; max-height: 130px; font-family: inherit; line-height: 1.5; }',
      ':focus-visible { outline: 2px solid #45C8E8; outline-offset: 1px; }',

      '.va-btn { appearance: none; border: 1px solid #3D4757; cursor: pointer;',
      '  background: linear-gradient(180deg, #222834, #151920); color: #E9ECF2; font: inherit;',
      '  font-size: 12.5px; padding: 7px 13px; }',
      '.va-btn:hover { border-color: #4C596B; }',
      '.va-btn:active { transform: translateY(1px); }',
      '.va-btn:disabled { opacity: .45; cursor: not-allowed; }',
      '.va-btn.va-primary { background: linear-gradient(180deg, #2E6E80, #1E4E5C); border-color: #3E8DA3; color: #EAFBFF; }',
      '.va-btn.va-amber { background: linear-gradient(180deg, #7A5410, #573A08); border-color: #A8760F; color: #FFF3DC; }',
      '.va-btn.va-sm { padding: 5px 10px; font-size: 11.5px; }',

      '.va-detect { }',
      '.va-detect dl { margin: 0; }',
      '.va-detect dt { font: 500 9px/1 ui-monospace, Consolas, monospace; text-transform: uppercase;',
      '  letter-spacing: .12em; color: #616B7C; margin-bottom: 2px; }',
      '.va-detect dd { margin: 0 0 8px; font-size: 12px; }',
      '.va-detect dd:last-child { margin-bottom: 0; }',
      '.va-conf { display: inline-flex; align-items: center; gap: 6px; }',
      '.va-conf b { font-family: ui-monospace, Consolas, monospace; }',
      '.va-meter { width: 84px; height: 5px; background: #0C1015; position: relative; border: 1px solid #232935; }',
      '.va-meter > i { position: absolute; inset: 0 auto 0 0; background: #45C8E8; }',
      '.va-check { display: flex; align-items: flex-start; gap: 7px; margin: 5px 0; font-size: 12px; color: #B9C2D0; cursor: pointer; }',
      '.va-check input { margin-top: 2px; accent-color: #45C8E8; }',

      /* chat */
      '.va-chat { display: flex; flex-direction: column; gap: 14px; }',
      '.va-msg { font-size: 12.5px; }',
      '.va-msg .va-who { font: 500 8.5px/1 ui-monospace, Consolas, monospace; text-transform: uppercase;',
      '  letter-spacing: .12em; color: #616B7C; margin-bottom: 4px; }',
      '.va-msg.va-you .va-bubble { border-left: 2px solid #45C8E8; padding-left: 9px; color: #C7CEDA; white-space: pre-wrap; }',
      '.va-answer { white-space: pre-wrap; color: #E9ECF2; border: 1px solid #232935; border-left: 2px solid rgba(69,200,232,.5);',
      '  background: #0E1218; padding: 10px 11px; line-height: 1.6; }',
      '.va-working { display: flex; align-items: center; gap: 8px; border: 1px solid #232935; background: #0E1218; padding: 9px 11px; color: #B9C2D0; }',
      '.va-working b { color: #E9ECF2; }',
      '.va-working .va-clock { margin-left: auto; font-family: ui-monospace, Consolas, monospace; color: #616B7C; }',

      '.va-note { border-left: 2px solid #3D4757; padding: 7px 9px; background: #0E1218; color: #97A1B2; font-size: 11.5px; }',
      '.va-note.va-warn { border-left-color: #FFB020; color: #E4D9A8; }',
      '.va-note.va-bad { border-left-color: #FF5F56; color: #FFC9C6; }',
      '.va-note.va-ok { border-left-color: #43D07F; }',
      '.va-note b { color: #E9ECF2; }',

      '.va-spin { display: inline-block; width: 11px; height: 11px; border: 2px solid #45C8E8;',
      '  border-right-color: transparent; animation: va-spin .7s linear infinite; vertical-align: -1px; }',
      '@keyframes va-spin { to { transform: rotate(360deg); } }',

      '.va-kv { display: grid; grid-template-columns: 92px 1fr; gap: 4px 10px; font-size: 12px; margin: 8px 0; }',
      '.va-kv dt { color: #616B7C; font-family: ui-monospace, Consolas, monospace; font-size: 10.5px; }',
      '.va-kv dd { margin: 0; }',
      '.va-linklike { color: #45C8E8; cursor: pointer; background: none; border: 0; font: inherit; font-size: 12px;',
      '  padding: 0; text-decoration: underline; text-align: left; }',
      '.va-muted { color: #616B7C; font-size: 11px; }',
      '.va-compose { display: flex; gap: 7px; align-items: flex-end; margin-top: 10px; }',
      '.va-compose .va-btn { flex: none; }',
    ].join('\n');
  }

  // ----------------------------------------------------------------- selection
  function readSelection() {
    const sel = window.getSelection();
    const text = sel ? String(sel.toString()).replace(/ /g, ' ').trim() : '';
    let rect = null;
    if (sel && sel.rangeCount) {
      const r = sel.getRangeAt(0).getBoundingClientRect();
      if (r && (r.width || r.height)) rect = r;
    }
    return { text, rect };
  }

  function el(tag, cls, html) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (html != null) n.innerHTML = html;
    return n;
  }

  // ----------------------------------------------------------------- placement
  const PAD = 8;

  // Keep the whole pop inside the viewport. For the panel, also cap its height
  // to the space actually available below its top edge (moving it up first if
  // that would still not be enough), so the footer buttons are never clipped.
  function clampInto(node) {
    const vw = document.documentElement.clientWidth;
    const vh = document.documentElement.clientHeight;
    const panel = node.querySelector && node.querySelector('.va-panel');
    if (panel) panel.style.maxHeight = 'none';
    const r = node.getBoundingClientRect();
    const w = r.width || parseFloat(node.style.width) || 360;
    let left = parseFloat(node.style.left);
    let top = parseFloat(node.style.top);
    if (!Number.isFinite(left)) left = r.left;
    if (!Number.isFinite(top)) top = r.top;

    left = Math.min(Math.max(PAD, left), Math.max(PAD, vw - w - PAD));

    if (panel) {
      const wanted = panel.scrollHeight + 2; // border
      const maxH = vh - 2 * PAD;
      const h = Math.min(wanted, maxH);
      top = Math.min(Math.max(PAD, top), Math.max(PAD, vh - h - PAD));
      panel.style.maxHeight = (vh - top - PAD) + 'px';
    } else {
      top = Math.min(Math.max(PAD, top), Math.max(PAD, vh - r.height - PAD));
    }
    node.style.left = Math.round(left) + 'px';
    node.style.top = Math.round(top) + 'px';
  }

  function placePill(node) {
    anchor.innerHTML = '';
    anchor.appendChild(node);
    const vw = document.documentElement.clientWidth;
    const nb = node.getBoundingClientRect();
    if (V.rect) {
      node.style.left = Math.round(Math.min(Math.max(PAD, V.rect.left), vw - nb.width - PAD)) + 'px';
      node.style.top = Math.round(Math.max(PAD, V.rect.bottom + 8)) + 'px';
    } else {
      node.style.left = Math.round(vw - nb.width - PAD) + 'px';
      node.style.top = PAD + 'px';
    }
    clampInto(node);
  }

  function placePanel(node) {
    anchor.innerHTML = '';
    anchor.appendChild(node);
    node.style.setProperty('--va-w', (V.width || 380) + 'px');
    if (V.pos && Number.isFinite(V.pos.left) && Number.isFinite(V.pos.top)) {
      node.style.left = V.pos.left + 'px';
      node.style.top = V.pos.top + 'px';
    } else {
      const vw = document.documentElement.clientWidth;
      const nb = node.getBoundingClientRect();
      let left = vw - nb.width - 16;
      let top = 64;
      if (V.rect) {
        left = Math.min(Math.max(PAD, V.rect.left), vw - nb.width - PAD);
        top = V.rect.bottom + 10;
      }
      node.style.left = Math.round(left) + 'px';
      node.style.top = Math.round(top) + 'px';
    }
    clampInto(node);
  }

  function persistPanel() {
    const pop = shadow.querySelector('.va-pop.va-is-panel');
    if (!pop) return;
    V.pos = { left: Math.round(parseFloat(pop.style.left) || 0),
              top: Math.round(parseFloat(pop.style.top) || 0) };
    storeSet(PANEL_KEY, { left: V.pos.left, top: V.pos.top, width: V.width });
  }

  function makeDraggable(pop, handle) {
    let sx = 0, sy = 0, ox = 0, oy = 0, dragging = false;
    const down = (e) => {
      if (e.button !== 0 && e.pointerType === 'mouse') return;
      if (e.target.closest('.va-x')) return;
      dragging = true;
      sx = e.clientX; sy = e.clientY;
      ox = parseFloat(pop.style.left) || pop.getBoundingClientRect().left;
      oy = parseFloat(pop.style.top) || pop.getBoundingClientRect().top;
      handle.setPointerCapture && handle.setPointerCapture(e.pointerId);
      e.preventDefault();
    };
    const move = (e) => {
      if (!dragging) return;
      pop.style.left = (ox + e.clientX - sx) + 'px';
      pop.style.top = (oy + e.clientY - sy) + 'px';
      clampInto(pop);
    };
    const up = () => {
      if (!dragging) return;
      dragging = false;
      persistPanel();
    };
    handle.addEventListener('pointerdown', down);
    handle.addEventListener('pointermove', move);
    handle.addEventListener('pointerup', up);
    handle.addEventListener('pointercancel', up);
  }

  function makeResizable(pop, grip) {
    let sx = 0, sy = 0, ow = 0, dragging = false;
    const down = (e) => {
      dragging = true; sx = e.clientX; sy = e.clientY;
      ow = pop.getBoundingClientRect().width;
      grip.setPointerCapture && grip.setPointerCapture(e.pointerId);
      e.preventDefault(); e.stopPropagation();
    };
    const move = (e) => {
      if (!dragging) return;
      const w = Math.max(320, Math.min(560,
        document.documentElement.clientWidth - 16, ow + (e.clientX - sx)));
      V.width = Math.round(w);
      pop.style.setProperty('--va-w', V.width + 'px');
      clampInto(pop);
    };
    const up = () => { if (!dragging) return; dragging = false; persistPanel(); };
    grip.addEventListener('pointerdown', down);
    grip.addEventListener('pointermove', move);
    grip.addEventListener('pointerup', up);
    grip.addEventListener('pointercancel', up);
  }

  const onResizeWindow = () => {
    const pop = shadow.querySelector('.va-pop');
    if (pop) clampInto(pop);
  };

  // ----------------------------------------------------------------- lifecycle
  function close() {
    cleanup();
    hostEl.remove();
    window.__vedaAnywhereOverlay = null;
  }
  function cleanup() {
    stopPolling();
    if (V._ro) { try { V._ro.disconnect(); } catch (_) {} V._ro = null; }
    document.removeEventListener('keydown', onKey, true);
    window.removeEventListener('resize', onResizeWindow);
  }
  function onKey(e) {
    if (e.key === 'Escape') { e.stopPropagation(); close(); }
  }

  function frame(mode, bodyNode, actionsNode) {
    const pop = el('div', 'va-pop va-is-panel');
    const panel = el('div', 'va-panel');
    const isCap = mode === 'capture';
    const tag = mode === 'ask' ? '<span class="va-tag">Ask</span>'
      : isCap ? '<span class="va-tag va-cap-tag">Capture</span>'
      : '<span class="va-tag va-neutral-tag">Anywhere</span>';
    const head = el('div', 'va-head',
      '<span class="va-grip" aria-hidden="true">⠿</span>' +
      '<span class="va-brand">VEDA</span>' + tag + '<span class="va-spacer"></span>');
    const x = el('button', 'va-x', '&times;');
    x.setAttribute('aria-label', 'Close');
    x.addEventListener('click', close);
    head.appendChild(x);
    panel.appendChild(head);

    const body = el('div', 'va-body');
    body.appendChild(bodyNode);
    panel.appendChild(body);
    if (actionsNode) panel.appendChild(actionsNode);

    const resize = el('div', 'va-resize');
    resize.setAttribute('aria-hidden', 'true');
    panel.appendChild(resize);

    pop.appendChild(panel);
    placePanel(pop);
    makeDraggable(pop, head);
    makeResizable(pop, resize);

    // Re-clamp when async content (detection, an answer) changes the height, so
    // the panel and its footer stay inside the viewport.
    if (V._ro) { try { V._ro.disconnect(); } catch (_) {} }
    if (window.ResizeObserver) {
      let raf = 0;
      V._ro = new ResizeObserver(() => {
        cancelAnimationFrame(raf);
        raf = requestAnimationFrame(() => { if (pop.isConnected) clampInto(pop); });
      });
      V._ro.observe(bodyNode);
      V._ro.observe(panel);
    }
    return { pop, body };
  }

  // ----------------------------------------------------------------- views
  function showPill() {
    const pop = el('div', 'va-pop');
    const pill = el('div', 'va-pill');
    pill.appendChild(el('span', 'va-mark', 'VEDA'));
    const ask = el('button', 'va-ask', '<span class="va-i">✦</span> Ask VEDA');
    const cap = el('button', 'va-cap', '<span class="va-i">＋</span> Capture in VEDA');
    ask.addEventListener('click', () => showAsk());
    cap.addEventListener('click', () => showCapture());
    pill.appendChild(ask);
    pill.appendChild(cap);
    pop.appendChild(pill);
    placePill(pop);
  }

  function gate(kind) {
    const body = el('div');
    let msg = '';
    const ctas = [];
    const openApp = (hash) => () => send({ type: MSG.OPEN_APP, hash });
    if (kind === 'unreachable') {
      msg = '<div class="va-note va-bad"><b>VEDA is not reachable.</b><br>Start the VEDA app, then try again.</div>';
    } else if (kind === 'not_connected') {
      msg = '<div class="va-note va-warn"><b>Connect to VEDA</b><br>Open VEDA Anywhere settings, enable it, choose Connect extension, then enter the code in the toolbar popup.</div>';
      ctas.push(['Open VEDA settings', openApp('#anywhere'), true]);
    } else if (kind === 'disabled') {
      msg = '<div class="va-note va-warn"><b>VEDA Anywhere is disabled.</b><br>No page interaction occurs while it is off. Enable it in the VEDA app.</div>';
      ctas.push(['Open VEDA settings', openApp('#anywhere'), true]);
    } else if (kind === 'no_project') {
      msg = '<div class="va-note va-warn"><b>No project yet</b><br>Ask VEDA and Capture need a project. Create one in VEDA, then invoke VEDA again.</div>';
      ctas.push(['＋ Create project in VEDA', openApp('#new-project'), true]);
      ctas.push(['Open VEDA', openApp(''), false]);
    } else if (kind === 'no_selection') {
      msg = '<div class="va-note"><b>Select text on the page to use VEDA.</b><br>Highlight a sentence, then invoke VEDA again.</div>';
    }
    body.innerHTML = msg;
    const actions = el('div', 'va-actions');
    actions.innerHTML = '<span class="va-spacer"></span>';
    ctas.forEach(([label, fn, primary]) => {
      const b = el('button', 'va-btn' + (primary ? ' va-primary' : ''), esc(label));
      b.addEventListener('click', () => { fn(); close(); });
      actions.appendChild(b);
    });
    const dismiss = el('button', 'va-btn', 'Dismiss');
    dismiss.addEventListener('click', close);
    actions.appendChild(dismiss);
    frame('menu', body, actions);
  }

  function projectSelector() {
    const projects = (V.session && V.session.projects) || [];
    const row = el('div', 'va-row');
    row.innerHTML = '<label>Project</label>';
    const sel = el('select');
    sel.innerHTML = projects.map((p) =>
      '<option value="' + esc(p.id) + '"' + (p.id === V.projectId ? ' selected' : '') + '>' +
      esc(p.name) + '</option>').join('');
    sel.addEventListener('change', async () => {
      V.projectId = sel.value;
      await send({ type: MSG.SET_ACTIVE_PROJECT, projectId: V.projectId });
      if (V.mode === 'capture') {
        V.detection = null; V._detecting = false; showCapture();
      } else if (V.mode === 'ask') {
        stopPolling(); V.thread = []; V.ask = null; showAsk();
      }
    });
    row.appendChild(sel);
    return row;
  }

  // ----- Ask VEDA ---------------------------------------------------------
  let pollTimer = null, tickTimer = null;
  function stopPolling() {
    clearTimeout(pollTimer); pollTimer = null;
    clearInterval(tickTimer); tickTimer = null;
  }

  function projectName() {
    const p = ((V.session && V.session.projects) || []).find((x) => x.id === V.projectId);
    return (p && p.name) || 'this project';
  }

  function showAsk() {
    V.mode = 'ask';
    const body = el('div');
    body.appendChild(projectSelector());

    if (V.injection && V.injection.flagged) {
      body.insertAdjacentHTML('beforeend',
        '<div class="va-note va-warn" style="margin-bottom:9px">Prompt-injection patterns detected in the selection (' +
        esc((V.injection.labels || []).join(', ')) +
        '). VEDA treats it as quoted data and answers your question only.</div>');
    }
    body.insertAdjacentHTML('beforeend',
      '<div class="va-selq" title="the text you selected">' + esc(V.selection) + '</div>');

    const chat = el('div', 'va-chat');
    V.thread.forEach((t) => {
      if (t.role === 'you') {
        chat.appendChild(el('div', 'va-msg va-you',
          '<div class="va-who">You</div><div class="va-bubble">' + esc(t.text) + '</div>'));
      } else if (t.pending) {
        const started = t.startedAt || Date.now();
        chat.appendChild(el('div', 'va-msg',
          '<div class="va-who">VEDA</div><div class="va-working">' +
          '<span class="va-spin"></span><div><b>' + esc(t.stage || 'Working') + '…</b>' +
          '<div class="va-muted">Answering from ' + esc(projectName()) + '. This can take a minute.</div></div>' +
          '<span class="va-clock" data-clock="' + started + '">' + fmtClock(Date.now() - started) + '</span>' +
          '</div>'));
      } else if (t.error) {
        chat.appendChild(el('div', 'va-msg',
          '<div class="va-who">VEDA</div><div class="va-note va-bad">' + esc(t.error) + '</div>'));
      } else {
        chat.appendChild(el('div', 'va-msg',
          '<div class="va-who">VEDA' + (t.provenance ? ' · ' + esc(String(t.provenance).replace(/_/g, ' ')) : '') +
          '</div><div class="va-answer">' + esc(t.text) + '</div>'));
      }
    });
    body.appendChild(chat);

    const compose = el('div', 'va-compose');
    compose.innerHTML = '<textarea rows="1" placeholder="' +
      (V.thread.length ? 'Ask a follow-up…' : 'Ask about this text, or type your own question…') + '"></textarea>';
    const ta = compose.querySelector('textarea');
    const grow = () => { ta.style.height = 'auto'; ta.style.height = Math.min(120, ta.scrollHeight) + 'px'; };
    ta.addEventListener('input', grow);
    const goBtn = el('button', 'va-btn va-primary', V.thread.length ? 'Send' : 'Ask VEDA');
    goBtn.disabled = V.busy;
    goBtn.addEventListener('click', () => doAsk(ta.value.trim()));
    ta.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); doAsk(ta.value.trim()); }
    });
    compose.appendChild(goBtn);
    body.appendChild(compose);

    const actions = el('div', 'va-actions');
    actions.innerHTML = '<span class="va-muted">Read-only · never changes the schedule</span><span class="va-spacer"></span>';
    const openApp = el('button', 'va-btn va-sm', 'Open in VEDA');
    openApp.addEventListener('click', () => send({ type: MSG.OPEN_APP, hash: '#ask' }));
    actions.appendChild(openApp);

    frame('ask', body, actions);
    const b = shadow.querySelector('.va-body');
    if (b) b.scrollTop = b.scrollHeight;
    startTick();
    setTimeout(grow, 0);
  }

  function startTick() {
    clearInterval(tickTimer);
    if (!V.thread.some((t) => t.pending)) return;
    tickTimer = setInterval(() => {
      shadow.querySelectorAll('.va-clock[data-clock]').forEach((c) => {
        c.textContent = fmtClock(Date.now() - Number(c.dataset.clock));
      });
    }, 1000);
  }

  async function persistAsk() {
    await storeSet(ASK_KEY, {
      projectId: V.projectId, selection: V.selection, host: V.host,
      thread: V.thread, jobId: V.ask && V.ask.jobId,
      startedAt: V.ask && V.ask.startedAt, updatedAt: Date.now(),
    });
  }

  async function doAsk(followUp) {
    if (V.busy) return;
    V.busy = true;
    if (followUp) V.thread.push({ role: 'you', text: followUp });
    const pending = { role: 'veda', pending: true, stage: 'Sending', startedAt: Date.now() };
    V.thread.push(pending);
    showAsk();

    const finish = (turn) => {
      stopPolling();
      V.thread = V.thread.filter((t) => !t.pending);
      V.thread.push(turn);
      V.busy = false;
      V.ask = null;
      storeDel(ASK_KEY);
      if (V.mode === 'ask') showAsk();
    };

    const started = await send({
      type: MSG.ASK,
      payload: {
        projectId: V.projectId, text: V.selection,
        followUp: followUp || null, sourceHost: V.host,
      },
    });
    if (!started || !started.ok || !started.jobId) {
      finish({ role: 'veda', error: (started && started.error) || 'VEDA could not start the question.' });
      return;
    }
    V.ask = { jobId: started.jobId, startedAt: pending.startedAt };
    pending.stage = 'Queued';
    persistAsk();
    resumePolling(started.jobId, pending.startedAt);
  }

  function resumePolling(jobId, startedAt) {
    stopPolling();
    const deadline = Date.now() + ASK_MAX_MS;
    startTick();

    const poll = async () => {
      if (V.mode !== 'ask') { stopPolling(); return; }
      const st = await send({ type: MSG.ASK_POLL, jobId: jobId, projectId: V.projectId });
      const pend = V.thread.find((t) => t.pending);
      if (st && st.ok && st.status === 'done' && st.answer) {
        stopPolling();
        V.thread = V.thread.filter((t) => !t.pending);
        V.thread.push({ role: 'veda', text: st.answer, provenance: st.provenance });
        V.busy = false; V.ask = null;
        await storeDel(ASK_KEY);
        if (V.mode === 'ask') showAsk();
        return;
      }
      if (st && st.status === 'failed') {
        stopPolling();
        V.thread = V.thread.filter((t) => !t.pending);
        V.thread.push({ role: 'veda', error: st.error || 'VEDA could not produce a grounded answer.' });
        V.busy = false; V.ask = null;
        await storeDel(ASK_KEY);
        if (V.mode === 'ask') showAsk();
        return;
      }
      if (pend && st && st.stage) {
        pend.stage = st.stage;
        const label = shadow.querySelector('.va-working b');
        if (label) label.textContent = st.stage + '…';
      }
      persistAsk();
      if (Date.now() > deadline) {
        // Keep the job (and the persisted conversation) alive - the answer is
        // guaranteed to land in the VEDA app's Ask VEDA page, and reopening the
        // panel resumes the wait.
        stopPolling();
        V.busy = false;
        V.thread = V.thread.filter((t) => !t.pending);
        V.thread.push({ role: 'veda', timeout: true, error:
          'Still working after ' + fmtClock(ASK_MAX_MS) + '. The answer will appear in Ask VEDA in the VEDA app — open it there, or reopen this panel to keep waiting.' });
        if (V.mode === 'ask') showAsk();
        return;
      }
      pollTimer = setTimeout(poll, ASK_POLL_MS);
    };
    pollTimer = setTimeout(poll, 900);
  }

  async function maybeResumeAsk() {
    const saved = await storeGet(ASK_KEY);
    if (!saved || saved.projectId !== V.projectId) return false;
    if (Date.now() - (saved.updatedAt || 0) > ASK_RESUME_MS) { storeDel(ASK_KEY); return false; }
    // If the operator highlighted DIFFERENT text and invoked Ask again, that is
    // a new question - keep the previous conversation only when the selection
    // matches or there is no fresh selection.
    const freshDifferent = V.selection && saved.selection && V.selection !== saved.selection;
    if (freshDifferent) { return false; }

    V.thread = Array.isArray(saved.thread)
      ? saved.thread.filter((t) => !t.pending && !t.timeout) : [];
    if (saved.selection && !V.selection) V.selection = saved.selection;
    if (saved.jobId) {
      V.thread.push({ role: 'veda', pending: true, stage: 'Reconnecting',
        startedAt: saved.startedAt || Date.now() });
      V.busy = true;
      V.ask = { jobId: saved.jobId, startedAt: saved.startedAt || Date.now() };
    }
    return V.thread.length > 0;
  }

  // ----- Capture in VEDA -----------------------------------------------------
  function showCapture() {
    V.mode = 'capture';
    const body = el('div');
    body.appendChild(projectSelector());
    body.insertAdjacentHTML('beforeend',
      '<div class="va-selq va-cap" title="the text you selected">' + esc(V.selection) + '</div>');

    if (V.injection && V.injection.quarantined) {
      body.insertAdjacentHTML('beforeend',
        '<div class="va-note va-bad" style="margin-bottom:9px"><b>This selection contains instruction-like text.</b> It can still be captured as evidence, but VEDA will hold it for security review and will not auto-link it.</div>');
    } else if (V.injection && V.injection.flagged) {
      body.insertAdjacentHTML('beforeend',
        '<div class="va-note va-warn" style="margin-bottom:9px">Flagged content — it will be stored as evidence and held for a human to review, not acted on as an instruction.</div>');
    }

    const detectSlot = el('div', 'va-detect');
    body.appendChild(detectSlot);
    renderDetect(detectSlot);

    const md = (V.session && V.session.captureMetadataDefaults) || {};
    const meta = el('div');
    meta.innerHTML =
      '<div class="va-row" style="margin-top:8px"><label>Optional</label><span class="va-muted">only what you tick is sent</span></div>' +
      '<label class="va-check"><input type="checkbox" data-meta="include_source_app"' + (md.include_source_app ? ' checked' : '') + '> Include source application (<span class="va-mono">' + esc(V.sourceApp) + '</span>)</label>' +
      '<label class="va-check"><input type="checkbox" data-meta="include_title"' + (md.include_title ? ' checked' : '') + '> Include page title</label>' +
      '<label class="va-check"><input type="checkbox" data-meta="include_url"' + (md.include_url ? ' checked' : '') + '> Include webpage URL</label>';
    body.appendChild(meta);

    const actions = el('div', 'va-actions');
    actions.innerHTML = '<span class="va-spacer"></span>';
    const captureBtn = el('button', 'va-btn va-amber', V.busy ? 'Capturing…' : 'Capture Evidence');
    captureBtn.disabled = V.busy || !V.projectId;
    captureBtn.addEventListener('click', () => doCapture(meta));
    actions.appendChild(captureBtn);

    frame('capture', body, actions);
  }

  function renderDetect(slot) {
    if (!V.projectId) { slot.innerHTML = '<div class="va-note va-warn">Select a project to detect the activity.</div>'; return; }
    if (V.detection === null) {
      slot.innerHTML = '<div class="va-note"><span class="va-spin"></span> Detecting activity and update type…</div>';
      if (!V._detecting) {
        V._detecting = true;
        send({ type: MSG.DETECT, payload: { projectId: V.projectId, text: V.selection } }).then((res) => {
          V._detecting = false;
          if (res && res.ok) {
            V.detection = res.detection || {};
            V.injection = res.injection || V.injection;
          } else {
            V.detection = { error: (res && res.error) || 'detection failed' };
          }
          if (V.mode === 'capture') renderDetect(slot);
        });
      }
      return;
    }
    const d = V.detection || {};
    if (d.error) {
      slot.innerHTML = '<div class="va-note va-warn">Could not detect an activity (' + esc(d.error) +
        '). You can still capture the text as evidence — VEDA will resolve it.</div>';
      return;
    }
    const act = d.activity;
    const confPct = act && act.confidence != null ? Math.round(act.confidence * 100)
      : (d.confidence != null ? Math.round(d.confidence * 100) : null);
    let html = '<dl><dt>VEDA detected</dt><dd>' + esc(d.detected_type || 'Field Note') + '</dd>';
    if (act && act.uid != null) {
      html += '<dt>Possible activity</dt><dd><b class="va-mono">' + esc(act.display_id || ('UID ' + act.uid)) +
        '</b> — ' + esc(act.name || '') + '</dd>';
      if (confPct != null) {
        html += '<dt>Confidence</dt><dd><span class="va-conf"><span class="va-meter"><i style="width:' + confPct + '%"></i></span><b>' + confPct + '%</b></span>';
        if (d.engine === 'deterministic_fallback') html += ' <span class="va-muted">(heuristic)</span>';
        html += '</dd>';
      }
    } else if (d.has_schedule) {
      html += '<dt>Possible activity</dt><dd class="va-muted">No confident match — VEDA runs the schedule-linking resolver after capture.</dd>';
    } else {
      html += '<dt>Schedule</dt><dd class="va-muted">No schedule loaded for this project yet — the text is stored as evidence.</dd>';
    }
    html += '</dl>';
    slot.innerHTML = html;

    if (Array.isArray(d.alternatives) && d.alternatives.length) {
      const alt = el('div');
      alt.style.marginTop = '6px';
      alt.innerHTML = '<div class="va-muted" style="margin-bottom:3px">Other candidates:</div>';
      d.alternatives.forEach((a) => {
        if (a.uid == null) return;
        const btn = el('button', 'va-linklike');
        btn.style.display = 'block';
        btn.textContent = (a.display_id || ('UID ' + a.uid)) + ' — ' + (a.name || '');
        btn.addEventListener('click', () => {
          V.detection = Object.assign({}, d, { activity: Object.assign({}, a), _overridden: true });
          renderDetect(slot);
        });
        alt.appendChild(btn);
      });
      slot.appendChild(alt);
    }
  }

  async function doCapture(metaNode) {
    if (V.busy || !V.projectId) return;
    const checks = {};
    metaNode.querySelectorAll('[data-meta]').forEach((c) => { checks[c.dataset.meta] = c.checked; });
    V.busy = true;
    showCapture();

    const d = V.detection || {};
    const act = d.activity && d.activity.uid != null ? d.activity : null;

    const res = await send({
      type: MSG.CAPTURE,
      payload: {
        projectId: V.projectId, text: V.selection,
        activityUid: act ? act.uid : null,
        eventState: d.event_state || 'progress',
        observedProgress: d.observed_progress == null ? null : d.observed_progress,
        clientCaptureId: stableKey([V.projectId, act ? String(act.uid) : '-', V.selection]),
        occurredAt: new Date().toISOString(), sourceHost: V.host,
        metadata: {
          include_url: checks.include_url, include_title: checks.include_title,
          include_source_app: checks.include_source_app,
          url: checks.include_url ? V.url : undefined,
          title: checks.include_title ? V.title : undefined,
          source_app: checks.include_source_app ? V.sourceApp : undefined,
        },
      },
    });
    V.busy = false;
    showCaptureResult(res);
  }

  function showCaptureResult(res) {
    const body = el('div');
    if (!res || !res.ok) {
      body.innerHTML = '<div class="va-note va-bad"><b>Capture failed.</b><br>' + esc((res && res.error) || 'Unknown error') + '</div>';
      const actions = el('div', 'va-actions');
      actions.innerHTML = '<span class="va-spacer"></span>';
      const back = el('button', 'va-btn', 'Back');
      back.addEventListener('click', () => showCapture());
      actions.appendChild(back);
      frame('capture', body, actions);
      return;
    }
    const m = res.matched_activity;
    body.innerHTML = '<div class="va-note va-ok"><b>✓ Captured in VEDA</b></div>';
    const kv = el('dl', 'va-kv');
    kv.innerHTML =
      '<dt>Project</dt><dd>' + esc((res.project && res.project.name) || '') + '</dd>' +
      (m && m.uid != null
        ? '<dt>Matched activity</dt><dd><b class="va-mono">' + esc(m.display_id || ('UID ' + m.uid)) + '</b> — ' + esc(m.name || '') + '</dd>'
        : '<dt>Matched activity</dt><dd class="va-muted">Pending — resolver / human review</dd>') +
      '<dt>Status</dt><dd>' + esc(res.review_status || res.status || 'Pending validation') + '</dd>' +
      '<dt>Evidence ID</dt><dd class="va-mono">' + esc(res.evidence_ref || res.evidence_id || '') + '</dd>';
    body.appendChild(kv);
    body.insertAdjacentHTML('beforeend',
      '<div class="va-note" style="margin-top:8px">' +
      esc(res.note || 'Captured text is evidence, not an instruction. It flows through VEDA’s existing reconciliation, review, approval and audit pipeline.') +
      '</div>');

    const actions = el('div', 'va-actions');
    actions.innerHTML = '<span class="va-spacer"></span>';
    const openApp = el('button', 'va-btn', 'Open in VEDA');
    openApp.addEventListener('click', () => { send({ type: MSG.OPEN_APP, hash: '#evidence' }); close(); });
    const done = el('button', 'va-btn va-primary', 'Done');
    done.addEventListener('click', close);
    actions.appendChild(openApp);
    actions.appendChild(done);
    frame('capture', body, actions);
  }

  // ----------------------------------------------------------------- init
  async function decideAndRender() {
    document.addEventListener('keydown', onKey, true);
    window.addEventListener('resize', onResizeWindow);

    const sres = await send({ type: MSG.SESSION_GET });
    if (!sres || !sres.ok) { gate('unreachable'); return; }
    V.session = sres.state || {};
    if (!V.session.connected) {
      const r = await send({ type: MSG.SESSION_REFRESH });
      V.session = (r && r.state) || V.session;
    }
    if (!V.session.connected) { gate('not_connected'); return; }

    const refreshed = await send({ type: MSG.SESSION_REFRESH });
    if (refreshed && refreshed.ok && refreshed.state) V.session = refreshed.state;
    if (!V.session.enabled) { gate('disabled'); return; }

    const projects = V.session.projects || [];
    if (!projects.length) { gate('no_project'); return; }
    V.projectId = V.session.activeProjectId || V.session.defaultProjectId || projects[0].id;

    if (V.mode === 'ask') {
      const resumed = await maybeResumeAsk();
      if (!V.selection && !resumed) { gate('no_selection'); return; }
      showAsk();
      if (V.ask && V.ask.jobId) resumePolling(V.ask.jobId, V.ask.startedAt);
      return;
    }

    if (!V.selection) { gate('no_selection'); return; }
    if (V.mode === 'capture') showCapture();
    else showPill();
  }

  let bootTimer = null;
  function boot(mode) {
    clearTimeout(bootTimer);
    stopPolling();
    V._detecting = false;
    const s = readSelection();
    // A fresh selection always replaces the old one; only keep the previous
    // selection if the page has nothing selected right now.
    if (s.text) V.selection = s.text.slice(0, 8000);
    else if (mode !== 'ask') V.selection = V.selection || '';
    V.rect = s.rect;
    V.mode = mode || 'menu';
    // maybeResumeAsk() decides whether to restore a prior conversation.
    V.thread = [];
    V.ask = null;
    V.detection = null;
    V.busy = false;
    // restore panel position/size (best effort)
    storeGet(PANEL_KEY).then((p) => {
      if (p && Number.isFinite(p.left)) { V.pos = { left: p.left, top: p.top }; }
      if (p && Number.isFinite(p.width)) V.width = p.width;
      decideAndRender();
    });
  }

  chrome.runtime.onMessage.addListener((message) => {
    if (message && message.type === MSG.OPEN_OVERLAY) boot(message.mode || 'menu');
  });

  window.__vedaAnywhereOverlay = { reopen: () => boot(V.mode || 'menu') };

  bootTimer = setTimeout(() => boot('menu'), 120);
})();
