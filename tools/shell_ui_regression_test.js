'use strict';

const fs = require('fs');
const path = require('path');

const root = path.resolve(__dirname, '..');
const read = (file) => fs.readFileSync(path.join(root, file), 'utf8');
const html = read('veda/web/index.html');
const app = read('veda/web/app.js');
const css = read('veda/web/app.css');
const worker = read('veda/web/service-worker.js');
const views = read('veda/web/views.js');
const capture = read('veda/web/field-capture.js');

const requireText = (source, text, message) => {
  if (!source.includes(text)) throw new Error(message);
};

requireText(app, "['overview', 'Dashboard']", 'Overview navigation must be named Dashboard');
requireText(html, 'id="notifications"', 'Header notification entry point is missing');
requireText(html, 'id="profile-toggle"', 'Header account entry point is missing');
requireText(html, 'id="quick-ask"', 'Header Ask VEDA shortcut is missing');
requireText(app, "const RAIL_STATE_KEY = 'veda-navigation-collapsed'",
  'Navigation collapse state must be durable');
requireText(css, 'body.rail-collapsed #app', 'Compact navigation layout is missing');
requireText(css, '@media (prefers-reduced-motion: reduce)',
  'Navigation motion must respect reduced-motion preferences');
requireText(worker, "const CACHE = 'veda-shell-1.75'", 'Shell cache version is stale');
requireText(worker, '/static/spatial-control.js?v=1.75', 'Spatial viewer is missing from the offline shell');
requireText(html, '/static/spatial-control.js?v=1.75', 'Local spatial viewer module is missing');
requireText(html, 'data-role-switch="worker"', 'Worker persona switch is missing');
requireText(app, "const WORKER_NAV =", 'Worker navigation must be separate from supervisor navigation');
requireText(app, "const WORKER_VIEWS = new Set", 'Worker route boundary is missing');
requireText(app, "new BroadcastChannel('veda-field-handoff')", 'Live field handoff channel is missing');
requireText(css, 'body[data-role="worker"]', 'Worker-specific shell treatment is missing');
requireText(views, 'controls autoplay muted playsinline', 'Fixed camera feeds must request muted autoplay');
requireText(capture, 'function autoplayCctv', 'CCTV review must recover autoplay after source changes');

if (html.includes('id="analyze"')) throw new Error('Run analysis must not live in the global header');
if (html.includes('id="theme-toggle"')) throw new Error('Theme toggle must not live in the global header');

console.log('shell UI regression test: PASS');
