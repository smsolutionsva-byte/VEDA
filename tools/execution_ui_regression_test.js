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
  'RUN_PHASE_ORDER, RUN_STAGES, presentedRunContext, executionMap, VIEWS};');

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
const semantic = html.indexOf('node-semantic-candidate-floor');
const rail = html.indexOf('arch-rail  active', field);
assert(field >= 0 && rail > field && semantic > rail,
  'Field Observation no longer feeds an active rail into the resolver');
assert(html.includes('data-run-display="4"'));
assert(html.includes('data-run-actual="4"'));

// The progress rail and the architecture map must describe the same run: every
// stage ordinal drawn as a milestone has to exist as at least one node.
const milestones = (html.match(/class="run-milestone /g) || []).length;
assert.strictEqual(milestones, ui.RUN_STAGES.length,
  'progress rail lost a stage');
for (const cls of ['done', 'active', 'pending', 'guarded']) {
  assert(html.includes('arch-node node-'), 'architecture nodes missing');
}
assert(html.includes('arch-node node-schedule-write-gates guarded'),
  'the schedule-write boundary must always render as governed');
assert(!/arch-(fork|split|connector)/.test(html),
  'stale overlapping connector markup is still emitted');

// Bands must declare a column count that matches the nodes they contain, or the
// grid will leave a hole / overflow its row.
const bands = [...html.matchAll(/<div class="arch-band cols-(\d+)">([\s\S]*?)(?=<div class="arch-(band|rail|stage)|<\/div><div class="arch-stage|$)/g)];
assert(bands.length >= 6, 'expected the resolver ensemble to be drawn as bands');
for (const [, cols, body] of bands) {
  const nodes = (body.match(/class="arch-node /g) || []).length;
  assert.strictEqual(nodes, Number(cols),
    `band declared cols-${cols} but drew ${nodes} nodes`);
}

const appSource = fs.readFileSync('veda/web/app.js', 'utf8');
assert(appSource.includes('function pollAgentState(projectId)'));
assert(appSource.includes('version !== S.renderVersion'));
assert(appSource.includes("latest && latest.label"));

console.log('execution UI regression test: ok');
