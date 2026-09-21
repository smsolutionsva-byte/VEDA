'use strict';

const fs = require('fs');
const path = require('path');

const root = path.resolve(__dirname, '..');
const views = fs.readFileSync(path.join(root, 'veda', 'web', 'views.js'), 'utf8');
const app = fs.readFileSync(path.join(root, 'veda', 'web', 'app.js'), 'utf8');
const html = fs.readFileSync(path.join(root, 'veda', 'web', 'index.html'), 'utf8');

if (!/openKey: 'ask:' \+ turn\.id,[\s\S]*?defaultOpen: false/.test(views)) {
  throw new Error('Ask VEDA reasoning must be collapsed by default');
}
if (!views.includes("agent_invoked: 'Choosing the right reasoning path'")) {
  throw new Error('Ask VEDA must hide provider-specific invocation labels');
}
if (!app.includes("askState.restoreScroll =")) {
  throw new Error('Ask VEDA must capture its nested scroll position on refresh');
}
if (!views.includes('scroll.scrollTop = restoreScroll.top')) {
  throw new Error('Ask VEDA must restore reader scroll position after refresh');
}
if (!html.includes('views.js?v=1.75')) {
  throw new Error('Ask VEDA frontend cache version was not updated');
}

console.log('Ask VEDA UI regression test: PASS');
