#!/usr/bin/env node
/* Focused state-machine checks for the persisted execution architecture. */
const fs = require('fs');
const assert = require('assert');

global.window = {
  esc: (value) => String(value === null || value === undefined ? '' : value)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;'),
  api: async () => ({}),
  post: async () => ({}),
};

const source = fs.readFileSync('veda/web/views.js', 'utf8');
eval(source + '\n;global.__vedaUi = {' +
  'RUN_PHASE_ORDER, presentedRunContext, executionMap, VIEWS};');

const ui = global.__vedaUi;
assert.strictEqual(ui.RUN_PHASE_ORDER.evidence_reused, 2);
assert.strictEqual(ui.RUN_PHASE_ORDER.resolver_indexing, 4);
assert.strictEqual(ui.RUN_PHASE_ORDER.resolver_validating, 5);
assert.strictEqual(ui.RUN_PHASE_ORDER.resolver_persisting, 6);

const job = {
  id: 'job-playback', kind: 'analysis', status: 'running',
  phase: 'agent_invoked', created_at: Date.now() / 1000,
};
let ctx = ui.presentedRunContext(job, [
  { step: 'agent_invoked', label: 'Reasoning started' },
]);
assert.strictEqual(ctx.ordinal, 0, 'live run skipped the Sources presentation');
assert.strictEqual(ctx.actualOrdinal, 3);

for (let expected = 1; expected <= 3; expected += 1) {
  ui.VIEWS._runPlayback[job.id].lastAdvance = 0;
  ctx = ui.presentedRunContext(job, []);
  assert.strictEqual(ctx.ordinal, expected, 'persisted stage playback jumped');
}

job.phase = 'resolver_indexing';
ui.VIEWS._runPlayback[job.id].lastAdvance = 0;
const html = ui.executionMap(job, [
  { step: 'resolver_indexing', label: 'Building the semantic candidate floor' },
]);
const field = html.indexOf('node-field-observation');
const firstActiveConnector = html.indexOf('arch-connector active', field);
const semantic = html.indexOf('node-semantic-candidate-floor');
assert(field >= 0 && firstActiveConnector > field && semantic > firstActiveConnector,
  'Field Observation no longer feeds an active Semantic connector');
assert(html.includes('data-run-display="4"'));
assert(html.includes('data-run-actual="4"'));

const appSource = fs.readFileSync('veda/web/app.js', 'utf8');
assert(appSource.includes('function pollAgentState(projectId)'));
assert(appSource.includes('version !== S.renderVersion'));
assert(appSource.includes("latest && latest.label"));

console.log('execution UI regression test: ok');
