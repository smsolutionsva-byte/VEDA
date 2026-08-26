/* VEDA views. Every value that came from a document or a model is escaped:
   uploaded files are untrusted data and must never render as markup. */

const VIEWS = {};
const E = (s) => window.esc(s);
const A = (p) => window.api(p);
const P = (p, b) => window.post(p, b);

/* ------------------------------------------------------------ helpers */
const day = (v) => v ? String(v).split('T')[0] : '—';
const num = (v, d) => (v === null || v === undefined || v === '')
  ? '—' : Number(v).toFixed(d === undefined ? 1 : d);
const int = (v) => (v === null || v === undefined || v === '')
  ? '—' : Math.round(Number(v)).toLocaleString();

function prov(p) {
  if (!p) return '';
  return '<span class="prov ' + E(p) + '">' + E(String(p).replace(/_/g, ' ')) +
    '</span>';
}

function provKey() {
  const items = [['MCP_FACT', 'Schedule fact'], ['SOURCE_FILE', 'Document'],
    ['HUMAN_INPUT', 'Human'], ['AI_INFERENCE', 'Inference'],
    ['DETERMINISTIC_CALCULATION', 'Computed'], ['DERIVED', 'Derived']];
  return '<div class="key"><span class="lbl">Provenance</span>' +
    items.map(([k, l]) => '<span class="prov ' + k + '">' + l + '</span>').join('') +
    '</div>';
}

function panel(title, body, extra) {
  return '<section class="panel"><header>' + title +
    '<div class="spacer"></div>' + (extra || '') + '</header>' + body + '</section>';
}

function stat(k, v, d, cls) {
  return '<div class="stat ' + (cls || '') + '"><div class="k">' + E(k) +
    '</div><div class="v">' + v + '</div>' +
    (d ? '<div class="d">' + d + '</div>' : '') + '</div>';
}

function empty(title, msg) {
  return '<div class="empty"><b>' + E(title) + '</b>' + E(msg || '') + '</div>';
}

function table(cols, rows, rowFn, opts) {
  opts = opts || {};
  if (!rows.length) return empty(opts.emptyTitle || 'Nothing here yet',
                                 opts.emptyMsg || '');
  return '<div class="tw"><table><thead><tr>' +
    cols.map(c => '<th class="' + (c.r ? 'r' : '') + (c.sort ? ' s' : '') + '"' +
      (c.sort ? ' data-sort="' + c.sort + '"' : '') + '>' + E(c.t) + '</th>').join('') +
    '</tr></thead><tbody>' + rows.map(rowFn).join('') + '</tbody></table></div>';
}

function bar(pct, cls) {
  const p = Math.max(0, Math.min(100, Number(pct) || 0));
  return '<div class="bar ' + (cls || '') + '"><i style="width:' + p + '%"></i></div>';
}

function sev(s) {
  return '<span class="sev-' + E(String(s || 'low').toLowerCase()) + '">' +
    E(s || '—') + '</span>';
}

function tagFor(v, map) {
  const c = map[String(v || '').toLowerCase()] || 'grey';
  return '<span class="tag ' + c + '">' + E(v || '—') + '</span>';
}
const ST = { complete: 'green', in_progress: 'blue', not_started: 'grey',
  open: 'amber', closed: 'green', linked: 'blue', confirmed: 'green',
  needs_review: 'amber', conflicting: 'red', quarantined: 'red',
  rejected: 'red', duplicate: 'grey', historical: 'violet', new: 'grey',
  pass: 'green', fail: 'red', not_evaluated: 'grey', high: 'red',
  critical: 'red', medium: 'amber', low: 'grey', approved: 'green',
  pending: 'amber', verified: 'green', failed: 'red', done: 'green',
  running: 'blue', queued: 'grey', awaiting_review: 'amber', partial: 'amber' };

/* ===================================================== no project */
VIEWS.noproject = () =>
  '<div class="panel" style="max-width:640px;margin:60px auto">' +
  '<header>Get started</header><div class="body">' +
  '<p style="margin-top:0;color:var(--ink-2)">VEDA reads a construction ' +
  'schedule through Horizun, interprets the field paperwork around it, and ' +
  'keeps every conclusion traceable to where it came from.</p>' +
  '<p style="color:var(--ink-2)">Create a project, then upload a schedule ' +
  '(XER, MPP, MSPDI XML, PMXML, Asta) together with the DPRs, registers and ' +
  'reports that describe what actually happened on site.</p>' +
  '<button class="btn primary" id="createFirst">Create a project</button>' +
  '</div></section>';

/* ===================================================== 1. overview */
VIEWS.overview = async (pid) => {
  const o = await A('/projects/' + pid + '/overview');
  const s = o.schedule, ev = o.earned_value, c = o.counts;
  if (!s) {
    return '<div class="head"><h1>' + E(o.project.name) + '</h1></div>' +
      panel('Project overview', '<div class="body">' +
        '<div class="note warn">No schedule has been analysed yet. Upload a ' +
        'schedule file and VEDA will open it through Horizun automatically.' +
        '</div><p><button class="btn primary" onclick="go(\'files\')">' +
        'Go to files</button></p></div>');
  }
  const late = s.forecast_finish && s.baseline_finish &&
    day(s.forecast_finish) > day(s.baseline_finish);

  return '<div class="head"><div><div class="eyebrow">Project overview</div>' +
    '<h1>' + E(o.project.name) + '</h1>' +
    '<div class="sub">' + E(s.project_name || '') +
    (o.project.location ? ' · ' + E(o.project.location) : '') +
    ' · data date ' + day(s.data_date) + ' · revision ' + E(s.revision) +
    '</div></div><div class="spacer"></div>' + provKey() + '</div>' +

    '<div class="grid g4" style="margin-bottom:14px">' +
    stat('Forecast finish', day(s.forecast_finish),
      s.baseline_finish ? 'baseline ' + day(s.baseline_finish) : 'no baseline',
      late ? 'hot' : 'good') +
    stat('Progress', num(s.percent_complete, 1) + '%',
      ev && ev.spi ? 'SPI ' + num(ev.spi, 3) : 'schedule complete') +
    stat('Critical', int(c.critical), 'of ' + int(c.activities) + ' activities',
      'warm') +
    stat('Schedule health', num(s.health_score, 1) + '%',
      o.quality.failed + ' of ' + (o.quality.passed + o.quality.failed +
        o.quality.not_evaluated) + ' checks failed',
      s.health_score < 60 ? 'hot' : 'good') +
    '</div>' +

    '<div class="grid g4" style="margin-bottom:14px">' +
    stat('Late activities', int(c.late), 'past baseline finish',
      c.late ? 'warm' : '') +
    stat('Evidence', int(c.evidence), 'field records held') +
    stat('Pending reviews', int(c.pending_reviews), 'need a human answer',
      c.pending_reviews ? 'warm' : 'good') +
    stat('Pending changes', int(c.pending_proposals), 'awaiting approval',
      c.pending_proposals ? 'warm' : 'good') +
    '</div>' +

    (o.summary ? panel('Latest analysis summary',
      '<div class="body"><div style="white-space:pre-wrap;font-size:13.5px;' +
      'line-height:1.6">' + E(o.summary) + '</div>' +
      '<div style="margin-top:10px">' + prov('AI_INFERENCE') +
      ' <span style="color:var(--ink-3);font-size:12px">Written by ' +
      E(o.provider_label || o.active_provider) + ' from the stored schedule ' +
      'facts and field evidence.</span></div></div>') : '') +

    '<div class="grid g2">' +
    panel('Schedule', '<div class="body"><dl class="kv">' +
      row('Schedule name', E(s.project_name)) +
      row('Data date', day(s.data_date)) +
      row('Planned start', day(s.planned_start)) +
      row('Planned finish', day(s.planned_finish)) +
      row('Forecast finish', day(s.forecast_finish)) +
      row('Baseline finish', s.baseline_finish ? day(s.baseline_finish)
        : '<span style="color:var(--ink-3)">none stored</span>') +
      row('Activities', int(s.task_count)) +
      row('Relationships', int(s.relationship_count)) +
      row('Resources', int(s.resource_count)) +
      '</dl><div style="margin-top:10px">' + prov('MCP_FACT') +
      ' <span style="color:var(--ink-3);font-size:12px">Read from Horizun. ' +
      'VEDA does not recompute schedule machinery.</span></div></div>') +
    panel('Earned value', ev
      ? '<div class="body"><dl class="kv">' +
        row('PV / BCWS', num(ev.pv, 2)) + row('EV / BCWP', num(ev.ev, 2)) +
        row('AC / ACWP', num(ev.ac, 2)) + row('BAC', num(ev.bac, 2)) +
        row('SPI', '<b class="' + (ev.spi < 1 ? 'sev-high' : 'sev-low') + '">' +
          num(ev.spi, 3) + '</b>') +
        row('CPI', num(ev.cpi, 3)) + row('EAC', num(ev.eac, 2)) +
        row('TCPI', num(ev.tcpi, 3)) +
        '</dl><div class="note mcp" style="margin-top:10px">Basis: ' +
        E(ev.basis || '') + '</div></div>'
      : '<div class="body"><div class="note warn">Earned value requires a ' +
        'stored baseline. This schedule has none, so Horizun reports the ' +
        'baseline checks as not evaluated rather than passing them.</div></div>') +
    '</div>';
};
const row = (k, v) => '<dt>' + E(k) + '</dt><dd>' + v + '</dd>';

/* ===================================================== 2. EPS */
VIEWS.eps = async (pid) => {
  const r = await A('/projects/' + pid + '/eps');
  if (!r.available) {
    return head('EPS', 'Enterprise project structure') +
      panel('EPS', '<div class="body"><div class="note warn">' +
        '<b>EPS information unavailable</b><br>' + E(r.detail || '') +
        '</div></div>');
  }
  return head('EPS', 'Enterprise project structure') +
    panel('EPS', table([{ t: 'Code' }, { t: 'Name' }, { t: 'Parent' },
      { t: 'Level', r: true }], r.nodes, n =>
      '<tr><td class="mono">' + E(n.code) + '</td><td>' + E(n.name) +
      '</td><td class="mono">' + E(n.parent_code || '—') + '</td>' +
      '<td class="r mono">' + E(n.level) + '</td></tr>'), '');
};

const head = (title, sub, extra) =>
  '<div class="head"><div><div class="eyebrow">' + E(sub || '') + '</div>' +
  '<h1>' + E(title) + '</h1></div><div class="spacer"></div>' +
  (extra || '') + '</div>';

/* ===================================================== 3. WBS */
VIEWS.wbs = async (pid) => {
  const r = await A('/projects/' + pid + '/wbs');
  return head('WBS', 'Work breakdown structure') +
    panel('Branches <small>' + r.nodes.length + '</small>',
      table([{ t: 'Code' }, { t: 'Name' }, { t: 'Start' }, { t: 'Finish' },
        { t: 'Progress' }, { t: 'Activities', r: true }, { t: 'Critical', r: true },
        { t: 'Late', r: true }, { t: 'Issues', r: true }, { t: 'Risks', r: true },
        { t: 'Evidence', r: true }],
      r.nodes, n =>
        '<tr class="click" onclick="go(\'activities\',{wbs:\'' + E(n.code) +
        '\'})"><td class="mono">' + E(n.code) + '</td><td>' + E(n.name) +
        '</td><td class="mono">' + day(n.start) + '</td><td class="mono">' +
        day(n.finish) + '</td><td style="min-width:124px"><div class="pcell">' +
        bar(n.percent_complete) + '<span class="mono pct">' +
        num(n.percent_complete, 0) + '%</span></div></td>' +
        '<td class="r mono">' + int(n.activity_count) + '</td>' +
        '<td class="r mono">' + int(n.critical_count) + '</td>' +
        '<td class="r mono">' + int(n.late_count) + '</td>' +
        '<td class="r mono">' + int(n.issues) + '</td>' +
        '<td class="r mono">' + int(n.risks) + '</td>' +
        '<td class="r mono">' + int(n.evidence) + '</td></tr>',
      { emptyTitle: 'No WBS yet', emptyMsg: 'Upload and analyse a schedule.' }));
};

/* ===================================================== 4. Activities */
VIEWS.activities = async (pid, params) => {
  const q = new URLSearchParams({
    limit: 200, offset: params.offset || 0,
    q: params.q || '', wbs: params.wbs || '', status: params.status || '',
    critical: params.critical || '', milestone: params.milestone || '',
    late: params.late || '', sort: params.sort || 'start',
    direction: params.direction || 'asc',
  });
  const r = await A('/projects/' + pid + '/activities?' + q);
  const t = table([
    { t: 'UID', sort: 'uid', r: true }, { t: 'ID' }, { t: 'Activity', sort: 'name' },
    { t: 'WBS', sort: 'wbs' }, { t: 'Status' },
    { t: 'Start', sort: 'start' }, { t: 'Finish', sort: 'finish' },
    { t: 'Dur', sort: 'duration', r: true }, { t: 'Prog', sort: 'progress' },
    { t: 'Float', sort: 'float', r: true }, { t: 'Var', sort: 'variance', r: true },
    { t: 'Ev', r: true }, { t: 'Is', r: true }, { t: 'Rk', r: true }],
    r.activities, a =>
    '<tr class="click ' + (a.critical ? 'crit' : '') +
    '" onclick="go(\'activity\',{id:' + a.uid + '})">' +
    '<td class="r mono">' + E(a.uid) + '</td>' +
    '<td class="mono" style="color:var(--ink-3)">' + E(a.display_id) + '</td>' +
    '<td class="trunc">' + (a.is_summary ? '<b>' : '') + E(a.name) +
    (a.is_summary ? '</b>' : '') +
    (a.is_milestone ? ' <span class="tag violet">MS</span>' : '') +
    (a.critical ? ' <span class="tag red">CP</span>' : '') + '</td>' +
    '<td class="mono">' + E(a.wbs) + '</td>' +
    '<td>' + tagFor(a.status, ST) + '</td>' +
    '<td class="mono">' + day(a.start) + '</td>' +
    '<td class="mono">' + day(a.finish) + '</td>' +
    '<td class="r mono">' + num(a.duration_days, 0) + '</td>' +
    '<td style="min-width:124px"><div class="pcell">' + bar(a.percent_complete) +
    '<span class="mono pct">' + num(a.percent_complete, 0) + '%</span>' +
    (a.observed_progress !== null && a.observed_progress !== undefined
      ? '<span class="mono pct" style="color:var(--human)" title="observed">' +
        num(a.observed_progress, 0) + '%</span>' : '') + '</div></td>' +
    '<td class="r mono ' + ((a.total_float_days || 0) < 0 ? 'sev-critical' : '') +
    '">' + num(a.total_float_days, 0) + '</td>' +
    '<td class="r mono ' + ((a.finish_variance_days || 0) > 0 ? 'sev-high' : '') +
    '">' + num(a.finish_variance_days, 0) + '</td>' +
    '<td class="r mono">' + (a.evidence_count || '') + '</td>' +
    '<td class="r mono">' + (a.issue_count || '') + '</td>' +
    '<td class="r mono">' + (a.risk_count || '') + '</td></tr>',
    { emptyTitle: 'No activities', emptyMsg: 'Analyse a schedule first.' });

  return head('Activities', 'Schedule facts, read from Horizun',
    prov('MCP_FACT')) +
    '<div class="toolbar">' +
    '<input class="inp" id="fq" placeholder="Search name, id or WBS" value="' +
    E(params.q || '') + '">' +
    '<select class="inp" id="fs"><option value="">Any status</option>' +
    ['not_started', 'in_progress', 'complete'].map(s => '<option ' +
      (params.status === s ? 'selected' : '') + '>' + s + '</option>').join('') +
    '</select>' +
    '<button class="btn sm' + (params.critical ? ' primary' : '') +
    '" id="fc">Critical only</button>' +
    '<button class="btn sm' + (params.late ? ' primary' : '') +
    '" id="fl">Late only</button>' +
    '<button class="btn sm' + (params.milestone ? ' primary' : '') +
    '" id="fm">Milestones</button>' +
    (params.wbs ? '<span class="tag blue">WBS ' + E(params.wbs) + '</span>' : '') +
    '<button class="btn sm" id="fr">Reset</button>' +
    '<div style="flex:1"></div><span class="mono" style="font-size:11.5px;' +
    'color:var(--ink-3)">' + r.returned + ' of ' + r.total + '</span></div>' +
    panel('Activities <small>' + r.total + '</small>', t) +
    (r.total > r.returned
      ? '<div class="pager"><button class="btn sm" id="prev">Previous</button>' +
        '<span>' + (r.offset + 1) + '–' + (r.offset + r.returned) + '</span>' +
        '<button class="btn sm" id="next">Next</button></div>' : '');
};

VIEWS.bind_activities = (pid, params) => {
  const set = (patch) => go('activities', Object.assign({}, params, patch,
    patch.offset === undefined ? { offset: 0 } : {}));
  const q = document.getElementById('fq');
  if (q) q.onkeydown = (e) => { if (e.key === 'Enter') set({ q: q.value }); };
  const s = document.getElementById('fs');
  if (s) s.onchange = () => set({ status: s.value });
  const c = document.getElementById('fc');
  if (c) c.onclick = () => set({ critical: params.critical ? '' : '1' });
  const l = document.getElementById('fl');
  if (l) l.onclick = () => set({ late: params.late ? '' : '1' });
  const m = document.getElementById('fm');
  if (m) m.onclick = () => set({ milestone: params.milestone ? '' : '1' });
  const r = document.getElementById('fr');
  if (r) r.onclick = () => go('activities', {});
  const nx = document.getElementById('next');
  if (nx) nx.onclick = () => set({ offset: (Number(params.offset) || 0) + 200 });
  const pv = document.getElementById('prev');
  if (pv) pv.onclick = () => set({
    offset: Math.max(0, (Number(params.offset) || 0) - 200) });
  document.querySelectorAll('th.s').forEach(th => th.onclick = () => set({
    sort: th.dataset.sort,
    direction: (params.sort === th.dataset.sort && params.direction === 'asc')
      ? 'desc' : 'asc' }));
};

/* =============================================== 5. Activity detail */
VIEWS.activity = async (pid, params) => {
  const d = await A('/projects/' + pid + '/activities/' + params.id);
  const a = d.activity;
  const relRow = (r, dir) =>
    '<tr class="click" onclick="go(\'activity\',{id:' +
    (dir === 'pred' ? r.pred_uid : r.succ_uid) + '})">' +
    '<td class="mono">' + E(dir === 'pred' ? r.pred_uid : r.succ_uid) + '</td>' +
    '<td class="trunc">' + E(dir === 'pred' ? r.pred_name : r.succ_name) + '</td>' +
    '<td><span class="tag blue">' + E(r.type) + '</span></td>' +
    '<td class="r mono">' + num(r.lag_days, 0) + 'd</td>' +
    '<td>' + (r.driving ? '<span class="tag red">driving</span>' : '') +
    '</td></tr>';

  const evGroups = Object.keys(d.evidence || {});
  const evPanel = evGroups.length
    ? evGroups.map(g => panel(
        'Evidence · ' + E(g) + ' <small>' + d.evidence[g].length + '</small>',
        table([{ t: 'Source' }, { t: 'Where' }, { t: 'Date' }, { t: 'Description' },
          { t: 'Conf', r: true }, { t: 'Validators' }, { t: 'From' }],
        d.evidence[g], l =>
          '<tr class="click" onclick="go(\'evidence-detail\',{id:\'' +
          E(l.evidence_id) + '\'})">' +
          '<td class="mono" style="font-size:11px">' + E(l.source_file) + '</td>' +
          '<td class="mono" style="font-size:11px;color:var(--ink-3)">' +
          E(l.locator) + '</td>' +
          '<td class="mono">' + day(l.date) + '</td>' +
          '<td class="trunc">' + E(l.description) + '</td>' +
          '<td class="r mono">' + num(l.confidence, 2) + '</td>' +
          '<td>' + tagFor(l.validator_result, ST) + '</td>' +
          '<td>' + prov(l.provenance) + '</td></tr>')))
      .join('')
    : panel('Evidence', empty('No field evidence linked',
        'Nothing in the uploaded documents has been associated with this ' +
        'activity yet.'));

  return '<div class="crumb"><a onclick="go(\'activities\')">Activities</a> / ' +
    'uid ' + E(a.uid) + '</div>' +
    '<div class="head"><div><div class="eyebrow">Activity ' + E(a.display_id) +
    ' · uid ' + E(a.uid) + '</div><h1>' + E(a.name) + '</h1>' +
    '<div class="sub">WBS ' + E(a.wbs) + ' · ' + E(a.status) +
    (a.critical ? ' · on the critical path' : '') + '</div></div>' +
    '<div class="spacer"></div>' + provKey() + '</div>' +

    '<div class="grid g4" style="margin-bottom:14px">' +
    stat('Official progress', num(a.percent_complete, 0) + '%',
      'from the schedule') +
    stat('Observed progress', d.observed_progress &&
      d.observed_progress.observed_percent !== null
      ? num(d.observed_progress.observed_percent, 0) + '%' : '—',
      d.observed_progress ? E(d.observed_progress.basis || '') +
        ' (' + d.observed_progress.evidence_count + ' records)'
      : 'no field evidence') +
    stat('Total float', num(a.total_float_days, 1) + 'd',
      a.critical ? 'critical' : 'has slack',
      (a.total_float_days || 0) < 0 ? 'hot' : '') +
    stat('Finish variance', num(a.finish_variance_days, 1) + 'd',
      a.baseline_finish ? 'vs baseline ' + day(a.baseline_finish) : 'no baseline',
      (a.finish_variance_days || 0) > 0 ? 'hot' : 'good') +
    '</div>' +

    '<div class="grid g2">' +
    panel('Schedule facts <small>MCP_FACT</small>',
      '<div class="body"><dl class="kv">' +
      row('Start', day(a.start)) + row('Finish', day(a.finish)) +
      row('Actual start', day(a.actual_start)) +
      row('Actual finish', day(a.actual_finish)) +
      row('Early start / finish', day(a.early_start) + ' → ' + day(a.early_finish)) +
      row('Late start / finish', day(a.late_start) + ' → ' + day(a.late_finish)) +
      row('Duration', num(a.duration_days, 1) + ' d') +
      row('Free float', num(a.free_float_days, 1) + ' d') +
      row('Calendar', E(a.calendar || '—')) +
      row('Constraint', E(a.constraint_type || '—') +
        (a.constraint_date ? ' ' + day(a.constraint_date) : '')) +
      row('Deadline', day(a.deadline)) +
      row('Resources', E(a.resource_names || '—')) +
      '</dl></div>') +
    panel('Baseline <small>variance</small>',
      '<div class="body"><dl class="kv">' +
      row('Baseline start', day(a.baseline_start)) +
      row('Baseline finish', day(a.baseline_finish)) +
      row('Start variance', num(a.start_variance_days, 1) + ' d') +
      row('Finish variance', num(a.finish_variance_days, 1) + ' d') +
      row('Duration variance', num(a.duration_variance_days, 1) + ' d') +
      '</dl>' + (a.baseline_finish ? '' :
        '<div class="note warn" style="margin-top:10px">This activity carries ' +
        'no baseline, so variance cannot be measured.</div>') + '</div>') +
    '</div>' +

    '<div class="grid g2">' +
    panel('Predecessors <small>' + d.predecessors.length + '</small>',
      table([{ t: 'UID' }, { t: 'Activity' }, { t: 'Type' }, { t: 'Lag', r: true },
        { t: '' }], d.predecessors, r => relRow(r, 'pred'),
        { emptyTitle: 'No predecessors',
          emptyMsg: 'Nothing holds this activity in place.' })) +
    panel('Successors <small>' + d.successors.length + '</small>',
      table([{ t: 'UID' }, { t: 'Activity' }, { t: 'Type' }, { t: 'Lag', r: true },
        { t: '' }], d.successors, r => relRow(r, 'succ'),
        { emptyTitle: 'No successors',
          emptyMsg: 'Nothing moves when this activity moves.' })) +
    '</div>' +

    panel('Resources and assignments <small>' + d.assignments.length + '</small>',
      table([{ t: 'Resource' }, { t: 'Units', r: true }, { t: 'Work h', r: true },
        { t: 'Actual h', r: true }, { t: 'Remaining h', r: true },
        { t: 'Cost', r: true }, { t: 'Start' }, { t: 'Finish' }],
      d.assignments, x =>
        '<tr><td>' + E(x.resource_name) + '</td>' +
        '<td class="r mono">' + num(x.units, 0) + '</td>' +
        '<td class="r mono">' + num(x.work_hours, 0) + '</td>' +
        '<td class="r mono">' + num(x.actual_work_hours, 0) + '</td>' +
        '<td class="r mono">' + num(x.remaining_work_hours, 0) + '</td>' +
        '<td class="r mono">' + num(x.cost, 0) + '</td>' +
        '<td class="mono">' + day(x.start) + '</td>' +
        '<td class="mono">' + day(x.finish) + '</td></tr>',
      { emptyTitle: 'No assignments', emptyMsg: '' })) +

    evPanel +

    (d.issues.length ? panel('Issues <small>' + d.issues.length + '</small>',
      table([{ t: 'Title' }, { t: 'Severity' }, { t: 'Status' }, { t: 'From' }],
      d.issues, i => '<tr class="click" onclick="go(\'issues\')"><td>' +
        E(i.title) + '</td><td>' + sev(i.severity) + '</td><td>' +
        tagFor(i.status, ST) + '</td><td>' + prov(i.provenance) +
        '</td></tr>')) : '') +
    (d.risks.length ? panel('Risks <small>' + d.risks.length + '</small>',
      table([{ t: 'Title' }, { t: 'Rating' }, { t: 'Status' }, { t: 'From' }],
      d.risks, i => '<tr class="click" onclick="go(\'risks\')"><td>' +
        E(i.title) + '</td><td>' + sev(i.rating) + '</td><td>' +
        tagFor(i.status, ST) + '</td><td>' + prov(i.provenance) +
        '</td></tr>')) : '') +
    (d.proposals.length ? panel('Change proposals <small>' + d.proposals.length +
      '</small>', '<div class="body">' + d.proposals.map(proposalCard).join('') +
      '</div>') : '') +
    panel('Audit <small>' + d.audit.length + '</small>', auditTable(d.audit));
};

/* ================================================ 6. Relationships */
VIEWS.relationships = async (pid, params) => {
  const r = await A('/projects/' + pid + '/relationships?' +
    new URLSearchParams({ type: params.type || '', driving: params.driving || '',
      q: params.q || '', limit: 500 }));
  const types = ['FS', 'SS', 'FF', 'SF'];
  return head('Relationships', 'Dependency network', prov('MCP_FACT')) +
    '<div class="grid g4" style="margin-bottom:14px">' +
    types.map(t => stat(t, int(r.by_type[t] || 0),
      t === 'FS' ? 'finish to start' : t === 'SS' ? 'start to start'
        : t === 'FF' ? 'finish to finish' : 'start to finish')).join('') +
    '</div>' +
    '<div class="grid g2" style="margin-bottom:14px">' +
    panel('Missing predecessor <small>' + r.missing_predecessor.length + '</small>',
      table([{ t: 'UID' }, { t: 'Activity' }], r.missing_predecessor, x =>
        '<tr class="click" onclick="go(\'activity\',{id:' + x.uid + '})">' +
        '<td class="mono">' + E(x.uid) + '</td><td>' + E(x.name) + '</td></tr>',
        { emptyTitle: 'Every activity has a predecessor', emptyMsg: '' })) +
    panel('Missing successor <small>' + r.missing_successor.length + '</small>',
      table([{ t: 'UID' }, { t: 'Activity' }], r.missing_successor, x =>
        '<tr class="click" onclick="go(\'activity\',{id:' + x.uid + '})">' +
        '<td class="mono">' + E(x.uid) + '</td><td>' + E(x.name) + '</td></tr>',
        { emptyTitle: 'Every activity has a successor', emptyMsg: '' })) +
    '</div>' +
    '<div class="toolbar">' +
    '<select class="inp" id="rt"><option value="">All types</option>' +
    types.map(t => '<option ' + (params.type === t ? 'selected' : '') + '>' + t +
      '</option>').join('') + '</select>' +
    '<button class="btn sm' + (params.driving ? ' primary' : '') +
    '" id="rd">Driving only</button>' +
    '<input class="inp" id="rq" placeholder="Search activity name" value="' +
    E(params.q || '') + '"></div>' +
    panel('Links <small>' + r.total + '</small>',
      table([{ t: 'Pred UID' }, { t: 'Predecessor' }, { t: 'Type' },
        { t: 'Lag', r: true }, { t: 'Succ UID' }, { t: 'Successor' },
        { t: 'Driving' }], r.relationships, x =>
        '<tr><td class="mono link" onclick="go(\'activity\',{id:' + x.pred_uid +
        '})">' + E(x.pred_uid) + '</td><td class="trunc">' + E(x.pred_name) +
        '</td><td><span class="tag blue">' + E(x.type) + '</span></td>' +
        '<td class="r mono">' + num(x.lag_days, 0) + 'd</td>' +
        '<td class="mono link" onclick="go(\'activity\',{id:' + x.succ_uid +
        '})">' + E(x.succ_uid) + '</td><td class="trunc">' + E(x.succ_name) +
        '</td><td>' + (x.driving ? '<span class="tag red">driving</span>' : '') +
        '</td></tr>'));
};
VIEWS.bind_relationships = (pid, params) => {
  const t = document.getElementById('rt');
  if (t) t.onchange = () => go('relationships',
    Object.assign({}, params, { type: t.value }));
  const d = document.getElementById('rd');
  if (d) d.onclick = () => go('relationships',
    Object.assign({}, params, { driving: params.driving ? '' : '1' }));
  const q = document.getElementById('rq');
  if (q) q.onkeydown = (e) => { if (e.key === 'Enter')
    go('relationships', Object.assign({}, params, { q: q.value })); };
};

/* ================================================ 7. Critical path */
VIEWS.critical = async (pid) => {
  const r = await A('/projects/' + pid + '/critical-path');
  const fd = r.float_distribution || {};
  return head('Critical path', 'Driving work and float distribution',
    prov('MCP_FACT')) +
    '<div class="note mcp" style="margin-bottom:14px">' + E(r.basis) +
    '. VEDA does not run its own CPM engine.</div>' +
    '<div class="grid g3" style="margin-bottom:14px">' +
    stat('Critical activities', int(r.critical.length), 'zero or negative float',
      'warm') +
    stat('Negative float', int(fd.negative || 0), 'cannot meet constraints',
      fd.negative ? 'hot' : 'good') +
    stat('Project finish', day(r.finish), 'forecast') +
    '</div>' +
    panel('Float distribution',
      '<div class="body"><dl class="kv">' +
      [['negative', 'Negative float'], ['zero', 'Zero float'],
       ['upTo5', 'Up to 5 days'], ['upTo20', 'Up to 20 days'],
       ['upTo44', 'Up to 44 days'], ['over44', 'Over 44 days']]
      .map(([k, l]) => row(l, '<span class="mono">' + int(fd[k] || 0) +
        '</span>')).join('') + '</dl></div>') +
    panel('Critical activities <small>' + r.critical.length + '</small>',
      table([{ t: 'UID' }, { t: 'Activity' }, { t: 'WBS' }, { t: 'Start' },
        { t: 'Finish' }, { t: 'Float', r: true }, { t: 'Progress', r: true }],
      r.critical, a =>
        '<tr class="click crit" onclick="go(\'activity\',{id:' + a.uid + '})">' +
        '<td class="mono">' + E(a.uid) + '</td><td class="trunc">' + E(a.name) +
        '</td><td class="mono">' + E(a.wbs) + '</td>' +
        '<td class="mono">' + day(a.start) + '</td>' +
        '<td class="mono">' + day(a.finish) + '</td>' +
        '<td class="r mono ' + ((a.total_float_days || 0) < 0 ? 'sev-critical' : '') +
        '">' + num(a.total_float_days, 1) + '</td>' +
        '<td class="r mono">' + num(a.percent_complete, 0) + '%</td></tr>',
      { emptyTitle: 'No critical activities', emptyMsg: '' })) +
    (r.driving_links.length ? panel('Driving links <small>' +
      r.driving_links.length + '</small>',
      table([{ t: 'Predecessor' }, { t: 'Type' }, { t: 'Successor' }],
      r.driving_links, x => '<tr><td class="trunc">' + E(x.pred_name) +
        '</td><td><span class="tag red">' + E(x.type) + '</span></td>' +
        '<td class="trunc">' + E(x.succ_name) + '</td></tr>')) : '');
};

/* ============================================== 8. Schedule quality */
VIEWS.quality = async (pid) => {
  const r = await A('/projects/' + pid + '/quality');
  const s = r.summary || {};
  return head('Schedule quality', 'DCMA 14-point and Horizun rules',
    prov('MCP_FACT')) +
    '<div class="grid g4" style="margin-bottom:14px">' +
    stat('Health', num(r.health_score, 1) + '%', 'checks passed',
      r.health_score < 60 ? 'hot' : 'good') +
    stat('Passed', int(s.passed), '', 'good') +
    stat('Failed', int(s.failed), '', s.failed ? 'hot' : '') +
    stat('Not evaluated', int(s.notEvaluated),
      'reported honestly, never passed') +
    '</div>' +
    '<div class="note mcp" style="margin-bottom:14px">' + E(r.basis) + '</div>' +
    panel('Findings <small>' + r.findings.length + '</small>',
      '<div class="body">' + (r.findings.length ? r.findings.map(f =>
      '<div class="check"><span class="m ' +
      (f.status === 'pass' ? 'pass' : f.status === 'fail' ? 'fail' : 'warn') +
      '">' + E(f.status === 'not_evaluated' ? 'n/e' : f.status) + '</span>' +
      '<span class="n">' + E(f.code) + '</span>' +
      '<span style="flex:1">' + E(f.title) + ' — ' + E(f.detail || '') +
      (f.task_uids && f.task_uids.length
        ? '<br><span class="mono" style="font-size:11px;color:var(--ink-3)">' +
          'affects uid ' + f.task_uids.slice(0, 24).map(E).join(', ') +
          (f.task_uids.length > 24 ? ' …' : '') + '</span>' : '') +
      '</span><span class="sev-' + E(String(f.severity || '').toLowerCase()) +
      '" style="font-family:var(--mono);font-size:11px">' + E(f.severity || '') +
      '</span></div>').join('')
      : empty('No quality findings', 'Analyse a schedule first.')) + '</div>');
};

/* ==================================================== 9. Baselines */
VIEWS.baselines = async (pid) => {
  const r = await A('/projects/' + pid + '/baselines');
  if (!r.baseline_present) {
    return head('Baselines', 'Plan versus current') +
      panel('Baseline', '<div class="body"><div class="note warn">' +
        E(r.message) + '</div></div>');
  }
  return head('Baselines', 'Plan versus current', prov('MCP_FACT')) +
    '<div class="grid g3" style="margin-bottom:14px">' +
    stat('Baseline finish', day(r.baseline_finish), 'as planned') +
    stat('Missed activities', int(r.missed_count), 'finishing after baseline',
      r.missed_count ? 'hot' : 'good') +
    stat('Measured', int(r.activities.length), 'activities with a baseline') +
    '</div>' +
    panel('Variance <small>worst first</small>',
      table([{ t: 'UID' }, { t: 'Activity' }, { t: 'Baseline start' },
        { t: 'Start' }, { t: 'Baseline finish' }, { t: 'Finish' },
        { t: 'Start var', r: true }, { t: 'Finish var', r: true },
        { t: 'Dur var', r: true }], r.activities, a =>
        '<tr class="click" onclick="go(\'activity\',{id:' + a.uid + '})">' +
        '<td class="mono">' + E(a.uid) + '</td><td class="trunc">' + E(a.name) +
        '</td><td class="mono">' + day(a.baseline_start) + '</td>' +
        '<td class="mono">' + day(a.start) + '</td>' +
        '<td class="mono">' + day(a.baseline_finish) + '</td>' +
        '<td class="mono">' + day(a.finish) + '</td>' +
        '<td class="r mono">' + num(a.start_variance_days, 1) + '</td>' +
        '<td class="r mono ' + ((a.finish_variance_days || 0) > 0
          ? 'sev-critical' : 'sev-low') + '">' +
        num(a.finish_variance_days, 1) + '</td>' +
        '<td class="r mono">' + num(a.duration_variance_days, 1) + '</td></tr>'));
};

/* ==================================================== 10. Resources */
VIEWS.resources = async (pid) => {
  const r = await A('/projects/' + pid + '/resources');
  return head('Resources', 'Availability and overallocation', prov('MCP_FACT')) +
    panel('Resources <small>' + r.resources.length + '</small>',
      table([{ t: 'UID' }, { t: 'Name' }, { t: 'Type' }, { t: 'Max units', r: true },
        { t: 'Rate', r: true }, { t: 'Work h', r: true }, { t: 'Cost', r: true },
        { t: 'Activities', r: true }, { t: 'Overallocated' }],
      r.resources, x =>
        '<tr class="click" onclick="go(\'assignments\',{resource:' + x.uid + '})">' +
        '<td class="mono">' + E(x.uid) + '</td><td>' + E(x.name) + '</td>' +
        '<td>' + tagFor(x.type, ST) + '</td>' +
        '<td class="r mono">' + num(x.max_units, 0) + '</td>' +
        '<td class="r mono">' + num(x.standard_rate, 0) + '</td>' +
        '<td class="r mono">' + num(x.work_hours, 0) + '</td>' +
        '<td class="r mono">' + num(x.cost, 0) + '</td>' +
        '<td class="r mono">' + int(x.assigned_activities) + '</td>' +
        '<td>' + (x.overallocated
          ? '<span class="tag red">' + int(x.overallocated_days) +
            ' days over</span>' : '<span class="tag green">ok</span>') +
        '</td></tr>',
      { emptyTitle: 'No resources', emptyMsg: 'This schedule carries none.' }));
};

VIEWS.assignments = async (pid, params) => {
  const r = await A('/projects/' + pid + '/assignments?' +
    new URLSearchParams(params.resource ? { resource_uid: params.resource } : {}));
  return head('Assignments', 'Resource to activity', prov('MCP_FACT')) +
    (params.resource ? '<div class="crumb"><a onclick="go(\'resources\')">' +
      'Resources</a> / filtered to resource uid ' + E(params.resource) +
      '</div>' : '') +
    panel('Assignments <small>' + r.assignments.length + '</small>',
      table([{ t: 'Resource' }, { t: 'Activity' }, { t: 'UID' },
        { t: 'Units', r: true }, { t: 'Work h', r: true },
        { t: 'Actual h', r: true }, { t: 'Remaining h', r: true },
        { t: 'Cost', r: true }, { t: 'Start' }, { t: 'Finish' }],
      r.assignments, x =>
        '<tr><td>' + E(x.resource_name) + '</td>' +
        '<td class="trunc link" onclick="go(\'activity\',{id:' + x.task_uid +
        '})">' + E(x.task_name) + '</td>' +
        '<td class="mono">' + E(x.task_uid) + '</td>' +
        '<td class="r mono">' + num(x.units, 0) + '</td>' +
        '<td class="r mono">' + num(x.work_hours, 0) + '</td>' +
        '<td class="r mono">' + num(x.actual_work_hours, 0) + '</td>' +
        '<td class="r mono">' + num(x.remaining_work_hours, 0) + '</td>' +
        '<td class="r mono">' + num(x.cost, 0) + '</td>' +
        '<td class="mono">' + day(x.start) + '</td>' +
        '<td class="mono">' + day(x.finish) + '</td></tr>',
      { emptyTitle: 'No assignments', emptyMsg: '' }));
};

/* =================================================== 11. Timephased */
VIEWS.timephased = async (pid) => {
  const r = await A('/projects/' + pid + '/timephased');
  if (!r.available) {
    return head('Timephased', 'Period distribution') +
      panel('Timephased', '<div class="body"><div class="note warn">' +
        E(r.message) + '</div></div>');
  }
  return head('Timephased', 'Distribution over time', prov('MCP_FACT')) +
    panel('S-curve <small>' + E(r.measure) + ' by ' + E(r.granularity) + '</small>',
      '<div class="body">' + sCurve(r.series) + '</div>') +
    panel('Periods <small>' + r.series.length + '</small>',
      table([{ t: 'Period' }, { t: 'Value', r: true }, { t: 'Cumulative', r: true }],
      r.series, s => '<tr><td class="mono">' + day(s.period) + '</td>' +
        '<td class="r mono">' + num(s.value, 2) + '</td>' +
        '<td class="r mono">' + num(s.cumulative, 2) + '</td></tr>'));
};

function sCurve(series) {
  if (!series.length) return empty('No data', '');
  const W = 900, H = 190, pad = 34;
  const cum = series.map(s => Number(s.cumulative) || 0);
  const per = series.map(s => Number(s.value) || 0);
  const maxC = Math.max.apply(null, cum) || 1;
  const maxP = Math.max.apply(null, per) || 1;
  const x = (i) => pad + i * (W - pad * 2) / Math.max(1, series.length - 1);
  const yC = (v) => H - 22 - (v / maxC) * (H - 46);
  const bw = Math.max(3, (W - pad * 2) / series.length - 5);
  const bars = series.map((s, i) =>
    '<rect x="' + (x(i) - bw / 2) + '" y="' +
    (H - 22 - (per[i] / maxP) * (H - 60)) + '" width="' + bw + '" height="' +
    ((per[i] / maxP) * (H - 60)) + '" fill="#1F5D6E" opacity=".55"/>').join('');
  const line = series.map((s, i) => (i ? 'L' : 'M') + x(i) + ' ' + yC(cum[i]))
    .join(' ');
  const labels = series.map((s, i) => (i % Math.ceil(series.length / 8) === 0)
    ? '<text class="axis" x="' + x(i) + '" y="' + (H - 7) +
      '" text-anchor="middle">' + E(String(s.period).slice(0, 7)) + '</text>' : '')
    .join('');
  return '<svg class="chart" viewBox="0 0 ' + W + ' ' + H +
    '" preserveAspectRatio="none">' +
    [0, .25, .5, .75, 1].map(f => '<line class="grid-l" x1="' + pad + '" x2="' +
      (W - pad) + '" y1="' + yC(maxC * f) + '" y2="' + yC(maxC * f) + '"/>').join('') +
    bars +
    '<path d="' + line + '" fill="none" stroke="#45C8E8" stroke-width="2"/>' +
    series.map((s, i) => '<circle cx="' + x(i) + '" cy="' + yC(cum[i]) +
      '" r="2.5" fill="#45C8E8"/>').join('') +
    labels + '</svg>' +
    '<div class="key" style="margin-top:8px"><span class="lbl">Cumulative</span>' +
    '<span class="tag blue">line</span><span class="lbl">Per period</span>' +
    '<span class="tag grey">bars</span></div>';
}

/* ================================================= 12. Earned value */
VIEWS.ev = async (pid) => {
  const r = await A('/projects/' + pid + '/earned-value');
  if (!r.available) {
    return head('Earned value', 'Performance against baseline') +
      panel('Earned value', '<div class="body"><div class="note warn">' +
        E(r.message) + '</div></div>');
  }
  const p = r.project || {};
  return head('Earned value', 'Performance against baseline', prov('MCP_FACT')) +
    '<div class="grid g4" style="margin-bottom:14px">' +
    stat('SPI', num(p.spi, 3), 'schedule performance',
      p.spi < 0.95 ? 'hot' : p.spi < 1 ? 'warm' : 'good') +
    stat('CPI', num(p.cpi, 3), 'cost performance',
      p.cpi < 0.95 ? 'hot' : 'good') +
    stat('Schedule variance', num(p.sv, 2), 'EV minus PV',
      (p.sv || 0) < 0 ? 'hot' : 'good') +
    stat('EAC', num(p.eac, 2), 'estimate at completion') +
    '</div>' +
    panel('Project totals', '<div class="body"><dl class="kv">' +
      row('PV / BCWS', num(p.pv, 2)) + row('EV / BCWP', num(p.ev, 2)) +
      row('AC / ACWP', num(p.ac, 2)) + row('BAC', num(p.bac, 2)) +
      row('SV', num(p.sv, 2)) + row('CV', num(p.cv, 2)) +
      row('TCPI', num(p.tcpi, 3)) + row('Status date', day(p.status_date)) +
      '</dl><div class="note mcp" style="margin-top:10px">Basis: ' +
      E(p.basis || '') + '</div></div>') +
    panel('By WBS branch <small>' + r.branches.length + '</small>',
      table([{ t: 'Branch' }, { t: 'PV', r: true }, { t: 'EV', r: true },
        { t: 'AC', r: true }, { t: 'SV', r: true }, { t: 'SPI', r: true },
        { t: 'CPI', r: true }, { t: 'EAC', r: true }], r.branches, b =>
        '<tr><td>' + E(b.scope_key) + '</td>' +
        '<td class="r mono">' + num(b.pv, 1) + '</td>' +
        '<td class="r mono">' + num(b.ev, 1) + '</td>' +
        '<td class="r mono">' + num(b.ac, 1) + '</td>' +
        '<td class="r mono ' + ((b.sv || 0) < 0 ? 'sev-high' : '') + '">' +
        num(b.sv, 1) + '</td>' +
        '<td class="r mono ' + ((b.spi || 1) < 1 ? 'sev-high' : '') + '">' +
        num(b.spi, 3) + '</td>' +
        '<td class="r mono">' + num(b.cpi, 3) + '</td>' +
        '<td class="r mono">' + num(b.eac, 1) + '</td></tr>'));
};

/* =================================================== 13. Milestones */
VIEWS.milestones = async (pid) => {
  const r = await A('/projects/' + pid + '/milestones');
  return head('Milestones', 'Dates that matter', prov('MCP_FACT')) +
    panel('Milestones <small>' + r.milestones.length + '</small>',
      table([{ t: 'UID' }, { t: 'Milestone' }, { t: 'Planned' }, { t: 'Baseline' },
        { t: 'Forecast' }, { t: 'Actual' }, { t: 'Variance', r: true },
        { t: 'Float', r: true }, { t: 'Status' }, { t: 'Critical' }],
      r.milestones, m =>
        '<tr class="click" onclick="go(\'activity\',{id:' + m.uid + '})">' +
        '<td class="mono">' + E(m.uid) + '</td><td>' + E(m.name) + '</td>' +
        '<td class="mono">' + day(m.planned_date) + '</td>' +
        '<td class="mono">' + day(m.baseline_date) + '</td>' +
        '<td class="mono">' + day(m.forecast_date) + '</td>' +
        '<td class="mono">' + day(m.actual_date) + '</td>' +
        '<td class="r mono ' + ((m.variance_days || 0) > 0 ? 'sev-critical' : '') +
        '">' + num(m.variance_days, 1) + '</td>' +
        '<td class="r mono">' + num(m.total_float_days, 0) + '</td>' +
        '<td>' + tagFor(m.status, ST) + '</td>' +
        '<td>' + (m.critical ? '<span class="tag red">CP</span>' : '') +
        '</td></tr>',
      { emptyTitle: 'No milestones', emptyMsg: '' }));
};

/* ================================================= 14. Issues/Risks */
VIEWS.issues = async (pid) => {
  const r = await A('/projects/' + pid + '/issues');
  return head('Issues', 'Problems that already exist',
    '<span class="tag grey">Issue = happening now</span>') +
    panel('Issues <small>' + r.issues.length + '</small>',
      '<div class="body">' + (r.issues.length ? r.issues.map(i =>
      '<div class="review"><div class="h">' +
      '<h3>' + sev(i.severity) + ' · ' + E(i.title) + '</h3>' +
      '<div style="display:flex;gap:7px;align-items:center;flex-wrap:wrap">' +
      tagFor(i.status, ST) + prov(i.provenance) +
      (i.ref ? '<span class="tag grey">' + E(i.ref) + '</span>' : '') +
      (i.date ? '<span class="mono" style="font-size:11px;color:var(--ink-3)">' +
        day(i.date) + '</span>' : '') +
      (i.schedule_impact_days
        ? '<span class="tag red">' + num(i.schedule_impact_days, 0) +
          'd impact</span>' : '') +
      '<div style="flex:1"></div>' +
      '<button class="btn sm" data-issue="' + E(i.id) + '" data-st="closed">' +
      'Close</button></div></div>' +
      '<div class="q">' + E(i.description) + '</div>' +
      '<div class="samples"><dl class="kv">' +
      (i.source ? row('Source', E(i.source)) : '') +
      (i.owner ? row('Owner', E(i.owner)) : '') +
      (i.activity_uids.length ? row('Activities', i.activity_uids.map(u =>
        '<span class="link mono" onclick="go(\'activity\',{id:' + u + '})">' +
        E(u) + '</span>').join(', ')) : '') +
      (i.evidence_ids.length ? row('Evidence', i.evidence_ids.map(x =>
        '<span class="link mono" onclick="go(\'evidence-detail\',{id:\'' + E(x) +
        '\'})">' + E(String(x).slice(0, 8)) + '</span>').join(', ')) : '') +
      row('Confidence', num(i.confidence, 2)) +
      '</dl></div></div>').join('')
      : empty('No issues recorded',
        'Run an analysis and VEDA will record what the documents report.')) +
      '</div>');
};
VIEWS.bind_issues = (pid) => {
  document.querySelectorAll('[data-issue]').forEach(b => b.onclick = async () => {
    await P('/projects/' + pid + '/issues/' + b.dataset.issue + '/status',
      { status: b.dataset.st });
    window.toast('Issue closed', 'good'); window.render();
  });
};

VIEWS.risks = async (pid) => {
  const r = await A('/projects/' + pid + '/risks');
  return head('Risks', 'Possible future events',
    '<span class="tag grey">Risk = might happen</span>') +
    panel('Risks <small>' + r.risks.length + '</small>',
      '<div class="body">' + (r.risks.length ? r.risks.map(i =>
      '<div class="review"><div class="h">' +
      '<h3>' + sev(i.rating) + ' · ' + E(i.title) + '</h3>' +
      '<div style="display:flex;gap:7px;align-items:center;flex-wrap:wrap">' +
      tagFor(i.status, ST) + prov(i.provenance) +
      '<span class="tag grey">P ' + E(i.probability) + '</span>' +
      '<span class="tag grey">I ' + E(i.impact) + '</span>' +
      (i.category ? '<span class="tag blue">' + E(i.category) + '</span>' : '') +
      (i.critical_path_relevance
        ? '<span class="tag red">critical path</span>' : '') +
      '<div style="flex:1"></div>' +
      '<button class="btn sm" data-risk="' + E(i.id) + '" data-st="closed">' +
      'Close</button></div></div>' +
      '<div class="q">' + E(i.description) + '</div>' +
      '<div class="samples"><dl class="kv">' +
      (i.mitigation ? row('Mitigation', E(i.mitigation)) : '') +
      (i.trigger ? row('Trigger', E(i.trigger)) : '') +
      (i.critical_path_relevance
        ? row('Critical path', E(i.critical_path_relevance)) : '') +
      (i.schedule_impact_days
        ? row('Schedule impact', num(i.schedule_impact_days, 0) + ' d') : '') +
      (i.activity_uids.length ? row('Activities', i.activity_uids.map(u =>
        '<span class="link mono" onclick="go(\'activity\',{id:' + u + '})">' +
        E(u) + '</span>').join(', ')) : '') +
      row('Confidence', num(i.confidence, 2)) +
      '</dl></div></div>').join('')
      : empty('No risks recorded', '')) + '</div>');
};
VIEWS.bind_risks = (pid) => {
  document.querySelectorAll('[data-risk]').forEach(b => b.onclick = async () => {
    await P('/projects/' + pid + '/risks/' + b.dataset.risk + '/status',
      { status: b.dataset.st });
    window.toast('Risk closed', 'good'); window.render();
  });
};

/* ================================================== 15. Evidence */
VIEWS.evidence = async (pid, params) => {
  const r = await A('/projects/' + pid + '/evidence?' + new URLSearchParams({
    state: params.state || '', q: params.q || '',
    discipline: params.discipline || '', source: params.source || '',
    limit: 150, offset: params.offset || 0 }));
  const sc = r.state_counts || {};
  return head('Field evidence', 'What the documents report',
    prov('SOURCE_FILE')) +
    '<div class="toolbar">' +
    '<input class="inp" id="eq" placeholder="Search description, crew, chainage" ' +
    'value="' + E(params.q || '') + '">' +
    '<select class="inp" id="es"><option value="">Any state</option>' +
    Object.keys(sc).map(s => '<option value="' + E(s) + '" ' +
      (params.state === s ? 'selected' : '') + '>' + E(s) + ' (' + sc[s] +
      ')</option>').join('') + '</select>' +
    '<select class="inp" id="ed"><option value="">Any discipline</option>' +
    r.disciplines.map(d => '<option ' +
      (params.discipline === d ? 'selected' : '') + '>' + E(d) + '</option>')
      .join('') + '</select>' +
    '<select class="inp" id="ef"><option value="">Any source</option>' +
    r.sources.map(d => '<option ' + (params.source === d ? 'selected' : '') + '>' +
      E(d) + '</option>').join('') + '</select>' +
    '<button class="btn sm" id="er">Reset</button>' +
    '<div style="flex:1"></div><span class="mono" style="font-size:11.5px;' +
    'color:var(--ink-3)">' + r.evidence.length + ' of ' + r.total + '</span></div>' +
    panel('Evidence <small>' + r.total + '</small>',
      table([{ t: 'Date' }, { t: 'Source' }, { t: 'Where' }, { t: 'Discipline' },
        { t: 'Crew' }, { t: 'Location' }, { t: 'Qty', r: true },
        { t: 'Description' }, { t: 'State' }, { t: 'Linked to' }, { t: 'Check' }],
      r.evidence, e =>
        '<tr class="click" onclick="go(\'evidence-detail\',{id:\'' + E(e.id) +
        '\'})"><td class="mono">' + day(e.date) + '</td>' +
        '<td class="mono" style="font-size:11px">' + E(e.source_file) + '</td>' +
        '<td class="mono" style="font-size:11px;color:var(--ink-3)">' +
        E(e.locator) + '</td>' +
        '<td>' + E(e.discipline || '—') + '</td>' +
        '<td class="mono">' + E(e.crew || '—') + '</td>' +
        '<td>' + E(e.location || e.chainage || '—') + '</td>' +
        '<td class="r mono">' + (e.quantity !== null && e.quantity !== undefined
          ? num(e.quantity, 0) + ' ' + E(e.unit || '') : '—') + '</td>' +
        '<td class="trunc" style="max-width:340px">' + E(e.description) + '</td>' +
        '<td>' + tagFor(e.state, ST) + '</td>' +
        '<td class="trunc" style="max-width:190px">' +
        (e.linked_activity_name
          ? '<span class="mono" style="font-size:11px">' +
            E(e.linked_activity_name) + '</span>' : '—') +
        (e.candidate_count ? ' <span class="tag amber">' + e.candidate_count +
          ' alt</span>' : '') + '</td>' +
        '<td>' + tagFor(e.validator_result, ST) + '</td></tr>',
      { emptyTitle: 'No evidence yet',
        emptyMsg: 'Upload DPRs, registers or reports.' })) +
    (r.total > r.evidence.length
      ? '<div class="pager"><button class="btn sm" id="eprev">Previous</button>' +
        '<span>' + (r.offset + 1) + '–' + (r.offset + r.evidence.length) +
        '</span><button class="btn sm" id="enext">Next</button></div>' : '');
};
VIEWS.bind_evidence = (pid, params) => {
  const set = (p) => go('evidence', Object.assign({}, params, p,
    p.offset === undefined ? { offset: 0 } : {}));
  const q = document.getElementById('eq');
  if (q) q.onkeydown = (e) => { if (e.key === 'Enter') set({ q: q.value }); };
  ['es:state', 'ed:discipline', 'ef:source'].forEach(pair => {
    const [id, key] = pair.split(':');
    const el = document.getElementById(id);
    if (el) el.onchange = () => set({ [key]: el.value });
  });
  const r = document.getElementById('er');
  if (r) r.onclick = () => go('evidence', {});
  const n = document.getElementById('enext');
  if (n) n.onclick = () => set({ offset: (Number(params.offset) || 0) + 150 });
  const p = document.getElementById('eprev');
  if (p) p.onclick = () => set({
    offset: Math.max(0, (Number(params.offset) || 0) - 150) });
};

VIEWS['evidence-detail'] = async (pid, params) => {
  const d = await A('/projects/' + pid + '/evidence/' + params.id);
  const e = d.evidence;
  const linkCard = (l) =>
    '<div class="review"><div class="h" style="display:flex;gap:9px;' +
    'align-items:center;flex-wrap:wrap">' +
    '<b>' + E(l.activity_name || ('uid ' + l.activity_uid)) + '</b>' +
    tagFor(l.relation, ST) +
    '<span class="tag grey">confidence ' + num(l.confidence, 2) + '</span>' +
    tagFor(l.validator_result, ST) + prov(l.provenance) +
    (l.human_decision ? '<span class="tag green">human: ' +
      E(l.human_decision) + '</span>' : '') +
    '<div style="flex:1"></div>' +
    (l.is_candidate ? '<button class="btn sm primary" data-accept="' +
      E(l.activity_uid) + '">Accept this link</button>' : '') +
    '</div><div class="samples" style="padding-top:12px">' +
    (l.supporting_signals.length
      ? '<div style="margin-bottom:6px"><span class="tag green">supporting</span> ' +
        l.supporting_signals.map(s => E(s)).join(' · ') + '</div>' : '') +
    (l.conflicting_signals.length
      ? '<div style="margin-bottom:6px"><span class="tag red">conflicting</span> ' +
        l.conflicting_signals.map(s => E(s)).join(' · ') + '</div>' : '') +
    ((l.validator && l.validator.checks)
      ? '<div style="margin-top:8px">' + l.validator.checks.map(c =>
        '<div class="check"><span class="m ' + E(c.result) + '">' + E(c.result) +
        '</span><span class="n">' + E(c.name) + '</span><span style="flex:1">' +
        E(c.message) + '</span></div>').join('') + '</div>' : '') +
    '</div></div>';

  return '<div class="crumb"><a onclick="go(\'evidence\')">Field evidence</a> / ' +
    E(String(e.id).slice(0, 10)) + '</div>' +
    '<div class="head"><div><div class="eyebrow">Evidence · ' +
    E(e.source_file) + ' · ' + E(e.locator) + '</div>' +
    '<h1 style="font-size:17px;font-weight:500;max-width:900px">' +
    E(e.description) + '</h1></div><div class="spacer"></div>' +
    prov(e.provenance) + '</div>' +

    '<div class="grid g2">' +
    panel('Record', '<div class="body"><dl class="kv">' +
      row('Date', day(e.date)) + row('Author', E(e.author || '—')) +
      row('Contractor', E(e.contractor || '—')) + row('Crew', E(e.crew || '—')) +
      row('Discipline', E(e.discipline || '—')) +
      row('Location', E(e.location || '—')) +
      row('Chainage', E(e.chainage || '—')) +
      row('Quantity', e.quantity !== null && e.quantity !== undefined
        ? num(e.quantity, 1) + ' ' + E(e.unit || '') : '—') +
      row('Observed progress', e.observed_progress !== null &&
        e.observed_progress !== undefined
        ? '<b style="color:var(--human)">' + num(e.observed_progress, 1) +
          '%</b> <span style="color:var(--ink-3);font-size:11.5px">' +
          '(observation only, never official progress)</span>' : '—') +
      row('State', tagFor(e.state, ST)) +
      row('Confidence', num(e.confidence, 2)) +
      '</dl></div>') +
    panel('Source document', d.source
      ? '<div class="body"><dl class="kv">' +
        row('File', E(d.source.filename)) +
        row('Type', E(d.source.ext)) +
        row('SHA-256', '<span class="mono" style="font-size:10.5px;' +
          'word-break:break-all">' + E(d.source.sha256) + '</span>') +
        row('Security', tagFor(d.source.security_state, ST)) +
        '</dl>' + (d.source.security_notes
          ? '<div class="note danger" style="margin-top:10px">' +
            E(d.source.security_notes) + '</div>' : '') +
        '<div style="margin-top:10px"><button class="btn sm" ' +
        'onclick="go(\'files\')">View files</button></div></div>'
      : '<div class="body">' + empty('No source file', '') + '</div>') +
    '</div>' +

    '<div class="eyebrow" style="margin-top:6px">Accepted association</div>' +
    (d.primary ? linkCard(d.primary)
      : panel('', empty('Not linked to any activity',
        'Either the signals were too weak or a human answer is still needed.'))) +
    (d.alternatives.length
      ? '<div class="eyebrow" style="margin-top:14px">Alternatives considered ' +
        '(contradictions are never hidden)</div>' +
        d.alternatives.map(linkCard).join('') : '') +

    panel('Decision', '<div class="body">' +
      '<div class="key" style="margin-bottom:10px"><span class="lbl">Set state' +
      '</span>' + ['confirmed', 'rejected', 'duplicate', 'conflicting',
        'historical', 'needs_review'].map(s =>
        '<button class="btn sm" data-dec="' + s + '">' + s + '</button>').join('') +
      '</div><div class="note">Marking evidence does not change the schedule. ' +
      'Identity is not permission to mutate: a change to the plan goes through ' +
      'a proposal, a dry-run and an approval.</div></div>') +
    '<div class="body" style="padding:0"></div>' +
    '<div id="rawwrap">' + panel('Raw record',
      '<div class="body"><pre class="mono" style="margin:0;white-space:pre-wrap;' +
      'font-size:11.5px;color:var(--ink-2)">' +
      E(JSON.stringify(e.raw, null, 1)) + '</pre></div>') + '</div>';
};
VIEWS['bind_evidence-detail'] = (pid, params) => {
  document.querySelectorAll('[data-dec]').forEach(b => b.onclick = async () => {
    await P('/projects/' + pid + '/evidence/' + params.id + '/decision',
      { decision: b.dataset.dec });
    window.toast('Evidence marked ' + b.dataset.dec, 'good'); window.render();
  });
  document.querySelectorAll('[data-accept]').forEach(b => b.onclick = async () => {
    await P('/projects/' + pid + '/evidence/' + params.id + '/decision',
      { decision: 'accept_link', activity_uid: Number(b.dataset.accept) });
    window.toast('Link accepted and recorded as human input', 'good');
    window.render();
  });
};

/* ============================================ 16. Review evidence */
VIEWS['review-evidence'] = async (pid) =>
  (await VIEWS.evidence(pid, { state: 'needs_review' }))
    .replace('Field evidence', 'Review evidence')
    .replace('What the documents report',
             'Records VEDA could not associate with confidence');
VIEWS['bind_review-evidence'] = (pid) =>
  VIEWS.bind_evidence(pid, { state: 'needs_review' });

/* ============================================ 17. Observed progress */
VIEWS.observed = async (pid) => {
  const r = await A('/projects/' + pid + '/observed-progress');
  return head('Observed progress', 'Field reports beside the schedule') +
    '<div class="note warn" style="margin-bottom:14px">' + E(r.note) + '</div>' +
    panel('Comparison <small>' + r.rows.length + '</small>',
      table([{ t: 'UID' }, { t: 'Activity' }, { t: 'Official' },
        { t: 'Observed' }, { t: 'Delta', r: true }, { t: 'Records', r: true },
        { t: 'As of' }, { t: 'Basis' }], r.rows, x =>
        '<tr class="click" onclick="go(\'activity\',{id:' + x.activity_uid +
        '})"><td class="mono">' + E(x.activity_uid) + '</td>' +
        '<td class="trunc">' + E(x.name) + '</td>' +
        '<td style="min-width:124px"><div class="pcell">' +
        bar(x.official_percent) + '<span class="mono pct">' +
        num(x.official_percent, 0) + '%</span></div></td>' +
        '<td style="min-width:124px">' + (x.observed_percent !== null &&
          x.observed_percent !== undefined
          ? '<div class="pcell">' + bar(x.observed_percent, 'obs') +
            '<span class="mono pct" style="color:var(--human)">' +
            num(x.observed_percent, 0) + '%</span></div>'
          : '<span style="color:var(--ink-3)">not stated</span>') + '</td>' +
        '<td class="r mono ' + ((x.delta || 0) < 0 ? 'sev-high' : '') + '">' +
        (x.delta === null || x.delta === undefined ? '—' : num(x.delta, 1)) +
        '</td>' +
        '<td class="r mono">' + int(x.evidence_count) + '</td>' +
        '<td class="mono">' + day(x.as_of) + '</td>' +
        '<td class="trunc" style="max-width:330px;color:var(--ink-3);' +
        'font-size:11.5px">' + E(x.basis) + '</td></tr>',
      { emptyTitle: 'No observed progress yet',
        emptyMsg: 'Link field evidence to activities first.' }));
};

/* ================================================== 18. Reviews */
VIEWS.reviews = async (pid, params) => {
  const status = params.status || 'open';
  const r = await A('/projects/' + pid + '/reviews?status=' + status);
  return head('Human review required', 'Only the questions that change the outcome',
    '<div class="key"><span class="lbl">Show</span>' +
    ['open', 'answered', 'all'].map(s => '<button class="btn sm' +
      (status === s ? ' primary' : '') + '" data-rst="' + s + '">' + s +
      '</button>').join('') + '</div>') +
    (r.reviews.length ? r.reviews.map(v =>
      '<div class="review"><div class="h">' +
      '<h3>' + E(v.title) + '</h3>' +
      '<div style="display:flex;gap:7px;align-items:center;flex-wrap:wrap">' +
      '<span class="tag ' + (v.kind === 'security_review' ? 'red' : 'blue') + '">' +
      E(v.kind.replace(/_/g, ' ')) + '</span>' +
      (v.affected_count > 1 ? '<span class="count-pill">one answer resolves ' +
        v.affected_count + ' records</span>' : '') +
      (v.priority === 'high' ? '<span class="tag amber">high</span>' : '') +
      (v.cluster_key ? '<span class="mono" style="font-size:10.5px;' +
        'color:var(--ink-4)">' + E(v.cluster_key) + '</span>' : '') +
      tagFor(v.status, ST) + '</div></div>' +
      '<div class="q">' + E(v.question) + '</div>' +
      (v.detail ? '<div class="samples"><div class="note">' + E(v.detail) +
        '</div></div>' : '') +
      (v.affected_sample && v.affected_sample.length
        ? '<div class="samples"><div class="eyebrow">Sample of affected records' +
          '</div>' + table([{ t: 'Source' }, { t: 'Where' }, { t: 'Date' },
            { t: 'Crew' }, { t: 'Description' }], v.affected_sample, s =>
            '<tr><td class="mono" style="font-size:11px">' + E(s.source_file) +
            '</td><td class="mono" style="font-size:11px;color:var(--ink-3)">' +
            E(s.locator) + '</td><td class="mono">' + day(s.date) + '</td>' +
            '<td class="mono">' + E(s.crew || '—') + '</td>' +
            '<td class="trunc">' + E(s.description) + '</td></tr>') + '</div>'
        : '') +
      (v.status === 'open'
        ? '<div class="opts">' + (v.options || []).map(o =>
            '<button class="btn" data-ans="' + E(o) + '" data-rid="' + E(v.id) +
            '">' + E(o) + '</button>').join('') +
          '<input class="inp" placeholder="Or type your own answer" ' +
          'data-free="' + E(v.id) + '">' +
          '<button class="btn primary" data-free-go="' + E(v.id) + '">Answer' +
          '</button></div>'
        : '<div class="samples"><dl class="kv">' +
          row('Answer', '<b>' + E(v.answer || '') + '</b>') +
          row('Answered by', E(v.answered_by || '')) +
          '</dl></div>') +
      '</div>').join('')
      : panel('Human review',
        empty('Nothing needs a human right now',
          'VEDA asks only where a decision genuinely changes the outcome.')));
};
VIEWS.bind_reviews = (pid) => {
  document.querySelectorAll('[data-rst]').forEach(b => b.onclick = () =>
    go('reviews', { status: b.dataset.rst }));
  const send = async (rid, answer) => {
    if (!answer) return;
    await P('/reviews/' + rid + '/answer', { answer: answer, by: 'site.engineer' });
    window.toast('Answer saved. The same job resumes and reprocesses the ' +
      'affected records.', 'good');
    window.render(); window.refreshCounts();
  };
  document.querySelectorAll('[data-ans]').forEach(b => b.onclick = () =>
    send(b.dataset.rid, b.dataset.ans));
  document.querySelectorAll('[data-free-go]').forEach(b => b.onclick = () => {
    const id = b.dataset.freeGo;
    const inp = document.querySelector('[data-free="' + id + '"]');
    send(id, inp && inp.value);
  });
};

/* ================================================= 19. Proposals */
function proposalCard(p) {
  const dr = p.dryrun || {};
  const im = dr.impact || {};
  const st = (label, value, cls) => '<div class="s ' + cls + '"><div class="k">' +
    label + '</div><div class="v">' + value + '</div></div>';
  const op = p.operation || 'update';
  const tf = (p.payload && p.payload.task_fields) || {};
  const title = op === 'create' ? 'Create · ' + (tf.name || p.target_name || 'new task')
    : op === 'delete' ? 'Delete · ' + (p.target_name || ('uid ' + p.target_uid))
    : (p.target_name || ('uid ' + p.target_uid)) + ' · ' + (p.field || 'update');
  const change = op === 'create'
    ? '<b style="color:var(--human)">new task</b> · <span class="mono">' +
      E(JSON.stringify(tf)) + '</span>'
    : op === 'delete'
      ? '<span class="mono">' + E(p.current_value || p.target_name || 'task') +
        ' <span style="color:var(--ink-4)">→</span> ' +
        '<b class="sev-critical">DELETE</b></span>'
      : '<span class="mono">' + E(p.current_value === null ||
        p.current_value === undefined ? '—' : p.current_value) +
        ' <span style="color:var(--ink-4)">→</span> <b style="color:var(--human)">' +
        E(p.proposed_value) + '</b></span>';
  return '<div class="review"><div class="h">' +
    '<h3>' + E(title) + '</h3>' +
    '<div style="display:flex;gap:7px;align-items:center;flex-wrap:wrap">' +
    change + '<span class="tag grey">' + E(op) + '</span>' +
    prov(p.provenance) +
    '<span class="tag grey">confidence ' + num(p.confidence, 2) + '</span>' +
    '<div style="flex:1"></div>' +
    (p.approval_state === 'pending'
      ? '<button class="btn sm" data-dry="' + E(p.id) + '">Re-run dry-run</button>' +
        '<button class="btn sm danger" data-rej="' + E(p.id) + '">Reject</button>' +
        '<button class="btn sm warn" data-app="' + E(p.id) +
        '">Approve and apply</button>'
      : tagFor(p.approval_state, ST)) +
    '</div></div>' +
    '<div class="q">' + E(p.reason) + '</div>' +
    '<div class="samples">' +
    '<div class="flow">' +
      st('Validation', E(p.validation_state),
        p.validation_state === 'passed' ? 'done'
          : p.validation_state === 'failed' ? 'fail' : 'wait') +
      st('Dry run', E(p.dryrun_state),
        p.dryrun_state === 'ok' ? 'done'
          : p.dryrun_state === 'failed' ? 'fail' : 'wait') +
      st('Approval', E(p.approval_state),
        p.approval_state === 'approved' ? 'done'
          : p.approval_state === 'rejected' ? 'fail' : 'wait') +
      st('Execution', E(p.execution_state),
        p.execution_state === 'executed' ? 'done'
          : p.execution_state === 'failed' ? 'fail' : 'wait') +
      st('Verification', E(p.verification_state),
        p.verification_state === 'verified' ? 'done'
          : p.verification_state === 'failed' ? 'fail' : 'wait') +
    '</div>' +
    (p.dryrun_state === 'ok'
      ? '<div class="eyebrow" style="margin-top:10px">Simulated impact ' +
        '(run against a throwaway copy)</div><dl class="kv">' +
        row('Tasks moved', int(im.tasksMoved)) +
        row('Finish before', day(p.impact_finish_before)) +
        row('Finish after', day(p.impact_finish_after)) +
        row('Critical path changes', p.impact_critical_change
          ? '<span class="tag red">yes</span>'
          : '<span class="tag green">no</span>') +
        row('New negative float', int(p.impact_negative_float)) +
        '</dl>' : '') +
    (p.execution_state === 'executed'
      ? '<div class="eyebrow" style="margin-top:10px">Verified write</div>' +
        '<dl class="kv">' +
        row('Requested', '<span class="mono">' + E(p.requested_value) + '</span>') +
        row('Resulting', '<span class="mono"><b>' + E(p.resulting_value) +
          '</b></span>') +
        row('Verified fields', (p.verified_fields || []).map(E).join(', ') || '—') +
        row('Rejected fields', (p.rejected_fields || []).length
          ? '<span class="sev-critical">' +
            E(JSON.stringify(p.rejected_fields)) + '</span>' : 'none') +
        row('Written to', '<span class="mono" style="font-size:11px">' +
          E(p.output_path || '') + '</span>') +
        '</dl><div class="note">The uploaded schedule is a source document and ' +
        'was not modified. This change was written to a new revision.</div>' : '') +
    ((p.validation && p.validation.checks)
      ? '<div class="eyebrow" style="margin-top:10px">Validators</div>' +
        p.validation.checks.map(c => '<div class="check"><span class="m ' +
        E(c.result) + '">' + E(c.result) + '</span><span class="n">' +
        E(c.name) + '</span><span style="flex:1">' + E(c.message) +
        '</span></div>').join('') : '') +
    '</div></div>';
}

VIEWS.proposals = async (pid) => {
  const r = await A('/projects/' + pid + '/proposals');
  return head('Proposed changes', 'Nothing is written without a dry-run and ' +
    'an approval') +
    '<div class="note warn" style="margin-bottom:14px">' +
    'Agent proposes → validators → Horizun dry-run → impact → human approval → ' +
    'verified write. VEDA reports success only after independently re-reading ' +
    'the value.</div>' +
    (r.proposals.length
      ? r.proposals.map(proposalCard).join('')
      : panel('Proposed changes', empty('No proposed changes',
        'The agent proposes a change only where the schedule demonstrably ' +
        'disagrees with verified field evidence.')));
};
VIEWS.bind_proposals = (pid) => {
  const act = async (id, body, msg) => {
    window.toast('Working…');
    try {
      const r = await P('/proposals/' + id + '/decision', body);
      window.toast(msg + (r.execution
        ? ' · verification: ' + r.execution.verification : ''), 'good');
    } catch (e) { window.toast('Failed: ' + e.message, 'bad'); }
    window.render(); window.refreshCounts();
  };
  document.querySelectorAll('[data-app]').forEach(b => b.onclick = () =>
    act(b.dataset.app, { approve: true, by: 'planning.manager' },
      'Approved and applied to a new revision'));
  document.querySelectorAll('[data-rej]').forEach(b => b.onclick = () =>
    act(b.dataset.rej, { approve: false, by: 'planning.manager' }, 'Rejected'));
  document.querySelectorAll('[data-dry]').forEach(b => b.onclick = async () => {
    window.toast('Running dry-run…');
    try { await P('/proposals/' + b.dataset.dry + '/dry-run'); }
    catch (e) { window.toast('Dry-run failed: ' + e.message, 'bad'); }
    window.render();
  });
};

/* ==================================================== 20. Ask VEDA */
VIEWS.ask = async (pid) => {
  const r = await A('/projects/' + pid + '/answers');
  return head('Ask VEDA', 'Grounded answers, not guesses') +
    panel('Ask a question', '<div class="body">' +
      '<textarea class="inp" id="qbox" rows="3" placeholder="Why is hydrotest ' +
      'late?"></textarea>' +
      '<div style="margin-top:9px;display:flex;gap:8px;align-items:center">' +
      '<button class="btn primary" id="qgo">Ask</button>' +
      '<span style="color:var(--ink-3);font-size:12px">The agent inspects the ' +
      'stored schedule facts, the field evidence and Horizun before answering.' +
      '</span></div></div>') +
    (r.answers.length ? r.answers.map(a =>
      '<div class="review"><div class="h"><h3>' + E(a.title) + '</h3>' +
      '<div style="display:flex;gap:7px">' + prov(a.provenance) +
      '<span class="mono" style="font-size:11px;color:var(--ink-3)">' +
      new Date(a.created_at * 1000).toLocaleString() + '</span></div></div>' +
      '<div class="q">' + E(a.description) + '</div></div>').join('')
      : panel('Answers', empty('No questions asked yet', '')));
};
VIEWS.bind_ask = (pid) => {
  const b = document.getElementById('qgo');
  if (b) b.onclick = async () => {
    const t = document.getElementById('qbox');
    if (!t.value.trim()) return;
    await P('/projects/' + pid + '/ask', { question: t.value.trim() });
    window.toast('Question queued. Watch Agent activity while it investigates.',
      'good');
    go('agent');
  };
};

/* =============================================== 21. Agent activity */
VIEWS.agent = async (pid) => {
  const [act, mcp, jobs] = await Promise.all([
    A('/projects/' + pid + '/agent-activity?limit=140'),
    A('/projects/' + pid + '/mcp-calls?limit=60'),
    A('/projects/' + pid + '/jobs?limit=1'),
  ]);
  const j = jobs.jobs[0];
  return head('Agent activity', 'High-level progress only — never internal ' +
    'reasoning') +
    (j ? '<div class="grid g4" style="margin-bottom:14px">' +
      stat('Latest job', E(j.kind), E(j.id.slice(0, 10))) +
      stat('Status', E(j.status), E(j.phase || ''),
        j.status === 'failed' ? 'hot' : j.status === 'done' ? 'good' : 'warm') +
      stat('Provider', E(j.provider || '—'), 'reasoning') +
      stat('Attempts', int(j.attempts), j.error ? 'last run failed' : '') +
      '</div>' : '') +
    (j && j.error ? '<div class="note danger" style="margin-bottom:14px">' +
      '<b>Job error</b><br><span class="mono" style="font-size:11.5px">' +
      E(j.error.slice(0, 900)) + '</span></div>' : '') +
    '<div class="grid g2">' +
    panel('Agent steps <small>' + act.activity.length + '</small>',
      '<div class="feed">' + (act.activity.length ? act.activity.map(a =>
      '<div class="row ' + (a.state === 'failed' ? 'fail' : '') + '">' +
      '<span class="t">' + new Date(a.created_at * 1000)
        .toLocaleTimeString() + '</span><i class="m"></i>' +
      '<span class="x">' + E(a.label) +
      (a.detail && a.state === 'failed'
        ? '<br><span class="d">' + E(String(a.detail).slice(0, 300)) + '</span>'
        : '') + '</span></div>').join('')
      : empty('No agent activity yet', 'Upload files or run an analysis.')) +
      '</div>') +
    panel('MCP calls <small>' + mcp.calls.length + '</small>',
      '<div class="feed">' + (mcp.calls.length ? mcp.calls.map(c =>
      '<div class="row ' + (c.state === 'failed' ? 'fail' : '') + '">' +
      '<span class="t">' + new Date(c.created_at * 1000)
        .toLocaleTimeString() + '</span><i class="m"></i>' +
      '<span class="x"><span class="mono">' + E(c.server) + '/' + E(c.tool) +
      '</span> — ' + E(c.state) +
      '<br><span class="d">' + E(c.summary || c.error || '') + ' · ' +
      int(c.duration_ms) + 'ms</span></span></div>').join('')
      : empty('No MCP calls yet', '')) + '</div>') +
    '</div>';
};

/* ==================================================== 22. Jobs */
VIEWS.jobs = async (pid) => {
  const r = await A('/projects/' + pid + '/jobs?limit=60');
  return head('Job status', 'Work VEDA has done and can retry') +
    panel('Jobs <small>' + r.jobs.length + '</small>',
      table([{ t: 'Kind' }, { t: 'Status' }, { t: 'Phase' }, { t: 'Provider' },
        { t: 'Created' }, { t: 'Duration', r: true }, { t: 'Attempts', r: true },
        { t: '' }], r.jobs, j =>
        '<tr><td>' + E(j.kind) + '</td><td>' + tagFor(j.status, ST) + '</td>' +
        '<td class="mono" style="font-size:11.5px">' + E(j.phase || '—') + '</td>' +
        '<td class="mono" style="font-size:11.5px">' + E(j.provider || '—') +
        '</td><td class="mono">' +
        new Date(j.created_at * 1000).toLocaleString() + '</td>' +
        '<td class="r mono">' + (j.finished_at && j.started_at
          ? Math.round(j.finished_at - j.started_at) + 's' : '—') + '</td>' +
        '<td class="r mono">' + int(j.attempts) + '</td>' +
        '<td>' + (j.status === 'failed'
          ? '<button class="btn sm" data-retry="' + E(j.id) + '">Retry</button>'
          : '') + '</td></tr>',
      { emptyTitle: 'No jobs yet', emptyMsg: '' }));
};
VIEWS.bind_jobs = (pid) => {
  document.querySelectorAll('[data-retry]').forEach(b => b.onclick = async () => {
    await P('/projects/' + pid + '/jobs/' + b.dataset.retry + '/retry');
    window.toast('Job re-queued', 'good'); window.render();
  });
};

/* ==================================================== 23. Files */
VIEWS.files = async (pid) => {
  const r = await A('/projects/' + pid + '/files');
  VIEWS._ingestState = VIEWS._ingestState || {};
  const st = VIEWS._ingestState[pid] ||
    (VIEWS._ingestState[pid] = { files: [], text: '', mode: 'field_note', title: '' });
  const revs = r.schedule_revisions || [];
  const staged = st.files || [];
  const stagedHtml = staged.length ? staged.map((f, i) =>
    '<div style="display:flex;gap:9px;align-items:center;padding:7px 0;' +
    'border-bottom:1px solid var(--line)"><span style="flex:1">' +
    E(f.name) + ' <span class="mono" style="color:var(--ink-3)">' +
    int(f.size) + ' B</span></span><button class="btn sm" data-rmfile="' + i +
    '">remove</button></div>').join('')
    : '<div class="note">No files staged yet. You can browse repeatedly; ' +
      'each selection is added to this batch.</div>';

  const accept = '.mpp,.mpt,.mpx,.xml,.xer,.pmxml,.pp,.planner,.sdef,' +
    '.csv,.tsv,.xlsx,.xlsm,.xls,.pdf,.docx,.txt,.json,.md,.log,' +
    '.png,.jpg,.jpeg,.bmp,.tif,.tiff,.webp';

  return head('Files', 'v0.1.2 multi-source inbox — immutable, incremental, auditable') +
    panel('Add project sources', '<div class="body">' +
      '<div id="ingestdrop" tabindex="0" style="border:1px dashed var(--ink-3);' +
      'border-radius:9px;padding:18px;text-align:center;cursor:pointer;' +
      'background:var(--paper-2)">' +
      '<div style="font-weight:650;margin-bottom:5px">Drop many files here</div>' +
      '<div style="color:var(--ink-3);font-size:12px;margin-bottom:11px">' +
      'Schedules + DPRs + spreadsheets + scanned PDFs/photos can arrive together. ' +
      'Focus this box and paste a screenshot too.</div>' +
      '<button class="btn" id="pickfiles" type="button">Browse files</button>' +
      '<input type="file" id="fileinput" multiple accept="' + accept + '" hidden>' +
      '</div>' +
      '<div id="stagedfiles" style="margin-top:10px">' + stagedHtml + '</div>' +
      '<div style="margin:18px 0 8px;border-top:1px solid var(--line)"></div>' +
      '<div class="grid g2">' +
        '<div><label class="lab">Pasted text type</label>' +
        '<select id="textmode" class="inp" style="width:100%">' +
          '<option value="field_note"' + (st.mode === 'field_note' ? ' selected' : '') +
          '>Field / supervisor note</option>' +
          '<option value="whatsapp"' + (st.mode === 'whatsapp' ? ' selected' : '') +
          '>WhatsApp / chat transcript</option>' +
          '<option value="change_request"' + (st.mode === 'change_request' ? ' selected' : '') +
          '>Schedule change request</option>' +
        '</select></div>' +
        '<div><label class="lab">Optional label</label>' +
        '<input id="texttitle" class="inp" style="width:100%" value="' +
        E(st.title || '') + '" placeholder="e.g. Piping supervisor update"></div>' +
      '</div>' +
      '<label class="lab" style="margin-top:10px">Paste text / notes</label>' +
      '<textarea id="pastetext" class="inp" style="width:100%;min-height:125px;' +
      'resize:vertical" placeholder="Paste WhatsApp messages, Notepad notes, ' +
      'field updates, or a deliberate change request here…">' + E(st.text || '') +
      '</textarea>' +
      '<div class="note" style="margin-top:9px">Image-only PDFs and photos use ' +
      'adaptive local OCR. Normal PDFs use embedded text first and OCR only on ' +
      'text-poor pages. Exact duplicate sources are skipped by SHA-256.</div>' +
      '<div style="display:flex;align-items:center;gap:10px;margin-top:13px">' +
      '<button class="btn primary" id="up">Ingest batch & analyse</button>' +
      '<span id="ingestsummary" style="color:var(--ink-3);font-size:12px">' +
      staged.length + ' file(s) staged' + (st.text ? ' + pasted text' : '') +
      '</span></div></div>') +
    (revs.length ? panel('Schedule revisions <small>' + revs.length + '</small>',
      '<div class="note" style="margin:0 12px 10px">A new schedule is a new ' +
      'revision. VEDA compares activities by Horizun stable UID and keeps the ' +
      'source file immutable.</div>' +
      table([{ t: 'Rev' }, { t: 'Source' }, { t: 'Activities', r: true },
        { t: 'Added', r: true }, { t: 'Removed', r: true },
        { t: 'Updated', r: true }, { t: 'Current' }], revs, x =>
        '<tr><td class="mono">r' + int(x.revision) + '</td>' +
        '<td class="trunc mono" style="max-width:260px">' +
        E((x.source_path || '').split(/[\\/]/).pop() || '—') + '</td>' +
        '<td class="r mono">' + int(x.task_count) + '</td>' +
        '<td class="r mono sev-low">+' + int(x.added_count || 0) + '</td>' +
        '<td class="r mono ' + ((x.removed_count || 0) ? 'sev-critical' : '') +
        '">−' + int(x.removed_count || 0) + '</td>' +
        '<td class="r mono">' + int(x.updated_count || 0) + '</td>' +
        '<td>' + (x.is_current ? '<span class="tag green">current</span>' : '') +
        '</td></tr>')) : '') +
    panel('Source library <small>' + r.files.length + '</small>',
      table([{ t: 'Name' }, { t: 'Kind' }, { t: 'Source mode' },
        { t: 'Size', r: true }, { t: 'SHA-256' }, { t: 'Extraction' },
        { t: 'Security' }, { t: 'Uploaded' }], r.files, f =>
        '<tr><td>' + E(f.filename) + '</td>' +
        '<td>' + tagFor(f.kind, { schedule: 'blue', evidence: 'grey',
          unknown: 'amber' }) + '</td>' +
        '<td>' + tagFor(f.source_mode || 'file', { file: 'grey', field_note: 'green',
          whatsapp: 'blue', change_request: 'amber' }) + '</td>' +
        '<td class="r mono">' + int(f.size_bytes) + '</td>' +
        '<td class="mono" style="font-size:10.5px;color:var(--ink-3)">' +
        E(String(f.sha256 || '').slice(0, 16)) + '…</td>' +
        '<td>' + tagFor(f.extract_state, { done: 'green', pending: 'grey',
          failed: 'red', skipped: 'amber' }) + '</td>' +
        '<td>' + (f.security_state === 'clean'
          ? '<span class="tag green">clean</span>'
          : '<span class="tag red">' + E(f.security_state) + '</span>') +
        '</td><td class="mono">' +
        new Date(f.created_at * 1000).toLocaleDateString() + '</td></tr>',
      { emptyTitle: 'No sources yet', emptyMsg: 'Drop a schedule and field evidence to begin.' })) +
    (r.files.some(f => f.security_state !== 'clean')
      ? panel('Quarantined content',
        '<div class="body">' + r.files.filter(f => f.security_state !== 'clean')
          .map(f => '<div class="note danger" style="margin-bottom:9px">' +
            '<b>' + E(f.filename) + '</b><br>' + E(f.security_notes || '') +
            '<br><span style="color:var(--ink-3)">Its content is withheld from ' +
            'the agent. Resolve it under Human review.</span></div>').join('') +
        '</div>') : '');
};
VIEWS.bind_files = (pid) => {
  VIEWS._ingestState = VIEWS._ingestState || {};
  const st = VIEWS._ingestState[pid] ||
    (VIEWS._ingestState[pid] = { files: [], text: '', mode: 'field_note', title: '' });
  const inp = document.getElementById('fileinput');
  const dz = document.getElementById('ingestdrop');
  const pick = document.getElementById('pickfiles');
  const list = document.getElementById('stagedfiles');
  const text = document.getElementById('pastetext');
  const mode = document.getElementById('textmode');
  const title = document.getElementById('texttitle');
  const b = document.getElementById('up');
  if (!b || !inp) return;

  const draw = () => {
    if (list) list.innerHTML = st.files.length ? st.files.map((f, i) =>
      '<div style="display:flex;gap:9px;align-items:center;padding:7px 0;' +
      'border-bottom:1px solid var(--line)"><span style="flex:1">' + E(f.name) +
      ' <span class="mono" style="color:var(--ink-3)">' + int(f.size) +
      ' B</span></span><button class="btn sm" data-rmfile="' + i +
      '">remove</button></div>').join('') :
      '<div class="note">No files staged yet. Browse or drop as many as you need.</div>';
    const sum = document.getElementById('ingestsummary');
    if (sum) sum.textContent = st.files.length + ' file(s) staged' +
      ((text && text.value.trim()) ? ' + pasted text' : '');
    if (list) list.querySelectorAll('[data-rmfile]').forEach(x => x.onclick = () => {
      st.files.splice(Number(x.dataset.rmfile), 1); draw();
    });
  };
  const addFiles = (fs) => {
    for (const f of Array.from(fs || [])) {
      const key = [f.name, f.size, f.lastModified].join('|');
      if (!st.files.some(x => [x.name, x.size, x.lastModified].join('|') === key))
        st.files.push(f);
    }
    draw();
  };

  if (pick) pick.onclick = (e) => { e.stopPropagation(); inp.click(); };
  inp.onchange = () => { addFiles(inp.files); inp.value = ''; };
  if (dz) {
    dz.onclick = (e) => { if (!e.target.closest('button')) inp.click(); };
    dz.ondragover = (e) => { e.preventDefault(); dz.style.opacity = '.72'; };
    dz.ondragleave = () => { dz.style.opacity = '1'; };
    dz.ondrop = (e) => {
      e.preventDefault(); dz.style.opacity = '1'; addFiles(e.dataTransfer.files);
    };
    dz.onpaste = (e) => {
      const fs = e.clipboardData && e.clipboardData.files;
      if (fs && fs.length) { e.preventDefault(); addFiles(fs); }
    };
  }
  if (text) text.oninput = () => { st.text = text.value; draw(); };
  if (mode) mode.onchange = () => { st.mode = mode.value; };
  if (title) title.oninput = () => { st.title = title.value; };
  draw();

  b.onclick = async () => {
    st.text = text ? text.value : st.text;
    st.mode = mode ? mode.value : st.mode;
    st.title = title ? title.value : st.title;
    if (!st.files.length && !String(st.text || '').trim())
      return window.toast('Add files or paste some text first');
    const fd = new FormData();
    for (const f of st.files) fd.append('files', f);
    if (String(st.text || '').trim()) {
      fd.append('text', st.text.trim());
      fd.append('text_mode', st.mode || 'field_note');
      fd.append('text_title', st.title || '');
    }
    b.disabled = true; b.textContent = 'Ingesting…';
    try {
      const r = await fetch('/api/projects/' + pid + '/ingest',
        { method: 'POST', body: fd });
      if (!r.ok) throw new Error(await r.text());
      const j = await r.json();
      VIEWS._ingestState[pid] = { files: [], text: '', mode: 'field_note', title: '' };
      let msg = j.stored_count + ' new source(s) stored';
      if (j.duplicate_count) msg += ', ' + j.duplicate_count + ' duplicate(s) skipped';
      if (j.schedule_count) msg += ', ' + j.schedule_count + ' schedule revision(s)';
      window.toast(msg + '.', 'good');
      if (j.event) go('agent'); else window.render();
    } catch (e) {
      window.toast('Ingestion failed: ' + e.message, 'bad');
      b.disabled = false; b.textContent = 'Ingest batch & analyse';
    }
  };
};

/* ==================================================== 24. Outputs */
VIEWS.outputs = async (pid) => {
  const r = await A('/projects/' + pid + '/artifacts');
  return head('Outputs', 'Everything VEDA produced') +
    panel('Artifacts <small>' + r.artifacts.length + '</small>',
      table([{ t: 'Kind' }, { t: 'Title' }, { t: 'Format' }, { t: 'From' },
        { t: 'Created' }, { t: '' }], r.artifacts, a =>
        '<tr><td>' + tagFor(a.kind, { summary: 'blue',
          schedule_revision: 'green', answer: 'violet',
          rejected_output: 'red' }) + '</td>' +
        '<td class="trunc">' + E(a.title) + '</td>' +
        '<td class="mono">' + E(a.format || '—') + '</td>' +
        '<td>' + prov(a.provenance) + '</td>' +
        '<td class="mono">' + new Date(a.created_at * 1000)
          .toLocaleString() + '</td>' +
        '<td>' + (a.path
          ? '<a class="btn sm" href="/api/projects/' + E(pid) + '/artifacts/' +
            E(a.id) + '/download">Download</a>' : '') + '</td></tr>',
      { emptyTitle: 'No outputs yet', emptyMsg: '' })) +
    (r.artifacts.filter(a => a.kind === 'summary' || a.kind === 'answer').length
      ? panel('Written output', '<div class="body">' +
        r.artifacts.filter(a => a.kind === 'summary' || a.kind === 'answer')
          .slice(0, 6).map(a => '<div class="review"><div class="h"><h3>' +
            E(a.title) + '</h3>' + prov(a.provenance) + '</div>' +
            '<div class="q">' + E(a.description || '') + '</div></div>').join('') +
        '</div>') : '');
};

/* ==================================================== 25. Audit */
function auditTable(rows) {
  return table([{ t: 'When' }, { t: 'Actor' }, { t: 'Action' }, { t: 'Entity' },
    { t: 'Previous' }, { t: 'New' }, { t: 'Approval' }, { t: 'Verification' },
    { t: 'Result' }], rows, a =>
    '<tr><td class="mono" style="font-size:11px">' +
    new Date(a.created_at * 1000).toLocaleString() + '</td>' +
    '<td>' + E(a.actor) + ' <span class="tag grey">' + E(a.actor_type) +
    '</span></td>' +
    '<td class="mono" style="font-size:11.5px">' + E(a.action) +
    (a.tool ? '<br><span style="color:var(--ink-3);font-size:10.5px">' +
      E(a.tool) + '</span>' : '') + '</td>' +
    '<td class="mono" style="font-size:11px">' + E(a.entity_type || '—') +
    (a.entity_id ? '<br><span style="color:var(--ink-4)">' +
      E(String(a.entity_id).slice(0, 12)) + '</span>' : '') + '</td>' +
    '<td class="trunc" style="max-width:160px">' + E(a.previous_value || '—') +
    '</td>' +
    '<td class="trunc" style="max-width:160px">' + E(a.new_value || '—') + '</td>' +
    '<td>' + (a.approval ? '<span class="tag green">' + E(a.approval) +
      '</span>' : '—') + '</td>' +
    '<td>' + (a.verification ? tagFor(a.verification, ST) : '—') + '</td>' +
    '<td class="trunc" style="max-width:230px;color:var(--ink-2)">' +
    E(a.result || '—') + '</td></tr>',
  { emptyTitle: 'No audit entries', emptyMsg: '' });
}

VIEWS.audit = async (pid) => {
  const r = await A('/projects/' + pid + '/audit?limit=500');
  return head('Audit', 'Every meaningful action, preserved') +
    panel('Audit trail <small>' + r.audit.length + '</small>',
      auditTable(r.audit));
};

/* ================================================= 26. System / MCP */
VIEWS.system = async (pid) => {
  const h = await A('/health');
  const hz = h.horizun || {};
  const caps = hz.capabilities || {};
  return head('System', 'Runtime, MCP and reasoning providers') +
    '<div class="grid g3" style="margin-bottom:14px">' +
    stat('Horizun', hz.ok ? 'online' : 'offline',
      E(hz.backend || hz.error || ''), hz.ok ? 'good' : 'hot') +
    stat('Active provider', E(h.active_provider),
      (h.providers[h.active_provider] || {}).ok ? 'reachable' : 'unavailable',
      (h.providers[h.active_provider] || {}).ok ? 'good' : 'hot') +
    stat('Worker', h.worker.current_job ? 'busy' : 'idle',
      E(h.worker.current_job || 'no job running')) +
    '</div>' +
    panel('Reasoning providers <small>VEDA is provider-neutral</small>',
      '<div class="body">' + Object.keys(h.providers).map(k => {
        const p = h.providers[k];
        return '<div class="review"><div class="h" style="display:flex;gap:9px;' +
          'align-items:center;flex-wrap:wrap"><b>' + E(p.label || k) + '</b>' +
          (p.ok ? '<span class="tag green">reachable</span>'
                : '<span class="tag red">unavailable</span>') +
          (p.active ? '<span class="tag blue">active</span>' : '') +
          '<div style="flex:1"></div>' +
          (p.active ? '' : '<button class="btn sm" data-prov="' + E(k) +
            '">Make active</button>') + '</div>' +
          '<div class="samples" style="padding-top:12px"><dl class="kv">' +
          (p.version ? row('Version', E(p.version)) : '') +
          (p.model ? row('Model', E(p.model)) : '') +
          (p.path ? row('Path', '<span class="mono" style="font-size:11px">' +
            E(p.path) + '</span>') : '') +
          (p.error ? row('Error', '<span class="sev-high">' + E(p.error) +
            '</span>') : '') +
          (p.hint ? row('Hint', E(p.hint)) : '') +
          '</dl></div></div>';
      }).join('') + '</div>') +
    panel('Horizun capability matrix <small>honoured, never assumed</small>',
      '<div class="body">' + (Object.keys(caps).length
        ? '<div class="key">' + Object.keys(caps).map(k =>
          '<span class="tag ' + (caps[k] ? 'green' : 'red') + '">' +
          E(k.replace(/_/g, ' ')) + (caps[k] ? '' : ' · no') + '</span>').join('') +
          '</div>' +
          '<div class="note mcp" style="margin-top:11px">VEDA refuses ' +
          'operations the runtime reports as unavailable rather than ' +
          'approximating them. Native .mpp authoring and resource levelling are ' +
          'the two that stay off on this backend.</div>'
        : '<div class="note danger">Horizun is not reachable: ' +
          E(hz.error || 'unknown') + '</div>') + '</div>') +
    panel('Horizun tools <small>' + (hz.tools || []).length + '</small>',
      '<div class="body"><div class="key">' + (hz.tools || []).map(t =>
        '<span class="tag grey mono">' + E(t) + '</span>').join('') +
      '</div></div>') +
    panel('Runtime', '<div class="body"><dl class="kv">' +
      row('VEDA version', E(h.veda.version)) +
      row('Data directory', '<span class="mono" style="font-size:11px">' +
        E(h.veda.data_dir) + '</span>') +
      row('Horizun command', '<span class="mono" style="font-size:11px">' +
        E(hz.command || '') + '</span>') +
      row('Server', E((hz.server && hz.server.name) || '—') + ' ' +
        E((hz.server && hz.server.version) || '')) +
      '</dl></div>');
};
VIEWS.bind_system = () => {
  document.querySelectorAll('[data-prov]').forEach(b => b.onclick = async () => {
    await P('/providers/active', { provider: b.dataset.prov });
    window.toast('Active provider changed to ' + b.dataset.prov, 'good');
    window.render();
  });
};

window.VIEWS = VIEWS;
