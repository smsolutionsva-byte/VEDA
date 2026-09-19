/* VEDA views. Every value that came from a document or a model is escaped:
   uploaded files are untrusted data and must never render as markup. */

const VIEWS = {};
const E = (s) => window.esc(s);
const A = (p) => window.api(p);
const P = (p, b) => window.post(p, b);

/* ------------------------------------------------------------ helpers */
const day = (v) => v ? String(v).split(/[T ]/)[0] : '—';
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

function completionTrajectoryCard(data) {
  data = data || {};
  const series = data.series || [];
  if (!data.available || !series.length) {
    return '<section class="control-visual-card"><header><div><small>Schedule × field truth</small>' +
      '<h3>Completion trajectory</h3></div>' + prov('DETERMINISTIC_CALCULATION') +
      '</header>' + empty('Not evaluable', 'Finish dates are not available yet.') + '</section>';
  }
  const W = 760, H = 220, left = 38, right = 12, top = 18, bottom = 36;
  const x = i => left + i * (W - left - right) / Math.max(1, series.length - 1);
  const y = value => top + (100 - Math.max(0, Math.min(100, Number(value)))) *
    (H - top - bottom) / 100;
  const path = key => {
    let open = false, value = '';
    series.forEach((point, i) => {
      if (point[key] === null || point[key] === undefined) { open = false; return; }
      value += (open ? 'L' : 'M') + x(i) + ' ' + y(point[key]) + ' ';
      open = true;
    });
    return value.trim();
  };
  const labelEvery = Math.max(1, Math.ceil(series.length / 6));
  const labels = series.map((point, i) =>
    (i % labelEvery === 0 || i === series.length - 1)
      ? '<text class="axis" x="' + x(i) + '" y="' + (H - 8) +
        '" text-anchor="middle">' + E(String(point.period).slice(0, 7)) + '</text>' : '').join('');
  const dots = (key, cls) => series.map((point, i) =>
    point[key] === null || point[key] === undefined ? '' :
      '<rect class="' + cls + '" x="' + (x(i) - 2.5) + '" y="' +
      (y(point[key]) - 2.5) + '" width="5" height="5"><title>' +
      E(String(point.period).slice(0, 7)) + ' · ' + num(point[key], 1) + '%</title></rect>').join('');
  return '<section class="control-visual-card trajectory-card"><header><div><small>Schedule × field truth</small>' +
    '<h3>Completion trajectory</h3></div>' + prov('DETERMINISTIC_CALCULATION') + '</header>' +
    '<div class="control-chart-wrap"><svg class="control-trajectory" viewBox="0 0 ' + W + ' ' + H +
      '" preserveAspectRatio="none">' +
      [0, 25, 50, 75, 100].map(value => '<line class="grid-l" x1="' + left + '" x2="' +
        (W - right) + '" y1="' + y(value) + '" y2="' + y(value) + '"/><text class="axis y" x="' +
        (left - 7) + '" y="' + (y(value) + 3) + '" text-anchor="end">' + value + '%</text>').join('') +
      '<path class="trajectory-reference" d="' + path('reference') + '"/>' +
      '<path class="trajectory-recorded" d="' + path('recorded') + '"/>' +
      '<path class="trajectory-field" d="' + path('field_verified') + '"/>' +
      dots('reference', 'trajectory-reference-dot') + dots('recorded', 'trajectory-recorded-dot') +
      dots('field_verified', 'trajectory-field-dot') + labels + '</svg></div>' +
    '<div class="trajectory-legend"><span class="reference"><i></i>' + E(data.reference_label || 'Reference') +
      ' <b>' + int(data.reference_coverage || 0) + '/' + int(data.denominator || 0) + '</b></span>' +
      '<span class="recorded"><i></i>Recorded actual finishes <b>' + int(data.recorded_finish_coverage || 0) +
      '</b></span><span class="field"><i></i>Field-verified finishes <b>' +
      int(data.verified_finish_coverage || 0) + '</b></span></div>' +
    '<footer>' + E(data.definition || '') + '</footer></section>';
}

function activityDistributionCard(data) {
  data = data || {};
  const total = Number(data.total || 0);
  const counts = data.counts || {};
  const rows = [
    ['completed', 'Completed', 'good'], ['in_progress', 'In progress', 'warm'],
    ['not_started', 'Not started', 'muted'], ['not_evaluable', 'Not evaluable', 'unknown']
  ].filter(row => Number(counts[row[0]] || 0) || row[0] !== 'not_evaluable');
  return '<section class="control-visual-card distribution-card"><header><div><small>Source schedule</small>' +
    '<h3>Activity distribution</h3></div>' + prov('MCP_FACT') + '</header>' +
    (data.available ? '<div class="distribution-body">' + rows.map(row => {
      const count = Number(counts[row[0]] || 0);
      const pct = total ? count * 100 / total : 0;
      return '<div class="distribution-row ' + row[2] + '"><div><span>' + row[1] + '</span><b>' +
        int(count) + ' <small>' + num(pct, 0) + '%</small></b></div><div class="distribution-track"><i style="width:' +
        Math.max(0, Math.min(100, pct)) + '%"></i></div></div>';
    }).join('') + '</div><footer>' + E(data.basis || '') + ' · ' + int(total) + ' source activities</footer>' :
      empty('Not evaluable', 'No leaf activities are available.')) + '</section>';
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
  running: 'blue', queued: 'grey', awaiting_review: 'amber', partial: 'amber',
  monitoring: 'blue', cleared: 'green', waived: 'violet', ready: 'green',
  blocked: 'red', attention: 'amber', not_assessed: 'grey', proposed: 'violet' };

function dashboardHero(title, detail, welcome = false) {
  return '<section class="dashboard-hero' + (welcome ? ' welcome-hero' : '') + '">' +
    '<span class="hero-caption">Illustrative project imagery</span>' +
    '<div class="eyebrow">' + (welcome ? 'VEDA · Project Intelligence' : 'Dashboard · Project Intelligence') + '</div>' +
    '<h1>' + E(title) + '</h1><p>From field reality to schedule certainty.</p>' +
    '<div class="hero-source">' + detail + '</div></section>';
}

function dashboardShortcuts() {
  const items = [
    ['controls', 'Execution Control', 'Lookaheads & constraints', 'M4 6h16M7 3v6M4 13h16M16 10v6M4 20h16'],
    ['ask', 'Ask VEDA', 'Grounded project answers', 'M4 5h16v12H9l-5 3V5zM8 10h8M8 13h5'],
    ['timeline', 'Schedule Timeline', 'Dates, logic & progress', 'M3 5h18v14H3zM7 9h7M10 13h8M5 17h9'],
    ['capture', 'Capture field update', 'Bring site evidence into view', 'M4 6h16v14H4zM9 6l1-3h4l1 3M12 10a3 3 0 100 6 3 3 0 000-6'],
  ];
  return '<nav class="dashboard-shortcuts" aria-label="Dashboard shortcuts">' + items.map(([id, title, detail, path]) =>
    '<button type="button" onclick="go(\'' + id + '\')"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="' + path + '"/></svg>' +
    '<span><b>' + title + '</b><small>' + detail + '</small></span><span class="shortcut-arrow" aria-hidden="true">→</span></button>'
  ).join('') + '</nav>';
}

/* ===================================================== no project */
VIEWS.noproject = () =>
  dashboardHero("Your project, connected.", "<span>Schedule · Evidence · Decisions</span>", true) +
  '<div class="panel welcome-panel">' +
  '<header>Get started</header><div class="body">' +
  '<p style="margin-top:0;color:var(--ink-2)">VEDA reads a construction ' +
  'schedule through Horizun, interprets the field paperwork around it, and ' +
  'keeps every conclusion traceable to where it came from.</p>' +
  '<p style="color:var(--ink-2)">Create a project, then upload a schedule ' +
  '(XER, MPP, MSPDI XML, PMXML, Asta) together with the DPRs, registers and ' +
  'reports that describe what actually happened on site.</p>' +
  '<button class="btn primary" id="createFirst">Create a project</button>' +
  '<p style="color:var(--ink-3);font-size:12px;margin-bottom:0">' +
  'Workspace settings — <a class="link" onclick="go(\'anywhere\')">VEDA Anywhere</a> ' +
  'and <a class="link" onclick="go(\'system\')">System / MCP</a> — do not need a project.</p>' +
  '</div></div>';

VIEWS.worker_noproject = () =>
  '<div class="worker-empty-state"><span class="worker-role-chip">SITE WORKER</span>' +
  '<h1>No project assigned</h1><p>Ask your supervisor to prepare a project before sending a field update.</p>' +
  '<small>Your capture tools will appear here as soon as a project is available.</small></div>';

const workerMode = () => Boolean(window.vedaRole && window.vedaRole() === 'worker');

function workerSubmissionCards(captures, limit) {
  const rows = (captures || []).slice(0, limit || 6);
  if (!rows.length) return empty('No updates sent yet',
    'Your voice notes, photos and videos will appear here after you submit them.');
  return '<div class="worker-submission-list">' + rows.map(c => {
    const detail = [c.activity_display_id, c.activity_name].filter(Boolean).join(' · ');
    const status = c.status === 'proposal_ready' ? ['Received', 'green'] :
      c.status === 'needs_activity' ? ['Planner linking', 'amber'] :
      c.status === 'conflict' ? ['Needs clarification', 'red'] : ['Saved', 'blue'];
    return '<article><div class="worker-submission-icon">✓</div><div><header><b>' +
      E(detail || 'Site observation') + '</b>' + tagFor(status[0], {[status[0].toLowerCase()]: status[1]}) +
      '</header><p>' + E(c.confirmed_text || '') + '</p><footer><span>' +
      E(c.reporter || 'Field reporter') + '</span><span>' + E(day(c.occurred_at)) + '</span>' +
      ((c.media_file_ids || []).length ? '<span>' + int(c.media_file_ids.length) + ' attachment(s)</span>' : '') +
      '</footer></div></article>';
  }).join('') + '</div>';
}

VIEWS['worker-home'] = async (pid) => {
  const [projectData, captureData] = await Promise.all([
    A('/projects/' + pid + '/overview'), A('/projects/' + pid + '/field-captures?limit=5')
  ]);
  const project = projectData.project || {};
  const schedule = projectData.schedule || {};
  const captures = (captureData.captures || []).filter(c =>
    String(c.reporter || '').toLowerCase().startsWith('r. dutta'));
  return '<section class="worker-home">' +
    '<header class="worker-welcome"><div><span class="worker-role-chip">SITE WORKER · PIPING CREW</span>' +
      '<h1>Good morning, R. Dutta</h1><p>' + E(project.name || 'Current project') +
      (project.location ? ' · ' + E(project.location) : '') + '</p></div>' +
      '<div class="worker-sync-state"><i></i><span><b>Connected</b><small>Updates go straight to Project Controls</small></span></div></header>' +
    '<div class="worker-action-grid">' +
      '<button class="worker-primary-action" type="button" onclick="go(\'capture\')"><span>＋</span><div><b>Send site update</b>' +
        '<small>Speak, type, photograph or record the workfront</small></div><i>→</i></button>' +
      '<button type="button" onclick="go(\'capture\')"><span>●</span><div><b>Record a voice note</b><small>VEDA creates an editable event card</small></div><i>→</i></button>' +
      '<button type="button" onclick="go(\'worker-submissions\')"><span>✓</span><div><b>Check my submissions</b><small>' +
        int(captures.length) + ' recent update(s) available</small></div><i>→</i></button>' +
    '</div>' +
    '<div class="worker-context-grid"><section class="worker-shift-card"><header><div><span>MY SHIFT</span><h2>Field reporting brief</h2></div>' +
      '<time>' + (schedule.data_date ? day(schedule.data_date) : 'Today') + '</time></header>' +
      '<div class="worker-brief-steps"><div><i>1</i><span><b>Observe</b><small>Capture only work you personally saw</small></span></div>' +
      '<div><i>2</i><span><b>Confirm</b><small>Correct names, quantities and activity IDs</small></span></div>' +
      '<div><i>3</i><span><b>Submit</b><small>Project Controls reviews every schedule proposal</small></span></div></div>' +
      '<footer><span>Offline safe</span><span>Original media retained</span><span>No direct P6 write</span></footer></section>' +
      '<section class="worker-help-card"><span>NEED HELP?</span><h2>Ask about today’s work</h2>' +
      '<p>Use plain English, Hindi or Hinglish. Ask for an activity ID, what to report, or what information is missing.</p>' +
      '<button class="btn" type="button" onclick="go(\'ask\')">Ask VEDA</button></section></div>' +
    '<section class="worker-recent"><header><div><span>FIELD → OFFICE HANDOFF</span><h2>Recent site submissions</h2></div>' +
      '<button class="link" type="button" onclick="go(\'worker-submissions\')">View all →</button></header>' +
      workerSubmissionCards(captures, 3) + '</section></section>';
};

VIEWS['worker-submissions'] = async (pid) => {
  const response = await A('/projects/' + pid + '/field-captures?limit=50');
  const captures = (response.captures || []).filter(c =>
    String(c.reporter || '').toLowerCase().startsWith('r. dutta'));
  return head('My submissions', 'Field updates sent to Project Controls',
    '<span class="tag green">' + int(captures.length) + ' received</span>' +
    '<button class="btn primary" type="button" onclick="go(\'capture\')">Send new update</button>') +
    '<div class="worker-submission-summary"><div><b>' + int(captures.length) + '</b><span>Submitted</span></div>' +
      '<div><b>' + int(captures.filter(c => c.status === 'proposal_ready').length) + '</b><span>Ready for review</span></div>' +
      '<div><b>' + int(captures.filter(c => c.status === 'needs_activity').length) + '</b><span>Planner linking</span></div></div>' +
    '<section class="worker-recent worker-all-submissions"><header><div><span>DURABLE HANDOFF</span>' +
      '<h2>Submission history</h2></div><small>Original evidence and corrections stay auditable</small></header>' +
      workerSubmissionCards(captures, 50) + '</section>';
};

/* ===================================================== Field capture */
VIEWS.capture = async (pid) => {
  const r = await A('/projects/' + pid + '/field-captures?limit=30');
  const captures = workerMode() ? (r.captures || []).filter(c =>
    String(c.reporter || '').toLowerCase().startsWith('r. dutta')) : (r.captures || []);
  const recent = captures.length ? captures.map(c => {
    const statusMap = { proposal_ready: 'green', confirmed_no_change: 'green',
      needs_activity: 'amber', conflict: 'red' };
    const detail = [c.activity_display_id, c.activity_name].filter(Boolean).join(' · ');
    return '<article class="capture-history-item">' +
      '<div class="capture-history-state"><i></i></div>' +
      '<div class="capture-history-copy"><div>' +
      tagFor(c.event_state, {start: 'blue', progress: 'amber', finish: 'green'}) +
      '<b>' + E(detail || 'Activity not linked yet') + '</b><span class="mono">' +
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

  const isWorker = workerMode();
  return head(isWorker ? 'Send site update' : 'Field capture',
    isWorker ? 'Speak, type, photograph or record · confirm before sending' :
      'Fast on site · confirmed by a person · safe offline',
    isWorker ? '<span class="tag green">Connected to supervisor</span>' :
      '<span class="tag blue">Site reporter workspace</span>' +
      '<button class="btn sm" onclick="go(\'files\')">Files</button>' +
      '<button class="btn sm" onclick="go(\'proposals\')">Edit proposals</button>') +
    '<div class="worker-capture-handoff"><i></i><div><b>Project Controls is connected</b>' +
      '<span>Your confirmed update will appear in the supervisor’s review workflow immediately.</span></div>' +
      '<small>FIELD → OFFICE</small></div>' +
    '<div class="capture-status-row"><div class="capture-connectivity" id="capture-connectivity">Checking connection…</div>' +
    '<div class="capture-outbox">Saved on device <b id="capture-outbox-count">0</b>' +
    '<button class="btn sm" id="capture-sync-now">Sync now</button></div></div>' +
    '<input id="capture-client-id" type="hidden">' +
    '<div class="capture-layout"><section class="capture-composer">' +
      '<div class="capture-section capture-source-section"><div class="capture-step"><span>1</span><div><b>Tell VEDA what happened</b>' +
      '<small>Speak naturally or type a note. VEDA turns it into an editable event card.</small></div></div>' +
      '<div class="capture-action-grid"><button class="capture-action voice" id="capture-voice" type="button"><i>●</i><b>Record voice</b><small>Audio is kept as evidence</small></button>' +
      '<button class="capture-action worker-only" id="capture-media-upload" type="button"><i>↑</i><b>Add photo or video</b><small>Choose existing site media</small></button>' +
      '<button class="capture-action worker-only" id="capture-video-record" type="button"><i>◉</i><b>Record site video</b><small>Open this device’s camera</small></button>' +
      '<button class="capture-action cctv" id="capture-cctv" type="button" aria-expanded="false" aria-controls="capture-cctv-panel"><i>▶</i><b>Review CCTV</b><small>Inspect footage and draft progress</small></button></div>' +
      '<section class="cctv-workstation" id="capture-cctv-panel" hidden aria-label="CCTV progress review workstation">' +
        '<header class="cctv-head"><div><span class="cctv-kicker"><i></i> LOCAL CAMERA · DEMO REVIEW</span>' +
        '<h3>Site Vision Review</h3><p>Pause, rewind, jump to an observation, then verify the AI draft before it becomes field evidence.</p></div>' +
        '<button class="cctv-close" id="capture-cctv-close" type="button" aria-label="Close CCTV review">×</button></header>' +
        '<div class="cctv-grid"><div class="cctv-feed-column"><div class="cctv-feed">' +
          '<video id="capture-cctv-player" title="Local site camera footage" src="/static/staticcams/CCTV_2.mp4" controls autoplay muted playsinline preload="metadata"></video>' +
          '<div class="site-vision-box-layer" id="capture-cctv-boxes" aria-hidden="true"><i class="vision-scan-line"></i></div>' +
          '<div class="cctv-feed-meta"><span><i></i> AI TRACKING</span><b id="capture-cctv-camera-label">Pipe laydown yard · CAM-03</b><time id="capture-cctv-clock">Frame 00:53</time></div>' +
        '</div><div class="cctv-feed-toolbar"><label><span>Demo camera</span><select class="inp" id="capture-cctv-camera">' +
          '<option value="yard">Pipe laydown yard · CAM-03</option>' +
          '<option value="drilling">Drilling operations · CAM-01</option>' +
        '</select></label><div class="vision-mode-switch" id="capture-cctv-mode"><button class="selected" type="button" data-capture-cctv-mode="ai">AI scan</button>' +
        '<button type="button" data-capture-cctv-mode="raw">Raw CCTV</button></div>' +
        '<a class="btn sm" id="capture-cctv-download" href="/static/staticcams/CCTV_2.mp4" download>Download clip</a></div>' +
        '<div class="cctv-observation-rail" aria-label="Detected observations">' +
          '<button type="button" data-cctv-observation="inventory"><time>00:05</time><span><b>Pipe stock visible</b><small>Material context · no progress claim</small></span><i>96%</i></button>' +
          '<button class="selected" type="button" data-cctv-observation="handling"><time>00:53</time><span><b>Stringing preparation</b><small>PIP-SP1-2002 · 41% estimate</small></span><i>91%</i></button>' +
          '<button type="button" data-cctv-observation="workfront"><time>01:35</time><span><b>Active laydown workfront</b><small>Worker + pipe context</small></span><i>86%</i></button>' +
        '</div></div>' +
        '<aside class="cctv-review-card"><div class="cctv-review-title"><div><span>AI observation draft</span><b id="capture-cctv-time">Frame 00:53</b></div><em>HUMAN REVIEW REQUIRED</em></div>' +
          '<label><span>Schedule activity ID</span><input class="inp" id="capture-cctv-activity-id" value="PIP-SP1-2002"></label>' +
          '<label><span>Observed work</span><input class="inp" id="capture-cctv-activity-name" value="Stringing 16&quot; API 5L Gr X52"></label>' +
          '<div class="cctv-review-fields"><label><span>Supervisor progress draft</span><div class="cctv-percent"><input class="inp" id="capture-cctv-progress" type="number" min="0" max="100" step="1" value="41"><b>%</b></div></label>' +
          '<label><span>Object detector</span><output id="capture-cctv-confidence">Loading local tracks…</output></label></div>' +
          '<label><span>Reviewer note</span><textarea class="inp" id="capture-cctv-note" rows="3">Pipe stock and an active handling workfront are visible; verify chainage and installed quantity.</textarea></label>' +
          '<div class="cctv-review-actions"><button class="btn" id="capture-cctv-jump" type="button">Jump to frame</button>' +
          '<button class="btn primary" id="capture-cctv-use" type="button">Review &amp; save field data</button></div>' +
          '<button class="cctv-attach" id="capture-cctv-photo" type="button">Attach a site image instead</button>' +
          '<p><b>Vision disclosure:</b> moving worker boxes use local pose detection and road vehicles use local object detection. Camera-calibrated labels and safety signals remain review candidates. The model does not detect pipe completion or measure progress. Saving creates an editable, auditable field draft only.</p>' +
        '</aside></div>' +
      '</section>' +
      '<input type="file" id="capture-photo-file" accept="image/*,video/*" multiple hidden>' +
      '<input type="file" id="capture-video-file" accept="video/*" capture="environment" hidden>' +
      '<input type="file" id="capture-audio-file" accept="audio/*" capture hidden>' +
      '<div id="capture-media-tray" class="capture-media-tray"></div>' +
      '<div class="capture-mic-row"><label><span>Microphone input</span>' +
      '<select class="inp" id="capture-microphone" aria-label="Microphone input"><option value="">Default microphone</option></select></label>' +
      '<button class="btn sm" id="capture-mic-refresh" type="button">Find microphones</button>' +
      '<small id="capture-mic-status">Allow microphone access to list available inputs.</small></div>' +
      '<div class="capture-fields-two capture-language-row"><label><span>Language</span><select class="inp" id="capture-language">' +
      '<option value="en">English</option><option value="hi-IN">हिन्दी / Hinglish</option>' +
      '<option value="ar">العربية</option><option value="es">Español</option>' +
      '<option value="fr">Français</option><option value="ur">اردو</option></select></label>' +
      '<div class="capture-transcript-state" id="capture-transcript-state"><i></i><span>Waiting for an observation</span></div></div>' +
      '<div class="capture-language-help"><i>↳</i><div><b>Adaptive language understanding</b>' +
      '<span>Common site phrases stay instant. If the corrected wording is unfamiliar, VEDA asks only the local reasoning service for a structured draft—never Claude or Codex—and you still edit every field.</span></div></div>' +
      '<label class="capture-wide-label"><span>Raw note / draft voice transcript <em>kept as source evidence</em></span>' +
      '<textarea class="inp" id="capture-original" rows="4" placeholder="Describe the work, exact area, quantities, blockers, and what you personally observed."></textarea></label>' +
      '<div class="capture-transcript-source" id="capture-transcript-source">Type a note, or record voice for a browser draft transcript.</div>' +
      '<div class="capture-correction"><div class="capture-correction-head"><div><b>Correct the transcript before extraction</b>' +
      '<small>VEDA extracts only from the corrected words below. The raw version stays unchanged in the audit trail.</small></div>' +
      '<button class="btn sm" id="capture-reset-transcript" type="button">Reset to raw</button></div>' +
      '<textarea class="inp" id="capture-confirmed" rows="4" placeholder="Review names, activity IDs, quantities and dates before extraction."></textarea>' +
      '<div class="capture-correction-note" id="capture-correction-note">No transcript corrections yet.</div></div>' +
      '<button class="btn primary capture-extract" id="capture-extract" type="button">Extract editable event card</button></div>' +

      '<div class="capture-section capture-structured-section" id="capture-structured-card" hidden><div class="capture-step"><span>2</span><div><b>Review the extracted event</b>' +
      '<small>Edit every field before confirming. Nothing below is accepted silently.</small></div></div>' +
      '<div class="capture-extracted-summary" id="capture-extracted-summary"></div>' +
      '<div class="capture-event-grid">' +
        '<label class="capture-event-option"><input type="radio" name="capture-event" value="start"><span><b>Started</b><small>Work began on site</small></span></label>' +
        '<label class="capture-event-option selected"><input type="radio" name="capture-event" value="progress" checked><span><b>Progress</b><small>Work advanced</small></span></label>' +
        '<label class="capture-event-option"><input type="radio" name="capture-event" value="finish"><span><b>Finished</b><small>Scope is complete</small></span></label>' +
      '</div><div class="capture-fields-two"><label><span>When observed</span>' +
      '<input class="inp" id="capture-occurred" type="datetime-local"></label>' +
      '<label><span>Your name / crew</span><input class="inp" id="capture-reporter" ' +
      (isWorker ? 'value="R. Dutta · Piping crew" ' : '') +
      'placeholder="e.g. S. Kumar · Piping A"></label></div>' +
      '<div class="capture-fields-two" id="capture-progress-fields"><label><span>Measured progress % <em>optional</em></span>' +
      '<input class="inp" id="capture-progress" type="number" min="0" max="100" step="0.1" inputmode="decimal" placeholder="e.g. 65"></label>' +
      '<label><span>Remaining working days <em>optional</em></span><input class="inp" id="capture-remaining" type="number" min="0" step="0.5" inputmode="decimal" placeholder="Only if explicitly known"></label></div>' +
      '<div class="note" id="capture-finish-rule" hidden>Finish creates a governed Actual Finish, 100% complete, and zero remaining-duration proposal bundle.</div></div>' +

      '<div class="capture-section capture-structured-section" id="capture-place-card" hidden><div class="capture-step"><span>3</span><div><b>Place and activity</b>' +
      '<small>Explicit selection prevents the wrong schedule activity from receiving actuals.</small></div></div>' +
      '<label class="capture-wide-label"><span>Schedule activity <em>search by ID, name, or WBS</em></span>' +
      '<input class="inp" id="capture-activity-search" autocomplete="off" placeholder="Start typing an activity…"></label>' +
      '<div class="capture-activity-results" id="capture-activity-results"></div>' +
      '<div class="capture-activity-selected" id="capture-activity-selected"></div>' +
      '<div class="capture-fields-two"><label><span>Area / location label</span>' +
      '<input class="inp" id="capture-location-label" placeholder="e.g. Unit 04 · Pipe rack B"></label>' +
      '<div class="capture-location-box"><button class="btn" id="capture-location" type="button">Use device location</button>' +
      '<small id="capture-location-status">Location is optional and permission-based.</small></div></div></div>' +

      '<div class="capture-section capture-confirm-section" id="capture-confirm-card" hidden><div class="capture-step"><span>4</span><div><b>Confirm before sending</b>' +
      '<small>VEDA uses these exact words; a transcript is never accepted silently.</small></div></div>' +
      '<div class="capture-confirm-badge"><i>✓</i><span><b>Human confirmation</b><small>The corrected transcript and every extracted field stay editable until you save.</small></span></div>' +
      '<div class="capture-policy"><span>Evidence saved</span><i>→</i><span>Activity identity</span><i>→</i><span>Proposal only</span><i>→</i><span>Planner approval</span></div>' +
      '<button class="btn primary capture-save" id="capture-save" type="button">' +
      (isWorker ? 'Submit to Project Controls' : 'Confirm & save update') + '</button>' +
      '<p class="capture-safety">' + (isWorker
        ? 'Your supervisor receives an evidence-backed draft. You cannot change Primavera or approve schedule values.'
        : 'Saving never writes to Primavera. If an official value differs, VEDA holds the conflict for a planner.') + '</p></div>' +
    '</section><aside class="capture-history">' + panel((isWorker ? 'Recent submissions' : 'Recent field updates') + ' <small>' + captures.length + '</small>',
      '<div class="capture-history-list">' + recent + '</div>') + '</aside></div>';
};
VIEWS.bind_capture = (pid) => {
  if (window.FieldCapture) window.FieldCapture.bind(pid);
};

function siteVisionDashboard() {
  return '<section class="site-vision-panel" id="site-vision-panel">' +
    '<header class="site-vision-head"><div><div class="eyebrow">Visual execution evidence</div>' +
    '<h2>Site Vision</h2><p>Review fixed cameras and worker uploads without leaving the project controls workspace.</p></div>' +
    '<div class="site-vision-head-actions"><span><i></i> LOCAL MEDIA</span>' +
    '<button class="btn sm" type="button" onclick="go(\'capture\')">Open Field Capture</button></div></header>' +
    '<nav class="site-vision-tabs" aria-label="Site Vision sources">' +
      '<button class="selected" type="button" data-site-vision-tab="cameras"><b>Fixed cameras</b><small>2 available</small></button>' +
      '<button type="button" data-site-vision-tab="uploads"><b>Worker uploads</b><small>1 video</small></button>' +
    '</nav>' +

    '<div class="site-vision-pane" data-site-vision-pane="cameras">' +
      '<div class="site-vision-grid"><div class="site-vision-stage"><div class="site-vision-video-shell">' +
        '<video id="site-camera-video" src="/static/staticcams/CCTV_2.mp4" controls autoplay muted playsinline preload="metadata"></video>' +
        '<div class="site-vision-box-layer" id="site-camera-boxes" aria-hidden="true"><i class="vision-scan-line"></i>' +
        '</div><div class="site-camera-hud"><span><i></i> AI TRACKING</span><b id="site-camera-hud-label">Pipe laydown yard · CAM-03</b>' +
        '<time id="site-camera-time">Frame 00:53</time></div>' +
      '</div><div class="site-vision-playerbar"><div class="vision-mode-switch" id="site-camera-mode">' +
        '<button class="selected" type="button" data-site-vision-mode="ai">AI scanning</button>' +
        '<button type="button" data-site-vision-mode="raw">Raw CCTV</button></div>' +
        '<span>Boxes are a review aid; schedule progress still needs human confirmation.</span></div></div>' +
      '<aside class="site-vision-inspector"><label class="site-vision-label"><span>Camera</span>' +
        '<select class="inp" id="site-camera-select"><option value="yard">Pipe laydown yard · CAM-03</option>' +
        '<option value="drilling">Drilling operations · CAM-01</option></select></label>' +
        '<div class="site-vision-signal"><span><i></i> CAMERA ONLINE</span><b id="site-camera-detected">Loading tracks…</b><small id="site-camera-model-state">Local playback · loading vision ensemble</small></div>' +
        '<div class="site-vision-detections" id="site-camera-detections"><div class="vision-detection-empty">Loading time-synchronised model tracks…</div>' +
        '</div><section class="site-safety-watch" id="site-safety-watch" hidden>' +
          '<header><span><i></i> SAFETY REVIEW</span><b id="site-safety-severity">HIGH</b></header>' +
          '<h3 id="site-safety-title">Potential struck-by / near-miss</h3>' +
          '<p id="site-safety-summary">Rapid worker posture change detected during material handling. Supervisor confirmation is required.</p>' +
          '<div><time id="site-safety-time">00:08</time><small id="site-safety-state">Assistive alert · not a confirmed incident</small></div>' +
          '<footer><button class="btn sm" id="site-safety-review" type="button">Review moment</button>' +
          '<button class="btn sm" id="site-safety-ack" type="button">Acknowledge</button></footer>' +
        '</section><div class="site-vision-candidate"><span>Schedule candidate</span>' +
          '<b id="site-camera-activity">PIP-SP1-2002 · Stringing 16&quot; API 5L Gr X52</b>' +
          '<div><strong id="site-camera-progress">41%</strong><small>visual draft · not an official actual</small></div>' +
          '<p id="site-camera-summary">Pipe stock and an active handling workfront are visible. Confirm chainage and installed quantity before accepting progress.</p></div>' +
        '<div class="site-vision-inspector-actions"><a class="btn sm" id="site-camera-download" href="/static/staticcams/CCTV_2.mp4" download>Download clip</a>' +
        '<button class="btn primary sm" id="site-camera-field-draft" type="button">Review field draft</button></div>' +
        '<p class="site-vision-disclosure">Worker tracks use local pose detection; road vehicles use local object detection. CAM-03 hook labels are camera-calibrated review candidates because COCO has no crane-hook class. Safety alerts use multi-frame posture change and are not confirmed incidents. Nothing writes to P6 automatically.</p>' +
      '</aside></div></div>' +

    '<div class="site-vision-pane" data-site-vision-pane="uploads" hidden>' +
      '<div class="site-vision-grid"><div class="site-vision-stage"><div class="site-vision-video-shell worker-upload-video">' +
        '<video id="site-worker-video" src="/static/staticcams/LiveCamera_1.mp4" controls autoplay muted playsinline preload="metadata"></video>' +
        '<div class="site-vision-box-layer" id="site-worker-boxes" hidden aria-hidden="true"><i class="vision-scan-line"></i>' +
        '</div><div class="site-camera-hud upload"><span><i></i> WORKER UPLOAD</span><b>Field walk-through · Duliajan</b><time>06:24</time></div>' +
      '</div><div class="site-vision-playerbar"><span>Uploaded by R. Dutta · Piping crew · Today 06:42 · starts muted</span>' +
        '<div><a class="link" href="/static/staticcams/LiveCamera_1.mp4" download>Download</a>' +
        '<button class="link" id="site-worker-share" type="button">Share</button></div></div></div>' +
      '<aside class="site-vision-inspector worker"><div class="worker-upload-state"><span><i></i> READY FOR SUPERVISOR REVIEW</span><small>Stored locally · original retained</small></div>' +
        '<label class="site-vision-label"><span>Headline</span><input class="inp" id="site-worker-title" value="Duliajan pipe-rack workfront walk-through"></label>' +
        '<label class="site-vision-label"><span>Worker description</span><textarea class="inp" id="site-worker-description" rows="3">Civil and pipe-rack workfront filmed during the morning walk. Workers and structural bays are visible.</textarea></label>' +
        '<label class="site-vision-label"><span>Supervisor observation</span><textarea class="inp" id="site-worker-note" rows="3" placeholder="Example: Pipe-rack steel erection at Duliajan reached 72%; two support bays remain.">Pipe-rack steel erection at Duliajan reached approximately 72%; two support bays and alignment checks remain.</textarea></label>' +
        '<div class="worker-review-actions"><button class="btn" id="site-worker-use-note" type="button">Use supervisor note</button>' +
        '<button class="btn primary" id="site-worker-scan" type="button">Let AI scan</button></div>' +
        '<div class="worker-scan-result" id="site-worker-result" hidden><header><span>VIDEO REVIEW DRAFT</span><b id="site-worker-result-state">Scan complete</b></header>' +
          '<h3 id="site-worker-result-title">Active pipe-rack workfront</h3>' +
          '<p id="site-worker-result-summary">Workers and structural bays are visible. The description supports a piping-erection progress event, subject to supervisor confirmation.</p>' +
          '<div><span><b>PIP-DUL-2016</b><small>Piping Erection on Rack - Duliajan</small></span><strong id="site-worker-result-progress">72%</strong></div>' +
          '<button class="btn primary" id="site-worker-field-draft" type="button">Review schedule update</button></div>' +
        '<p class="site-vision-disclosure">The scan combines local people/vehicle tracks with the worker headline and description. It does not infer installed pipe quantity or schedule progress.</p>' +
      '</aside></div></div>' +
  '</section>';
}

function supervisorFieldHandoff(captures) {
  const rows = (captures || []).slice(0, 3);
  if (!rows.length) return '';
  return '<section class="supervisor-handoff"><header><div><span><i></i> LIVE FIELD HANDOFF</span>' +
    '<h2>Updates from site crews</h2></div><button class="link" type="button" onclick="go(\'capture\')">Open field inbox →</button></header>' +
    '<div>' + rows.map(c => {
      const detail = [c.activity_display_id, c.activity_name].filter(Boolean).join(' · ');
      return '<article><div><b>' + E(detail || 'Unlinked site observation') + '</b><small>' +
        E(c.reporter || 'Field reporter') + ' · ' + E(day(c.occurred_at)) + '</small></div><p>' +
        E(c.confirmed_text || '') + '</p><span>' +
        ((c.media_file_ids || []).length ? int(c.media_file_ids.length) + ' media' : 'Text update') + '</span></article>';
    }).join('') + '</div><footer>Worker submissions become immutable field evidence; schedule changes remain proposals until supervisor approval.</footer></section>';
}

/* ===================================================== 1. overview */
VIEWS.overview = async (pid) => {
  const [o, captureData] = await Promise.all([
    A('/projects/' + pid + '/overview'), A('/projects/' + pid + '/field-captures?limit=3')
  ]);
  const fieldCaptures = captureData.captures || [];
  const s = o.schedule, ev = o.earned_value, c = o.counts;
  const f = o.field_context || {};
  const insights = o.control_insights || {};
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
  const forecastValue = s.forecast_finish ? day(s.forecast_finish) : '—';
  const forecastDetail = s.forecast_finish
    ? (s.forecast_basis || 'source-supported current forecast')
    : 'Not evaluable — source does not establish a current forecast finish';
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
  const qaValue = evaluatedQa ? num(s.health_score, 1) + '%' : '—';
  const qaDetail = evaluatedQa
    ? (o.quality.passed + ' passed · ' + o.quality.failed + ' failed · ' +
      o.quality.not_evaluated + ' not evaluated')
    : 'Not evaluable — ' + o.quality.not_evaluated + ' check(s) not evaluated';
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
  if (Number(c.open_hindrances || 0) + Number(c.open_constraints || 0)) interventions.push('<button onclick="go(\'controls\')"><b>' +
    int(Number(c.open_hindrances || 0) + Number(c.open_constraints || 0)) +
    ' execution control flags</b><span>Review active hindrances and look-ahead readiness constraints</span><i>Open controls →</i></button>');

  return dashboardHero(o.project.name,
    '<span>Authoritative schedule: ' + E(s.project_name || '') + '</span>' +
    (o.project.location ? '<span>' + E(o.project.location) + '</span>' : '') +
    '<span>Data/status date · ' + (s.data_date ? day(s.data_date) : 'not evaluable') + '</span>' +
    '<span>Revision ' + E(s.revision) + '</span>') +
    '<div class="dashboard-key">' + provKey() + '</div>' +

    '<div class="grid g4 dashboard-metrics">' +
    stat('Current forecast finish', forecastValue, E(forecastDetail),
      lateFinish ? 'hot' : (s.forecast_finish ? 'good' : '')) +
    stat('Recorded schedule progress', progressAvailable ? num(s.percent_complete, 1) + '%' : '—',
      progressAvailable ? E(progressDetail) : 'Not evaluable — ' + E(progressDetail)) +
    stat('Critical activities', criticalAvailable ? int(c.critical) : '—',
      criticalAvailable ? ('of ' + int(c.activities) + ' source activities · ' + E(criticalDetail))
        : 'Not evaluable — ' + E(criticalDetail), criticalAvailable && c.critical ? 'warm' : '') +
    stat('Source-evaluable schedule QA', qaValue, qaDetail,
      evaluatedQa && Number(s.health_score) < 60 ? 'hot' : (evaluatedQa ? 'good' : '')) +
    '</div>' +

    '<div class="control-visual-grid">' +
      completionTrajectoryCard(insights.completion_trajectory) +
      activityDistributionCard(insights.activity_distribution) +
    '</div>' +

    dashboardShortcuts() +

    '<div class="control-strip">' +
      '<div><span>Decisions</span><b class="' + (decisionCount ? 'warm' : 'good') + '">' +
        int(decisionCount) + '</b><small>' + (decisionCount ? 'require a person' : 'nothing waiting') + '</small></div>' +
      '<div><span>Unresolved evidence</span><b class="' + (f.unresolved_record_count ? 'warm' : 'good') + '">' +
        int(f.unresolved_record_count || 0) + '</b><small>without settled identity</small></div>' +
      '<div><span>Reporting freshness</span><b class="' +
        (reportingLag === null ? 'muted' : reportingLag > 2 ? 'warm' : 'good') + '">' +
        (reportingLag === null ? '—' : reportingLag + 'd') + '</b><small>' +
        (reportingLag === null ? 'not evaluable — no comparable field/status dates' : 'behind schedule status date') + '</small></div>' +
      '<div><span>Validated actuals coverage</span><b>' + int(f.validated_activity_count || 0) +
        '</b><small>activities with trusted evidence</small></div>' +
    '</div>' +
    supervisorFieldHandoff(fieldCaptures) +
    '<section class="intervention-panel"><header><div><div class="eyebrow">Intervention queue</div>' +
      '<h2>' + (interventions.length ? 'What needs attention now' : 'No immediate intervention') +
      '</h2></div><span>' + latestFieldDate + ' latest field date</span></header>' +
      '<div class="intervention-list">' + (interventions.length ? interventions.join('') :
        '<div class="control-clear"><b>Project inputs are reconciled.</b><span>New evidence will appear here when it creates an exception.</span></div>') +
      '</div></section>' +

    siteVisionDashboard() +

    '<details class="dashboard-details"' + (VIEWS._dashboardDetails?.[pid] ? ' open' : '') + '><summary>Detailed project metrics<span>Schedule, evidence and decisions</span></summary>' +
    '<div class="grid g4" style="margin-bottom:14px">' +
    stat('Overdue vs reference plan', overdueEvaluable ? int(c.overdue) : '—',
      overdueEvaluable ? 'unfinished activities whose reference finish is before the supplied data/status date' :
        'Not evaluable — the source does not supply a data/status date',
      overdueEvaluable && c.overdue ? 'warm' : '') +
    stat('Completed after reference finish', completedLateEvaluable ? int(c.completed_late) : '—',
      completedLateEvaluable ? 'completed activities whose actual finish is later than the stored baseline/reference finish' :
        'Not applicable — no completed activity with an actual finish is available for comparison',
      completedLateEvaluable && c.completed_late ? 'warm' : '') +
    stat('Project-control reference rows', int(ref.reference_record_count || 0),
      'supporting dictionaries/registers; not field-progress evidence') +
    stat('Active WBS nodes', int(c.wbs), 'schedule hierarchy nodes; not activities') +
    '</div>' +

    '<div class="grid g4" style="margin-bottom:14px">' +
    stat('Evidence sources', int(f.evidence_source_count || f.source_file_count || 0),
      'uploaded documents; each is a container decomposed into atomic observations' +
      (int(f.extraction_required_count || 0) ? ' · ' + int(f.extraction_required_count) + ' need a text-extractable copy' : ''),
      int(f.extraction_required_count || 0) ? 'warm' : '') +
    stat('Evidence observations', int(f.evidence_observation_count || f.record_count || 0),
      (f.evidence_observation_count
        ? int(f.activity_observation_count || 0) + ' activity-progress · ' + int(f.issue_observation_count || 0) + ' issue · ' +
          int(f.context_observation_count || 0) + ' context (manpower/equipment/weather/metadata) · latest ' + latestFieldDate
        : 'no observations extracted yet')) +
    stat('Activities with validated evidence', int(f.validated_activity_count || 0),
      int(f.validated_link_record_count || 0) + ' validated supporting record(s); does not change official schedule progress') +
    stat('Observations stating a progress %', int(f.reported_progress_record_count || 0),
      int(f.numeric_observed_activity_count || 0) + ' schedule activity/activities have a validated numeric field observation; this is not official schedule progress') +
    '</div>' +

    '<div class="grid g4" style="margin-bottom:14px">' +
    stat('Decisions waiting on you', int(Number(c.pending_reviews || 0) + Number(c.pending_proposals || 0)),
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

    '</details>' +

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
      row('Data/status date', s.data_date ? day(s.data_date) : '<span class="ink-3">Not evaluable — not supplied by source</span>') +
      row('Earliest planned activity start', day(s.planned_start)) +
      row('Latest planned activity finish', day(s.planned_finish)) +
      (s.must_finish_by ? row('Project Must Finish By', day(s.must_finish_by)) : '') +
      row('Current forecast finish', s.forecast_finish ? day(s.forecast_finish)
        : '<span class="ink-3">Not evaluable — source does not establish a current forecast</span>') +
      (s.forecast_basis ? row('Forecast basis', E(s.forecast_basis)) : '') +
      row('Baseline/reference start', s.baseline_start ? day(s.baseline_start)
        : '<span class="ink-3">Not evaluable — no usable baseline/reference start stored</span>') +
      row('Baseline/reference finish', s.baseline_finish ? day(s.baseline_finish)
        : '<span class="ink-3">Not evaluable — no usable baseline/reference finish stored</span>') +
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
          ? 'Not evaluable — baseline/reference dates are available, but the source does not establish all current status/progress/cost inputs required for earned-value metrics.'
          : 'Not evaluable — the source does not establish a usable baseline/reference plus the current status/progress/cost inputs required for earned-value metrics.') +
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

VIEWS.bind_overview = (pid) => {
  const details = document.querySelector('.dashboard-details');
  if (details) details.addEventListener('toggle', () => {
    VIEWS._dashboardDetails = VIEWS._dashboardDetails || {};
    VIEWS._dashboardDetails[pid] = details.open;
  });
  const root = document.getElementById('site-vision-panel');
  if (!root) return;
  VIEWS._siteVisionBusy = false;
  root.addEventListener('pointerdown', () => { VIEWS._siteVisionBusy = true; });
  root.addEventListener('input', () => { VIEWS._siteVisionBusy = true; });
  const feeds = {
    yard: {
      src: '/static/staticcams/CCTV_2.mp4', label: 'Pipe laydown yard · CAM-03', at: 6,
      tracks: '/static/staticcams/detections/CCTV_2.json',
      activityId: 'PIP-SP1-2002', activityName: 'Stringing 16" API 5L Gr X52', progress: 41,
      summary: 'Pipe stock and an active handling workfront are visible. Confirm chainage and installed quantity before accepting progress.',
    },
    drilling: {
      src: '/static/staticcams/CCTV_1.mp4', label: 'Drilling operations · CAM-01', at: 151,
      tracks: '/static/staticcams/detections/CCTV_1.json',
      activityId: 'CIV-DUL-1005', activityName: 'Pump Foundation Piling', progress: 54,
      summary: 'A rotary drilling workfront and field crew are visible. Confirm pile number, bore depth and accepted quantity before accepting progress.',
    },
  };
  let activeFeed = 'yard';
  let workerMode = 'scan';
  let cameraTracker = null;
  let cameraAiEnabled = true;
  let latestCameraDetections = [];
  let cameraModelState = 'Local playback · loading vision ensemble';
  let currentSafetyEvent = null;
  const warnedEvents = new Set();
  const cameraVideo = root.querySelector('#site-camera-video');
  const cameraBoxes = root.querySelector('#site-camera-boxes');

  const timeLabel = seconds => {
    const whole = Math.max(0, Math.round(Number(seconds) || 0));
    return String(Math.floor(whole / 60)).padStart(2, '0') + ':' +
      String(whole % 60).padStart(2, '0');
  };
  const playMuted = video => {
    if (!video) return;
    video.muted = true;
    const attempt = video.play();
    if (attempt && attempt.catch) attempt.catch(() => {
      /* Autoplay can still be blocked by a browser setting; controls remain available. */
    });
  };
  const detectionMarkup = detections => {
    if (!detections.length) return '<div class="vision-detection-empty">No supported object detected at this frame</div>';
    const detail = item => {
      if (item.basis === 'pose') return 'Pose-backed worker · ' +
        int(item.visible_keypoints || 0) + ' visible joints · ' +
        Math.round(item.confidence * 100) + '% confidence';
      if (item.basis === 'camera_calibrated_lifting_corridor')
        return 'Calibrated lifting corridor · supervisor review required';
      if (item.basis === 'fixed_camera_scene_memory') return 'Fixed-camera scene memory · ' +
        int(item.supporting_observations || 0) + ' repeated confirmations';
      return 'Local object track · ' + Math.round(item.confidence * 100) + '% confidence';
    };
    return detections.slice().sort((a, b) =>
      (a.class === 'suspended-load' ? -2 : a.class === 'worker' ? -1 : 0) -
      (b.class === 'suspended-load' ? -2 : b.class === 'worker' ? -1 : 0) ||
      b.confidence - a.confidence)
      .slice(0, 6).map(item => '<div class="' + (item.review_required ? 'needs-review' : '') +
        '"><i class="' + E(item.class || 'equipment') + '"></i><span><b>' +
        E(item.label || 'Object') + ' #' + E(item.id) + '</b><small>' +
        E(detail(item)) + '</small></span></div>').join('');
  };

  const renderSafetyWatch = events => {
    const card = root.querySelector('#site-safety-watch');
    currentSafetyEvent = (events || []).find(item => item.severity === 'high') ||
      (events || [])[0] || null;
    card.hidden = !currentSafetyEvent;
    if (!currentSafetyEvent) return;
    const storageKey = 'veda-vision-alert-ack:' + pid + ':' + currentSafetyEvent.id;
    const acknowledged = localStorage.getItem(storageKey) === '1';
    root.querySelector('#site-safety-severity').textContent = acknowledged ? 'ACKNOWLEDGED' :
      String(currentSafetyEvent.severity || 'review').toUpperCase();
    root.querySelector('#site-safety-title').textContent = currentSafetyEvent.label ||
      'Safety review candidate';
    root.querySelector('#site-safety-summary').textContent =
      (currentSafetyEvent.signals || []).join('. ') + '.';
    root.querySelector('#site-safety-time').textContent = timeLabel(currentSafetyEvent.t);
    root.querySelector('#site-safety-state').textContent = acknowledged
      ? 'Supervisor acknowledged · review record retained locally'
      : (currentSafetyEvent.disclaimer || 'Assistive alert · supervisor confirmation required');
    const acknowledge = root.querySelector('#site-safety-ack');
    acknowledge.textContent = acknowledged ? 'Acknowledged' : 'Acknowledge';
    acknowledge.disabled = acknowledged;
    card.classList.toggle('acknowledged', acknowledged);
  };

  const seekWhenReady = (video, seconds) => {
    const seek = () => {
      if (Number.isFinite(video.duration) && video.duration > 0)
        video.currentTime = Math.min(seconds, Math.max(0, video.duration - .25));
      playMuted(video);
    };
    if (video.readyState >= 1) seek();
    else video.addEventListener('loadedmetadata', seek, {once: true});
  };
  const applyCameraMode = mode => {
    const ai = mode !== 'raw';
    cameraAiEnabled = ai;
    cameraBoxes.hidden = !ai;
    if (cameraTracker) cameraTracker.setVisible(ai);
    root.querySelectorAll('[data-site-vision-mode]').forEach(button =>
      button.classList.toggle('selected', button.dataset.siteVisionMode === (ai ? 'ai' : 'raw')));
    const hud = root.querySelector('.site-camera-hud > span');
    if (hud) hud.innerHTML = ai ? '<i></i> AI TRACKING' : '<i></i> RAW CCTV';
    const detected = root.querySelector('#site-camera-detected');
    const modelState = root.querySelector('#site-camera-model-state');
    const rail = root.querySelector('#site-camera-detections');
    if (!ai) {
      if (detected) detected.textContent = 'Overlay hidden';
      if (modelState) modelState.textContent = 'Raw CCTV · model overlay paused';
      if (rail) rail.innerHTML = '<div class="vision-detection-empty">AI overlay hidden in raw mode</div>';
    } else {
      if (detected) detected.textContent = latestCameraDetections.length +
        (latestCameraDetections.length === 1 ? ' model track' : ' model tracks');
      if (modelState) modelState.textContent = cameraModelState;
      if (rail) rail.innerHTML = detectionMarkup(latestCameraDetections);
    }
  };
  const bindCameraTracker = feed => {
    if (cameraTracker) cameraTracker.destroy();
    cameraBoxes.innerHTML = '<i class="vision-scan-line"></i>';
    latestCameraDetections = [];
    cameraModelState = 'Local playback · loading vision ensemble';
    renderSafetyWatch([]);
    root.querySelector('#site-camera-detected').textContent = 'Loading tracks…';
    root.querySelector('#site-camera-model-state').textContent = 'Local playback · loading vision ensemble';
    root.querySelector('#site-camera-detections').innerHTML =
      '<div class="vision-detection-empty">Loading time-synchronised model tracks…</div>';
    if (!window.VisionTracks) {
      root.querySelector('#site-camera-model-state').textContent = 'Vision tracker unavailable';
      return;
    }
    cameraTracker = window.VisionTracks.bind({video: cameraVideo, layer: cameraBoxes,
      dataUrl: feed.tracks, visible: cameraAiEnabled,
      onUpdate: (detections, payload, activeEvents) => {
        latestCameraDetections = detections;
        if (cameraAiEnabled) {
          root.querySelector('#site-camera-detected').textContent = detections.length +
            (detections.length === 1 ? ' model track' : ' model tracks');
          root.querySelector('#site-camera-detections').innerHTML = detectionMarkup(detections);
        }
        if ((activeEvents || []).length) {
          const alert = activeEvents[0];
          if (!warnedEvents.has(alert.id)) {
            warnedEvents.add(alert.id);
            window.toast('Safety review at ' + timeLabel(alert.t) + ': ' + alert.label, 'bad');
          }
        }
      },
      onStatus: (status, payload) => {
        cameraModelState = status === 'ready'
          ? (payload.model.name + ' · ' + payload.sample_fps + ' sampled FPS · browser interpolation')
          : 'Model track data could not be loaded';
        if (cameraAiEnabled) root.querySelector('#site-camera-model-state').textContent = cameraModelState;
        renderSafetyWatch(status === 'ready' ? payload.events || [] : []);
      }});
    cameraTracker.ready.catch(() => {});
  };
  const renderFeed = key => {
    const feed = feeds[key] || feeds.yard;
    activeFeed = key in feeds ? key : 'yard';
    cameraVideo.pause();
    cameraVideo.muted = true;
    cameraVideo.src = feed.src;
    cameraVideo.load();
    seekWhenReady(cameraVideo, feed.at);
    root.querySelector('#site-camera-hud-label').textContent = feed.label;
    root.querySelector('#site-camera-time').textContent = 'Frame ' + timeLabel(feed.at);
    root.querySelector('#site-camera-activity').textContent = feed.activityId + ' · ' + feed.activityName;
    root.querySelector('#site-camera-progress').textContent = feed.progress + '%';
    root.querySelector('#site-camera-summary').textContent = feed.summary;
    root.querySelector('#site-camera-download').href = feed.src;
    bindCameraTracker(feed);
    applyCameraMode('ai');
  };
  const queueCaptureDraft = draft => {
    try {
      localStorage.setItem('veda-visual-capture-draft', JSON.stringify({projectId: pid, ...draft}));
      go('capture');
    } catch (_) { window.toast('Could not prepare the field draft in this browser', 'bad'); }
  };

  root.querySelectorAll('[data-site-vision-tab]').forEach(button => button.onclick = () => {
    const tab = button.dataset.siteVisionTab;
    root.querySelectorAll('[data-site-vision-tab]').forEach(item =>
      item.classList.toggle('selected', item === button));
    root.querySelectorAll('[data-site-vision-pane]').forEach(pane =>
      pane.hidden = pane.dataset.siteVisionPane !== tab);
    if (tab === 'uploads') seekWhenReady(root.querySelector('#site-worker-video'), 192);
  });
  root.querySelector('#site-camera-select').onchange = event => renderFeed(event.target.value);
  root.querySelectorAll('[data-site-vision-mode]').forEach(button =>
    button.onclick = () => applyCameraMode(button.dataset.siteVisionMode));
  cameraVideo.ontimeupdate = () => {
    root.querySelector('#site-camera-time').textContent = 'Frame ' + timeLabel(cameraVideo.currentTime);
  };
  root.querySelector('#site-camera-field-draft').onclick = () => {
    const feed = feeds[activeFeed];
    queueCaptureDraft({source: 'Fixed camera review · ' + feed.label,
      activityId: feed.activityId, activityName: feed.activityName, progress: feed.progress,
      location: feed.label, mediaName: feed.src.split('/').pop(),
      text: 'Fixed camera review (' + feed.label + ', frame ' + timeLabel(cameraVideo.currentTime) +
        '): ' + feed.activityId + ' ' + feed.activityName + ' visual progress is estimated at ' +
        feed.progress + '%. Work remains. ' + feed.summary + ' Human verification required.'});
  };
  root.querySelector('#site-safety-review').onclick = () => {
    if (!currentSafetyEvent) return;
    applyCameraMode('ai');
    seekWhenReady(cameraVideo, Math.max(0, Number(currentSafetyEvent.t) - 1.5));
    cameraVideo.play().catch(() => {});
    root.querySelector('#site-safety-watch').classList.add('reviewing');
  };
  root.querySelector('#site-safety-ack').onclick = () => {
    if (!currentSafetyEvent) return;
    localStorage.setItem('veda-vision-alert-ack:' + pid + ':' + currentSafetyEvent.id, '1');
    renderSafetyWatch([currentSafetyEvent]);
    window.toast('Safety alert acknowledged. It remains available for review.', 'good');
  };

  const workerVideo = root.querySelector('#site-worker-video');
  const workerBoxes = root.querySelector('#site-worker-boxes');
  let workerTracker = null;
  const title = root.querySelector('#site-worker-title');
  const description = root.querySelector('#site-worker-description');
  const note = root.querySelector('#site-worker-note');
  const result = root.querySelector('#site-worker-result');
  const storageKey = 'veda-worker-video-meta:' + pid;
  try {
    const stored = JSON.parse(localStorage.getItem(storageKey) || 'null');
    if (stored) {
      title.value = stored.title || title.value;
      description.value = stored.description || description.value;
      note.value = stored.note || note.value;
    }
  } catch (_) {}
  const saveWorkerMeta = () => {
    try { localStorage.setItem(storageKey, JSON.stringify({title: title.value,
      description: description.value, note: note.value})); } catch (_) {}
  };
  [title, description, note].forEach(input => input.oninput = saveWorkerMeta);
  const paintWorkerResult = (mode, visionPayload) => {
    workerMode = mode;
    const pctMatch = note.value.match(/\b(100(?:\.0+)?|\d{1,2}(?:\.\d+)?)\s*%/);
    const progress = pctMatch ? Number(pctMatch[1]) : 72;
    result.hidden = false;
    workerBoxes.hidden = false;
    root.querySelector('#site-worker-result-state').textContent = mode === 'note'
      ? 'Supervisor-authored' : 'Local vision scan';
    root.querySelector('#site-worker-result-title').textContent = title.value.trim() ||
      'Worker-uploaded site observation';
    root.querySelector('#site-worker-result-summary').textContent = mode === 'note'
      ? (note.value.trim() || 'Add a supervisor observation before creating the field draft.')
      : 'The local detector produced ' +
        (((visionPayload || {}).class_samples || {}).Worker || 0) + ' person and ' +
        ((((visionPayload || {}).class_samples || {}).Vehicle || 0) +
          (((visionPayload || {}).class_samples || {}).Truck || 0) +
          (((visionPayload || {}).class_samples || {}).Bus || 0)) +
        ' vehicle detections across sampled frames. Reporter context: ' +
        (description.value.trim() || 'No description supplied.') +
        ' The model does not measure installed quantity; confirm the activity and progress before approval.';
    root.querySelector('#site-worker-result-progress').textContent = progress + '%';
    result.dataset.progress = String(progress);
  };
  root.querySelector('#site-worker-use-note').onclick = () => paintWorkerResult('note');
  if (window.VisionTracks) {
    workerTracker = window.VisionTracks.bind({video: workerVideo, layer: workerBoxes,
      dataUrl: '/static/staticcams/detections/LiveCamera_1.json', visible: false});
    workerTracker.ready.catch(() => {});
  }
  root.querySelector('#site-worker-scan').onclick = async event => {
    const button = event.currentTarget;
    button.disabled = true; button.textContent = 'Loading local model tracks…';
    try {
      if (!workerTracker) throw new Error('Vision tracker unavailable');
      const payload = await workerTracker.ready;
      workerTracker.setVisible(true);
      seekWhenReady(workerVideo, Number(payload.highlight_time) || 192);
      workerVideo.muted = true;
      workerVideo.play().catch(() => {});
      paintWorkerResult('scan', payload);
      result.scrollIntoView({behavior: 'smooth', block: 'nearest'});
    } catch (_) {
      window.toast('Local model tracks could not be loaded', 'bad');
    } finally {
      button.disabled = false; button.textContent = 'Let AI scan';
    }
  };
  root.querySelector('#site-worker-field-draft').onclick = () => {
    const progress = Number(result.dataset.progress || 72);
    const summary = root.querySelector('#site-worker-result-summary').textContent;
    queueCaptureDraft({source: (workerMode === 'note' ? 'Supervisor observation' : 'Video review draft') +
        ' · LiveCamera_1.mp4', activityId: 'PIP-DUL-2016',
      activityName: 'Piping Erection on Rack - Duliajan', progress,
      location: 'Duliajan terminal · pipe-rack workfront', mediaName: 'LiveCamera_1.mp4',
      text: 'Worker video review (LiveCamera_1.mp4): ' +
        (title.value.trim() || 'Duliajan field walk-through') + '. ' + summary +
        ' PIP-DUL-2016 Piping Erection on Rack - Duliajan visual progress is estimated at ' +
        progress + '%. Work remains. Human verification required.'});
  };
  root.querySelector('#site-worker-share').onclick = async () => {
    const url = new URL('/static/staticcams/LiveCamera_1.mp4', location.origin).href;
    try {
      if (navigator.share) await navigator.share({title: title.value.trim() || 'VEDA site video',
        text: description.value.trim(), url});
      else { await navigator.clipboard.writeText(url); window.toast('Local video link copied', 'good'); }
    } catch (error) {
      if (!error || error.name !== 'AbortError') window.toast('This browser could not share the clip', 'bad');
    }
  };
  renderFeed('yard');
};
VIEWS.hasActiveSiteVision = () => Boolean(VIEWS._siteVisionBusy);

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

/* ========================================= evidence-aware schedule timeline */
function timelinePos(value, start, span) {
  if (!value) return null;
  const parsed = new Date(day(value) + 'T00:00:00Z').getTime();
  const first = new Date(start + 'T00:00:00Z').getTime();
  if (!Number.isFinite(parsed) || !Number.isFinite(first)) return null;
  return Math.max(0, Math.min(100, (parsed - first) / span * 100));
}

function timelineBar(startValue, finishValue, rangeStart, rangeMs, cls, label) {
  const left = timelinePos(startValue, rangeStart, rangeMs);
  const right = timelinePos(finishValue, rangeStart, rangeMs);
  if (left === null || right === null) return '';
  const begin = Math.min(left, right), width = Math.max(.35, Math.abs(right - left));
  return '<i class="tl-bar ' + cls + '" style="left:' + begin + '%;width:' + width +
    '%"><span>' + E(label) + ' · ' + day(startValue) + ' → ' + day(finishValue) + '</span></i>';
}

function timelineMark(value, rangeStart, rangeMs, cls, label) {
  const left = timelinePos(value, rangeStart, rangeMs);
  if (left === null) return '';
  return '<i class="tl-mark ' + cls + '" style="left:' + left + '%"><span>' +
    E(label) + ' · ' + day(value) + '</span></i>';
}

VIEWS.timeline = async (pid, params) => {
  params = params || {};
  const query = new URLSearchParams({
    window: params.window || '90', anchor: params.anchor || '', q: params.q || '',
    wbs: params.wbs || '', critical: params.critical ? 'true' : 'false',
    blockers: params.blockers ? 'true' : 'false', limit: 350,
  });
  const r = await A('/projects/' + pid + '/timeline?' + query);
  const startMs = new Date(r.range_start + 'T00:00:00Z').getTime();
  const finishMs = new Date(r.range_finish + 'T00:00:00Z').getTime();
  const spanMs = Math.max(86400000, finishMs - startMs);
  const spanDays = Math.max(1, Math.round(spanMs / 86400000));
  const canvasWidth = Math.max(760, Math.min(5200, spanDays * (r.window === 'full' ? 7 : 10)));
  const ticks = Array.from({length: 7}, (_, index) => {
    const at = new Date(startMs + spanMs * index / 6);
    return '<i style="left:' + (index * 100 / 6) + '%"><span>' +
      E(at.toISOString().slice(0, 10)) + '</span></i>';
  }).join('');
  const anchor = timelinePos(r.anchor, r.range_start, spanMs);
  const rows = (r.activities || []).map(a => {
    const blockerCount = Number(a.constraint_count || 0) + Number(a.hindrance_count || 0);
    const tracks = timelineBar(a.baseline_start, a.baseline_finish, r.range_start, spanMs,
      'baseline', 'Baseline/reference') +
      timelineBar(a.start, a.finish, r.range_start, spanMs, 'current', 'Current schedule') +
      timelineBar(a.actual_start, a.actual_finish, r.range_start, spanMs, 'actual', 'Recorded actual') +
      timelineMark(a.actual_start, r.range_start, spanMs, 'actual-start', 'Recorded actual start') +
      timelineMark(a.actual_finish, r.range_start, spanMs, 'actual-finish', 'Recorded actual finish') +
      timelineMark(a.verified_actual_start, r.range_start, spanMs, 'verified-start', 'Field-verified start') +
      timelineMark(a.verified_actual_finish, r.range_start, spanMs, 'verified-finish', 'Field-verified finish');
    return '<div class="timeline-row"><button class="timeline-label" onclick="go(\'activity\',{id:' +
      a.uid + '})"><small>' + E(a.display_id || ('UID ' + a.uid)) + ' · ' + E(a.wbs || '') +
      '</small><b>' + E(a.name) + '</b><span>' + tagFor(a.status, ST) +
      (a.critical ? '<em class="tag red">CP</em>' : '') +
      (a.evidence_count ? '<em class="tag blue">' + int(a.evidence_count) + ' evidence</em>' : '') +
      (blockerCount ? '<em class="tag amber">' + int(blockerCount) + ' control flags</em>' : '') +
      (a.bim_identifier_count ? '<em class="tag violet">BIM ' + int(a.bim_identifier_count) + '</em>' : '') +
      '</span></button><div class="timeline-track">' + ticks.replaceAll('<span>', '<span hidden>') +
      (anchor === null ? '' : '<i class="tl-data-date" style="left:' + anchor + '%"><span>Data/status date ' +
        E(r.anchor) + '</span></i>') + tracks + '</div></div>';
  }).join('');
  const legend = '<div class="timeline-legend"><span class="baseline"><i></i>Baseline/reference</span>' +
    '<span class="current"><i></i>Current schedule</span><span class="actual"><i></i>Recorded actual</span>' +
    '<span class="verified"><i></i>Field-verified event</span><span class="data-date"><i></i>Data/status date</span></div>';
  return head('Schedule Timeline', 'Baseline × current plan × verified execution',
    '<button class="btn sm" onclick="go(\'controls\')">Execution Control</button>') +
    '<div class="timeline-toolbar"><input class="inp" id="tl-query" placeholder="Search activity, ID or WBS" value="' +
      E(params.q || '') + '"><input class="inp" id="tl-wbs" placeholder="WBS prefix" value="' + E(params.wbs || '') + '">' +
      '<select class="inp" id="tl-window"><option value="14">2 weeks</option><option value="42">6 weeks</option>' +
      '<option value="90">90 days</option><option value="180">180 days</option><option value="full">Full schedule</option></select>' +
      '<button class="btn sm' + (params.critical ? ' primary' : '') + '" id="tl-critical">Critical only</button>' +
      '<button class="btn sm' + (params.blockers ? ' primary' : '') + '" id="tl-blockers">With control flags</button>' +
      '<button class="btn sm" id="tl-reset">Reset</button><span class="spacer"></span><span class="mono">' +
      int(r.returned) + ' activities · ' + E(r.range_start) + ' → ' + E(r.range_finish) + '</span></div>' +
    legend + '<section class="timeline-viewport"><div class="timeline-canvas" style="--timeline-width:' +
      canvasWidth + 'px"><div class="timeline-axis-row"><div class="timeline-axis-label">Activity</div>' +
      '<div class="timeline-axis">' + ticks + '</div></div>' +
      (rows || empty('No activities in this window', 'Change the range or filters.')) + '</div></section>' +
    (r.limited ? '<div class="note warn">The view is capped at 350 activities. Narrow the WBS or search to inspect a dense schedule safely.</div>' : '') +
    '<div class="note">Bars and markers preserve their source meaning. A field-verified event does not silently replace the recorded schedule actual.</div>';
};

VIEWS.bind_timeline = (pid, params) => {
  const set = patch => go('timeline', Object.assign({}, params, patch));
  const windowSelect = document.getElementById('tl-window');
  if (windowSelect) { windowSelect.value = params.window || '90'; windowSelect.onchange = () => set({window: windowSelect.value}); }
  const q = document.getElementById('tl-query');
  const wbs = document.getElementById('tl-wbs');
  const apply = () => set({q: q ? q.value : '', wbs: wbs ? wbs.value : ''});
  if (q) q.onkeydown = e => { if (e.key === 'Enter') apply(); };
  if (wbs) wbs.onkeydown = e => { if (e.key === 'Enter') apply(); };
  const critical = document.getElementById('tl-critical');
  if (critical) critical.onclick = () => set({critical: params.critical ? '' : '1'});
  const blockers = document.getElementById('tl-blockers');
  if (blockers) blockers.onclick = () => set({blockers: params.blockers ? '' : '1'});
  const reset = document.getElementById('tl-reset');
  if (reset) reset.onclick = () => go('timeline', {});
};

/* ===================================================== execution controls */
function controlForm(title, summary, id, body, button) {
  return '<details class="control-form"><summary><div><b>' + E(title) + '</b><span>' +
    E(summary) + '</span></div><i>+</i></summary><form id="' + id + '">' + body +
    '<footer><button class="btn primary" type="submit">' + E(button) + '</button></footer></form></details>';
}

function readinessCard(a) {
  const constraints = (a.constraints || []).map(c => '<div class="constraint-line"><div>' +
    tagFor(c.status, ST) + '<b>' + E(String(c.constraint_type || '').replace(/_/g, ' ')) + '</b>' +
    '<span>' + E(c.description) + '</span></div><small>' + (c.owner ? E(c.owner) + ' · ' : '') +
    'needed ' + day(c.required_by) + '</small>' +
    (['open', 'in_progress'].includes(c.status) ? '<button class="btn sm" data-clear-constraint="' +
      E(c.id) + '">Clear</button>' : '') + '</div>').join('');
  return '<article class="readiness-card ' + E(a.readiness) + '"><header><div><small>' +
    E(a.display_id || ('UID ' + a.uid)) + ' · ' + E(a.wbs || '') + '</small><h3>' + E(a.name) +
    '</h3></div>' + tagFor(a.readiness, ST) + '</header><div class="readiness-meta"><span>' +
    day(a.start) + ' → ' + day(a.finish) + '</span><span>' +
    (a.days_to_start === null || a.days_to_start === undefined ? 'start not dated' :
      (a.days_to_start < 0 ? Math.abs(a.days_to_start) + 'd past planned start' : a.days_to_start + 'd to start')) +
    '</span>' + (a.critical ? '<span class="tag red">critical path</span>' : '') + '</div>' +
    '<div class="constraint-list">' + (constraints || '<span class="constraint-empty">No readiness assessment recorded.</span>') +
    '</div><footer><button class="btn sm" onclick="go(\'activity\',{id:' + a.uid + '})">Open activity</button>' +
    '<button class="btn sm" data-add-constraint="' + a.uid + '">Add constraint</button></footer></article>';
}

VIEWS.controls = async (pid, params) => {
  params = params || {};
  const r = await A('/projects/' + pid + '/execution-controls?' + new URLSearchParams({
    days: params.days || 42, anchor: params.anchor || '',
  }));
  const look = r.lookahead || {activities: [], counts: {}};
  const hindrances = (r.hindrances || []).map(h => '<article class="hindrance-card"><header><div>' +
    '<small>' + E(h.ref || h.category || 'Site hindrance') + '</small><h3>' + E(h.title) + '</h3></div>' +
    sev(h.severity) + tagFor(h.status, ST) + '</header><p>' + E(h.description || 'No description') + '</p>' +
    '<div class="hindrance-meta"><span>' + day(h.started_on || h.reported_on) + ' → ' + day(h.cleared_on) + '</span>' +
    (h.owner ? '<span>Owner · ' + E(h.owner) + '</span>' : '') +
    (h.responsibility ? '<span>Responsibility · ' + E(h.responsibility) + '</span>' : '') +
    (h.schedule_impact_days !== null && h.schedule_impact_days !== undefined ? '<span>' + num(h.schedule_impact_days, 1) + 'd stated impact</span>' : '') +
    '</div>' +
    '<footer><span>' + (h.activity_uids || []).map(uid => '<button class="link mono" onclick="go(\'activity\',{id:' + uid + '})">UID ' + uid + '</button>').join(' ') + '</span>' +
    (['open', 'monitoring'].includes(h.status) ? '<button class="btn sm" data-clear-hindrance="' + E(h.id) + '">Mark cleared</button>' : '') +
    '</footer></article>').join('');
  const context = (r.site_context || []).slice(0, 30).map(item => '<tr><td class="mono">' + day(item.date) +
    '</td><td>' + tagFor(item.observation_type, {weather:'blue',manpower:'violet',equipment:'amber',report_metadata:'grey'}) +
    '</td><td>' + E(item.description) + '</td><td>' + E(item.location || '—') + '</td><td>' +
    (item.activity_uids || []).map(uid => '<button class="link mono" onclick="go(\'activity\',{id:' + uid + '})">' + uid + '</button>').join(', ') + '</td></tr>').join('');
  const bimRows = (r.bim_identifiers || []).map(item => '<tr><td>' + tagFor(item.status, ST) + '</td><td class="mono">' +
    E(item.identifier_type) + '</td><td class="mono">' + E(item.identifier_value) + '</td><td>' + E(item.model_name || '—') +
    '</td><td>' + E(item.element_type || '—') + '</td><td>' + (item.activity_uid ? '<button class="link" onclick="go(\'activity\',{id:' +
    item.activity_uid + '})">' + E(item.display_id || ('UID ' + item.activity_uid)) + ' · ' + E(item.activity_name || '') + '</button>' :
      '<span class="tag violet">awaiting proposal verification</span>') + '</td></tr>');
  const newScope = (r.new_scope_events || []).map(item => '<article class="new-scope-card"><div><small>' +
    E(item.source_file || 'Field evidence') + ' · ' + day(item.event_date) + '</small><b>' +
    E(item.description || 'Unplanned execution event') + '</b><span>Kept outside the current schedule until a planner chooses to propose an activity.</span></div>' +
    '<button class="btn sm" data-new-scope="' + E(item.execution_event_id) + '" data-evidence="' + E(item.evidence_id || '') +
    '" data-name="' + E(item.description || '') + '">Draft governed activity</button></article>').join('');

  const constraintForm = controlForm('Add readiness constraint', 'Tie a drawing, material, access or other hold to one activity.',
    'constraint-form', '<div class="control-form-grid"><label><span>Activity UID</span><input class="inp" name="activity_uid" required></label>' +
    '<label><span>Constraint type</span><select class="inp" name="constraint_type"><option>drawing</option><option>material</option><option>permit</option><option>access</option><option>workfront</option><option>crew</option><option>equipment</option><option>inspection</option><option>ndt</option><option>safety</option><option>interface</option><option>other</option></select></label>' +
    '<label><span>Needed by</span><input class="inp" name="required_by" type="date"></label><label><span>Owner</span><input class="inp" name="owner"></label>' +
    '<label><span>Control level</span><select class="inp" name="criticality"><option value="blocker">Blocker</option><option value="watch">Watch</option></select></label></div>' +
    '<label><span>Description</span><textarea class="inp" name="description" rows="3" required></textarea></label>', 'Add constraint');
  const hindranceForm = controlForm('Register hindrance', 'Record what actually obstructed work; optionally make it a readiness blocker.',
    'hindrance-form', '<div class="control-form-grid"><label><span>Title</span><input class="inp" name="title" required></label>' +
    '<label><span>Reference</span><input class="inp" name="ref" placeholder="HIN-001"></label><label><span>Category</span><select class="inp" name="category"><option>weather</option><option>drawing</option><option>material</option><option>access</option><option>permit</option><option>equipment</option><option>interface</option><option>other</option></select></label>' +
    '<label><span>Severity</span><select class="inp" name="severity"><option>medium</option><option>low</option><option>high</option><option>critical</option></select></label>' +
    '<label><span>Started</span><input class="inp" type="date" name="started_on"></label><label><span>Activity UIDs</span><input class="inp" name="activity_uids" placeholder="101, 102"></label>' +
    '<label><span>Owner</span><input class="inp" name="owner"></label><label><span>Responsible party</span><input class="inp" name="responsibility"></label>' +
    '<label><span>Stated impact days</span><input class="inp" type="number" min="0" step="0.5" name="schedule_impact_days"></label></div>' +
    '<label><span>Description and observed cause</span><textarea class="inp" name="description" rows="3"></textarea></label>' +
    '<label class="checkline"><input type="checkbox" name="create_readiness_blocker"><span>Create an open readiness blocker for every listed activity</span></label>', 'Register hindrance');
  const contextForm = controlForm('Add site context', 'Weather, manpower and equipment remain typed evidence—not automatic progress.',
    'context-form', '<div class="control-form-grid"><label><span>Date</span><input class="inp" type="date" name="date" value="' +
    E(look.anchor || '') + '"></label><label><span>Location</span><input class="inp" name="location"></label><label><span>Contractor</span><input class="inp" name="contractor"></label>' +
    '<label><span>Related activity UIDs</span><input class="inp" name="activity_uids" placeholder="101, 102"></label></div>' +
    '<label><span>Weather</span><input class="inp" name="weather" placeholder="Heavy rain 14:00–16:30"></label>' +
    '<div class="control-form-grid"><label><span>Manpower · one per line</span><textarea class="inp" rows="3" name="manpower" placeholder="Welders: 8&#10;Fitters: 12"></textarea></label>' +
    '<label><span>Equipment · one per line</span><textarea class="inp" rows="3" name="equipment" placeholder="Crane: 1&#10;Excavator: 2"></textarea></label></div>' +
    '<label><span>Context note</span><textarea class="inp" rows="2" name="notes"></textarea></label>', 'Save confirmed context');
  const bimForm = controlForm('Link BIM identifier', 'Add an exact model identity signal to an existing activity.', 'bim-form',
    '<div class="control-form-grid"><label><span>Activity UID</span><input class="inp" name="activity_uid" required></label>' +
    '<label><span>Identifier type</span><select class="inp" name="identifier_type"><option>IFC_GUID</option><option>REVIT_UNIQUE_ID</option><option>COBIE_TAG</option><option>BIM_OBJECT_ID</option><option>MODEL_ELEMENT_ID</option></select></label>' +
    '<label><span>Identifier</span><input class="inp mono" name="identifier_value" required></label><label><span>Model</span><input class="inp" name="model_name"></label>' +
    '<label><span>Element type</span><input class="inp" name="element_type"></label><label><span>Location</span><input class="inp" name="location"></label></div>', 'Link identifier');
  const suggestionForm = controlForm('Suggest new schedule activity', 'Creates a pending proposal only; it cannot bypass dry-run and approval.',
    'new-activity-form', '<input type="hidden" name="source_event_id"><input type="hidden" name="evidence_ids"><div class="control-form-grid">' +
    '<label><span>Activity name</span><input class="inp" name="name" required></label><label><span>Duration days</span><input class="inp" type="number" min="0" step="0.5" name="duration"></label>' +
    '<label><span>Planned start</span><input class="inp" type="date" name="start"></label><label><span>Parent UID</span><input class="inp" type="number" name="parent_uid"></label>' +
    '<label><span>BIM identifier</span><input class="inp mono" name="identifier_value"></label><label><span>BIM model</span><input class="inp" name="model_name"></label></div>' +
    '<label><span>Why this is new scope</span><textarea class="inp" rows="3" name="reason"></textarea></label>', 'Create governed proposal');

  return head('Execution Control', 'Look-ahead readiness · hindrances · field context · BIM identity',
    '<select class="inp" id="lookahead-days"><option value="14">2 weeks</option><option value="42">6 weeks</option><option value="90">90 days</option></select>' +
    '<button class="btn sm" onclick="go(\'timeline\',{window:\'42\'})">Open timeline</button>') +
    '<div class="grid g4 control-summary">' + stat('Open hindrances', int(r.counts.open_hindrances), 'observed obstructions', r.counts.open_hindrances ? 'warm' : 'good') +
    stat('Open readiness constraints', int(r.counts.open_constraints), 'drawing, material, access and other holds', r.counts.open_constraints ? 'warm' : 'good') +
    stat('Confirmed BIM identities', int(r.counts.bim_links), 'exact model-to-activity links') +
    stat('New-scope events', int(r.counts.new_scope_waiting), 'not yet represented by a governed activity proposal', r.counts.new_scope_waiting ? 'warm' : 'good') + '</div>' +
    '<div class="control-forms">' + constraintForm + hindranceForm + contextForm + bimForm + suggestionForm + '</div>' +
    '<div class="section-divider"><span>' + E(look.anchor) + ' → ' + E(look.horizon) + '</span><small>Readiness look-ahead</small></div>' +
    '<div class="readiness-strip"><span class="green">' + int(look.counts.ready) + ' ready</span><span class="red">' + int(look.counts.blocked) +
    ' blocked</span><span class="amber">' + int(look.counts.attention) + ' attention</span><span>' + int(look.counts.not_assessed) + ' not assessed</span><small>' + E(look.definition) + '</small></div>' +
    '<div class="readiness-grid">' + ((look.activities || []).map(readinessCard).join('') || empty('No unfinished activities in this look-ahead', 'Change the horizon or verify the schedule dates.')) + '</div>' +
    '<div class="section-divider"><span>Hindrance register</span><small>Actual obstructions, separate from possible risks</small></div>' +
    '<div class="hindrance-grid">' + (hindrances || empty('No hindrances registered', 'Use the form above when a condition actually obstructs work.')) + '</div>' +
    '<div class="section-divider"><span>New-scope queue</span><small>Reality graph events outside the current schedule</small></div>' +
    '<div class="new-scope-list">' + (newScope || empty('No unrepresented execution events', 'New physical scope appears here without being forced onto the nearest activity.')) + '</div>' +
    panel('Weather, manpower and equipment context <small>' + int((r.site_context || []).length) + '</small>',
      '<div class="body"><div class="note">Context helps explain execution conditions. It never becomes progress without activity evidence.</div>' +
      '<div class="tw"><table><thead><tr><th>Date</th><th>Type</th><th>Observation</th><th>Location</th><th>Activities</th></tr></thead><tbody>' + context + '</tbody></table></div></div>') +
    panel('BIM and model identifiers <small>' + int((r.bim_identifiers || []).length) + '</small>',
      '<div class="body">' + table([{t:'State'},{t:'Type'},{t:'Identifier'},{t:'Model'},{t:'Element'},{t:'Schedule activity'}], r.bim_identifiers || [], (_, index) => bimRows[index],
        {emptyTitle:'No BIM identifiers linked',emptyMsg:'VEDA works without BIM. Add identifiers only when an authoritative model mapping is available.'}) + '</div>');
};

VIEWS.bind_controls = (pid, params) => {
  const days = document.getElementById('lookahead-days');
  if (days) { days.value = String(params.days || 42); days.onchange = () => go('controls', {days: days.value}); }
  const payload = form => {
    const body = Object.fromEntries(new FormData(form).entries());
    form.querySelectorAll('input[type="checkbox"][name]').forEach(box => body[box.name] = box.checked);
    return body;
  };
  const bindForm = (id, path, message) => {
    const form = document.getElementById(id);
    if (!form) return;
    form.onsubmit = async event => {
      event.preventDefault(); const button = form.querySelector('[type="submit"]'); button.disabled = true;
      try { await P(path, payload(form)); window.toast(message, 'good'); window.render(); }
      catch (error) { window.toast(error.message, 'bad'); button.disabled = false; }
    };
  };
  bindForm('constraint-form', '/projects/' + pid + '/readiness-constraints', 'Readiness constraint added');
  bindForm('hindrance-form', '/projects/' + pid + '/hindrances', 'Hindrance registered');
  bindForm('context-form', '/projects/' + pid + '/site-context', 'Site context saved as evidence');
  bindForm('bim-form', '/projects/' + pid + '/bim-identifiers', 'BIM identifier linked');
  bindForm('new-activity-form', '/projects/' + pid + '/new-activity-suggestions', 'Governed activity proposal created');
  document.querySelectorAll('[data-clear-constraint]').forEach(button => button.onclick = async () => {
    await P('/projects/' + pid + '/readiness-constraints/' + button.dataset.clearConstraint + '/status', {status:'cleared'});
    window.toast('Constraint cleared', 'good'); window.render();
  });
  document.querySelectorAll('[data-clear-hindrance]').forEach(button => button.onclick = async () => {
    await P('/projects/' + pid + '/hindrances/' + button.dataset.clearHindrance + '/status', {status:'cleared'});
    window.toast('Hindrance cleared', 'good'); window.render();
  });
  document.querySelectorAll('[data-add-constraint]').forEach(button => button.onclick = () => {
    const form = document.getElementById('constraint-form'); const details = form && form.closest('details');
    if (!form) return; form.elements.activity_uid.value = button.dataset.addConstraint;
    if (details) details.open = true; form.scrollIntoView({behavior:'smooth', block:'center'});
  });
  document.querySelectorAll('[data-new-scope]').forEach(button => button.onclick = () => {
    const form = document.getElementById('new-activity-form'); const details = form && form.closest('details');
    if (!form) return;
    form.elements.source_event_id.value = button.dataset.newScope;
    form.elements.evidence_ids.value = button.dataset.evidence || '';
    form.elements.name.value = String(button.dataset.name || '').slice(0, 240);
    if (details) details.open = true; form.scrollIntoView({behavior:'smooth', block:'center'});
  });
};

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
    '>' + (r.criticality_available ? 'Critical only' : 'Critical — not evaluable') + '</button>' +
    '<button class="btn sm' + (params.late ? ' primary' : '') +
    '" id="fl" ' + (r.completed_late_evaluable ? '' : 'disabled title="No completed actual finishes available for baseline comparison"') +
    '>' + (r.completed_late_evaluable ? 'Completed after reference finish' : 'Completed after reference — not evaluable') + '</button>' +
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
  // Older running VEDA processes may not yet include the additive
  // execution-control collections. Treat omitted collections as empty so a
  // milestone/activity click remains readable during a rolling restart.
  for (const key of ['predecessors', 'successors', 'assignments', 'issues',
    'risks', 'proposals', 'hindrances', 'readiness_constraints',
    'site_context', 'bim_identifiers', 'audit']) {
    if (!Array.isArray(d[key])) d[key] = [];
  }
  if (!d.evidence || typeof d.evidence !== 'object') d.evidence = {};
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
      ? num(a.total_float_days, 1) + 'd' : '—',
      activityCriticalAvailable ? (a.critical ? 'critical' : 'source/engine float') : 'Not evaluable — float/criticality unavailable from source',
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

    '<div class="grid g2">' +
    panel('Readiness constraints <small>' + d.readiness_constraints.length + '</small>',
      table([{t:'Type'},{t:'Description'},{t:'Needed by'},{t:'Owner'},{t:'Status'}],
        d.readiness_constraints, c => '<tr><td>' + E(String(c.constraint_type || '').replace(/_/g, ' ')) +
        '</td><td>' + E(c.description) + '</td><td class="mono">' + day(c.required_by) + '</td><td>' +
        E(c.owner || '—') + '</td><td>' + tagFor(c.status, ST) + '</td></tr>',
        {emptyTitle:'Readiness not assessed',emptyMsg:'No recorded constraint does not mean ready.'}),
      '<button class="btn sm" onclick="go(\'controls\')">Manage readiness</button>') +
    panel('Hindrances <small>' + d.hindrances.length + '</small>',
      table([{t:'Hindrance'},{t:'Started'},{t:'Impact'},{t:'Status'}], d.hindrances, h =>
        '<tr><td><b>' + E(h.title) + '</b><small class="block-sub">' + E(h.cause || h.description || '') +
        '</small></td><td class="mono">' + day(h.started_on || h.reported_on) + '</td><td class="mono">' +
        (h.schedule_impact_days === null || h.schedule_impact_days === undefined ? '—' : num(h.schedule_impact_days, 1) + 'd') +
        '</td><td>' + tagFor(h.status, ST) + '</td></tr>',
        {emptyTitle:'No hindrance linked',emptyMsg:'Observed obstructions remain separate from possible risks.'}),
      '<button class="btn sm" onclick="go(\'controls\')">Open register</button>') + '</div>' +

    '<div class="grid g2">' +
    panel('Site context <small>' + d.site_context.length + '</small>',
      table([{t:'Date'},{t:'Type'},{t:'Observation'},{t:'Source'}], d.site_context, item =>
        '<tr class="click" onclick="go(\'evidence-detail\',{id:\'' + E(item.id) + '\'})"><td class="mono">' +
        day(item.date) + '</td><td>' + E(String(item.observation_type || '').replace(/_/g, ' ')) + '</td><td>' +
        E(item.description) + '</td><td>' + prov(item.provenance) + '</td></tr>',
        {emptyTitle:'No linked context',emptyMsg:'Weather, manpower and equipment can be linked without asserting progress.'})) +
    panel('BIM identities <small>' + d.bim_identifiers.length + '</small>',
      table([{t:'Type'},{t:'Identifier'},{t:'Model'},{t:'State'}], d.bim_identifiers, item =>
        '<tr><td>' + E(item.identifier_type) + '</td><td class="mono">' + E(item.identifier_value) +
        '</td><td>' + E(item.model_name || '—') + '</td><td>' + tagFor(item.status, ST) + '</td></tr>',
        {emptyTitle:'No BIM identity',emptyMsg:'Optional; the activity remains usable without a model.'}),
      '<button class="btn sm" onclick="go(\'controls\')">Link identifier</button>') + '</div>' +

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
    stat('Critical activities', critAvailable ? int(r.critical.length) : '—',
      critAvailable ? (E(r.criticality_basis || 'source/engine criticality method') +
      (r.criticality_threshold_days !== null && r.criticality_threshold_days !== undefined
        ? ' · threshold ' + num(r.criticality_threshold_days, 2) + 'd' : '')) : 'Not evaluable — criticality unavailable from source',
      critAvailable && r.critical.length ? 'warm' : '') +
    stat('Negative float', critAvailable ? int(fd.negative || 0) : '—',
      critAvailable ? 'cannot meet constraints' : 'Not evaluable — float unavailable from source',
      critAvailable && fd.negative ? 'hot' : '') +
    stat('Project finish', r.finish ? day(r.finish) : '—',
      r.finish ? 'current forecast' : 'Not evaluable — current forecast unavailable') +
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
      '">' + E(f.status === 'not_evaluated' ? 'not evaluated' : f.status) + '</span>' +
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
    '<rect class="c-bar" x="' + (x(i) - bw / 2) + '" y="' +
    (H - 22 - (per[i] / maxP) * (H - 60)) + '" width="' + bw + '" height="' +
    ((per[i] / maxP) * (H - 60)) + '"/>').join('');
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
    '<path class="c-line" d="' + line + '" fill="none" stroke-width="2"/>' +
    series.map((s, i) => '<rect class="c-dot" x="' + (x(i) - 2.5) + '" y="' +
      (yC(cum[i]) - 2.5) + '" width="5" height="5"/>').join('') +
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
  const risks = Array.isArray(r.risks) ? r.risks : [];
  const statusOptions = ['open', 'monitoring', 'closed'];
  const statusLabel = {open: 'Open', monitoring: 'Monitoring', closed: 'Closed'};
  return head('Risks', 'Possible future events',
    '<span class="tag grey">Risk = might happen</span>') +
    panel('Risks <small>' + risks.length + '</small>',
      '<div class="body">' + (risks.length ? risks.map(i => {
        const activityUids = Array.isArray(i.activity_uids) ? i.activity_uids : [];
        const evidenceIds = Array.isArray(i.evidence_ids) ? i.evidence_ids : [];
        const current = String(i.status || 'open').toLowerCase();
        const options = statusOptions.includes(current)
          ? statusOptions : [current].concat(statusOptions);
        const actionStatus = current === 'closed' ? 'open' : 'closed';
        const actionLabel = current === 'closed' ? 'Reopen' : 'Close';
        return '<article class="review risk-card"><div class="h">' +
          '<div class="risk-heading"><h3>' + sev(i.rating) + ' · ' +
          E(i.title) + '</h3>' + (i.ref ? '<span class="mono risk-ref">' +
            E(i.ref) + '</span>' : '') + '</div>' +
          '<div class="risk-meta">' + tagFor(i.status, ST) + prov(i.provenance) +
          '<span class="tag grey">P ' + E(i.probability || '—') + '</span>' +
          '<span class="tag grey">I ' + E(i.impact || '—') + '</span>' +
          (i.category ? '<span class="tag blue">' + E(i.category) + '</span>' : '') +
          (i.critical_path_relevance ? '<span class="tag red">critical path</span>' : '') +
          '<div class="risk-actions"><label class="risk-status-control"><span>Status</span>' +
          '<select class="inp risk-status" data-risk-status="' + E(i.id) +
          '" aria-label="Update risk status">' + options.map(status =>
            '<option value="' + E(status) + '"' + (status === current ? ' selected' : '') +
            '>' + E(statusLabel[status] || status) + '</option>').join('') +
          '</select></label><button class="btn sm" data-risk="' + E(i.id) +
          '" data-st="' + actionStatus + '">' + actionLabel + '</button></div></div></div>' +
          '<details class="risk-details"><summary><span>Inspect risk details</span>' +
          '<small>' + (activityUids.length + evidenceIds.length) +
          ' linked record(s)</small></summary><div class="risk-details-body">' +
          '<div class="q">' + E(i.description || 'No description recorded.') + '</div>' +
          '<div class="samples"><dl class="kv">' +
          (i.owner ? row('Owner', E(i.owner)) : '') +
          (i.mitigation ? row('Mitigation', E(i.mitigation)) : '') +
          (i.trigger ? row('Trigger', E(i.trigger)) : '') +
          (i.critical_path_relevance ? row('Critical path', E(i.critical_path_relevance)) : '') +
          (i.schedule_impact_days !== null && i.schedule_impact_days !== undefined
            ? row('Schedule impact', num(i.schedule_impact_days, 0) + ' d') : '') +
          (activityUids.length ? row('Activities', activityUids.map(u =>
            '<span class="link mono" onclick="go(\'activity\',{id:' + u + '})">' +
            E(u) + '</span>').join(', ')) : '') +
          (evidenceIds.length ? row('Evidence', evidenceIds.map(x =>
            '<span class="link mono" onclick="go(\'evidence-detail\',{id:\'' + E(x) +
            '\'})">' + E(String(x).slice(0, 8)) + '</span>').join(', ')) : '') +
          row('Confidence', num(i.confidence, 2)) +
          '</dl></div></div></details></article>';
      }).join('') : empty('No risks recorded', '')) + '</div>');
};
VIEWS.bind_risks = (pid) => {
  document.querySelectorAll('[data-risk-status]').forEach(select => select.onchange = async () => {
    const status = select.value;
    select.disabled = true;
    try {
      await P('/projects/' + pid + '/risks/' + select.dataset.riskStatus + '/status', {status});
      window.toast('Risk status updated to ' + (status === 'closed' ? 'closed' : status), 'good');
      window.render();
    } catch (error) {
      select.disabled = false;
      window.toast(error.message || 'Risk status could not be updated', 'bad');
    }
  });
  document.querySelectorAll('[data-risk]').forEach(b => b.onclick = async () => {
    b.disabled = true;
    try {
      await P('/projects/' + pid + '/risks/' + b.dataset.risk + '/status',
        { status: b.dataset.st });
      window.toast(b.dataset.st === 'closed' ? 'Risk closed' : 'Risk reopened', 'good');
      window.render();
    } catch (error) {
      b.disabled = false;
      window.toast(error.message || 'Risk status could not be updated', 'bad');
    }
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

function scoreComponentRows(c) {
  return '<div class="score-components" aria-label="Eight-component match score">' +
    (c.score_components || []).map(component => {
      const value = component.score === null || component.score === undefined
        ? null : Math.max(0, Math.min(100, Number(component.score) * 100));
      return '<div class="score-component"><span>' + E(component.label) + '</span>' +
        '<i><b style="width:' + (value === null ? 0 : value) + '%"></b></i><em>' +
        (value === null ? 'N/E' : num(value, 0)) + '</em></div>';
    }).join('') + '</div>';
}

function candidateExplanation(c, rid, policy) {
  policy = policy || {};
  const strongAt = Number(policy.strong_confidence || .85) * 100;
  const reviewAt = Number(policy.review_confidence || .70) * 100;
  const gapAt = Number(policy.ambiguity_margin || .12) * 100;
  const probability = c.probability === null || c.probability === undefined
    ? null : Math.max(0, Math.min(100, Number(c.probability) * 100));
  const confidence = probability === null
    ? (c.rank_score === null || c.rank_score === undefined
      ? '<span class="match-score neutral">Not scored</span>'
      : '<span class="match-score neutral">Rank ' + num(c.rank_score, 3) + '</span>')
    : '<span class="match-score ' + (probability >= strongAt ? 'strong' : probability >= reviewAt ? 'review' : 'weak') + '">' +
      num(probability, 0) + '% ' + (c.calibration_is_empirical ? 'calibrated' : 'cold-start estimate') + '</span>';
  const support = (c.supporting_signals || []).length
    ? '<div class="signal-list supports">' + (c.supporting_signals || []).map(s =>
        '<span><i>+</i>' + E(s) + '</span>').join('') + '</div>'
    : '<div class="signal-empty">No positive signal explanation was stored.</div>';
  const conflict = (c.conflicting_signals || []).length
    ? '<div class="signal-list conflicts">' + (c.conflicting_signals || []).map(s =>
        '<span><i>!</i>' + E(s) + '</span>').join('') + '</div>' : '';
  const option = c.option_label || '';
  const gap = c.separation === null || c.separation === undefined
    ? null : Number(c.separation) * 100;
  const gate = Number(c.rank || 0) === 1
    ? '<div class="candidate-gate ' + E(c.review_band || 'weak') + '"><div><b>' +
      (c.ambiguous ? 'Human choice required' : c.review_band === 'strong'
        ? 'Strong candidate' : c.review_band === 'review' ? 'Review carefully' : 'Weak evidence') +
      '</b><span>' + (gap === null ? 'Only one candidate retained' :
        num(gap, 0) + ' point lead · ' + (gap >= gapAt ? 'clear of ' : 'inside ') +
        num(gapAt, 0) + ' point ambiguity gate') + '</span></div>' +
      '<small>Suggestion only · never schedule-write authority</small></div>' : '';
  return '<article class="candidate-card' + (Number(c.rank || 0) === 1 ? ' top' : '') + '">' +
    '<div class="candidate-head"><span class="candidate-rank">#' + int(c.rank || 0) +
      '</span><div><div class="candidate-id">' +
      E(c.display_id || ('UID ' + c.uid)) + (c.critical ? ' · CRITICAL' : '') +
      '</div><h4>' + E(c.name || 'Unnamed schedule activity') + '</h4></div>' +
      confidence + '</div>' +
    '<div class="candidate-meta">' +
      (c.wbs ? '<span>' + E(c.wbs) + '</span>' : '') +
      '<span>' + day(c.planned_start) + ' → ' + day(c.planned_finish) + '</span>' +
      (c.status ? '<span>' + E(c.status.replace(/_/g, ' ')) + '</span>' : '') +
      (c.matched_records ? '<span>' + int(c.matched_records) + ' record(s)</span>' : '') +
    '</div>' + gate + scoreComponentRows(c) +
    '<div class="candidate-signals"><div><b>Why it fits</b>' + support +
      '</div>' + (conflict ? '<div><b>What conflicts</b>' + conflict + '</div>' : '') +
    '</div>' +
    (option ? '<button class="btn primary choose-match" data-attention-answer="' +
      E(option) + '" data-rid="' + E(rid) + '">Confirm this activity</button>' : '') +
    '</article>';
}

function attentionReviewCard(v, policy, position, total) {
  const options = v.options || [];
  const candidates = v.candidate_explanations || [];
  const leave = options.find(o => o === 'Leave unassigned for now');
  const samples = v.affected_sample || [];
  const strong = Math.round(Number((policy || {}).strong_confidence || .85) * 100);
  const review = Math.round(Number((policy || {}).review_confidence || .70) * 100);
  const gap = Math.round(Number((policy || {}).ambiguity_margin || .12) * 100);
  const safetyCopy = v.kind === 'clarification'
    ? 'This decision only settles the evidence-to-activity identity.'
    : v.kind === 'security_review'
      ? 'This decision only governs how the quarantined source is handled.'
      : 'This decision resolves the review case; governed schedule writes remain separate.';
  return '<article class="inbox-item"><header><div><div class="eyebrow">' +
    E(reviewKindLabel(v.kind)) + '</div><h2>' + E(v.title) + '</h2></div>' +
    '<div class="inbox-item-meta">' +
      '<span class="count-pill">Case ' + int(position || 1) + ' / ' + int(total || 1) + '</span>' +
      (v.priority === 'high' ? '<span class="tag amber">High priority</span>' : '') +
      '<span class="count-pill">' + int(v.affected_count || 1) +
      ' record' + (Number(v.affected_count || 1) === 1 ? '' : 's') + '</span>' +
    '</div></header><div class="inbox-question">' + E(v.question) + '</div>' +
    '<div class="review-workspace"><section class="evidence-pane">' +
      '<div class="pane-label"><span>Field evidence</span><small>What was reported</small></div>' +
      (samples.length ? samples.map(s => '<button class="evidence-quote" data-open-evidence="' +
        E(s.id) + '"><div class="evidence-type-row"><b>' +
        E(String(s.document_type || 'field record').toUpperCase()) + '</b>' +
        (s.observation_type ? '<em>' + E(String(s.observation_type).replace(/_/g, ' ')) + '</em>' : '') +
        (s.extraction_confidence !== null && s.extraction_confidence !== undefined
          ? '<i>' + num(Number(s.extraction_confidence) * 100, 0) + '% extracted</i>' : '') +
        '</div><span>“' + E(s.description) + '”</span><small>' +
        E(s.source_file || 'Source') + (s.locator ? ' · ' + E(s.locator) : '') +
        ' · ' + day(s.date) + (s.discipline ? ' · ' + E(s.discipline) : '') +
        '</small></button>').join('') : '<div class="signal-empty">No sample rows available.</div>') +
      (v.detail ? '<div class="review-note">' + E(v.detail) + '</div>' : '') +
    '</section><section class="candidate-pane">' +
      '<div class="pane-label"><span>Schedule candidates</span><small>Why VEDA suggested them</small></div>' +
      (candidates.length ? '<div class="match-policy" title="Reviewer orientation thresholds; automation remains empirically gated">' +
        '<span><b>' + strong + '%</b> strong</span><span><b>' + review + '%</b> review</span>' +
        '<span><b>' + gap + ' pt</b> separation</span></div>' +
        candidates.map(c => candidateExplanation(c, v.id, policy)).join('') :
        '<div class="generic-options">' + options.filter(o => o !== leave).map(o =>
          '<button class="btn" data-attention-answer="' + E(o) + '" data-rid="' +
          E(v.id) + '">' + E(o) + '</button>').join('') + '</div>') +
    '</section></div>' +
    '<footer class="inbox-actions"><span>No official schedule value changes here. ' +
      E(safetyCopy) + '</span><div class="spacer"></div>' +
      (leave ? '<button class="btn" data-attention-answer="' + E(leave) +
        '" data-rid="' + E(v.id) + '">Leave unassigned</button>' : '') +
      (!options.length ? '<input class="inp" data-attention-free="' + E(v.id) +
        '" placeholder="Type your answer"><button class="btn primary" data-attention-free-go="' +
        E(v.id) + '">Apply</button>' : '') + '</footer></article>';
}

function reviewCaseQueue(reviews, selectedId) {
  return '<aside class="case-rail" tabindex="0" aria-label="Open review cases"><div class="case-rail-head">' +
    '<span>Open cases</span><b>' + int(reviews.length) + '</b></div><div class="case-rail-list">' +
    reviews.map((review, index) => {
      const sample = (review.affected_sample || [])[0] || {};
      const top = (review.candidate_explanations || [])[0] || {};
      const confidence = top.probability === null || top.probability === undefined
        ? null : Number(top.probability) * 100;
      return '<button class="case-rail-item ' + (String(review.id) === String(selectedId) ? 'active' : '') +
        '" data-review-case="' + E(review.id) + '"><small>' + E(reviewKindLabel(review.kind)) +
        ' · ' + (index + 1) + '</small><b>' + E(review.title) + '</b><span>' +
        E(sample.description || review.question || '') + '</span><em>' +
        (confidence === null ? int(review.affected_count || 1) + ' record(s)' :
          num(confidence, 0) + '% top candidate') + '</em></button>';
    }).join('') + '</div><div class="case-rail-hint">Use ↑ / ↓ to move between cases</div></aside>';
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
  const selected = reviews.find(v => String(v.id) === String(params.review || '')) || reviews[0];
  const selectedIndex = selected ? reviews.indexOf(selected) : -1;
  const stateNote = '<div class="note ' + (ps.code === 'retry' ? 'danger' : ps.code === 'needs_input' || ps.code === 'choose_schedule' ? 'warn' : '') + '" style="margin-bottom:14px"><b>' + E(ps.label || 'Project state') + '</b><br>' + E(ps.detail || '') + '</div>';
  const reviewHtml = selected ? '<div class="review-queue-shell">' +
    reviewCaseQueue(reviews, selected.id) + '<section class="case-workstation">' +
    attentionReviewCard(selected, r.match_policy || {}, selectedIndex + 1, reviews.length) +
    '</section></div>' : '';
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
      '<span class="tag blue">Planner decision workstation</span>') +
    '<div class="review-brief"><div><div class="eyebrow">Decision brief</div>' +
      '<h2>' + (r.attention_count ? int(r.attention_count) + ' item' +
        (Number(r.attention_count) === 1 ? ' needs' : 's need') + ' a person' : 'No decisions waiting') +
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

VIEWS.bind_attention = (pid, params) => {
  document.querySelectorAll('[data-inbox-focus]').forEach(b => b.onclick = () =>
    go('attention', { focus: b.dataset.inboxFocus }));
  const caseButtons = Array.from(document.querySelectorAll('[data-review-case]'));
  caseButtons.forEach(b => b.onclick = () =>
    go('attention', {focus: params.focus || 'all', review: b.dataset.reviewCase}));
  const caseRail = document.querySelector('.case-rail');
  if (caseRail) caseRail.onkeydown = (event) => {
    if (!caseButtons.length || !['ArrowUp', 'ArrowDown'].includes(event.key)) return;
    const current = Math.max(0, caseButtons.findIndex(b => b.classList.contains('active')));
    const next = event.key === 'ArrowDown'
      ? Math.min(caseButtons.length - 1, current + 1) : Math.max(0, current - 1);
    if (next !== current) { event.preventDefault(); caseButtons[next].click(); }
  };
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

/* ======================================== 18b. Actuals certificates */
VIEWS.certificates = async (pid) => {
  const [data, conflictData] = await Promise.all([
    A('/projects/' + pid + '/actuals-certificates'),
    A('/projects/' + pid + '/conflicts?status=open')
  ]);
  const cards = (data.certificates || []).map(rowData => {
    const c = rowData.certificate || {};
    const m = c.metrics || {};
    const gates = (c.gates || []).map(gate => '<div class="check"><span class="m ' +
      (gate.state === 'pass' ? 'pass' : gate.state === 'warning' ? 'warn' : 'fail') + '">' +
      E(gate.state) + '</span><span class="n">' + E(gate.name) +
      '</span><span style="flex:1">' + E(gate.detail) + '</span></div>').join('');
    const actuals = Object.entries(c.recommended_actuals || {}).map(([key, value]) =>
      '<span class="tag green">' + E(key) + ' · ' + E(value) + '</span>').join(' ');
    return '<article class="review"><div class="h"><h3>' +
      E((c.activity || {}).display_id || 'UID ' + c.activity_uid) + ' · ' +
      E((c.activity || {}).name || 'Activity') + '</h3><div>' +
      '<span class="tag ' + (c.status === 'admissible' ? 'green' : c.status === 'blocked' ? 'red' : 'amber') + '">' +
      E(c.status) + '</span> ' + prov('DETERMINISTIC_CALCULATION') + '</div></div>' +
      '<div class="samples"><div class="grid g4" style="margin-bottom:12px">' +
      stat('DPR records', int(m.dpr_records || 0), 'linked execution observations') +
      stat('Traced welds', int(m.unique_welds || 0), 'stable weld identities') +
      stat('NDT accepted', int(m.accepted_welds || 0), int(m.rejected_welds || 0) + ' rejected/repair') +
      stat('Open NCRs', int(m.open_ncrs || 0), m.scope_total ? 'scope ' + num(m.scope_total) : 'scope denominator not stated') +
      '</div>' + gates +
      '<div style="margin-top:11px"><div class="eyebrow">Admissible actuals</div>' +
      (actuals || '<span class="muted">None—proof is incomplete or blocked.</span>') + '</div>' +
      ((c.limitations || []).length ? '<div class="note warn" style="margin-top:10px">' +
        E(c.limitations.join(' ')) + '</div>' : '') +
      '<dl class="kv" style="margin-top:10px">' +
      row('Sources', E((c.sources || []).join(' · ') || '—')) +
      row('Proof fingerprint', '<span class="mono">' + E((rowData.proof_hash || '').slice(0, 20)) + '…</span>') +
      row('Contract', E(c.contract_type + ' v' + c.contract_version)) + '</dl></div></article>';
  }).join('');
  const conflictRows = (conflictData.conflicts || []).map(c =>
    '<div class="check"><span class="m fail">open</span><span class="n">' + E(c.kind) +
    '</span><span style="flex:1">' + E(c.detail) + '</span>' +
    '<button class="btn sm" data-resolve-conflict="' + E(c.id) + '">Resolve</button></div>').join('');
  return head('Actuals Certificates', 'Execution proof, not another progress dashboard',
    '<button class="btn primary" id="generate-certificates">Generate / recheck</button>') +
    '<div class="note" style="margin-bottom:14px">The pipeline welding contract requires linked DPR, welding and independent NDT records. Open NCRs block acceptance. A finish is never certified without an authoritative scope denominator.</div>' +
    (cards || panel('Execution proof', empty('No certificates yet',
      'Link DPR, welding and NDT/NCR records to a schedule activity, then generate certificates.'))) +
    panel('Durable conflicts <small>' + int((conflictData.conflicts || []).length) + '</small>',
      '<div class="body">' + (conflictRows || '<div class="note good">No open actuals conflicts.</div>') + '</div>');
};
VIEWS.bind_certificates = (pid) => {
  const generate = document.getElementById('generate-certificates');
  if (generate) generate.onclick = async () => {
    generate.disabled = true; generate.textContent = 'Checking proof…';
    try { const result = await P('/projects/' + pid + '/actuals-certificates/generate',
      {by:'planning.manager'}); window.toast('Checked ' + int(result.count || 0) + ' activity certificate(s).', 'good'); }
    catch (error) { window.toast(error.message, 'bad'); }
    window.render();
  };
  document.querySelectorAll('[data-resolve-conflict]').forEach(button => button.onclick = async () => {
    const resolution = window.prompt('Record how this conflict was resolved:');
    if (!resolution) return;
    try { await P('/conflicts/' + button.dataset.resolveConflict + '/resolve',
      {resolution, by:'planning.manager'}); window.toast('Conflict resolved with an audit entry.', 'good'); }
    catch (error) { window.toast(error.message, 'bad'); }
    window.render(); window.refreshCounts();
  });
};

/* ================================================= 19. Proposals */
function proposalCard(p, options) {
  options = options || {};
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
    (p.approval_state === 'pending' && !options.groupMember
      ? '<button class="btn sm" data-dry="' + E(p.id) + '">Re-run dry-run</button>' +
        '<button class="btn sm danger" data-rej="' + E(p.id) + '">Reject</button>' +
        '<button class="btn sm warn" data-app="' + E(p.id) +
        '">Approve and apply</button>'
      : options.groupMember ? '<span class="tag grey">bundle member</span>' : tagFor(p.approval_state, ST)) +
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

function proposalGroupCard(group, members) {
  return '<section class="panel"><div class="ph"><div><div class="eyebrow">Atomic proposal bundle</div>' +
    '<h2>' + E(group.purpose || 'Coupled schedule actuals') + ' · ' + int(members.length) +
    ' fields</h2></div><div style="display:flex;gap:7px;flex-wrap:wrap">' +
    (group.approval_state === 'pending'
      ? '<button class="btn sm" data-group-dry="' + E(group.id) + '">Dry-run bundle</button>' +
        '<button class="btn sm danger" data-group-rej="' + E(group.id) + '">Reject bundle</button>' +
        '<button class="btn sm warn" data-group-app="' + E(group.id) + '">Approve & apply all</button>'
      : tagFor(group.approval_state, ST)) + '</div></div>' +
    '<div class="body"><div class="note">One approval boundary: no revision is published unless every field passes independent read-back verification.</div>' +
    members.map(p => proposalCard(p, {groupMember:true})).join('') + '</div></section>';
}

VIEWS.proposals = async (pid) => {
  const [r, p6] = await Promise.all([
    A('/projects/' + pid + '/proposals'),
    A('/integrations/primavera/status').catch(() => ({configured: false, gates: {}})),
  ]);
  const gates = p6.gates || {};
  const groupedIds = new Set((r.groups || []).map(group => group.id));
  const grouped = (r.groups || []).map(group => proposalGroupCard(group,
    r.proposals.filter(p => p.proposal_group_id === group.id))).join('');
  const ungrouped = r.proposals.filter(p => !p.proposal_group_id || !groupedIds.has(p.proposal_group_id))
    .map(p => proposalCard(p)).join('');
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
      ? grouped + ungrouped
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
  const actGroup = async (groupId, body, message) => {
    window.toast('Working…');
    try {
      const result = await P('/proposal-groups/' + groupId + '/decision', body);
      window.toast(message + (result.execution
        ? ' · verification: ' + result.execution.verification : ''), 'good');
    } catch (error) { window.toast('Failed: ' + error.message, 'bad'); }
    window.render(); window.refreshCounts();
  };
  document.querySelectorAll('[data-group-app]').forEach(b => b.onclick = () =>
    actGroup(b.dataset.groupApp, {approve:true, by:'planning.manager'},
      'Bundle approved and applied'));
  document.querySelectorAll('[data-group-rej]').forEach(b => b.onclick = () =>
    actGroup(b.dataset.groupRej, {approve:false, by:'planning.manager'},
      'Bundle rejected'));
  document.querySelectorAll('[data-group-dry]').forEach(b => b.onclick = async () => {
    window.toast('Running bundle dry-run…');
    try { await P('/proposal-groups/' + b.dataset.groupDry + '/dry-run'); }
    catch (error) { window.toast('Bundle dry-run failed: ' + error.message, 'bad'); }
    window.render();
  });
};

/* ============================================ 19b. Thinking trace (shared)
   VEDA never shows raw chain-of-thought (spec 50) - `step()` on the server
   only ever logs safe, high-level progress. What we render here is that same
   persisted trace, styled the way an LLM product shows its reasoning: a
   one-line collapsed headline that updates as the run progresses, and an
   expandable timeline for anyone who wants the detail. Execution intelligence
   and Ask VEDA both build on this so a run "thinks" the same way everywhere. */
VIEWS._thinkOpen = VIEWS._thinkOpen || {};

function fmtDur(seconds) {
  seconds = Math.max(0, Math.round(seconds));
  if (seconds < 60) return seconds + 's';
  return Math.floor(seconds / 60) + 'm ' + (seconds % 60) + 's';
}

function reasoningStepLabel(entry) {
  const labels = {
    agent_invoked: 'Choosing the right reasoning path',
    agent_unavailable: 'Reasoning service unavailable',
    agent_started: 'Project context sent',
    agent_processing: 'Working on the response…',
    provider_selected: 'Reasoning complete',
    structured_output_partial: 'Checking the response',
    structured_output_rejected: 'Response check failed',
    agent_failed: 'Reasoning attempt failed',
    fallback_analysis: 'Using built-in project rules',
  };
  return labels[entry.step] || entry.label;
}

function thinkItem(entry) {
  const isTool = entry.kind === 'tool';
  const failed = entry.state === 'failed';
  const cls = 'think-item ' + (isTool ? 'tool' : 'step') +
    (failed ? ' failed' : '') + (entry.active ? ' active' : '');
  const title = isTool
    ? E(entry.server) + '<span class="think-slash">/</span>' + E(entry.tool)
    : E(reasoningStepLabel(entry));
  const detailRaw = isTool
    ? [entry.summary || entry.error, (entry.duration_ms !== null && entry.duration_ms !== undefined)
        ? Math.round(entry.duration_ms) + 'ms' : null].filter(Boolean).join(' · ')
    : (entry.detail || '');
  const marker = failed ? '!' : isTool ? '⇄' : '•';
  return '<div class="' + cls + '"><span class="think-dot">' + marker + '</span>' +
    '<div><div class="think-row"><span class="think-kind">' +
    (isTool ? 'Horizun' : 'Reasoning') + '</span>' +
    '<b>' + title + '</b>' +
    '<span class="think-time">' + new Date(entry.created_at * 1000).toLocaleTimeString() +
    '</span></div>' +
    (detailRaw ? '<div class="think-detail' + (isTool ? ' mono' : '') + '">' +
      E(String(detailRaw).slice(0, 320)) + '</div>' : '') +
    '</div></div>';
}

/* opts: { status: live|done|failed|idle, steps, calls, openKey, idleHint,
          emptyLabel, extra, defaultOpen, kicker }
   `extra` is HTML appended inside the trace, after the reasoning timeline -
   Execution intelligence uses it to nest the full run visualisation. */
VIEWS._vizOpen = VIEWS._vizOpen || {};

function thinkingPanel(opts) {
  const steps = (opts.steps || []).map(s => Object.assign({ kind: 'step' }, s));
  const calls = (opts.calls || []).map(c => Object.assign({ kind: 'tool' }, c));
  const merged = steps.concat(calls).filter(e => e.created_at)
    .sort((a, b) => a.created_at - b.created_at);
  const status = opts.status || 'idle';
  const live = status === 'live';
  if (merged.length && live) merged[merged.length - 1].active = true;
  const first = merged[0], last = merged[merged.length - 1];
  const elapsed = first ? (live ? (Date.now() / 1000 - first.created_at)
    : (last.created_at - first.created_at)) : 0;
  const headlineText = live ? (first ? 'Thinking for ' + fmtDur(elapsed) : 'Starting…')
    : status === 'done' ? 'Thought for ' + fmtDur(elapsed)
    : status === 'failed' ? 'Reasoning stopped' : 'No reasoning trace yet';
  const kicker = opts.kicker || (live ? 'Reasoning · live'
    : status === 'done' ? 'Reasoning · complete'
    : status === 'failed' ? 'Reasoning · halted' : 'Reasoning');
  const sub = last ? (last.kind === 'tool'
      ? ('Horizun · ' + last.server + '/' + last.tool + (last.state === 'failed' ? ' failed' : ''))
      : last.label)
    : (opts.idleHint || '');
  const key = opts.openKey || '';
  const stored = key ? VIEWS._thinkOpen[key] : undefined;
  const open = stored === undefined ? !!opts.defaultOpen : !!stored;
  return '<section class="think-panel ' + status + '" data-open="' + (open ? 1 : 0) +
    '" data-think-key="' + E(key) + '">' +
    '<div class="think-frame" aria-hidden="true"><i></i><i></i><i></i><i></i></div>' +
    '<button class="think-toggle" type="button" aria-expanded="' + (open ? 'true' : 'false') + '">' +
    '<span class="think-beacon" aria-hidden="true"><i></i></span>' +
    '<span class="think-headline"><span class="think-kicker">' + E(kicker) + '</span>' +
    '<b' +
    (live && first ? ' data-think-live="1" data-think-first="' + first.created_at + '"' : '') +
    '>' + E(headlineText) + '</b>' +
    (sub ? '<em>' + E(String(sub).slice(0, 140)) + '</em>' : '') + '</span>' +
    (merged.length ? '<span class="think-count">' + merged.length +
      ' step' + (merged.length === 1 ? '' : 's') + '</span>' : '') +
    '<span class="think-chevron" aria-hidden="true">⌄</span></button>' +
    (live ? '<div class="think-scan" aria-hidden="true"></div>' : '') +
    '<div class="think-trace"' + (open ? '' : ' hidden') + '>' +
    '<div class="think-timeline">' +
    (merged.length ? merged.map(thinkItem).join('') :
      '<div class="think-empty">' + E(opts.emptyLabel || 'Nothing recorded yet.') + '</div>') +
    '</div>' + (opts.extra || '') +
    '</div></section>';
}

window.bindThinkToggles = function bindThinkToggles(root) {
  const scope = root || document;
  scope.querySelectorAll('.think-toggle').forEach((btn) => {
    btn.onclick = () => {
      const panel = btn.closest('.think-panel');
      const trace = panel.querySelector('.think-trace');
      const willOpen = trace.hidden;
      trace.hidden = !willOpen;
      panel.dataset.open = willOpen ? '1' : '0';
      btn.setAttribute('aria-expanded', String(willOpen));
      const key = panel.dataset.thinkKey;
      if (key) VIEWS._thinkOpen[key] = willOpen;
    };
  });
  // The nested run visualisation is a native <details>; remember where the
  // reader left it so a live re-render never snaps it shut under them.
  scope.querySelectorAll('.run-reveal').forEach((d) => {
    d.addEventListener('toggle', () => {
      const k = d.dataset.vizKey;
      if (k) VIEWS._vizOpen[k] = d.open;
    });
  });
};

/* ==================================================== 20. Ask VEDA
   A full-height chat surface, laid out the way ChatGPT / Claude are: the
   conversation scrolls in the middle (oldest at top, newest at the bottom),
   the composer is docked at the bottom, and sending a message pins that
   exchange to the top of the viewport so the answer reads from its first line.
   VEDA's reasoning trace rides above each answer via the shared think-panel. */
VIEWS._askDraft = VIEWS._askDraft || {};
VIEWS._ask = VIEWS._ask || {};
VIEWS.stopAskVoice = (pid) => {
  const voice = VIEWS._ask[pid] && VIEWS._ask[pid].voice;
  if (!voice) return;
  voice.userStopped = true;
  voice.listening = false;
  if (voice.recognition) { try { voice.recognition.stop(); } catch (_) {} }
  if (voice.stream) {
    try { voice.stream.getTracks().forEach(track => track.stop()); } catch (_) {}
  }
  voice.recognition = null;
  voice.stream = null;
};

const ASK_SUGGESTIONS = [
  'What is driving the current forecast finish?',
  'Which activities have unresolved evidence conflicts right now?',
  'Summarize open risks sitting on the critical path.',
];

function askTurn(turn, steps, calls) {
  const you = '<div class="ask-msg you"><div class="ask-avatar you-mark">You</div>' +
    '<div class="ask-bubble"><p>' + E(turn.question) + '</p></div></div>';

  let inner;
  if (turn.kind === 'pending') {
    inner = thinkingPanel({
      status: 'live', steps: steps, calls: calls, openKey: 'ask:' + turn.id,
      defaultOpen: false,
      idleHint: 'Preparing a response…',
    });
  } else if (turn.kind === 'failed') {
    inner = thinkingPanel({
        status: 'failed', steps: steps, calls: calls, openKey: 'ask:' + turn.id,
        emptyLabel: 'No reasoning trace stored for this attempt.',
      }) +
      '<div class="ask-error"><b>VEDA could not produce a grounded answer.</b>' +
      (turn.error ? '<span class="mono">' + E(String(turn.error).slice(0, 300)) +
        '</span>' : 'The reasoning provider chain was exhausted.') + '</div>';
  } else {
    inner = thinkingPanel({
        status: 'done', steps: steps, calls: calls, openKey: 'ask:' + turn.id,
        emptyLabel: 'No reasoning trace stored for this answer.',
      }) +
      '<div class="ask-answer">' + E(turn.answer) + '</div>' +
      '<div class="ask-meta">' + prov(turn.provenance) +
      (turn.source === 'browser_extension' ? '<span class="tag blue">via VEDA Anywhere</span>' : '') +
      '<span class="ask-time">' + new Date(turn.created_at * 1000).toLocaleString() +
      '</span></div>';
  }
  return '<div class="ask-turn" data-turn="' + E(turn.id) + '">' + you +
    '<div class="ask-msg veda' + (turn.kind === 'pending' ? ' thinking' : '') + '">' +
    '<div class="ask-avatar veda-mark">V</div><div class="ask-bubble">' + inner +
    '</div></div></div>';
}

VIEWS.ask = async (pid) => {
  const [r, jobsR, actR, mcpR] = await Promise.all([
    A('/projects/' + pid + '/answers?limit=80'),
    A('/projects/' + pid + '/jobs?limit=30'),
    A('/projects/' + pid + '/agent-activity?limit=500'),
    A('/projects/' + pid + '/mcp-calls?limit=300'),
  ]);
  const answers = (r.answers || []).slice().reverse(); // oldest first for chat order
  const answeredJobIds = new Set(answers.map(a => String(a.job_id || '')));
  const qJobs = (jobsR.jobs || []).filter(j => j.kind === 'question');
  const unresolved = qJobs
    .filter(j => !answeredJobIds.has(String(j.id)) &&
      ['queued', 'running', 'failed', 'cancelled'].includes(String(j.status)))
    .sort((a, b) => (a.created_at || 0) - (b.created_at || 0))[0];

  const actByJob = {}, callsByJob = {};
  (actR.activity || []).forEach(a => (actByJob[a.job_id] = actByJob[a.job_id] || []).push(a));
  (mcpR.calls || []).forEach(c => (callsByJob[c.job_id] = callsByJob[c.job_id] || []).push(c));

  const turns = answers.map(a => ({
    kind: 'answer', id: a.id, jobId: a.job_id, question: a.title,
    answer: a.description, provenance: a.provenance, created_at: a.created_at,
    source: a.source_type,
  }));
  if (unresolved) {
    const live = unresolved.status === 'queued' || unresolved.status === 'running';
    const qin = (unresolved.result && unresolved.result.input) || {};
    const q = qin.display_question || qin.question || 'Question in progress…';
    turns.push({
      kind: live ? 'pending' : 'failed', id: unresolved.id, jobId: unresolved.id,
      question: q, error: unresolved.error, created_at: unresolved.created_at,
      source: qin.veda_anywhere ? 'browser_extension' : null,
    });
  }

  const draft = VIEWS._askDraft[pid] || '';
  const thread = turns.length
    ? turns.map(t => askTurn(t, actByJob[t.jobId] || [], callsByJob[t.jobId] || [])).join('')
    : '<div class="ask-hello"><div class="ask-avatar veda-mark">V</div>' +
      '<h2>Ask VEDA anything about this project</h2>' +
      '<p>VEDA inspects the stored schedule facts, the field evidence and Horizun ' +
      'before answering — grounded, never a guess. Captures made from VEDA Anywhere ' +
      'appear here too.</p>' +
      '<div class="ask-suggest">' + ASK_SUGGESTIONS.map(s =>
        '<button type="button" data-suggest="' + E(s) + '">' + E(s) + '</button>').join('') +
      '</div></div>';

  VIEWS._ask[pid] = VIEWS._ask[pid] || {};
  VIEWS._ask[pid].turnCount = turns.length;
  VIEWS._ask[pid].hasPending = turns.some(t => t.kind === 'pending');

  return '<div class="ask-view">' +
    '<div class="ask-topbar"><div><div class="eyebrow">Ask VEDA</div>' +
    '<b>A grounded agent conversation</b></div><div class="spacer"></div>' +
    (turns.length ? '<span class="ask-count mono">' + turns.length + ' exchange' +
      (turns.length === 1 ? '' : 's') + '</span>' : '') + '</div>' +
    '<div class="ask-scroll" id="ask-scroll"><div class="ask-thread" id="ask-thread">' +
    thread + '<div class="ask-tail-spacer" id="ask-tail-spacer"></div></div></div>' +
    '<div class="ask-dock"><div class="ask-composer">' +
    '<textarea class="ask-input" id="qbox" rows="1" ' +
    'placeholder="Ask about an activity, a date, progress, a risk…">' + E(draft) + '</textarea>' +
    '<button class="ask-voice" id="ask-voice" type="button" aria-label="Speak question" ' +
    'title="Speak question"><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="9" y="3" width="6" height="11" rx="3"></rect>' +
    '<path d="M5 11a7 7 0 0 0 14 0M12 18v3M8 21h8"></path></svg></button>' +
    '<button class="ask-send" id="qgo" type="button" aria-label="Send question">' +
    '<i aria-hidden="true">➤</i></button></div>' +
    '<div class="ask-dock-tools"><label class="ask-grounding"><input id="ask-grounded" type="checkbox" ' +
    ((VIEWS._ask[pid] || {}).forceGrounded ? 'checked' : '') + '><span><i></i>Deep-check project sources</span></label>' +
    '<span class="ask-voice-status" id="ask-voice-status" role="status" aria-live="polite"></span>' +
    '<div class="ask-dock-hint mono">Auto routes simple chat quickly · grounded mode stays read-only</div></div>' +
    '</div></div>';
};

VIEWS.bind_ask = (pid) => {
  const box = document.getElementById('qbox');
  const btn = document.getElementById('qgo');
  const scroll = document.getElementById('ask-scroll');
  const thread = document.getElementById('ask-thread');
  const spacer = document.getElementById('ask-tail-spacer');
  const grounded = document.getElementById('ask-grounded');
  const voiceBtn = document.getElementById('ask-voice');
  const voiceStatus = document.getElementById('ask-voice-status');
  if (!box || !btn || !scroll) return;

  const st = VIEWS._ask[pid] = VIEWS._ask[pid] || {};

  const grow = () => {
    box.style.height = 'auto';
    box.style.height = Math.min(180, box.scrollHeight) + 'px';
  };
  grow();

  // --- scroll management -----------------------------------------------
  // Chat behaviour: sending pins the exchange to the top of the viewport so a
  // long answer reads from its first line; otherwise the view follows the
  // newest content unless the reader has scrolled up.
  const turnEls = () => thread.querySelectorAll('.ask-turn');
  const sizeSpacer = () => {
    const turns = turnEls();
    const last = turns[turns.length - 1];
    if (spacer && last) {
      spacer.style.height = Math.max(0,
        scroll.clientHeight - last.getBoundingClientRect().height - 28) + 'px';
    } else if (spacer) {
      spacer.style.height = '0px';
    }
  };
  const pinLast = () => {
    const turns = turnEls();
    const last = turns[turns.length - 1];
    if (!last) return;
    st._prog = true;
    scroll.scrollTop += last.getBoundingClientRect().top - scroll.getBoundingClientRect().top - 10;
    setTimeout(() => { st._prog = false; }, 90);
  };
  const toBottom = () => {
    st._prog = true;
    scroll.scrollTop = scroll.scrollHeight;
    setTimeout(() => { st._prog = false; }, 90);
  };

  sizeSpacer();
  const grew = (st.lastTurnCount || 0) < st.turnCount;
  const restoreScroll = st.restoreScroll;
  delete st.restoreScroll;
  if (st.pin && (grew || st.pinSticky)) {
    pinLast();
    // Stop re-pinning once the answer has landed - let the reader scroll freely.
    if (!st.hasPending && !grew) { st.pinSticky = false; st.pin = false; }
  } else if (restoreScroll && !restoreScroll.nearBottom) {
    st._prog = true;
    scroll.scrollTop = restoreScroll.top;
    st.follow = false;
    setTimeout(() => { st._prog = false; }, 90);
  } else if (grew || st.follow !== false) {
    toBottom();
  }
  st.lastTurnCount = st.turnCount;

  scroll.onscroll = () => {
    if (st._prog) return;
    const nearBottom = scroll.scrollHeight - scroll.scrollTop - scroll.clientHeight < 90;
    st.follow = nearBottom;
    if (!nearBottom) { st.pin = false; st.pinSticky = false; }
  };
  if (VIEWS._ask._resize) window.removeEventListener('resize', VIEWS._ask._resize);
  VIEWS._ask._resize = () => { if (scroll.isConnected) sizeSpacer(); };
  window.addEventListener('resize', VIEWS._ask._resize);

  // --- speak-to-text ---------------------------------------------------
  // Ask VEDA voice input is a draft composer aid, not a field-capture
  // recording. The operator can edit the words and still has to press Send.
  const voiceState = st.voice || (st.voice = {
    recognition: null, stream: null, listening: false,
    finalText: '', userStopped: false, error: null,
  });
  const setVoiceUi = (message, tone) => {
    if (voiceBtn) {
      voiceBtn.classList.toggle('is-listening', !!voiceState.listening);
      voiceBtn.setAttribute('aria-pressed', voiceState.listening ? 'true' : 'false');
      voiceBtn.title = voiceState.listening ? 'Stop speaking' : 'Speak question';
      voiceBtn.setAttribute('aria-label', voiceState.listening ? 'Stop speaking' : 'Speak question');
    }
    if (voiceStatus) {
      voiceStatus.className = 'ask-voice-status' + (tone ? ' ' + tone : '');
      voiceStatus.textContent = message || '';
    }
  };
  const releaseVoiceStream = () => {
    if (!voiceState.stream) return;
    try { voiceState.stream.getTracks().forEach(track => track.stop()); } catch (_) {}
    voiceState.stream = null;
  };
  const stopVoice = (userStopped) => {
    voiceState.userStopped = !!userStopped;
    voiceState.listening = false;
    if (voiceState.recognition) { try { voiceState.recognition.stop(); } catch (_) {} }
    releaseVoiceStream();
    voiceState.recognition = null;
    setVoiceUi(userStopped ? 'Voice input stopped · review the draft before sending.' : '', '');
  };
  const voiceError = (error) => {
    const denied = error && (error.name === 'NotAllowedError' || error.name === 'SecurityError' ||
      error.error === 'not-allowed' || error.error === 'service-not-allowed');
    const message = denied
      ? 'Microphone permission was denied. Allow it for this VEDA page, then try again.'
      : error && (error.name === 'NotFoundError' || error.error === 'audio-capture')
        ? 'No microphone is available. Check the selected input and try again.'
        : 'Voice input is unavailable here. Type your question instead.';
    voiceState.error = message;
    stopVoice(false);
    setVoiceUi(message, 'warn');
    if (window.toast) window.toast(message, 'bad');
  };
  const startVoice = async () => {
    if (voiceState.listening) { stopVoice(true); return; }
    const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!Recognition) {
      setVoiceUi('Voice input is not supported in this browser. Type your question instead.', 'warn');
      return;
    }
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      setVoiceUi('This browser cannot request microphone access. Type your question instead.', 'warn');
      return;
    }
    if (voiceBtn) voiceBtn.disabled = true;
    setVoiceUi('Requesting microphone…', '');
    let acquiredStream = null;
    try {
      acquiredStream = await navigator.mediaDevices.getUserMedia({audio: true});
      const recognition = new Recognition();
      const stream = acquiredStream;
      voiceState.stream = stream;
      voiceState.recognition = recognition;
      voiceState.listening = true;
      voiceState.userStopped = false;
      voiceState.error = null;
      voiceState.finalText = box.value.trim();
      recognition.lang = navigator.language || 'en-IN';
      recognition.continuous = true;
      recognition.interimResults = true;
      recognition.maxAlternatives = 1;
      recognition.onresult = (event) => {
        let interim = '';
        for (let i = event.resultIndex; i < event.results.length; i += 1) {
          const phrase = event.results[i][0].transcript.trim();
          if (!phrase) continue;
          if (event.results[i].isFinal) voiceState.finalText +=
            (voiceState.finalText ? ' ' : '') + phrase;
          else interim += (interim ? ' ' : '') + phrase;
        }
        const value = (voiceState.finalText + (interim ? ' ' + interim : '')).trim();
        const liveBox = document.getElementById('qbox');
        if (!liveBox) return;
        liveBox.value = value;
        VIEWS._askDraft[pid] = value;
        liveBox.dispatchEvent(new Event('input', {bubbles: true}));
      };
      recognition.onerror = (event) => {
        if (event && event.error === 'aborted') return;
        voiceError(event || new Error('recognition_failed'));
      };
      recognition.onend = () => {
        if (!voiceState.listening) return;
        const stoppedByUser = voiceState.userStopped;
        voiceState.listening = false;
        releaseVoiceStream();
        voiceState.recognition = null;
        setVoiceUi(stoppedByUser
          ? 'Voice input stopped · review the draft before sending.'
          : 'Voice draft ready · review before sending.', '');
      };
      const track = stream.getAudioTracks && stream.getAudioTracks()[0];
      try {
        if (track) recognition.start(track); else recognition.start();
      } catch (_) {
        // Older browsers expose SpeechRecognition but reject the optional
        // MediaStreamTrack argument. Release the probe stream and retry using
        // their normal microphone path.
        releaseVoiceStream();
        recognition.start();
      }
      setVoiceUi('Listening… speak naturally, then review the draft.', 'active');
    } catch (error) {
      if (acquiredStream && !voiceState.stream) {
        try { acquiredStream.getTracks().forEach(track => track.stop()); } catch (_) {}
      }
      voiceError(error);
    } finally {
      if (voiceBtn) voiceBtn.disabled = false;
    }
  };
  if (voiceBtn) {
    voiceBtn.onclick = startVoice;
    if (voiceState.listening) setVoiceUi('Listening… speak naturally, then review the draft.', 'active');
  }

  // --- send ------------------------------------------------------------
  box.oninput = () => { VIEWS._askDraft[pid] = box.value; grow(); };
  const send = async () => {
    const text = box.value.trim();
    if (!text || btn.disabled) return;
    if (voiceState.listening) stopVoice(true);
    btn.disabled = true;
    box.disabled = true;
    try {
      await P('/projects/' + pid + '/ask', {
        question: text, force_grounded: Boolean(grounded && grounded.checked),
      });
      VIEWS._askDraft[pid] = '';
      box.value = ''; grow();
      st.pin = true; st.pinSticky = true; st.follow = true;
      await window.refreshCounts();
      window.render();
    } catch (e) {
      btn.disabled = false;
      box.disabled = false;
      window.toast('Could not send question: ' + e.message, 'bad');
    }
  };
  btn.onclick = send;
  box.onkeydown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
  };
  document.querySelectorAll('[data-suggest]').forEach(b => b.onclick = () => {
    box.value = b.dataset.suggest; VIEWS._askDraft[pid] = box.value; grow(); box.focus();
  });
  if (grounded) grounded.onchange = () => { st.forceGrounded = grounded.checked; };
  if (!VIEWS._askDraft[pid]) box.focus();
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

function runNode(level, ctx, title, question, meta, guarded) {
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

function runDuration(job) {
  if (!job) return 'Awaiting a run';
  const start = Number(job.started_at || job.created_at || 0);
  const end = Number(job.finished_at || Date.now() / 1000);
  if (!start) return 'Duration unavailable';
  const seconds = Math.max(0, Math.round(end - start));
  if (seconds < 60) return seconds + 's elapsed';
  return Math.floor(seconds / 60) + 'm ' + (seconds % 60) + 's elapsed';
}

/* The execution map is one pipeline drawn top to bottom.  Every stage of the
   run is present exactly once, in the same order and with the same ordinals as
   the progress rail above it, so the rail and the map can never disagree.  A
   stage is a labelled band; a band is a CSS grid, so nodes inside a fan-out sit
   in their own columns and connectors are real elements between bands. */
const RUN_STAGES = [
  [0, 'Sources'], [1, 'Schedule'], [2, 'Evidence'], [3, 'Reasoning'],
  [4, 'Resolver'], [5, 'Validation'], [6, 'Controls'], [7, 'Decision'],
];

function runBand(cols, nodes) {
  return '<div class="arch-band cols-' + cols + '">' + nodes.join('') + '</div>';
}

function runRail(level, ctx, kind) {
  // kind: '' (stem) | 'split' | 'merge', optionally with a width modifier.
  return '<div class="arch-rail ' + (kind || '') + ' ' + runState(level, ctx, false) +
    '" aria-hidden="true"><i></i></div>';
}

function runStage(label, body, guard) {
  return '<div class="arch-stage' + (guard ? ' guard' : '') + '">' +
    '<div class="arch-stage-label">' + E(label) + '</div>' + body + '</div>';
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

  const map =
    runStage('Intake', runBand(1, [
      runNode(0, ctx, 'Field observation', 'What changed on site?',
        'DPR · note · report · image'),
    ])) +
    runRail(1, ctx) +
    runStage('Schedule and field record', runBand(2, [
      runNode(1, ctx, 'Horizun snapshot', 'What does the plan say?',
        'Activities · logic · dates · float'),
      runNode(2, ctx, 'Evidence extraction', 'What did the documents record?',
        'Rows · quantities · provenance'),
    ])) +
    runRail(3, ctx) +
    runStage('Reasoning', runBand(1, [
      runNode(3, ctx, 'Reasoning provider', 'What does the agent propose?',
        'Structured output only · never a schedule fact'),
    ])) +
    runRail(4, ctx) +
    runStage('Resolver ensemble',
      runBand(1, [
        runNode(4, ctx, 'Semantic candidate floor', 'Which activities are plausible?',
          'Candidate retrieval · no forced match'),
      ]) +
      runRail(4, ctx, 'split mid') +
      runBand(3, [
        runNode(4, ctx, 'Engineering', 'What?', 'Scope and workface semantics'),
        runNode(4, ctx, 'Tree', 'Where?', 'WBS · location · hierarchy'),
        runNode(4, ctx, 'Rescheduler v2', 'Changed world?', 'Revision-aware candidates'),
      ]) +
      runRail(4, ctx, 'merge mid') +
      runBand(1, [
        runNode(4, ctx, 'Candidate union', 'Four candidate lists converge',
          'Stable activity identity retained'),
      ]) +
      runRail(4, ctx, 'split wide') +
      runBand(2, [
        runNode(4, ctx, 'Expert utility predictors', '', 'Specialist ranking signals'),
        runNode(4, ctx, 'Candidate-level evidence', '', 'Support · conflict · provenance'),
      ]) +
      runRail(4, ctx, 'merge wide') +
      runBand(1, [
        runNode(4, ctx, 'LambdaMART MetaRank', 'Which activity best explains it?',
          'Learned ensemble · evidence-aware'),
      ]) +
      runRail(4, ctx) +
      runBand(1, [
        runNode(4, ctx, 'Final activity rank', 'Best supported identity',
          'Ranking margin · not a probability'),
      ])) +
    runRail(5, ctx) +
    runStage('Governed decision boundary', runBand(5, [
      runNode(5, ctx, 'Calibration', '', 'Uncertainty made explicit'),
      runNode(5, ctx, 'Deterministic validators', '', 'Rules · dates · relationships'),
      runNode(6, ctx, 'Risk policy', '', 'Safe action boundary'),
      runNode(7, ctx, 'Review / identity link', '',
        needsReview ? 'Human decision required' : 'No forced identity'),
      runNode(8, ctx, 'Schedule-write gates', '', 'Human approval only', true),
    ]), true);

  return '<section class="intelligence-run ' + statusClass + '" aria-label="VEDA execution status"' +
    ' data-run-job="' + E(job ? job.id : '') + '"' +
    ' data-run-display="' + E(ctx.ordinal) + '"' +
    ' data-run-actual="' + E(ctx.actualOrdinal) + '"' +
    ' data-run-terminal="' + E(job ? job.status : '') + '"' +
    (statusClass === 'running' ? ' aria-busy="true"' : '') + '>' +
    '<header class="run-header"><div class="run-title">' +
      '<div class="eyebrow">Persisted execution intelligence</div>' +
      '<h2>Field truth → governed schedule decision</h2>' +
      '<p>Every highlight is derived from the latest stored job phase. Nothing ' +
      'below is animated ahead of what VEDA has actually persisted.</p></div>' +
      '<div class="run-status"><span class="run-beacon" aria-hidden="true"></span>' +
      '<div><b>' + E(statusLabel) + '</b><small>' + E(phaseLabel) + ' · ' +
      E(runDuration(job)) + '</small></div></div></header>' +
    '<div class="run-milestones" aria-label="Execution stages">' +
      RUN_STAGES.map(([level, label]) => {
        const state = runState(level, ctx, false);
        return '<div class="run-milestone ' + state + '"' +
          (state === 'active' ? ' aria-current="step"' : '') + '>' +
          '<i aria-hidden="true"></i><span>' + E(label) + '</span></div>';
      }).join('') + '</div>' +
    '<div class="architecture-map">' +
      '<div class="map-caption"><span>Live architecture</span>' +
      '<small>WHAT × WHERE × CHANGED WORLD</small></div>' + map + '</div>' +
    '<footer class="run-footer"><div class="run-legend">' +
      '<span class="done"><i></i>Persisted complete</span>' +
      '<span class="active"><i></i>Current stage</span>' +
      '<span class="pending"><i></i>Waiting</span>' +
      '<span class="guarded"><i></i>Governed boundary</span></div>' +
      '<div class="run-latest"><span>Latest durable event</span><b>' +
      E(ctx.latest ? ctx.latest.label : 'No execution events yet') + '</b></div>' +
    '</footer></section>';
}

/* Reasoning provider labels, mirroring agent/registry.py LABELS so the console
   reads well even before /health has landed in window.S. */
const PROVIDER_LABELS = {
  auto: 'Auto', antigravity_cli: 'Antigravity', claude_code: 'Claude Code',
  codex: 'Codex', gemini_api: 'Gemini API',
  local_antigravity: 'Antigravity · local bridge',
};

/* The full execution visualiser, nested inside a run's thinking panel. It is
   auto-collapsed until there is a run to show, then unfolds with the panel so
   expanding the thinking reveals the entire architecture in depth. The
   reader's own toggle is remembered and always wins. */
function executionReveal(pid, job, activity) {
  const live = !!job && ['queued', 'running'].includes(String(job.status || ''));
  const vizKey = 'viz:' + (pid || '');
  const stored = VIEWS._vizOpen[vizKey];
  const open = stored === undefined ? !!job : !!stored;
  const caption = job
    ? (live ? 'Live · every stage as VEDA persists it'
       : job.status === 'done' ? 'Complete · full persisted pipeline'
       : 'Stopped safely · pipeline as far as it ran')
    : 'Preview · the pipeline a run will follow';
  return '<details class="run-reveal"' + (open ? ' open' : '') +
    ' data-viz-key="' + E(vizKey) + '">' +
    '<summary><span class="run-reveal-mark" aria-hidden="true"></span>' +
    '<b>Execution visualisation</b>' +
    '<span class="run-reveal-hint">' + E(caption) + '</span>' +
    '<span class="run-reveal-chevron" aria-hidden="true">⌄</span></summary>' +
    '<div class="run-reveal-body">' + executionMap(job, activity) + '</div>' +
    '</details>';
}

/* The reasoning-provider console that sits below the run's thinking panel -
   who is doing the thinking (often the local Antigravity bridge), whether it
   is reachable, and this run's telemetry, in one arranged instrument block. */
function providerConsole(job) {
  const health = (typeof window !== 'undefined' && window.S && window.S.health) || null;
  const providers = (health && health.providers) || {};
  const activeName = health ? health.active_provider : null;
  const auto = providers.auto || null;
  let key = (job && job.provider) || activeName || null;
  if (key === 'auto') key = (auto && auto.selected) || 'auto';
  const ph = key ? providers[key] : null;
  const label = (ph && ph.label) || PROVIDER_LABELS[key] || key || 'Reasoning provider';
  const reachable = ph ? !!ph.ok : null;
  const model = (ph && (ph.model || ph.version)) || '';
  const note = (ph && (ph.note || ph.hint)) || '';
  const isLocal = key === 'local_antigravity' || key === 'antigravity_cli' ||
    activeName === 'local_antigravity';
  const chain = (auto && auto.chain) || [];
  const usingAuto = activeName === 'auto';

  const healthTag = reachable === null
    ? '<span class="pc-health unknown"><i></i>status pending</span>'
    : reachable
      ? '<span class="pc-health ok"><i></i>reachable</span>'
      : '<span class="pc-health bad"><i></i>unavailable</span>';

  const cells = [];
  if (job) {
    cells.push(['Job', E(String(job.id || '').slice(0, 10)) || '—']);
    cells.push(['Kind', E(job.kind || '—')]);
    cells.push(['Status', E(job.status || '—')]);
    cells.push(['Phase', E(String(job.phase || '—').replace(/_/g, ' '))]);
    cells.push(['Attempts', int(job.attempts)]);
    cells.push(['Elapsed', E(runDuration(job))]);
  }

  return '<section class="provider-console' + (isLocal ? ' local' : '') +
    (reachable === false ? ' offline' : '') + '">' +
    '<header class="pc-head">' +
      '<div class="pc-id"><span class="pc-mark" aria-hidden="true"><i></i></span>' +
      '<div class="pc-id-copy"><div class="eyebrow">Reasoning provider' +
      (usingAuto ? ' · auto-selected' : '') + '</div>' +
      '<b>' + E(label) + '</b>' +
      (model ? '<small>' + E(model) + '</small>' : '') + '</div></div>' +
      healthTag +
    '</header>' +
    (cells.length
      ? '<div class="pc-grid">' + cells.map(([k, v]) =>
          '<div class="pc-cell"><span>' + E(k) + '</span><b>' + v + '</b></div>').join('') +
        '</div>'
      : '<div class="pc-empty">No run yet — the provider engages the moment you ' +
        'start an analysis.</div>') +
    (usingAuto && chain.length
      ? '<div class="pc-chain"><span>Fallback order</span>' + chain.map(c =>
          '<i class="' + (c.ok ? 'ok' : 'down') +
          (c.provider === key ? ' on' : '') + '">' +
          E(PROVIDER_LABELS[c.provider] || c.provider) + '</i>').join('') + '</div>'
      : '') +
    (note ? '<p class="pc-note">' + E(note) + '</p>' : '') +
    (job && job.error
      ? '<div class="pc-error"><b>Last run error</b>' +
        '<span class="mono">' + E(String(job.error).slice(0, 900)) + '</span></div>'
      : '') +
  '</section>';
}

VIEWS.agent = async (pid) => {
  const [act, mcp, jobs] = await Promise.all([
    A('/projects/' + pid + '/agent-activity?limit=160'),
    A('/projects/' + pid + '/mcp-calls?limit=140'),
    A('/projects/' + pid + '/jobs?limit=1'),
  ]);
  const j = jobs.jobs[0];
  const currentActivity = j
    ? act.activity.filter(a => String(a.job_id || '') === String(j.id || ''))
    : [];
  const currentCalls = j
    ? mcp.calls.filter(c => String(c.job_id || '') === String(j.id || ''))
    : [];
  // Keep the payload so the stage animation can advance without re-fetching.
  VIEWS._agentSnapshot = { pid: pid, job: j, activity: currentActivity };
  const jobStatus = j ? String(j.status || 'queued') : 'empty';
  const thinkStatus = (jobStatus === 'queued' || jobStatus === 'running') ? 'live'
    : jobStatus === 'done' ? 'done'
    : (jobStatus === 'failed' || jobStatus === 'cancelled') ? 'failed' : 'idle';

  return head('Execution intelligence', 'A live, evidence-safe view of VEDA’s ' +
    'persisted run state') +
    thinkingPanel({
      status: thinkStatus, steps: currentActivity, calls: currentCalls,
      openKey: 'agent:' + pid,
      kicker: thinkStatus === 'live' ? 'Execution reasoning · live'
        : thinkStatus === 'done' ? 'Execution reasoning · complete'
        : thinkStatus === 'failed' ? 'Execution reasoning · halted'
        : 'Execution reasoning',
      idleHint: 'Upload files and run an analysis to see VEDA reason through this project.',
      emptyLabel: 'No reasoning trace for this run yet.',
      extra: executionReveal(pid, j, currentActivity),
    }) +
    providerConsole(j);
};

/* Repaint only the execution map from the payload the last full render already
   fetched. The stage playback is presentation, so advancing it must not cost a
   round trip; durable state still arrives via SSE and the reconcile poll. */
VIEWS.paintRun = (pid) => {
  const snap = VIEWS._agentSnapshot;
  if (!snap || snap.pid !== pid) return false;
  const mounted = document.querySelector('#main .intelligence-run');
  if (!mounted) return false;
  mounted.outerHTML = executionMap(snap.job, snap.activity);
  return true;
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

  return head('Files', 'v0.4 typed source inbox — immutable, relevant, auditable') +
    panel('Add project sources', '<div class="body">' +
      '<div id="ingestdrop" tabindex="0">' +
      '<div style="font-weight:650;margin-bottom:5px">Drop many files here</div>' +
      '<div style="color:var(--ink-3);font-size:12px;margin-bottom:11px">' +
      'Schedules + DPRs + spreadsheets + scanned PDFs/photos can arrive together. ' +
      'Focus this box and paste a screenshot too.</div>' +
      '<button class="btn" id="pickfiles" type="button">Browse files</button> ' +
      '<button class="btn" id="pickfolder" type="button">Select project folder</button>' +
      '<input type="file" id="fileinput" multiple accept="' + accept + '" hidden>' +
      '<input type="file" id="folderinput" multiple webkitdirectory directory hidden>' +
      '<small id="folderhelp" style="display:block;color:var(--ink-3);margin-top:8px">Choose a folder to stage its supported files recursively.</small>' +
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
      table([{ t: 'Name' }, { t: 'Type / schema' }, { t: 'Relevance' }, { t: 'Source mode' },
        { t: 'Size', r: true }, { t: 'SHA-256' }, { t: 'Extraction' },
        { t: 'Security' }, { t: 'Uploaded' }], r.files, f =>
        '<tr><td>' + E(f.relative_path || f.filename) + '</td>' +
        '<td>' + tagFor(f.document_type || f.kind, { schedule: 'blue', evidence: 'grey',
          unknown: 'amber', REFERENCE_DOCUMENT: 'grey', WELDING_REGISTER: 'blue',
          NDT_REGISTER: 'green', NCR_REGISTER: 'red', MATERIAL_REGISTER: 'amber' }) +
          (f.schema_name ? '<small style="display:block;color:var(--ink-3);margin-top:3px">' +
            E(f.schema_name) + ' v' + E(f.schema_version || '—') + '</small>' : '') + '</td>' +
        '<td title="' + E(f.relevance_reason || '') + '">' + tagFor(f.relevance_state || 'pending',
          {evidence:'green', context:'blue', reference:'grey', unclassified:'amber', pending:'grey'}) + '</td>' +
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
  // File System Access directory handle -> the same File[] shape as the
  // drag-and-drop and <input webkitdirectory> paths use, each tagged with a
  // path relative to the chosen folder.
  const filesFromDirHandle = async (handle, prefix) => {
    const out = [];
    for await (const [name, child] of handle.entries()) {
      const path = prefix ? prefix + '/' + name : name;
      if (child.kind === 'file') {
        const f = await child.getFile();
        try { Object.defineProperty(f, '_vedaRelativePath', { value: path, configurable: true }); }
        catch (_) { f._vedaRelativePath = path; }
        out.push(f);
      } else if (child.kind === 'directory') {
        out.push(...await filesFromDirHandle(child, path));
      }
    }
    return out;
  };

  if (pick) pick.onclick = (e) => { e.stopPropagation(); inp.click(); };

  // Folder selection needs the File System Access API. Some embedded Chromium
  // hosts render a webkitdirectory chooser but return an empty FileList after
  // selection, so showing that fallback gives the operator a false success.
  const hasDirPicker = typeof window.showDirectoryPicker === 'function';
  const folderHelp = document.getElementById('folderhelp');
  if (folderInp) {
    folderInp.onchange = () => {
      const picked = folderInp.files ? folderInp.files.length : 0;
      addFiles(folderInp.files);
      folderInp.value = '';
      if (picked) window.toast(picked + ' file(s) staged from the selected folder.', 'good');
      else window.toast('No folder was imported. Highlight the folder and press Select Folder; if it still returns 0, use Browse files and select its contents.', 'bad');
    };
  }
  if (pickFolder) {
    if (!hasDirPicker) {
      pickFolder.hidden = true;
      if (folderHelp) folderHelp.textContent =
        'Folder selection is unavailable in this embedded browser. Use Browse files (Ctrl+A inside the folder), or drag the folder into this box.';
    } else {
      const label = pickFolder.textContent;
      pickFolder.onclick = async (e) => {
        e.stopPropagation();
        let handle;
        try {
          handle = await window.showDirectoryPicker({ id: 'veda-ingest', mode: 'read' });
        } catch (err) {
          if (!err || err.name !== 'AbortError') {
            window.toast('Could not open the folder picker: ' + (err && err.message || err), 'bad');
          }
          return;
        }
        pickFolder.disabled = true;
        pickFolder.textContent = 'Reading folder…';
        try {
          const files = await filesFromDirHandle(handle, handle.name);
          if (!files.length) window.toast('No files found in that folder.', 'bad');
          else addFiles(files);
        } catch (err) {
          window.toast('Could not read that folder: ' + err.message, 'bad');
        } finally {
          pickFolder.disabled = false;
          pickFolder.textContent = label;
        }
      };
    }
  }
  inp.onchange = () => { addFiles(inp.files); inp.value = ''; };
  if (dz) {
    dz.onclick = (e) => { if (!e.target.closest('button')) inp.click(); };
    dz.ondragover = (e) => { e.preventDefault(); dz.classList.add('drag'); };
    dz.ondragleave = () => { dz.classList.remove('drag'); };
    dz.ondrop = async (e) => {
      e.preventDefault(); dz.classList.remove('drag');
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

/* ============================================== VEDA Anywhere (browser companion)
   Opt-in bridge into the tools a project team already uses. Disabled by default.
   The extension only ever sends VEDA text the operator explicitly selected and
   explicitly submitted - it never reads, scrapes or monitors a page. This view
   is the control plane: enable/disable, pair a browser, and scope website
   access. It reads /anywhere/config, which never invokes the agent. */
VIEWS._anywhere = VIEWS._anywhere || { pairPoll: null, pairUntil: 0 };

const ANYWHERE_RULES = [
  'Does not continuously monitor web pages',
  'Does not scrape page content or collect browsing history',
  'Does not inspect chat messages or watch keyboard input',
  'Does not auto-send selected text, URLs or page contents',
  'No background AI analysis of any page',
];

function anywhereExtension() {
  const el = document.documentElement;
  const v = el.getAttribute('data-veda-anywhere') ||
    (window.__vedaAnywhere && window.__vedaAnywhere.version);
  return v ? { installed: true, version: String(v) } : { installed: false, version: null };
}

function anywhereStatePill(enabled, connected, installed) {
  if (!installed) return '<span class="aw-pill warn">Extension not installed</span>';
  if (!connected) return '<span class="aw-pill">Not connected</span>';
  return enabled
    ? '<span class="aw-pill ok">Active</span>'
    : '<span class="aw-pill">Connected · disabled</span>';
}

VIEWS.anywhere = async () => {
  const cfg = await A('/anywhere/config');
  const ext = anywhereExtension();
  VIEWS._anywhere.cfg = cfg;
  const s = cfg.settings || {};
  const tokens = cfg.tokens || [];
  const connected = (cfg.active_token_count || 0) > 0;
  const projects = cfg.projects || [];
  const install = cfg.install || {};
  const defProject = s.default_project_id ||
    (projects[0] && projects[0].id) || '';

  const privacyPanel = panel(
    'Privacy-first by design <small>opt-in · nothing automatic</small>',
    '<div class="body"><div class="aw-hero">' +
      '<p><b>Bring VEDA to where project information already lives</b> — Teams, ' +
      'Slack, Gmail, WhatsApp Web, an internal portal or a project dashboard — ' +
      'without leaving your current workflow.</p>' +
      '<div class="aw-flow"><span>You select text</span><i>→</i>' +
      '<span>You invoke VEDA</span><i>→</i><span>Only the selection is read</span>' +
      '<i>→</i><span>You choose Ask or Capture</span></div>' +
      '<div class="aw-receives"><i>■</i><div><b>During normal browsing, VEDA receives nothing.</b>' +
      '<small>The companion is inert until you explicitly select text and invoke it.</small></div></div>' +
      '<ul class="aw-rules">' + ANYWHERE_RULES.map(r => '<li>' + E(r) + '</li>').join('') + '</ul>' +
    '</div></div>');

  const statusPanel = panel(
    'VEDA Anywhere <small>' + E(cfg.server_version || '') + '</small>' +
      '<div class="spacer"></div>' + anywhereStatePill(s.enabled, connected, ext.installed),
    '<div class="body"><div class="aw-enable">' +
      '<div><b>' + (s.enabled ? 'VEDA Anywhere is enabled' : 'VEDA Anywhere is disabled') + '</b>' +
      '<small>' + (s.enabled
        ? 'The paired browser can send selected text for Ask VEDA and Capture in VEDA.'
        : 'Turn this on to use VEDA on other websites. It stays off until you enable it here, and you can disable it again at any time.') +
      '</small></div><div class="spacer"></div>' +
      '<button class="btn ' + (s.enabled ? 'danger' : 'primary') + '" id="aw-toggle">' +
      (s.enabled ? 'Disable VEDA Anywhere' : 'Enable VEDA Anywhere') + '</button></div>' +
      (s.enabled && !connected
        ? '<div class="note warn" style="margin-top:11px">Enabled, but no browser is paired yet. Connect the extension below.</div>'
        : '') +
    '</div>');

  let extBody;
  if (!ext.installed) {
    extBody = '<div class="body"><div class="aw-install">' +
      '<div class="aw-install-head"><b>Browser companion not installed</b>' +
      '<small>VEDA Anywhere needs the desktop browser extension (Chrome / Edge).</small></div>' +
      '<ol class="aw-steps">' +
      (install.load_unpacked_steps || []).map(x => '<li>' + E(x) + '</li>').join('') +
      '</ol>' +
      '<label class="aw-path"><span>Extension folder</span>' +
      '<input class="inp mono" id="aw-path" readonly value="' + E(install.unpacked_path || '') + '"></label>' +
      '<button class="btn" id="aw-copy-path">Copy folder path</button>' +
      '<p class="aw-hint">After loading it, return here and choose <b>Connect extension</b>. ' +
      'This page detects the companion automatically once it is installed.</p>' +
      '</div></div>';
  } else {
    const companions = tokens.length
      ? tokens.map(t => '<div class="aw-companion"><div><b>' + E(t.label || 'Browser companion') +
          '</b><small class="mono">' + E((t.user_agent || 'unknown browser').slice(0, 72)) + '</small>' +
          '<small>Paired ' + (t.created_at ? new Date(t.created_at * 1000).toLocaleString() : '—') +
          (t.last_used_at ? ' · last used ' + new Date(t.last_used_at * 1000).toLocaleString() : ' · not used yet') +
          '</small></div><div class="spacer"></div>' +
          '<button class="btn sm danger" data-aw-revoke="' + E(t.id) + '">Revoke</button></div>').join('')
      : '<div class="empty"><b>No browser paired yet</b>Generate a pairing code and confirm it in the extension.</div>';
    extBody = '<div class="body">' +
      '<div class="aw-connect-row"><div><b>' + (connected ? 'Companion connected' : 'Pair this browser') +
      '</b><small>Pairing generates a short-lived code and exchanges it for a secure token ' +
      'scoped to this VEDA workspace. The extension reuses your existing project access — ' +
      'it can never reach a project you cannot open here.</small></div><div class="spacer"></div>' +
      '<button class="btn primary" id="aw-connect">' + (connected ? 'Pair another browser' : 'Connect extension') +
      '</button></div>' +
      '<div id="aw-pair-slot"></div>' +
      '<div class="aw-companions">' + companions + '</div>' +
      (tokens.length ? '<button class="btn sm" id="aw-revoke-all">Revoke all companions</button>' : '') +
      '</div>';
  }
  const extPanel = panel('Browser companion' +
    (ext.installed ? ' <small>detected · v' + E(ext.version) + '</small>' : ''), extBody);

  const sitesPanel = panel('Website access <small>prefer least privilege</small>',
    '<div class="body"><div class="aw-mode">' +
      '<label class="aw-radio' + (s.site_access_mode === 'selected' ? ' selected' : '') +
      '"><input type="radio" name="aw-mode" value="selected"' +
      (s.site_access_mode === 'selected' ? ' checked' : '') + '>' +
      '<span><b>Selected websites only</b><small>Recommended. The companion only offers VEDA on the domains you list.</small></span></label>' +
      '<label class="aw-radio' + (s.site_access_mode === 'all' ? ' selected' : '') +
      '"><input type="radio" name="aw-mode" value="all"' +
      (s.site_access_mode === 'all' ? ' checked' : '') + '>' +
      '<span><b>All websites</b><small>Broader. Only choose this if you need VEDA on many internal tools. You can still invoke it manually per page.</small></span></label>' +
    '</div>' +
    '<div class="aw-sites' + (s.site_access_mode === 'all' ? ' dim' : '') + '" id="aw-sites">' +
      (s.allowed_sites || []).map(h => '<span class="aw-site">' + E(h) +
        '<button type="button" data-aw-site="' + E(h) + '" aria-label="Remove ' + E(h) + '">×</button></span>').join('') +
      (!(s.allowed_sites || []).length ? '<span class="aw-site-empty">No sites yet</span>' : '') +
    '</div>' +
    '<div class="aw-site-add"><input class="inp" id="aw-site-input" placeholder="add a domain, e.g. internal.company.com" autocomplete="off">' +
    '<button class="btn" id="aw-site-add">Add site</button></div>' +
    '<p class="aw-hint">The extension enforces its own browser permissions too. VEDA only ever ' +
    'processes a selection you explicitly send — this list just controls where the ' +
    'VEDA action appears.</p>' +
    '</div>');

  const projectPanel = panel('Active project <small>always shown before any capture</small>',
    '<div class="body"><div class="aw-project">' +
      (projects.length
        ? '<label><span>Default project for the companion</span>' +
          '<select class="inp" id="aw-project">' +
          projects.map(p => '<option value="' + E(p.id) + '"' +
            (p.id === defProject ? ' selected' : '') + '>' + E(p.name) + '</option>').join('') +
          '</select></label>' +
          '<p class="aw-hint">Users may belong to several projects. The extension always shows the ' +
          'active project in its popup and on every capture confirmation, and lets you switch ' +
          'it per capture — VEDA never submits to a project without showing which one is active.</p>' +
          '<button class="btn sm" id="aw-new-project">+ New project</button>'
        : '<div class="note warn"><b>No projects yet.</b> VEDA Anywhere can be set up now, but Ask VEDA ' +
          'and Capture in VEDA need a project. Create one to start using the companion.</div>' +
          '<button class="btn primary" id="aw-new-project" style="margin-top:11px">Create a project</button>') +
    '</div></div>');

  return head('VEDA Anywhere', 'Opt-in browser companion') +
    privacyPanel + statusPanel + extPanel + sitesPanel + projectPanel;
};

function anywhereRenderPairSlot(code, expiresAt) {
  const slot = document.getElementById('aw-pair-slot');
  if (!slot) return;
  if (!code) { slot.innerHTML = ''; return; }
  slot.innerHTML = '<div class="aw-code-card"><div class="aw-code-head"><b>Pairing code</b>' +
    '<small id="aw-code-countdown">expires soon</small></div>' +
    '<div class="aw-code mono">' + E(code) + '</div>' +
    '<ol class="aw-code-steps"><li>Click the <b>VEDA Anywhere</b> icon in your browser toolbar</li>' +
    '<li>Paste this code and choose <b>Pair with code</b></li></ol>' +
    '<p class="aw-hint">The extension connects only when you enter this code. It is valid once, for a few minutes. This page updates automatically once paired.</p>' +
    '<button class="btn sm" id="aw-copy-code">Copy code</button> ' +
    '<button class="btn sm" id="aw-cancel-pair">Cancel</button></div>';
  const cd = document.getElementById('aw-code-countdown');
  const tick = () => {
    if (!document.getElementById('aw-code-countdown')) return;
    const left = Math.max(0, Math.round((expiresAt * 1000 - Date.now()) / 1000));
    cd.textContent = left ? 'expires in ' + left + 's' : 'expired';
  };
  tick();
  const copy = document.getElementById('aw-copy-code');
  if (copy) copy.onclick = () => {
    navigator.clipboard.writeText(code).then(() => window.toast('Pairing code copied', 'good'),
      () => window.toast('Could not copy', 'bad'));
  };
  const cancel = document.getElementById('aw-cancel-pair');
  if (cancel) cancel.onclick = async () => {
    anywhereStopPairPoll();
    try { await window.api('/anywhere/pair', { method: 'DELETE' }); } catch (_) {}
    anywhereRenderPairSlot(null);
  };
  clearInterval(VIEWS._anywhere.cdTimer);
  VIEWS._anywhere.cdTimer = setInterval(tick, 1000);
}

function anywhereStopPairPoll() {
  clearInterval(VIEWS._anywhere.pairPoll);
  clearInterval(VIEWS._anywhere.cdTimer);
  VIEWS._anywhere.pairPoll = null;
}

VIEWS.bind_anywhere = () => {
  const cfg = VIEWS._anywhere.cfg || {};
  const startCount = cfg.active_token_count || 0;

  // Ask the injected bridge (if any) to announce itself, so a freshly installed
  // extension is detected without a manual reload.
  try {
    window.postMessage({ source: 'veda-web', channel: 'veda-anywhere', type: 'ping' }, location.origin);
  } catch (_) {}

  VIEWS._anywhere.sawExtension = anywhereExtension().installed;

  // Listen once for the bridge announcing that the extension is installed, so a
  // freshly loaded extension is detected without a manual page reload.
  if (!VIEWS._anywhere.msgBound) {
    VIEWS._anywhere.msgBound = true;
    window.addEventListener('message', (e) => {
      if (e.source !== window || e.origin !== location.origin) return;
      const d = e.data || {};
      if (d.channel !== 'veda-anywhere' || d.source !== 'veda-anywhere') return;
      if (d.type === 'hello' || d.type === 'pong') {
        try { document.documentElement.setAttribute('data-veda-anywhere', String(d.version)); } catch (_) {}
        if (window.S && window.S.view === 'anywhere' && !VIEWS._anywhere.sawExtension) window.render();
      }
    });
  }

  const toggle = document.getElementById('aw-toggle');
  if (toggle) toggle.onclick = async () => {
    toggle.disabled = true;
    try {
      const next = !(cfg.settings && cfg.settings.enabled);
      await P('/anywhere/enable', { enabled: next });
      window.toast(next ? 'VEDA Anywhere enabled' : 'VEDA Anywhere disabled', 'good');
      window.render();
    } catch (e) {
      toggle.disabled = false;
      window.toast('Could not update: ' + e.message, 'bad');
    }
  };

  const copyPath = document.getElementById('aw-copy-path');
  if (copyPath) copyPath.onclick = () => {
    const v = (document.getElementById('aw-path') || {}).value || '';
    navigator.clipboard.writeText(v).then(() => window.toast('Folder path copied', 'good'),
      () => window.toast('Could not copy', 'bad'));
  };

  const connect = document.getElementById('aw-connect');
  if (connect) connect.onclick = async () => {
    connect.disabled = true;
    try {
      const r = await P('/anywhere/pair', {});
      anywhereRenderPairSlot(r.code, r.expires_at);
      // No automatic hand-off. The operator copies this code and enters it in
      // the extension. We only watch for the token to appear.
      anywhereStopPairPoll();
      VIEWS._anywhere.pairUntil = Date.now() + (r.ttl_seconds || 300) * 1000;
      VIEWS._anywhere.pairPoll = setInterval(async () => {
        // Stop if the operator navigated away or the code expired.
        if (!window.S || window.S.view !== 'anywhere' ||
            Date.now() > VIEWS._anywhere.pairUntil) {
          anywhereStopPairPoll();
          anywhereRenderPairSlot(null);
          return;
        }
        try {
          const c = await A('/anywhere/config');
          if ((c.active_token_count || 0) > startCount) {
            anywhereStopPairPoll();
            window.toast('Browser companion connected', 'good');
            if (window.S && window.S.view === 'anywhere') window.render();
          }
        } catch (_) {}
      }, 2000);
    } catch (e) {
      window.toast('Could not start pairing: ' + e.message, 'bad');
    } finally {
      connect.disabled = false;
    }
  };

  document.querySelectorAll('[data-aw-revoke]').forEach(b => b.onclick = async () => {
    if (!confirm('Revoke this browser companion? It will need to pair again.')) return;
    try {
      await P('/anywhere/tokens/' + encodeURIComponent(b.dataset.awRevoke) + '/revoke', {});
      window.toast('Companion revoked', 'good');
      window.render();
    } catch (e) { window.toast('Could not revoke: ' + e.message, 'bad'); }
  });

  const revokeAll = document.getElementById('aw-revoke-all');
  if (revokeAll) revokeAll.onclick = async () => {
    if (!confirm('Revoke every paired browser companion?')) return;
    try {
      await P('/anywhere/tokens/revoke-all', {});
      window.toast('All companions revoked', 'good');
      window.render();
    } catch (e) { window.toast('Could not revoke: ' + e.message, 'bad'); }
  };

  document.querySelectorAll('[name="aw-mode"]').forEach(r => r.onchange = async () => {
    try {
      await P('/anywhere/config', { site_access_mode: r.value });
      window.render();
    } catch (e) { window.toast('Could not update: ' + e.message, 'bad'); }
  });

  const sites = (cfg.settings && cfg.settings.allowed_sites) || [];
  const saveSites = async (next) => {
    try {
      await P('/anywhere/config', { allowed_sites: next });
      window.render();
    } catch (e) { window.toast('Could not update site list: ' + e.message, 'bad'); }
  };
  document.querySelectorAll('[data-aw-site]').forEach(b => b.onclick = () =>
    saveSites(sites.filter(h => h !== b.dataset.awSite)));
  const addSite = document.getElementById('aw-site-add');
  const siteInput = document.getElementById('aw-site-input');
  const doAdd = () => {
    const v = (siteInput.value || '').trim();
    if (!v) return;
    saveSites(sites.concat([v]));
  };
  if (addSite) addSite.onclick = doAdd;
  if (siteInput) siteInput.onkeydown = (e) => {
    if (e.key === 'Enter') { e.preventDefault(); doAdd(); }
  };

  const proj = document.getElementById('aw-project');
  if (proj) proj.onchange = async () => {
    try {
      await P('/anywhere/config', { default_project_id: proj.value });
      window.toast('Default companion project updated', 'good');
    } catch (e) { window.toast('Could not update: ' + e.message, 'bad'); }
  };

  const newProj = document.getElementById('aw-new-project');
  if (newProj && window.openNewProjectDialog) {
    newProj.onclick = () => window.openNewProjectDialog();
  }
};

window.VIEWS = VIEWS;
