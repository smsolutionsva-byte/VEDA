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

/* ===================================================== Field capture */
VIEWS.capture = async (pid) => {
  const r = await A('/projects/' + pid + '/field-captures?limit=30');
  const captures = r.captures || [];
  const recent = captures.length ? captures.map(c => {
    const statusMap = { proposal_ready: 'green', confirmed_no_change: 'green',
      needs_activity: 'amber', conflict: 'red' };
    const detail = [c.activity_display_id, c.activity_name].filter(Boolean).join(' · ');
    return '<article class="capture-history-item">' +
      '<div class="capture-history-state"><i></i><span>' +
      tagFor(c.event_state, {start: 'blue', progress: 'amber', finish: 'green'}) +
      '</span></div><div class="capture-history-copy"><div><b>' +
      E(detail || 'Activity not linked yet') + '</b><span class="mono">' +
      E(day(c.occurred_at)) + '</span></div><p>' + E(c.confirmed_text) + '</p>' +
      '<footer>' + tagFor(c.status, statusMap) +
      (c.observed_progress !== null && c.observed_progress !== undefined
        ? '<span>' + num(c.observed_progress) + '% complete</span>' : '') +
      (c.remaining_days !== null && c.remaining_days !== undefined
        ? '<span>' + num(c.remaining_days) + 'd remaining</span>' : '') +
      ((c.media_file_ids || []).length ? '<span>' + int(c.media_file_ids.length) + ' media</span>' : '') +
      ((c.proposal_ids || []).length ? '<button class="link" onclick="go(\'proposals\')">Review proposals</button>' : '') +
      (c.status === 'needs_activity' && c.evidence_id
        ? '<button class="link" onclick="go(\'evidence-detail\',{id:\'' + E(c.evidence_id) + '\'})">Link evidence</button>' : '') +
      '</footer></div></article>';
  }).join('') : empty('No field updates yet',
    'The first confirmed update will appear here with its activity link and proposal state.');

  return head('Field capture', 'Fast on site · confirmed by a person · safe offline',
    '<button class="btn sm" onclick="go(\'files\')">Files</button>' +
    '<button class="btn sm" onclick="go(\'proposals\')">Edit proposals</button>') +
    '<div class="capture-status-row"><div class="capture-connectivity" id="capture-connectivity">Checking connection…</div>' +
    '<div class="capture-outbox">Saved on device <b id="capture-outbox-count">0</b>' +
    '<button class="btn sm" id="capture-sync-now">Sync now</button></div></div>' +
    '<input id="capture-client-id" type="hidden">' +
    '<div class="capture-layout"><section class="capture-composer">' +
      '<div class="capture-section"><div class="capture-step"><span>1</span><div><b>What changed?</b>' +
      '<small>Choose the event you personally observed.</small></div></div>' +
      '<div class="capture-event-grid">' +
        '<label class="capture-event-option"><input type="radio" name="capture-event" value="start"><span><b>Started</b><small>Work began on site</small></span></label>' +
        '<label class="capture-event-option selected"><input type="radio" name="capture-event" value="progress" checked><span><b>Progress</b><small>Work advanced</small></span></label>' +
        '<label class="capture-event-option"><input type="radio" name="capture-event" value="finish"><span><b>Finished</b><small>Scope is complete</small></span></label>' +
      '</div><div class="capture-fields-two"><label><span>When observed</span>' +
      '<input class="inp" id="capture-occurred" type="datetime-local"></label>' +
      '<label><span>Your name / crew</span><input class="inp" id="capture-reporter" placeholder="e.g. S. Kumar · Piping A"></label></div>' +
      '<div class="capture-fields-two" id="capture-progress-fields"><label><span>Measured progress % <em>optional</em></span>' +
      '<input class="inp" id="capture-progress" type="number" min="0" max="100" step="0.1" inputmode="decimal" placeholder="e.g. 65"></label>' +
      '<label><span>Remaining working days <em>optional</em></span><input class="inp" id="capture-remaining" type="number" min="0" step="0.5" inputmode="decimal" placeholder="Only if explicitly known"></label></div>' +
      '<div class="note" id="capture-finish-rule" hidden>Finish creates a governed Actual Finish, 100% complete, and zero remaining-duration proposal bundle.</div></div>' +

      '<div class="capture-section"><div class="capture-step"><span>2</span><div><b>Capture the field truth</b>' +
      '<small>Voice and photos remain attached to the confirmed words.</small></div></div>' +
      '<div class="capture-action-grid"><button class="capture-action voice" id="capture-voice" type="button"><i>●</i><b>Record voice</b><small>Audio is kept as evidence</small></button>' +
      '<button class="capture-action photo" id="capture-photo" type="button"><i>▣</i><b>Take photos</b><small>Use camera or gallery</small></button></div>' +
      '<input type="file" id="capture-photo-file" accept="image/*" capture="environment" multiple hidden>' +
      '<input type="file" id="capture-audio-file" accept="audio/*" capture hidden>' +
      '<div id="capture-media-tray" class="capture-media-tray"></div>' +
      '<label class="capture-wide-label"><span>Spoken or typed observation</span>' +
      '<textarea class="inp" id="capture-original" rows="4" placeholder="Describe the work, exact area, quantities, blockers, and what you personally observed."></textarea></label>' +
      '<div class="capture-transcript-source" id="capture-transcript-source">Type a note, or record voice for an optional on-device draft transcript.</div></div>' +

      '<div class="capture-section"><div class="capture-step"><span>3</span><div><b>Place and activity</b>' +
      '<small>Explicit selection prevents the wrong schedule activity from receiving actuals.</small></div></div>' +
      '<label class="capture-wide-label"><span>Schedule activity <em>search by ID, name, or WBS</em></span>' +
      '<input class="inp" id="capture-activity-search" autocomplete="off" placeholder="Start typing an activity…"></label>' +
      '<div class="capture-activity-results" id="capture-activity-results"></div>' +
      '<div class="capture-activity-selected" id="capture-activity-selected"></div>' +
      '<div class="capture-fields-two"><label><span>Area / location label</span>' +
      '<input class="inp" id="capture-location-label" placeholder="e.g. Unit 04 · Pipe rack B"></label>' +
      '<div class="capture-location-box"><button class="btn" id="capture-location" type="button">Use device location</button>' +
      '<small id="capture-location-status">Location is optional and permission-based.</small></div></div></div>' +

      '<div class="capture-section capture-confirm-section"><div class="capture-step"><span>4</span><div><b>Confirm before sending</b>' +
      '<small>VEDA uses these exact words; a transcript is never accepted silently.</small></div></div>' +
      '<div class="capture-fields-two"><label><span>Language</span><select class="inp" id="capture-language">' +
      '<option value="en">English</option><option value="hi-IN">हिन्दी</option>' +
      '<option value="ar">العربية</option><option value="es">Español</option>' +
      '<option value="fr">Français</option><option value="ur">اردو</option></select></label>' +
      '<div class="capture-confirm-badge"><i>✓</i><span><b>Human confirmation</b><small>Required for every event</small></span></div></div>' +
      '<label class="capture-wide-label"><span>Confirmed field update</span>' +
      '<textarea class="inp" id="capture-confirmed" rows="5" placeholder="Review or translate the observation, then confirm the exact wording here."></textarea></label>' +
      '<div class="capture-policy"><span>Evidence saved</span><i>→</i><span>Activity identity</span><i>→</i><span>Proposal only</span><i>→</i><span>Planner approval</span></div>' +
      '<button class="btn primary capture-save" id="capture-save" type="button">Confirm & save update</button>' +
      '<p class="capture-safety">Saving never writes to Primavera. If an official value differs, VEDA holds the conflict for a planner.</p></div>' +
    '</section><aside class="capture-history">' + panel('Recent field updates <small>' + captures.length + '</small>',
      '<div class="capture-history-list">' + recent + '</div>') + '</aside></div>';
};
VIEWS.bind_capture = (pid) => {
  if (window.FieldCapture) window.FieldCapture.bind(pid);
};

/* ===================================================== 1. overview */
VIEWS.overview = async (pid) => {
  const o = await A('/projects/' + pid + '/overview');
  const s = o.schedule, ev = o.earned_value, c = o.counts;
  const f = o.field_context || {};
  if (!s) {
    return '<div class="head"><h1>' + E(o.project.name) + '</h1></div>' +
      panel('Project overview', '<div class="body">' +
        '<div class="note warn">No authoritative schedule snapshot has been analysed yet. ' +
        'Upload a schedule source; if multiple schedule revisions are detected, choose one and VEDA will start analysis automatically.' +
        '</div><p><button class="btn primary" onclick="go(\'files\')">' +
        'Go to files</button></p></div>');
  }
  const lateFinish = s.forecast_finish && s.baseline_finish &&
    day(s.forecast_finish) > day(s.baseline_finish);
  const forecastValue = s.forecast_finish ? day(s.forecast_finish) : 'N/E';
  const forecastDetail = s.forecast_finish
    ? (s.forecast_basis || 'source-supported current forecast')
    : 'source does not establish a current forecast finish';
  const baselineFallback = String(s.baseline_basis || '').toLowerCase().includes('fallback');
  const criticalAvailable = Number(s.criticality_available || 0) === 1;
  const overdueEvaluable = Number(s.overdue_evaluable || 0) === 1;
  const completedLateEvaluable = Number(s.completed_late_evaluable || 0) === 1;
  const progressAvailable = Number(s.progress_available || 0) === 1;
  const criticalDetail = criticalAvailable
    ? ((s.criticality_basis || 'stored criticality method') +
      (s.criticality_threshold_days !== null && s.criticality_threshold_days !== undefined
        ? ' · threshold ' + num(s.criticality_threshold_days, 2) + 'd' : ''))
    : 'source does not provide enough information to evaluate criticality';
  const statusCounts = (() => {
    try { return JSON.parse(s.info_json || '{}').source?.status_counts || {}; }
    catch (_) { return {}; }
  })();
  let progressDetail = s.progress_basis || (progressAvailable ? 'source-supported schedule progress' : 'not available from source');
  if (progressAvailable && Number(statusCounts.not_started || 0) === Number(s.task_count || 0) && Number(s.task_count || 0) > 0) {
    progressDetail = int(s.task_count) + '/' + int(s.task_count) + ' source activities are Not Started';
  } else if (ev && ev.spi !== null && ev.spi !== undefined) {
    progressDetail += ' · SPI ' + num(ev.spi, 3) + (baselineFallback ? ' against fallback reference' : '');
  }
  const ref = o.reference_context || {};
  const evaluatedQa = Number(o.quality.passed || 0) + Number(o.quality.failed || 0);
  const qaValue = evaluatedQa ? num(s.health_score, 1) + '%' : 'N/E';
  const qaDetail = evaluatedQa
    ? (o.quality.passed + ' passed · ' + o.quality.failed + ' failed · ' +
      o.quality.not_evaluated + ' not evaluated')
    : (o.quality.not_evaluated + ' checks not evaluated');
  const latestFieldDate = f.latest_date ? day(f.latest_date) : 'none';
  const decisionCount = Number(c.pending_reviews || 0) + Number(c.pending_proposals || 0);
  const reportingLag = (() => {
    if (!f.latest_date || !s.data_date) return null;
    const gap = Math.floor((new Date(day(s.data_date) + 'T00:00:00Z') -
      new Date(day(f.latest_date) + 'T00:00:00Z')) / 86400000);
    return Number.isFinite(gap) ? Math.max(0, gap) : null;
  })();
  const interventions = [];
  if (decisionCount) interventions.push('<button onclick="go(\'attention\')"><b>' +
    int(decisionCount) + ' decision' + (decisionCount === 1 ? '' : 's') +
    ' waiting</b><span>Review evidence matches and governed changes</span><i>Open inbox →</i></button>');
  if (Number(f.unresolved_record_count || 0)) interventions.push('<button onclick="go(\'evidence\',{state:\'needs_review\'})"><b>' +
    int(f.unresolved_record_count) + ' evidence rows unresolved</b><span>Inspect records without a settled activity identity</span><i>Open evidence →</i></button>');
  if (Number(c.open_issues || 0) + Number(c.open_risks || 0)) interventions.push('<button onclick="go(\'issues\')"><b>' +
    int(Number(c.open_issues || 0) + Number(c.open_risks || 0)) +
    ' open issue/risk records</b><span>Review execution conditions that may need intervention</span><i>Investigate →</i></button>');

  return '<div class="head"><div><div class="eyebrow">Control room</div>' +
    '<h1>' + E(o.project.name) + '</h1>' +
    '<div class="sub">Authoritative schedule: ' + E(s.project_name || '') +
    (o.project.location ? ' · ' + E(o.project.location) : '') +
    ' · data/status date ' + (s.data_date ? day(s.data_date) : 'N/E') +
    ' · schedule revision ' + E(s.revision) +
    '</div></div><div class="spacer"></div>' + provKey() + '</div>' +

    '<div class="control-strip">' +
      '<div><span>Decisions</span><b class="' + (decisionCount ? 'warm' : 'good') + '">' +
        int(decisionCount) + '</b><small>' + (decisionCount ? 'require a person' : 'nothing waiting') + '</small></div>' +
      '<div><span>Unresolved evidence</span><b class="' + (f.unresolved_record_count ? 'warm' : 'good') + '">' +
        int(f.unresolved_record_count || 0) + '</b><small>without settled identity</small></div>' +
      '<div><span>Reporting freshness</span><b class="' +
        (reportingLag === null ? 'muted' : reportingLag > 2 ? 'warm' : 'good') + '">' +
        (reportingLag === null ? 'N/E' : reportingLag + 'd') + '</b><small>' +
        (reportingLag === null ? 'no comparable field/status dates' : 'behind schedule status date') + '</small></div>' +
      '<div><span>Validated actuals coverage</span><b>' + int(f.validated_activity_count || 0) +
        '</b><small>activities with trusted evidence</small></div>' +
    '</div>' +
    '<section class="intervention-panel"><header><div><div class="eyebrow">Intervention queue</div>' +
      '<h2>' + (interventions.length ? 'What needs attention now' : 'No immediate intervention') +
      '</h2></div><span>' + latestFieldDate + ' latest field date</span></header>' +
      '<div class="intervention-list">' + (interventions.length ? interventions.join('') :
        '<div class="control-clear"><b>Project inputs are reconciled.</b><span>New evidence will appear here when it creates an exception.</span></div>') +
      '</div></section>' +

    '<div class="grid g4" style="margin-bottom:14px">' +
    stat('Current forecast finish', forecastValue, E(forecastDetail),
      lateFinish ? 'hot' : (s.forecast_finish ? 'good' : '')) +
    stat('Recorded schedule progress', progressAvailable ? num(s.percent_complete, 1) + '%' : 'N/E',
      E(progressDetail)) +
    stat('Critical activities', criticalAvailable ? int(c.critical) : 'N/E',
      criticalAvailable ? ('of ' + int(c.activities) + ' source activities · ' + E(criticalDetail))
        : E(criticalDetail), criticalAvailable && c.critical ? 'warm' : '') +
    stat('Source-evaluable schedule QA', qaValue, qaDetail,
      evaluatedQa && Number(s.health_score) < 60 ? 'hot' : (evaluatedQa ? 'good' : '')) +
    '</div>' +

    '<div class="grid g4" style="margin-bottom:14px">' +
    stat('Overdue vs reference plan', overdueEvaluable ? int(c.overdue) : 'N/E',
      overdueEvaluable ? 'unfinished activities whose reference finish is before the supplied data/status date' :
        'not evaluable because the source does not supply a data/status date',
      overdueEvaluable && c.overdue ? 'warm' : '') +
    stat('Completed after reference finish', completedLateEvaluable ? int(c.completed_late) : 'N/A',
      completedLateEvaluable ? 'completed activities whose actual finish is later than the stored baseline/reference finish' :
        'not applicable/evaluable: no completed activity with an actual finish is available for comparison',
      completedLateEvaluable && c.completed_late ? 'warm' : '') +
    stat('Project-control reference rows', int(ref.reference_record_count || 0),
      'supporting dictionaries/registers; not field-progress evidence') +
    stat('Active WBS nodes', int(c.wbs), 'schedule hierarchy nodes; not activities') +
    '</div>' +

    '<div class="grid g4" style="margin-bottom:14px">' +
    stat('Field-evidence records', int(f.record_count || 0),
      (f.record_count ? int(f.source_file_count || 0) + ' source file(s) · latest dated evidence ' + latestFieldDate :
        'no field/report evidence extracted yet')) +
    stat('Activities with validated evidence', int(f.validated_activity_count || 0),
      int(f.validated_link_record_count || 0) + ' validated supporting record(s); does not change official schedule progress') +
    stat('Evidence rows stating a progress %', int(f.reported_progress_record_count || 0),
      int(f.numeric_observed_activity_count || 0) + ' schedule activity/activities have a validated numeric field observation; this is not official schedule progress') +
    stat('Evidence without a settled activity link', int(f.unresolved_record_count || 0),
      'records with no validated activity link or a link conflict; deliberately deferred records are excluded',
      f.unresolved_record_count ? 'warm' : 'good') +
    '</div>' +

    '<div class="grid g4" style="margin-bottom:14px">' +
    stat('Decisions waiting on you', int(c.pending_reviews || 0) + int(c.pending_proposals || 0),
      int(c.pending_reviews || 0) + ' evidence/security decision(s) · ' + int(c.pending_proposals || 0) + ' schedule-change approval(s)',
      (c.pending_reviews || c.pending_proposals) ? 'warm' : 'good') +
    stat('Open derived issues', int(c.open_issues || 0), 'stored issue records derived from rules/analysis; not a count of failed schedule-QA checks',
      c.open_issues ? 'warm' : 'good') +
    stat('Open derived risks', int(c.open_risks || 0), 'stored possible-future-event records derived from rules/analysis; not a count of failed schedule-QA checks',
      c.open_risks ? 'warm' : 'good') +
    stat('Evidence deliberately deferred', int(f.deferred_record_count || 0),
      'records a human explicitly chose to leave unassigned for now; they are not silently unresolved',
      f.deferred_record_count ? 'warm' : 'good') +
    '</div>' +

    (o.state_summary ? panel('Current state summary',
      '<div class="body"><div style="white-space:pre-wrap;font-size:13.5px;line-height:1.6">' +
      E(o.state_summary) + '</div><div style="margin-top:10px">' + prov('DERIVED') +
      ' <span style="color:var(--ink-3);font-size:12px">Deterministically assembled from persisted schedule, QA, and evidence state. QA findings, issues, risks, and field-observed progress remain separate concepts.</span></div></div>') : '') +

    (o.summary ? panel('Latest agent interpretation',
      '<div class="body"><div style="white-space:pre-wrap;font-size:13.5px;line-height:1.6">' + E(o.summary) + '</div>' +
      '<div style="margin-top:10px">' + prov('AI_INFERENCE') +
      ' <span style="color:var(--ink-3);font-size:12px">Interpretive analysis from ' +
      E(o.provider_label || o.active_provider) + '; it does not override the deterministic current-state summary above.</span></div></div>') : '') +

    '<div class="grid g2">' +
    panel('Authoritative schedule facts', '<div class="body"><dl class="kv">' +
      row('Schedule source', E(s.project_name)) +
      row('Data/status date', s.data_date ? day(s.data_date) : '<span style="color:var(--ink-3)">N/E — not supplied by source</span>') +
      row('Earliest planned activity start', day(s.planned_start)) +
      row('Latest planned activity finish', day(s.planned_finish)) +
      (s.must_finish_by ? row('Project Must Finish By', day(s.must_finish_by)) : '') +
      row('Current forecast finish', s.forecast_finish ? day(s.forecast_finish)
        : '<span style="color:var(--ink-3)">N/E — source does not establish a current forecast</span>') +
      (s.forecast_basis ? row('Forecast basis', E(s.forecast_basis)) : '') +
      row('Baseline/reference start', s.baseline_start ? day(s.baseline_start)
        : '<span style="color:var(--ink-3)">N/E — no usable baseline/reference start stored</span>') +
      row('Baseline/reference finish', s.baseline_finish ? day(s.baseline_finish)
        : '<span style="color:var(--ink-3)">N/E — no usable baseline/reference finish stored</span>') +
      (s.baseline_basis ? row('Baseline/reference basis', E(s.baseline_basis)) : '') +
      (s.baseline_present ? row('Activities with baseline/reference dates', int(s.baseline_coverage_count) + ' / ' + int(s.task_count)) : '') +
      row('Source activities', int(s.task_count)) +
      row('Active WBS nodes', int(s.wbs_count)) +
      row('Source WBS Summary activities', int(s.summary_activity_count || 0)) +
      row('Source milestone activities', int(s.milestone_count || c.milestones || 0)) +
      (s.loe_count ? row('Source Level of Effort activities', int(s.loe_count)) : '') +
      row('Predecessor/relationship links', int(s.relationship_count)) +
      row('Unique schedule resource labels', int(s.resource_count)) +
      row('Activity-resource assignments', int(s.resource_assignment_count !== null && s.resource_assignment_count !== undefined ? s.resource_assignment_count : c.assignments)) +
      (s.resource_basis ? row('Resource-count basis', E(s.resource_basis)) : '') +
      '</dl><div style="margin-top:10px">' + prov('MCP_FACT') +
      ' <span style="color:var(--ink-3);font-size:12px">Horizun performs supported schedule calculations; VEDA preserves source capability boundaries so transport defaults cannot become source facts.</span></div></div>') +
    panel('Earned-value status', ev
      ? '<div class="body"><dl class="kv">' +
        row('PV / BCWS', num(ev.pv, 2)) + row('EV / BCWP', num(ev.ev, 2)) +
        row('AC / ACWP', num(ev.ac, 2)) + row('BAC', num(ev.bac, 2)) +
        row('SPI', '<b class="' + (ev.spi < 1 ? 'sev-high' : 'sev-low') + '">' +
          num(ev.spi, 3) + '</b>') +
        row('CPI', num(ev.cpi, 3)) + row('EAC', num(ev.eac, 2)) +
        row('TCPI', num(ev.tcpi, 3)) +
        '</dl><div class="note ' + (baselineFallback ? 'warn' : 'mcp') +
        '" style="margin-top:10px">Calculation basis: ' + E(ev.basis || '') +
        (baselineFallback ? '<br>Baseline note: P6 is using the current project as a fallback reference; this is not an independently frozen/assigned baseline.' : '') +
        '</div></div>'
      : '<div class="body"><div class="note warn">' +
        (s.baseline_present
          ? 'N/E — baseline/reference dates are available, but the source does not establish all current status/progress/cost inputs required for earned-value metrics.'
          : 'N/E — the source does not establish a usable baseline/reference plus the current status/progress/cost inputs required for earned-value metrics.') +
        '</div></div>') +
    '</div>' +
    (ref.reference_record_count !== undefined ? panel('Project-control source integrity',
      '<div class="body"><dl class="kv">' +
      row('Reference-table rows', int(ref.reference_record_count)) +
      row('Activity-code dictionary rows', int(ref.activity_code_count)) +
      row('Calendar-definition rows', int(ref.calendar_definition_count)) +
      row('Milestone-register rows', int(ref.milestone_register_count)) +
      row('Resource-master rows', int(ref.resource_master_count)) +
      row('WBS-dictionary rows', int(ref.wbs_dictionary_count)) +
      row('Unique resource labels used by schedule', int(ref.resource_schedule_label_count)) +
      row('Exact schedule-label → resource-master matches', int(ref.resource_exact_match_count)) +
      row('Schedule resource labels needing mapping/review', int(ref.resource_unresolved_count)) +
      row('Schedule calendar labels needing mapping/review', int(ref.calendar_unresolved_count)) +
      row('Milestone-register activity links unresolved against selected schedule', int(ref.milestone_links_unresolved_count)) +
      '</dl>' +
      ((ref.warnings || []).length ? '<div class="note warn" style="margin-top:10px">' +
        (ref.warnings || []).map(w => '<div style="margin-bottom:6px"><b>' + E(w.code || 'SOURCE_WARNING') +
          '</b><br>' + E(w.summary || '') + '</div>').join('') + '</div>' : '') +
      '</div>') : '');
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
        { t: 'Recorded schedule %' }, { t: 'Activities', r: true }, { t: 'Critical', r: true },
        { t: 'Overdue*', r: true }, { t: 'Issues', r: true }, { t: 'Risks', r: true },
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
    { t: 'Dur', sort: 'duration', r: true }, { t: 'Sched %', sort: 'progress' },
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

  return head('Activities', 'Source schedule activities and governed analysis',
    (r.activities[0] ? prov(r.activities[0].provenance) : prov('MCP_FACT'))) +
    '<div class="toolbar">' +
    '<input class="inp" id="fq" placeholder="Search name, id or WBS" value="' +
    E(params.q || '') + '">' +
    '<select class="inp" id="fs"><option value="">Any status</option>' +
    ['not_started', 'in_progress', 'complete'].map(s => '<option ' +
      (params.status === s ? 'selected' : '') + '>' + s + '</option>').join('') +
    '</select>' +
    '<button class="btn sm' + (params.critical ? ' primary' : '') +
    '" id="fc" ' + (r.criticality_available ? '' : 'disabled title="Criticality unavailable from source"') +
    '>' + (r.criticality_available ? 'Critical only' : 'Critical N/E') + '</button>' +
    '<button class="btn sm' + (params.late ? ' primary' : '') +
    '" id="fl" ' + (r.completed_late_evaluable ? '' : 'disabled title="No completed actual finishes available for baseline comparison"') +
    '>' + (r.completed_late_evaluable ? 'Completed after reference finish' : 'Completed-after-reference N/A') + '</button>' +
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
  if (c && !c.disabled) c.onclick = () => set({ critical: params.critical ? '' : '1' });
  const l = document.getElementById('fl');
  if (l && !l.disabled) l.onclick = () => set({ late: params.late ? '' : '1' });
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
  const asem = d.schedule_semantics || {};
  const activityCriticalAvailable = !!asem.criticality_available;
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
    (activityCriticalAvailable && a.critical ? ' · on the critical path' : '') + '</div></div>' +
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
    stat('Total float', activityCriticalAvailable && a.total_float_days !== null && a.total_float_days !== undefined
      ? num(a.total_float_days, 1) + 'd' : 'N/E',
      activityCriticalAvailable ? (a.critical ? 'critical' : 'source/engine float') : 'float/criticality unavailable from source',
      activityCriticalAvailable && (a.total_float_days || 0) < 0 ? 'hot' : '') +
    stat('Finish variance', num(a.finish_variance_days, 1) + 'd',
      a.baseline_finish ? 'vs baseline ' + day(a.baseline_finish) : 'no baseline',
      (a.finish_variance_days || 0) > 0 ? 'hot' : 'good') +
    '</div>' +

    '<div class="grid g2">' +
    panel('Schedule facts <small>' + E(a.provenance || 'MCP_FACT') + '</small>',
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
      row('Schedule resource labels', E(a.resource_names || '—')) +
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
  const types = ['FS', 'SS', 'FF', 'SF', 'unspecified'];
  return head('Relationships', 'Dependency network', prov('MCP_FACT')) +
    '<div class="grid g4" style="margin-bottom:14px">' +
    types.map(t => stat(t, int(r.by_type[t] || 0),
      t === 'FS' ? 'finish to start' : t === 'SS' ? 'start to start'
        : t === 'FF' ? 'finish to finish' : t === 'SF' ? 'start to finish'
        : 'type not supplied by source')).join('') +
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
        '<td class="r mono">' + (x.lag_days === null || x.lag_days === undefined ? '—' : num(x.lag_days, 0) + 'd') + '</td>' +
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
  const critAvailable = !!r.criticality_available;
  return head('Critical path', 'Driving work and float distribution',
    critAvailable ? prov('MCP_FACT') : prov('DETERMINISTIC_CALCULATION')) +
    '<div class="note ' + (critAvailable ? 'mcp' : 'warn') + '" style="margin-bottom:14px">' + E(r.basis) +
    (critAvailable ? '. VEDA does not run its own CPM engine.' : '') + '</div>' +
    '<div class="grid g3" style="margin-bottom:14px">' +
    stat('Critical activities', critAvailable ? int(r.critical.length) : 'N/E',
      critAvailable ? (E(r.criticality_basis || 'source/engine criticality method') +
      (r.criticality_threshold_days !== null && r.criticality_threshold_days !== undefined
        ? ' · threshold ' + num(r.criticality_threshold_days, 2) + 'd' : '')) : 'criticality unavailable from source',
      critAvailable && r.critical.length ? 'warm' : '') +
    stat('Negative float', critAvailable ? int(fd.negative || 0) : 'N/E',
      critAvailable ? 'cannot meet constraints' : 'float unavailable from source',
      critAvailable && fd.negative ? 'hot' : '') +
    stat('Project finish', r.finish ? day(r.finish) : 'N/E',
      r.finish ? 'current forecast' : 'current forecast unavailable') +
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
        { t: 'Finish' }, { t: 'Float', r: true }, { t: 'Recorded schedule %', r: true }],
      r.critical, a =>
        '<tr class="click crit" onclick="go(\'activity\',{id:' + a.uid + '})">' +
        '<td class="mono">' + E(a.uid) + '</td><td class="trunc">' + E(a.name) +
        '</td><td class="mono">' + E(a.wbs) + '</td>' +
        '<td class="mono">' + day(a.start) + '</td>' +
        '<td class="mono">' + day(a.finish) + '</td>' +
        '<td class="r mono ' + ((a.total_float_days || 0) < 0 ? 'sev-critical' : '') +
        '">' + num(a.total_float_days, 1) + '</td>' +
        '<td class="r mono">' + num(a.percent_complete, 0) + '%</td></tr>',
      { emptyTitle: critAvailable ? 'No critical activities' : 'Criticality not evaluated',
        emptyMsg: critAvailable ? '' : 'The selected source does not establish critical/float semantics.' })) +
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
  const g = s.semanticGuard || {};
  return head('Schedule QA', 'Source-evaluable DCMA/Horizun checks',
    prov('MCP_FACT') + ' ' + prov('DETERMINISTIC_CALCULATION')) +
    '<div class="grid g4" style="margin-bottom:14px">' +
    stat('Evaluable-check pass rate', num(r.health_score, 1) + '%', 'passed / evaluated checks only; not-evaluated checks are excluded',
      r.health_score < 60 ? 'hot' : 'good') +
    stat('Passed', int(s.passed), '', 'good') +
    stat('Failed', int(s.failed), '', s.failed ? 'hot' : '') +
    stat('Not evaluated', int(s.notEvaluated),
      'reported honestly, never passed') +
    '</div>' +
    '<div class="note mcp" style="margin-bottom:14px">' + E(r.basis) + '</div>' +
    (g.applied ? '<div class="note" style="margin-bottom:14px">' +
      '<b>Source-semantic guard applied.</b> ' +
      (g.sourceFormat ? E(String(g.sourceFormat).toUpperCase()) + ': ' : '') +
      (g.sourceFormat && String(g.sourceFormat).toLowerCase() !== 'xer'
        ? ((g.baselineValuesAvailable ? 'embedded baseline/reference values available' : 'baseline/reference values unavailable') +
          ' · ' + (g.criticalityAvailable ? 'criticality available' : 'criticality unavailable') +
          ' · ' + (g.relationshipTypesAvailable ? 'relationship types available' : 'relationship types unavailable') +
          ' · ' + (g.resourceAssignmentsAvailable ? 'resource assignments available' : 'resource assignments unavailable'))
        : ((g.forecastValuesAvailable ? 'current forecast dates available' : 'current forecast dates unavailable') + ' · ' +
          (g.baselineAssigned ? 'assigned baseline present' : 'assigned baseline absent'))) +
      (g.dataDate ? ' · data date ' + day(g.dataDate) : ' · data/status date unavailable') + '</div>' : '') +
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
      '</span>' + prov(f.provenance) + '<span class="sev-' +
      E(String(f.severity || '').toLowerCase()) +
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
          ((v.kind === 'clarification' || (v.options || []).length) ? '</div>' : '<input class="inp" placeholder="Type answer" data-free="' + E(v.id) + '"><button class="btn primary" data-free-go="' + E(v.id) + '">Answer</button></div>')
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
    window.toast('Decision applied. Project state updated immediately.', 'good');
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

/* ================================================ Needs Attention */
function reviewKindLabel(kind) {
  return ({ clarification: 'Activity match', security_review: 'Source security',
    failed_validation: 'Processing failure' })[kind] ||
    String(kind || 'Decision').replace(/_/g, ' ');
}

function candidateExplanation(c, rid) {
  const probability = c.probability === null || c.probability === undefined
    ? null : Math.max(0, Math.min(100, Number(c.probability) * 100));
  const confidence = probability === null
    ? (c.rank_score === null || c.rank_score === undefined
      ? '<span class="match-score neutral">Not scored</span>'
      : '<span class="match-score neutral">Rank ' + num(c.rank_score, 3) + '</span>')
    : '<span class="match-score ' + (probability >= 90 ? 'strong' : probability >= 70 ? 'review' : 'weak') + '">' +
      num(probability, 0) + '% ' + (c.calibration_is_empirical ? 'calibrated' : 'cold-start estimate') + '</span>';
  const support = (c.supporting_signals || []).length
    ? '<div class="signal-list supports">' + (c.supporting_signals || []).map(s =>
        '<span><i>+</i>' + E(s) + '</span>').join('') + '</div>'
    : '<div class="signal-empty">No positive signal explanation was stored.</div>';
  const conflict = (c.conflicting_signals || []).length
    ? '<div class="signal-list conflicts">' + (c.conflicting_signals || []).map(s =>
        '<span><i>!</i>' + E(s) + '</span>').join('') + '</div>' : '';
  const option = c.option_label || '';
  return '<article class="candidate-card">' +
    '<div class="candidate-head"><div><div class="candidate-id">' +
      E(c.display_id || ('UID ' + c.uid)) + (c.critical ? ' · CRITICAL' : '') +
      '</div><h4>' + E(c.name || 'Unnamed schedule activity') + '</h4></div>' +
      confidence + '</div>' +
    '<div class="candidate-meta">' +
      (c.wbs ? '<span>' + E(c.wbs) + '</span>' : '') +
      '<span>' + day(c.planned_start) + ' → ' + day(c.planned_finish) + '</span>' +
      (c.status ? '<span>' + E(c.status.replace(/_/g, ' ')) + '</span>' : '') +
      (c.matched_records ? '<span>' + int(c.matched_records) + ' record(s)</span>' : '') +
    '</div><div class="candidate-signals"><div><b>Why it fits</b>' + support +
      '</div>' + (conflict ? '<div><b>What conflicts</b>' + conflict + '</div>' : '') +
    '</div>' +
    (option ? '<button class="btn primary choose-match" data-attention-answer="' +
      E(option) + '" data-rid="' + E(rid) + '">Confirm this activity</button>' : '') +
    '</article>';
}

function attentionReviewCard(v) {
  const options = v.options || [];
  const candidates = v.candidate_explanations || [];
  const leave = options.find(o => o === 'Leave unassigned for now');
  const samples = v.affected_sample || [];
  return '<article class="inbox-item"><header><div><div class="eyebrow">' +
    E(reviewKindLabel(v.kind)) + '</div><h2>' + E(v.title) + '</h2></div>' +
    '<div class="inbox-item-meta">' +
      (v.priority === 'high' ? '<span class="tag amber">High priority</span>' : '') +
      '<span class="count-pill">' + int(v.affected_count || 1) +
      ' record' + (Number(v.affected_count || 1) === 1 ? '' : 's') + '</span>' +
    '</div></header><div class="inbox-question">' + E(v.question) + '</div>' +
    '<div class="review-workspace"><section class="evidence-pane">' +
      '<div class="pane-label"><span>Field evidence</span><small>What was reported</small></div>' +
      (samples.length ? samples.map(s => '<button class="evidence-quote" data-open-evidence="' +
        E(s.id) + '"><span>“' + E(s.description) + '”</span><small>' +
        E(s.source_file || 'Source') + (s.locator ? ' · ' + E(s.locator) : '') +
        ' · ' + day(s.date) + (s.discipline ? ' · ' + E(s.discipline) : '') +
        '</small></button>').join('') : '<div class="signal-empty">No sample rows available.</div>') +
      (v.detail ? '<div class="review-note">' + E(v.detail) + '</div>' : '') +
    '</section><section class="candidate-pane">' +
      '<div class="pane-label"><span>Schedule candidates</span><small>Why VEDA suggested them</small></div>' +
      (candidates.length ? candidates.map(c => candidateExplanation(c, v.id)).join('') :
        '<div class="generic-options">' + options.filter(o => o !== leave).map(o =>
          '<button class="btn" data-attention-answer="' + E(o) + '" data-rid="' +
          E(v.id) + '">' + E(o) + '</button>').join('') + '</div>') +
    '</section></div>' +
    '<footer class="inbox-actions"><span>No official schedule value changes here. ' +
      'This decision only settles the evidence-to-activity identity.</span><div class="spacer"></div>' +
      (leave ? '<button class="btn" data-attention-answer="' + E(leave) +
        '" data-rid="' + E(v.id) + '">Leave unassigned</button>' : '') +
      (!options.length ? '<input class="inp" data-attention-free="' + E(v.id) +
        '" placeholder="Type your answer"><button class="btn primary" data-attention-free-go="' +
        E(v.id) + '">Apply</button>' : '') + '</footer></article>';
}

function inboxFilterCard(id, label, count, detail, current, tone) {
  return '<button class="inbox-filter ' + (tone || '') + (current === id ? ' active' : '') +
    '" data-inbox-focus="' + E(id) + '"><span>' + E(label) + '</span><b>' +
    int(count || 0) + '</b><small>' + E(detail) + '</small></button>';
}

VIEWS.attention = async (pid, params) => {
  const r = await A('/projects/' + pid + '/attention');
  const ps = r.state || {};
  const counts = r.inbox_counts || {};
  const focus = params.focus || 'all';
  const reviews = (r.reviews || []).filter(v => focus === 'all' ||
    (focus === 'matches' && v.kind === 'clarification') ||
    (focus === 'security' && v.kind === 'security_review') ||
    (focus === 'failures' && v.kind === 'failed_validation'));
  const proposals = focus === 'all' || focus === 'changes' ? (r.proposals || []) : [];
  const stateNote = '<div class="note ' + (ps.code === 'retry' ? 'danger' : ps.code === 'needs_input' || ps.code === 'choose_schedule' ? 'warn' : '') + '" style="margin-bottom:14px"><b>' + E(ps.label || 'Project state') + '</b><br>' + E(ps.detail || '') + '</div>';
  const reviewHtml = reviews.length ? reviews.map(attentionReviewCard).join('') : '';
  const proposalHtml = proposals.length ? '<div class="section-divider"><span>Governed schedule changes</span><small>Dry-run and approval required</small></div>' + proposals.map(proposalCard).join('') : '';
  const deferred = r.deferred_evidence ? '<div class="note" style="margin-top:12px"><b>' + int(r.deferred_evidence) + ' evidence record(s) deliberately left unassigned.</b><br>These are deferred by a human choice, not unresolved by the system.</div>' : '';
  const recent = (r.recent_decisions || []).length ? '<details class="recent-decisions"><summary>Recent evidence decisions <span>' + int((r.recent_decisions || []).length) + '</span></summary>' + (r.recent_decisions || []).map(v =>
    '<div class="review"><div class="h"><h3>' + E(v.title) + '</h3><span class="tag green">' + E(v.status) + '</span></div>' +
    '<div class="q"><b>' + E(v.answer || '') + '</b></div><div class="opts"><button class="btn" data-change-decision="' + E(v.id) + '">Change decision</button></div></div>').join('') + '</details>' : '';
  const noReviewException = r.unresolved_evidence && !r.reviews.length
    ? '<div class="note warn"><b>' + int(r.unresolved_evidence) +
      ' unresolved evidence row(s) have no open review question.</b><br>' +
      'Open the evidence workbench to inspect them individually. ' +
      '<button class="btn sm" onclick="go(\'evidence\',{state:\'needs_review\'})">Open evidence</button></div>' : '';
  return head('Review Inbox', 'Resolve exceptions, not spreadsheets',
      '<span class="tag grey">Evidence identity layer</span>') +
    '<div class="review-brief"><div><div class="eyebrow">Decision brief</div>' +
      '<h2>' + (r.attention_count ? int(r.attention_count) + ' item' +
        (Number(r.attention_count) === 1 ? '' : 's') + ' need a person' : 'No decisions waiting') +
      '</h2><p>Every match shows its source, schedule candidate, supporting evidence, ' +
      'contradictions, and confidence basis before you act.</p></div>' +
      '<div class="safety-rule"><b>Write safety</b><span>Confirming a match never writes to the schedule. ' +
      'Actuals still require validation, dry-run, approval, and verification.</span></div></div>' +
    '<div class="inbox-filters">' +
      inboxFilterCard('all', 'All open', r.attention_count, 'everything requiring action', focus, 'primary') +
      inboxFilterCard('matches', 'Activity matches', counts.matches, 'semantic links to confirm', focus) +
      inboxFilterCard('changes', 'Schedule changes', counts.changes, 'governed write proposals', focus, 'warn') +
      inboxFilterCard('security', 'Source security', counts.security, 'quarantined-file decisions', focus, 'danger') +
      inboxFilterCard('failures', 'Processing failures', counts.failures, 'retry or keep safe fallback', focus) +
    '</div>' + stateNote + noReviewException +
    (reviewHtml || proposalHtml ? reviewHtml + proposalHtml + deferred + recent :
      panel('Nothing in this queue', empty('Up to date', focus === 'all'
        ? 'New uploads and completed decisions flow into the project automatically.'
        : 'Choose another inbox category or return when new evidence arrives.')) + recent + deferred);
};

VIEWS.bind_attention = (pid) => {
  document.querySelectorAll('[data-inbox-focus]').forEach(b => b.onclick = () =>
    go('attention', { focus: b.dataset.inboxFocus }));
  document.querySelectorAll('[data-open-evidence]').forEach(b => b.onclick = () =>
    go('evidence-detail', { id: b.dataset.openEvidence }));
  const send = async (rid, answer) => {
    if (!answer) return;
    try {
      const r = await P('/reviews/' + rid + '/answer', {answer, by:'site.engineer'});
      const e = r.effect || {};
      let msg = 'Decision applied immediately.';
      if (e.assigned) msg = e.assigned + ' record(s) linked to ' + (e.activity_display_id || e.activity_name || 'the selected activity') + '.';
      else if (e.deferred) msg = e.deferred + ' record(s) left unassigned for now.';
      window.toast(msg, 'good');
      await window.refreshCounts(); window.render();
    } catch (err) { window.toast(err.message, 'bad'); }
  };
  document.querySelectorAll('[data-attention-answer]').forEach(b => b.onclick = () => send(b.dataset.rid, b.dataset.attentionAnswer));
  document.querySelectorAll('[data-attention-free-go]').forEach(b => b.onclick = () => {
    const rid=b.dataset.attentionFreeGo; const i=document.querySelector('[data-attention-free="'+rid+'"]'); send(rid, i && i.value);
  });
  document.querySelectorAll('[data-change-decision]').forEach(b => b.onclick = async () => {
    try {
      await P('/reviews/' + b.dataset.changeDecision + '/reopen', {by:'site.engineer'});
      window.toast('Decision reopened. Choose the correct activity below.', 'good');
      await window.refreshCounts(); window.render();
    } catch (err) { window.toast(err.message, 'bad'); }
  });
  if (VIEWS.bind_proposals) VIEWS.bind_proposals(pid);
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
  const [r, p6] = await Promise.all([
    A('/projects/' + pid + '/proposals'),
    A('/integrations/primavera/status').catch(() => ({configured: false, gates: {}})),
  ]);
  const gates = p6.gates || {};
  return head('Proposed changes', 'Nothing is written without a dry-run and ' +
    'an approval') +
    '<div class="note warn" style="margin-bottom:14px">' +
    'Agent proposes → validators → Horizun dry-run → impact → human approval → ' +
    'verified write. VEDA reports success only after independently re-reading ' +
    'the value.</div>' +
    panel('Primavera sandbox adapter', '<div class="body"><div class="integration-status">' +
      '<div><span class="integration-beacon ' + (p6.configured ? 'ready' : '') + '"></span>' +
      '<div><b>' + E(p6.configured ? 'P6 REST connection configured' : 'P6 REST connection not configured') + '</b>' +
      '<small>' + E(p6.note || '') + '</small></div></div>' +
      '<div class="integration-gates">' +
      [['Sandbox', gates.sandbox_environment], ['Writes armed', p6.writes_armed],
       ['Project allow-list', gates.project_allowlist], ['Activity IDs', gates.activity_id_mapping],
       ['Duration units', gates.duration_conversion]].map(x =>
        '<span class="' + (x[1] ? 'ok' : '') + '"><i>' + (x[1] ? '✓' : '–') + '</i>' + E(x[0]) + '</span>').join('') +
      '</div></div><div class="note" style="margin-top:11px">The adapter maps only approved Actual Start, Actual Finish, Percent Complete, and Remaining Duration proposals. Production writes are disabled in this release; sandbox writes require OAuth, an explicit ProjectObjectId allow-list, and verified activity ID mapping.</div></div>') +
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
    window.toast('Question accepted. The answer will appear here when ready.', 'good');
    t.value = '';
    await window.refreshCounts();
    window.render();
  };
};

/* =============================================== 21. Execution intelligence */
const RUN_PHASE_ORDER = {
  queued: 0, files_received: 0,
  mcp_health: 1, schedule_detected: 1, schedule_reused: 1,
  schedule_parsed: 1, schedule_loaded: 1, schedule_snapshot: 1,
  evidence_quarantined: 2, evidence_processed: 2, evidence_reused: 2,
  agent_invoked: 3, agent_status: 3, agent_unavailable: 3,
  agent_error: 3, agent_failed: 3, tool_call: 3,
  structured_output_rejected: 3, structured_output_partial: 3,
  provider_selected: 3, fallback_analysis: 3,
  output_ready: 4, resolver_indexing: 4, resolver_experts: 4,
  resolver_ranking: 4, resolver_validating: 5, dry_run_complete: 5,
  resolver_persisting: 6,
  associations_validated: 6, human_review_required: 7,
};

function runContext(job, activity) {
  const names = new Set((activity || []).map(a => a.step));
  let phase = job ? String(job.phase || 'queued') : 'queued';
  let ordinal = RUN_PHASE_ORDER[phase];
  if (ordinal === undefined) {
    if (names.has('human_review_required')) ordinal = 7;
    else if (names.has('associations_validated')) ordinal = 6;
    else if (names.has('output_ready')) ordinal = 4;
    else if (names.has('agent_invoked')) ordinal = 3;
    else if (names.has('evidence_processed')) ordinal = 2;
    else if (names.has('mcp_health')) ordinal = 1;
    else ordinal = 0;
  }
  const status = job ? String(job.status || 'queued') : 'empty';
  const latest = (activity || [])[0] || null;
  return { phase, ordinal, status, latest, names };
}

VIEWS._runPlayback = VIEWS._runPlayback || {};

function presentedRunContext(job, activity) {
  const actual = runContext(job, activity);
  if (!job || actual.status === 'empty' ||
      actual.status === 'failed' || actual.status === 'cancelled') {
    return { ...actual, actualOrdinal: actual.ordinal, catchingUp: false };
  }

  const now = Date.now();
  let playback = VIEWS._runPlayback[job.id];
  if (!playback) {
    // A terminal job opened from history should be immediately truthful. A
    // live job starts at Sources, then replays only stages the server persisted.
    const firstOrdinal = actual.status === 'done' ? actual.ordinal : 0;
    playback = VIEWS._runPlayback[job.id] = {
      ordinal: Math.min(firstOrdinal, actual.ordinal), lastAdvance: now,
    };
  }
  if (actual.ordinal < playback.ordinal) {
    playback.ordinal = actual.ordinal;
    playback.lastAdvance = now;
  } else if (actual.ordinal > playback.ordinal && now - playback.lastAdvance >= 620) {
    playback.ordinal += 1;
    playback.lastAdvance = now;
  }
  const catchingUp = playback.ordinal < actual.ordinal;
  return {
    ...actual,
    actualOrdinal: actual.ordinal,
    ordinal: playback.ordinal,
    status: actual.status === 'done' && catchingUp ? 'running' : actual.status,
    catchingUp,
  };
}

function runState(level, ctx, guarded) {
  if (guarded) return 'guarded';
  if (ctx.status === 'empty') return 'pending';
  if (ctx.status === 'failed' || ctx.status === 'cancelled') {
    if (level < ctx.ordinal) return 'done';
    if (level === ctx.ordinal) return 'failed';
    return 'pending';
  }
  if (ctx.status === 'done') return 'done';
  if (level < ctx.ordinal) return 'done';
  if (level === ctx.ordinal) return 'active';
  return 'pending';
}

function runNode(level, ctx, title, question, meta, delay, guarded) {
  const state = runState(level, ctx, guarded);
  const slug = String(title).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '');
  const marker = state === 'done' ? '✓' : state === 'failed' ? '!' :
    state === 'guarded' ? '◇' : '•';
  return '<div class="arch-node node-' + slug + ' ' + state + '">' +
    '<span class="arch-marker" aria-hidden="true">' +
    marker + '</span><div><b>' + E(title) + '</b>' +
    (question ? '<em>' + E(question) + '</em>' : '') +
    (meta ? '<small>' + E(meta) + '</small>' : '') + '</div></div>';
}

function runConnector(level, ctx) {
  return '<div class="arch-connector ' + runState(level, ctx, false) +
    '" aria-hidden="true"><i></i></div>';
}

function runDuration(job) {
  if (!job) return 'Awaiting a run';
  const start = Number(job.started_at || job.created_at || 0);
  const end = Number(job.finished_at || Date.now() / 1000);
  if (!start) return 'Duration unavailable';
  const seconds = Math.max(0, Math.round(end - start));
  if (seconds < 60) return seconds + 's elapsed';
  return Math.floor(seconds / 60) + 'm ' + (seconds % 60) + 's elapsed';
}

function executionMap(job, activity) {
  const ctx = presentedRunContext(job, activity);
  const phaseLabel = String(ctx.phase || 'queued').replace(/_/g, ' ');
  const needsReview = ctx.names.has('human_review_required');
  const statusLabel = ctx.status === 'done' ? 'Analysis complete' :
    ctx.status === 'failed' ? 'Run stopped safely' :
    ctx.status === 'cancelled' ? 'Run cancelled' :
    ctx.status === 'empty' ? 'Ready for sources' : 'Live execution';
  const statusClass = ctx.status === 'done' ? 'done' :
    (ctx.status === 'failed' || ctx.status === 'cancelled') ? 'failed' :
    ctx.status === 'empty' ? 'idle' : 'running';
  const milestones = [
    [0, 'Sources'], [1, 'Schedule'], [2, 'Evidence'], [3, 'Reasoning'],
    [4, 'Resolver'], [6, 'Controls'], [7, 'Decision'],
  ];

  return '<section class="intelligence-run ' + statusClass + '" aria-label="VEDA execution status"' +
    ' data-run-job="' + E(job ? job.id : '') + '"' +
    ' data-run-display="' + E(ctx.ordinal) + '"' +
    ' data-run-actual="' + E(ctx.actualOrdinal) + '"' +
    ' data-run-terminal="' + E(job ? job.status : '') + '"' +
    (statusClass === 'running' ? ' aria-busy="true"' : '') + '>' +
    '<header class="run-header"><div class="run-title">' +
      '<div class="eyebrow">Persisted execution intelligence</div>' +
      '<h2>Field truth → governed schedule decision</h2>' +
      '<p>Every highlight is derived from the latest stored job phase. ' +
      'The resolver ensemble is shown as one governed execution stage.</p></div>' +
      '<div class="run-status"><span class="run-beacon" aria-hidden="true"></span>' +
      '<div><b>' + E(statusLabel) + '</b><small>' + E(phaseLabel) + ' · ' +
      E(runDuration(job)) + '</small></div></div></header>' +
    '<div class="run-milestones" aria-label="Execution stages">' +
      milestones.map(([level, label]) => {
        const state = runState(level, ctx, false);
        return '<div class="run-milestone ' + state + '"' +
          (state === 'active' ? ' aria-current="step"' : '') + '>' +
          '<i aria-hidden="true"></i><span>' + E(label) + '</span></div>';
      }).join('') + '</div>' +
    '<div class="architecture-map">' +
      '<div class="map-caption"><span>Live architecture</span>' +
      '<small>WHAT × WHERE × CHANGED WORLD</small></div>' +
      runNode(0, ctx, 'Field observation', 'What changed on site?',
        'DPR · note · report · image', 0, false) +
      runConnector(4, ctx) +
      runNode(4, ctx, 'Semantic candidate floor', 'Which activities are plausible?',
        'Candidate retrieval · no forced match', 80, false) +
      '<div class="arch-fork ' + runState(4, ctx, false) + '">' +
        runNode(4, ctx, 'Engineering', 'WHAT?', 'Scope and workface semantics', 150, false) +
        runNode(4, ctx, 'Tree', 'WHERE?', 'WBS · location · hierarchy', 230, false) +
        runNode(4, ctx, 'Rescheduler v2', 'CHANGED WORLD?', 'Revision-aware candidate lists', 310, false) +
      '</div>' +
      runConnector(4, ctx) +
      runNode(4, ctx, 'Candidate union', 'Four candidate lists converge',
        'Stable activity identity retained', 390, false) +
      '<div class="arch-split ' + runState(4, ctx, false) + '">' +
        runNode(4, ctx, 'Expert utility predictors', '', 'Specialist ranking signals', 470, false) +
        runNode(4, ctx, 'Candidate-level evidence', '', 'Support · conflict · provenance', 540, false) +
      '</div>' +
      runConnector(4, ctx) +
      runNode(4, ctx, 'LambdaMART MetaRank', 'Which activity best explains the observation?',
        'Learned ensemble · evidence-aware', 620, false) +
      runConnector(4, ctx) +
      runNode(4, ctx, 'Final activity rank', 'Best supported identity',
        'Confidence remains calibrated', 700, false) +
      '<div class="gate-chain">' +
        runNode(5, ctx, 'Calibration', '', 'Uncertainty made explicit', 780, false) +
        runNode(5, ctx, 'Deterministic validators', '', 'Rules · dates · relationships', 850, false) +
        runNode(6, ctx, 'Risk policy', '', 'Safe action boundary', 920, false) +
        runNode(7, ctx, 'Review / identity link', '',
          needsReview ? 'Human decision required' : 'No forced identity', 990, false) +
        runNode(8, ctx, 'Schedule-write gates', '', 'Human approval only', 1060, true) +
      '</div>' +
    '</div>' +
    '<footer class="run-footer"><div class="run-legend">' +
      '<span class="done"><i></i>Persisted complete</span>' +
      '<span class="active"><i></i>Current stage</span>' +
      '<span class="pending"><i></i>Waiting</span>' +
      '<span class="guarded"><i></i>Governed boundary</span></div>' +
      '<div class="run-latest"><span>Latest durable event</span><b>' +
      E(ctx.latest ? ctx.latest.label : 'No execution events yet') + '</b></div>' +
    '</footer></section>';
}

VIEWS.agent = async (pid) => {
  const [act, mcp, jobs] = await Promise.all([
    A('/projects/' + pid + '/agent-activity?limit=140'),
    A('/projects/' + pid + '/mcp-calls?limit=60'),
    A('/projects/' + pid + '/jobs?limit=1'),
  ]);
  const j = jobs.jobs[0];
  const currentActivity = j
    ? act.activity.filter(a => String(a.job_id || '') === String(j.id || ''))
    : [];
  return head('Execution intelligence', 'A live, evidence-safe view of VEDA’s ' +
    'persisted run state') +
    executionMap(j, currentActivity) +
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
    '<details class="run-details"><summary>Run evidence & technical log' +
      '<span>' + act.activity.length + ' steps · ' + mcp.calls.length +
      ' Horizun calls</span></summary><div class="grid g2">' +
    panel('Persisted steps <small>' + act.activity.length + '</small>',
      '<div class="feed">' + (act.activity.length ? act.activity.map(a =>
      '<div class="row ' + (a.state === 'failed' ? 'fail' : '') +
      (a === act.activity[0] && j && !['done', 'failed', 'cancelled'].includes(j.status)
        ? ' run' : '') + '">' +
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
    '</div></details>';
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
  const pendingBatch = (r.batches || []).find(x => x.status === 'awaiting_schedule');
  const pendingCandidates = pendingBatch ? (r.files || []).filter(f =>
    f.batch_id === pendingBatch.id && f.kind === 'schedule').map(f => ({
      id: f.id, filename: f.filename, relative_path: f.relative_path || f.filename,
      alternate_hint: /extended|extension|recovery|alternate|alternative|draft|what[-_ ]?if/i.test(f.relative_path || f.filename)
    })) : [];
  const stagedHtml = staged.length ? staged.map((f, i) =>
    '<div style="display:flex;gap:9px;align-items:center;padding:7px 0;' +
    'border-bottom:1px solid var(--line)"><span style="flex:1">' +
    E(f._vedaRelativePath || f.webkitRelativePath || f.name) + ' <span class="mono" style="color:var(--ink-3)">' +
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
      '<button class="btn" id="pickfiles" type="button">Browse files</button> ' +
      '<button class="btn" id="pickfolder" type="button">Browse project folder</button>' +
      '<input type="file" id="fileinput" multiple accept="' + accept + '" hidden>' +
      '<input type="file" id="folderinput" multiple webkitdirectory directory hidden>' +
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
      '<div style="display:flex;align-items:center;gap:10px;margin-top:13px;flex-wrap:wrap">' +
      '<button class="btn primary" id="up">Ingest & analyse automatically</button>' +
      '<span id="ingestsummary" style="color:var(--ink-3);font-size:12px">' +
      staged.length + ' file(s) staged' + (st.text ? ' + pasted text' : '') +
      '</span></div>' +
      '<div class="ingest-live" id="ingest-live" hidden aria-live="polite">' +
        '<div class="ingest-live-head"><span class="run-beacon"></span><div>' +
        '<b>Secure source intake underway</b><small>No reload needed — the live ' +
        'execution map opens as soon as the run is created.</small></div></div>' +
        '<div class="ingest-lanes">' +
          '<span><i>01</i><b>Transfer batch</b><small>Files + pasted field truth</small></span>' +
          '<span><i>02</i><b>Integrity checks</b><small>SHA-256 · duplicates · security</small></span>' +
          '<span><i>03</i><b>Create run</b><small>Immutable sources → analysis</small></span>' +
        '</div>' +
      '</div></div>') +
    (pendingBatch ? panel('Schedule selection required <small>' + pendingCandidates.length + ' candidates</small>',
      '<div class="body"><div class="note warn" style="margin-bottom:10px">This project folder contains multiple schedule revisions. VEDA has paused before choosing one.</div>' +
      '<button class="btn primary" data-choose-schedule-batch="' + E(pendingBatch.id) + '">Choose authoritative schedule</button></div>') : '') +
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
        '<tr><td>' + E(f.relative_path || f.filename) + '</td>' +
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
            'the agent. Resolve it under Needs Attention.</span></div>').join('') +
        '</div>') : '');
};
VIEWS.choose_schedule_candidate = (pid, batchId, candidates) => new Promise((resolve) => {
  const old = document.getElementById('schedule-choice-scrim');
  if (old) old.remove();
  let selected = null;
  const scrim = document.createElement('div');
  scrim.className = 'scrim'; scrim.id = 'schedule-choice-scrim';
  scrim.innerHTML = '<section class="modal" style="max-width:720px"><header>' +
    '<div><div class="eyebrow">Schedule candidates</div><h2>Choose the authoritative schedule</h2></div></header>' +
    '<div class="body"><div class="note warn" style="margin-bottom:12px">VEDA found multiple schedule-shaped files. It will not silently treat an EXTENDED / recovery / alternate revision as current.</div>' +
    '<div id="schedule-choice-list"></div><div class="modal-actions"><button class="btn" id="schedule-choice-cancel">Cancel</button>' +
    '<div class="spacer"></div><button class="btn primary" id="schedule-choice-go" disabled>Use selected schedule</button></div></div></section>';
  document.body.appendChild(scrim);
  const list = scrim.querySelector('#schedule-choice-list');
  const draw = () => {
    list.innerHTML = candidates.map(c => '<button class="delete-project-row' + (selected === c.id ? ' selected' : '') +
      '" data-schedule-choice="' + E(c.id) + '"><span class="delete-radio">' + (selected === c.id ? '●' : '') +
      '</span><span class="delete-project-copy"><b>' + E(c.relative_path || c.filename) + '</b><small>' +
      (c.alternate_hint ? 'Looks like an alternate / extended / recovery revision' : 'Detected schedule candidate') +
      '</small></span>' + (c.alternate_hint ? '<span class="tag amber">alternate?</span>' : '') + '</button>').join('');
    list.querySelectorAll('[data-schedule-choice]').forEach(x => x.onclick = () => { selected = x.dataset.scheduleChoice; draw(); });
    scrim.querySelector('#schedule-choice-go').disabled = !selected;
  };
  draw();
  scrim.querySelector('#schedule-choice-cancel').onclick = () => { scrim.remove(); resolve(false); };
  scrim.onclick = (e) => { if (e.target === scrim) { scrim.remove(); resolve(false); } };
  scrim.querySelector('#schedule-choice-go').onclick = async () => {
    const goBtn = scrim.querySelector('#schedule-choice-go'); goBtn.disabled = true; goBtn.textContent = 'Starting analysis…';
    try {
      const r = await P('/projects/' + pid + '/ingest/' + batchId + '/select-schedule', { file_id: selected });
      const chosen = candidates.find(c => c.id === selected);
      scrim.remove();
      window.toast('Authoritative schedule selected. Analysis started automatically.', 'good');
      if (r && r.job_id) go('agent'); else window.render();
      resolve(true);
    } catch (e) { goBtn.disabled = false; goBtn.textContent = 'Use selected schedule'; window.toast(e.message, 'bad'); }
  };
});

VIEWS.bind_files = (pid) => {
  VIEWS._ingestState = VIEWS._ingestState || {};
  const st = VIEWS._ingestState[pid] ||
    (VIEWS._ingestState[pid] = { files: [], text: '', mode: 'field_note', title: '' });
  const inp = document.getElementById('fileinput');
  const dz = document.getElementById('ingestdrop');
  const pick = document.getElementById('pickfiles');
  const pickFolder = document.getElementById('pickfolder');
  const folderInp = document.getElementById('folderinput');
  const list = document.getElementById('stagedfiles');
  const text = document.getElementById('pastetext');
  const mode = document.getElementById('textmode');
  const title = document.getElementById('texttitle');
  const b = document.getElementById('up');
  const live = document.getElementById('ingest-live');
  if (!b || !inp) return;
  document.querySelectorAll('[data-choose-schedule-batch]').forEach(x => x.onclick = async () => {
    const batchId = x.dataset.chooseScheduleBatch;
    const rr = await A('/projects/' + pid + '/files');
    const candidates = (rr.files || []).filter(f => f.batch_id === batchId && f.kind === 'schedule').map(f => ({
      id: f.id, filename: f.filename, relative_path: f.relative_path || f.filename,
      alternate_hint: /extended|extension|recovery|alternate|alternative|draft|what[-_ ]?if/i.test(f.relative_path || f.filename)
    }));
    await VIEWS.choose_schedule_candidate(pid, batchId, candidates);
  });

  const draw = () => {
    if (list) list.innerHTML = st.files.length ? st.files.map((f, i) =>
      '<div style="display:flex;gap:9px;align-items:center;padding:7px 0;' +
      'border-bottom:1px solid var(--line)"><span style="flex:1">' + E(f._vedaRelativePath || f.webkitRelativePath || f.name) +
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
      const rel = f._vedaRelativePath || f.webkitRelativePath || f.name;
      const key = [rel, f.size, f.lastModified].join('|');
      if (!st.files.some(x => [x._vedaRelativePath || x.webkitRelativePath || x.name,
          x.size, x.lastModified].join('|') === key)) st.files.push(f);
    }
    draw();
  };
  const readDirEntries = async (reader) => {
    const out = [];
    while (true) {
      const batch = await new Promise((resolve, reject) => reader.readEntries(resolve, reject));
      if (!batch.length) return out;
      out.push(...batch);
    }
  };
  const filesFromEntry = async (entry) => {
    if (!entry) return [];
    if (entry.isFile) {
      const f = await new Promise((resolve, reject) => entry.file(resolve, reject));
      try { Object.defineProperty(f, '_vedaRelativePath', { value: entry.fullPath.replace(/^\//, ''), configurable: true }); }
      catch (_) { f._vedaRelativePath = entry.fullPath.replace(/^\//, ''); }
      return [f];
    }
    if (entry.isDirectory) {
      const children = await readDirEntries(entry.createReader());
      const nested = await Promise.all(children.map(filesFromEntry));
      return nested.flat();
    }
    return [];
  };

  if (pick) pick.onclick = (e) => { e.stopPropagation(); inp.click(); };
  if (pickFolder && folderInp) pickFolder.onclick = (e) => { e.stopPropagation(); folderInp.click(); };
  inp.onchange = () => { addFiles(inp.files); inp.value = ''; };
  if (folderInp) folderInp.onchange = () => { addFiles(folderInp.files); folderInp.value = ''; };
  if (dz) {
    dz.onclick = (e) => { if (!e.target.closest('button')) inp.click(); };
    dz.ondragover = (e) => { e.preventDefault(); dz.style.opacity = '.72'; };
    dz.ondragleave = () => { dz.style.opacity = '1'; };
    dz.ondrop = async (e) => {
      e.preventDefault(); dz.style.opacity = '1';
      const items = Array.from((e.dataTransfer && e.dataTransfer.items) || []);
      const entries = items.map(x => x.webkitGetAsEntry ? x.webkitGetAsEntry() : null).filter(Boolean);
      if (entries.some(x => x.isDirectory)) {
        const nested = await Promise.all(entries.map(filesFromEntry));
        addFiles(nested.flat());
      } else addFiles(e.dataTransfer.files);
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
    for (const f of st.files) {
      fd.append('files', f);
      fd.append('relative_paths', f._vedaRelativePath || f.webkitRelativePath || f.name);
    }
    if (String(st.text || '').trim()) {
      fd.append('text', st.text.trim());
      fd.append('text_mode', st.mode || 'field_note');
      fd.append('text_title', st.title || '');
    }
    b.disabled = true; b.textContent = 'Securing sources…';
    if (live) { live.hidden = false; live.classList.add('running'); }
    try {
      const r = await fetch('/api/projects/' + pid + '/ingest',
        { method: 'POST', body: fd });
      if (!r.ok) throw new Error(await r.text());
      const j = await r.json();
      VIEWS._ingestState[pid] = { files: [], text: '', mode: 'field_note', title: '' };
      if (j.schedule_selection_required) {
        b.disabled = false; b.textContent = 'Ingest & analyse automatically';
        if (live) { live.hidden = true; live.classList.remove('running'); }
        await VIEWS.choose_schedule_candidate(pid, j.batch_id, j.schedule_candidates || []);
        return;
      }
      let msg = j.stored_count + ' new source(s) stored';
      if (j.duplicate_count) msg += ', ' + j.duplicate_count + ' duplicate(s) skipped';
      if (j.schedule_count) msg += ', ' + j.schedule_count + ' schedule revision(s)';
      window.toast(msg + (j.job_id ? '. Analysis started automatically.' : '.'), 'good');
      if (j.job_id || j.event) go('agent'); else window.render();
    } catch (e) {
      window.toast('Ingestion failed: ' + e.message, 'bad');
      b.disabled = false; b.textContent = 'Ingest & analyse automatically';
      if (live) { live.classList.remove('running'); live.classList.add('failed'); }
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
    stat('Active provider', E(h.active_provider === 'auto' &&
      (h.providers.auto || {}).selected_label
        ? 'auto → ' + h.providers.auto.selected_label : h.active_provider),
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
