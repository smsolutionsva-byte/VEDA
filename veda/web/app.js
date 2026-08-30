/* VEDA shell: state, routing, live event stream.
   Browsing never invokes the agent - every view reads persisted rows. */

const S = {
  project: null, projects: [], view: 'overview', params: {},
  counts: {}, health: null, es: null, streamProject: null, overview: null,
  agentCompletionTimer: null,
  agentWatchTimer: null, agentWatchProject: null, agentJobFingerprint: null,
  agentSyncBusy: false, renderVersion: 0,
  renderedView: null, renderedProject: null, agentPaintTimer: null,
};

const $ = (s, r) => (r || document).querySelector(s);

/* ------------------------------------------------------ read coalescing
   A live run fires many events, and each one asks the header and the current
   view for state. Several of those are the same GET issued microseconds apart
   (the control room re-reads /overview right after the header did). Share a
   read for a fraction of a second, and drop the whole cache the moment anything
   is written, so a refresh never shows a value older than the last mutation. */
const READ_TTL = 400;
const _reads = new Map();

function invalidateReads() { _reads.clear(); }

const api = async (path, opts) => {
  const isRead = !opts || !opts.method || opts.method === 'GET';
  if (isRead) {
    const hit = _reads.get(path);
    if (hit && (performance.now() - hit.at) < READ_TTL) return hit.promise;
  } else {
    invalidateReads();
  }
  const request = (async () => {
    const r = await fetch('/api' + path, opts);
    if (!r.ok) {
      let msg = r.status + ' ' + r.statusText;
      try { const j = await r.json(); msg = j.detail || msg; } catch (e) {}
      throw new Error(msg);
    }
    return r.json();
  })();
  if (isRead) {
    _reads.set(path, { at: performance.now(), promise: request });
    // A failed read must not be replayed to later callers.
    request.catch(() => _reads.delete(path));
  } else {
    // Whatever the write did, the next read has to see it.
    request.then(invalidateReads, invalidateReads);
  }
  return request;
};
const post = (p, body) => api(p, {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body || {}),
});

/* ---------------------------------------------------- navigation map
   Grouped by the responsibility model, not alphabetically: what the
   schedule says, what the field says, what needs a decision, and what
   the machinery is doing. */
const NAV = [
  ['Workspace', [
    ['capture', 'Capture field update'], ['files', 'Files'],
    ['proposals', 'Edit / proposed changes'],
    ['attention', 'Review Inbox', 'attention'],
  ]],
  ['Control', [
    ['overview', 'Control Room'], ['ask', 'Ask VEDA'],
  ]],
  ['Field Truth', [
    ['evidence', 'Evidence', 'evidence'], ['observed', 'Field vs Schedule'],
    ['issues', 'Issues', 'issues'], ['risks', 'Risks', 'risks'],
  ]],
  ['Schedule', [
    ['activities', 'Activities', 'activities'], ['critical', 'Critical Path', 'critical'],
    ['milestones', 'Milestones', 'milestones'], ['quality', 'Schedule QA', 'qa_failed'],
  ]],
  ['Project Data', [
    ['outputs', 'Reports & Exports'], ['audit', 'Audit Trail'],
  ]],
  ['Advanced', [
    ['wbs', 'WBS'], ['relationships', 'Relationships', 'relationships'],
    ['baselines', 'Baselines'], ['resources', 'Resources', 'resources'],
    ['assignments', 'Assignments', 'assignments'], ['timephased', 'Timephased'],
    ['ev', 'Earned Value'], ['eps', 'EPS'],
    ['anywhere', 'VEDA Anywhere'], ['system', 'System / MCP'],
  ]],
];

function toast(msg, kind) {
  const el = document.createElement('div');
  el.className = 'toast ' + (kind || '');
  el.textContent = msg;
  $('#toasts').appendChild(el);
  setTimeout(() => el.remove(), 5200);
}

/* -------------------------------------------------------------- rail */
function renderRail() {
  const c = S.counts || {};
  $('#rail').innerHTML = NAV.map(([grp, items]) => (
    '<div class="grp">' + grp + '</div>' +
    items.map(([id, label, key]) => {
      const n = key ? c[key] : undefined;
      const alert = key === 'attention' && n > 0;
      return '<a data-v="' + id + '" class="' + (S.view === id ? 'on' : '') + '">' +
        '<span>' + label + '</span>' +
        (n !== undefined && n !== null
          ? '<span class="n' + (alert ? ' alert' : '') + '">' + n + '</span>' : '') +
        '</a>';
    }).join('')
  )).join('');
  $('#rail').querySelectorAll('a').forEach(a =>
    a.onclick = () => go(a.dataset.v));
}

function go(view, params) {
  S.view = view; S.params = params || {};
  if (view !== 'agent') {
    clearTimeout(S.agentCompletionTimer);
    S.agentCompletionTimer = null;
  }
  location.hash = view + (params && params.id ? '/' + params.id : '');
  document.body.classList.remove('nav-open');
  const navToggle = $('#nav-toggle');
  if (navToggle) navToggle.setAttribute('aria-expanded', 'false');
  renderRail(); syncAgentWatchdog(); render();
}
window.go = go;

/* Views that are workspace-level, not project-level: they read config or
   runtime state, never a project, so they stay reachable before the first
   project exists. */
const PROJECT_OPTIONAL_VIEWS = new Set(['anywhere', 'system']);

/* ------------------------------------------------------------ render */
async function render() {
  const main = $('#main');
  const version = ++S.renderVersion;
  const renderProject = S.project;
  const renderView = S.view;
  if (!S.project && !PROJECT_OPTIONAL_VIEWS.has(renderView)) {
    document.body.classList.remove('ask-mode');
    main.innerHTML = VIEWS.noproject();
    bindNoProject();
    syncAgentWatchdog();
    S.renderedView = 'noproject';
    S.renderedProject = null;
    return;
  }
  const fn = VIEWS[S.view] || (S.project ? VIEWS.overview : VIEWS.noproject);
  // A live refresh re-renders the same view. Blanking it to a spinner on every
  // event makes real progress look like a stall and throws away the reader's
  // scroll position, so only show the placeholder on a genuine view change.
  const sameView = S.renderedView === renderView && S.renderedProject === renderProject;
  const scroll = sameView ? main.scrollTop : 0;
  if (!sameView && main.childElementCount) main.innerHTML = '<div class="empty">Loading…</div>';
  try {
    const html = await fn(renderProject, S.params);
    if (version !== S.renderVersion || renderProject !== S.project ||
        renderView !== S.view) return;
    document.body.classList.toggle('ask-mode', renderView === 'ask');
    main.innerHTML = html;
    if (sameView && scroll && renderView !== 'ask') main.scrollTop = scroll;
    S.renderedView = renderView;
    S.renderedProject = renderProject;
    if (fn === VIEWS.noproject) bindNoProject();
    if (window.bindThinkToggles) window.bindThinkToggles(main);
    if (VIEWS['bind_' + renderView]) VIEWS['bind_' + renderView](renderProject, S.params);
    syncAgentWatchdog();
  } catch (e) {
    if (version !== S.renderVersion || renderProject !== S.project ||
        renderView !== S.view) return;
    document.body.classList.remove('ask-mode');
    main.innerHTML = '<div class="panel"><div class="body">' +
      '<div class="note danger"><b>Could not load this view.</b><br>' +
      esc(e.message) + '</div></div></div>';
    S.renderedView = null;
    syncAgentWatchdog();
  }
}
window.render = render;

/* ------------------------------------------------------------ header */
async function refreshCounts() {
  if (!S.project) return;
  try {
    const o = await api('/projects/' + S.project + '/overview');
    S.overview = o;
    const latestJob = o.latest_job || null;
    const analysisRunning = Boolean(latestJob &&
      ['queued', 'running'].includes(String(latestJob.status || '')));
    S.counts = Object.assign({}, o.counts, {
      qa_failed: o.quality.failed,
      attention: Number(o.counts.pending_reviews || 0) +
        Number(o.counts.pending_proposals || 0) +
        ((!analysisRunning && Number(o.counts.unresolved_evidence || 0) > 0 &&
          Number(o.counts.pending_reviews || 0) === 0) ? 1 : 0),
    });
    renderRail();
    const ps = o.project_state || { code: 'up_to_date', label: 'Up to date' };
    const chip = $('#chip-job');
    chip.className = 'chip ' + (ps.code === 'updating' ? 'busy'
      : (ps.code === 'retry' ? 'bad' : (ps.code === 'needs_input' || ps.code === 'choose_schedule' ? '' : 'ok')));
    chip.querySelector('span').textContent = ps.label;
  } catch (e) { /* header is best-effort */ }
}
window.refreshCounts = refreshCounts;

async function refreshHealth() {
  try {
    const h = await api('/health');
    S.health = h;
    const a = h.providers[h.active_provider] || {};
    const ca = $('#chip-agent');
    ca.className = 'chip ' + (a.ok ? 'ok' : 'bad');
    const agentName = h.active_provider === 'auto' && a.selected_label
      ? 'Auto → ' + a.selected_label : (a.label || h.active_provider);
    ca.querySelector('span').textContent = agentName + (a.ok ? '' : ' offline');
    const cm = $('#chip-mcp');
    cm.className = 'chip ' + (h.horizun.ok ? 'ok' : 'bad');
    cm.querySelector('span').textContent = 'Horizun' +
      (h.horizun.ok ? ' · ' + (h.horizun.backend || 'ok') : ' offline');
  } catch (e) {
    $('#chip-mcp').className = 'chip bad';
  }
}

/* ------------------------------------------------------------- theme */
function syncThemeToggle() {
  const b = $('#theme-toggle');
  if (!b) return;
  const theme = document.documentElement.dataset.theme || 'dark';
  const next = theme === 'dark' ? 'light' : 'dark';
  b.dataset.theme = theme;
  b.setAttribute('aria-label', 'Switch to ' + next + ' theme');
  const label = b.querySelector('em');
  if (label) label.textContent = theme === 'dark' ? 'Dark' : 'Light';
}

function applyTheme(theme, persist) {
  document.documentElement.dataset.theme = theme === 'light' ? 'light' : 'dark';
  if (persist) {
    try { localStorage.setItem('veda-theme', document.documentElement.dataset.theme); }
    catch (_) { /* Theme still applies when browser storage is unavailable. */ }
  }
  syncThemeToggle();
}

/* ------------------------------------------------------------ projects */
async function loadProjects(selectId) {
  const r = await api('/projects');
  S.projects = r.projects;
  const sel = $('#projpick');
  sel.innerHTML = r.projects.length
    ? r.projects.map(p => '<option value="' + p.id + '">' + esc(p.name) +
        '</option>').join('')
    : '<option value="">No projects yet</option>';
  const nextProject = selectId || (r.projects[0] && r.projects[0].id) || null;
  const changed = nextProject !== S.project;
  if (changed) stopAgentWatchdog();
  S.project = nextProject;
  if (S.project) sel.value = S.project;
  if (changed && S.project) await activateCurrentProject(S.project);
  if (changed) connectStream();
  await refreshCounts();
  render();
}

function closeNewProjectDialog() {
  const old = $('#project-new-scrim');
  if (old) old.remove();
}

window.openNewProjectDialog = openNewProjectDialog;
function openNewProjectDialog() {
  closeNewProjectDialog();
  const scrim = document.createElement('div');
  scrim.className = 'scrim';
  scrim.id = 'project-new-scrim';
  scrim.innerHTML =
    '<section class="modal new-project-modal" id="project-new-modal">' +
    '<header><div><div class="eyebrow">Workspace</div>' +
    '<h2>Create a project</h2></div></header>' +
    '<div class="body">' +
      '<div class="np-grid">' +
        '<label class="np-field np-wide"><span>Project name <em>required</em></span>' +
        '<input class="inp" id="np-name" autocomplete="off" ' +
        'placeholder="e.g. TransRidge Interconnector, Section 4"></label>' +
        '<label class="np-field"><span>Client <em>optional</em></span>' +
        '<input class="inp" id="np-client" autocomplete="off" placeholder="e.g. NHAI"></label>' +
        '<label class="np-field"><span>Location <em>optional</em></span>' +
        '<input class="inp" id="np-location" autocomplete="off" placeholder="e.g. Uttar Pradesh, India"></label>' +
        '<label class="np-field np-wide"><span>Description <em>optional</em></span>' +
        '<textarea class="inp" id="np-description" rows="3" placeholder=' +
        '"Scope, boundaries, anything useful for later reference."></textarea></label>' +
      '</div>' +
      '<div class="np-next"><b>What happens next</b><div class="np-next-steps">' +
      '<span><i>1</i>Upload a schedule &mdash; XER, MPP, MSPDI XML, PMXML or Asta</span>' +
      '<span><i>2</i>Add DPRs, registers and reports describing what happened on site</span>' +
      '<span><i>3</i>VEDA reconciles both automatically and flags what needs a decision</span>' +
      '</div></div>' +
      '<div class="note danger" id="np-error" hidden></div>' +
      '<div class="modal-actions"><button class="btn" id="np-cancel">Cancel</button>' +
      '<div class="spacer"></div>' +
      '<button class="btn primary" id="np-create">Create project</button></div>' +
    '</div></section>';
  scrim.onclick = (e) => { if (e.target === scrim) closeNewProjectDialog(); };
  document.body.appendChild(scrim);

  const nameInput = $('#np-name');
  const errBox = $('#np-error');
  const showError = (msg) => { errBox.hidden = false; errBox.textContent = msg; };

  const submit = async () => {
    const name = nameInput.value.trim();
    if (!name) { showError('Project name is required.'); nameInput.focus(); return; }
    const btn = $('#np-create');
    btn.disabled = true; btn.textContent = 'Creating…';
    errBox.hidden = true;
    try {
      const r = await post('/projects', {
        name: name,
        client: $('#np-client').value.trim() || null,
        location: $('#np-location').value.trim() || null,
        description: $('#np-description').value.trim() || null,
      });
      closeNewProjectDialog();
      toast('Project created. Upload a schedule and project files to begin.', 'good');
      await loadProjects(r.id);
      go('files');
    } catch (e) {
      btn.disabled = false; btn.textContent = 'Create project';
      showError('Could not create project: ' + e.message);
    }
  };
  $('#np-create').onclick = submit;
  $('#np-cancel').onclick = closeNewProjectDialog;
  nameInput.onkeydown = (e) => { if (e.key === 'Enter') { e.preventDefault(); submit(); } };
  requestAnimationFrame(() => nameInput.focus());
}

function closeProjectDeleteDialog() {
  const old = $('#project-delete-scrim');
  if (old) old.remove();
}

function projectDeleteMeta(p) {
  const bits = [];
  if (p.client) bits.push(p.client);
  if (p.location) bits.push(p.location);
  const c = p.counts || {};
  const files = Number(c.files || 0);
  const activities = Number(c.activities || 0);
  bits.push(files + ' file' + (files === 1 ? '' : 's'));
  if (activities) bits.push(activities + ' activities');
  return bits.join(' · ');
}

function showDeleteConfirmation(project) {
  const modal = $('#project-delete-modal');
  if (!modal) return;
  modal.innerHTML =
    '<header><div><div class="eyebrow">Delete project</div>' +
    '<h2>Confirm deletion</h2></div></header>' +
    '<div class="body">' +
      '<div class="delete-warning">' +
        '<b>This permanently deletes “' + esc(project.name) + '”.</b>' +
        '<span>Uploaded files, analysis, project history, and any running or queued work for this project will be removed.</span>' +
      '</div>' +
      '<div class="delete-confirm-name">' + esc(project.name) + '</div>' +
      '<div class="modal-actions">' +
        '<button class="btn" id="delete-back">Back</button>' +
        '<div class="spacer"></div>' +
        '<button class="btn" id="delete-cancel">Cancel</button>' +
        '<button class="btn danger" id="delete-confirm">Delete project</button>' +
      '</div>' +
    '</div>';

  $('#delete-back').onclick = () => renderProjectDeletePicker(project.id);
  $('#delete-cancel').onclick = closeProjectDeleteDialog;
  $('#delete-confirm').onclick = async () => {
    const b = $('#delete-confirm');
    b.disabled = true;
    b.textContent = 'Deleting…';
    try {
      const deletingCurrent = project.id === S.project;
      const keepProject = deletingCurrent ? null : S.project;
      await api('/projects/' + encodeURIComponent(project.id), { method: 'DELETE' });

      if (deletingCurrent) {
        if (S.es) { S.es.close(); S.es = null; }
        stopAgentWatchdog();
        clearTimeout(S.agentCompletionTimer);
        S.agentCompletionTimer = null;
        S.project = null;
        S.overview = null;
        S.counts = {};
      }

      closeProjectDeleteDialog();
      toast('Deleted “' + project.name + '”.', 'good');
      await loadProjects(keepProject || undefined);
    } catch (e) {
      b.disabled = false;
      b.textContent = 'Delete project';
      toast('Could not delete project: ' + e.message, 'bad');
    }
  };
}

function renderProjectDeletePicker(selectedId) {
  const modal = $('#project-delete-modal');
  if (!modal) return;

  const projects = S.projects || [];
  if (!projects.length) {
    modal.innerHTML =
      '<header><h2>Delete project</h2></header>' +
      '<div class="body"><div class="empty"><b>No projects to delete</b>' +
      'Create a project first.</div>' +
      '<div class="modal-actions"><div class="spacer"></div>' +
      '<button class="btn" id="delete-close">Close</button></div></div>';
    $('#delete-close').onclick = closeProjectDeleteDialog;
    return;
  }

  modal.innerHTML =
    '<header><div><div class="eyebrow">Project management</div>' +
    '<h2>Choose a project to delete</h2></div></header>' +
    '<div class="body">' +
      '<div class="delete-project-list">' +
      projects.map(p => {
        const selected = p.id === selectedId;
        const current = p.id === S.project;
        return '<button class="delete-project-row' + (selected ? ' selected' : '') +
          '" data-delete-project="' + esc(p.id) + '">' +
          '<span class="delete-radio">' + (selected ? '●' : '') + '</span>' +
          '<span class="delete-project-copy"><b>' + esc(p.name) + '</b>' +
          '<small>' + esc(projectDeleteMeta(p)) + '</small></span>' +
          (current ? '<span class="tag amber">Current</span>' : '') +
          '</button>';
      }).join('') +
      '</div>' +
      '<div class="modal-actions">' +
        '<button class="btn" id="delete-picker-cancel">Cancel</button>' +
        '<div class="spacer"></div>' +
        '<button class="btn danger" id="delete-picker-next"' +
          (selectedId ? '' : ' disabled') + '>Continue</button>' +
      '</div>' +
    '</div>';

  modal.querySelectorAll('[data-delete-project]').forEach(row => {
    row.onclick = () => renderProjectDeletePicker(row.dataset.deleteProject);
  });
  $('#delete-picker-cancel').onclick = closeProjectDeleteDialog;
  $('#delete-picker-next').onclick = () => {
    const project = projects.find(p => p.id === selectedId);
    if (project) showDeleteConfirmation(project);
  };
}

async function openProjectDeleteDialog() {
  // Re-read the list so the picker cannot show a stale/deleted project.
  try {
    const r = await api('/projects');
    S.projects = r.projects || [];
  } catch (e) {
    return toast('Could not load projects: ' + e.message, 'bad');
  }

  closeProjectDeleteDialog();
  const scrim = document.createElement('div');
  scrim.className = 'scrim';
  scrim.id = 'project-delete-scrim';
  scrim.innerHTML = '<section class="modal delete-project-modal" id="project-delete-modal"></section>';
  scrim.onclick = (e) => {
    if (e.target === scrim) closeProjectDeleteDialog();
  };
  document.body.appendChild(scrim);
  renderProjectDeletePicker(null);
}

async function activateCurrentProject(pid) {
  if (!pid) return;
  try {
    const r = await post('/projects/' + pid + '/activate');
    if (r.cancelled && r.cancelled.length) {
      toast('Stopped the previous project and switched immediately.', 'good');
    }
  } catch (e) {
    toast('Could not switch project: ' + e.message, 'bad');
    throw e;
  }
}

/* ------------------------------------------------ durable run watchdog
   SSE is the fast path. This scoped reconciliation loop covers a suspended
   tab, reconnect gap, or coalesced burst by comparing durable job/activity
   fingerprints while the execution view is visible. */
function stopAgentWatchdog() {
  if (S.agentWatchTimer) clearInterval(S.agentWatchTimer);
  if (S.agentPaintTimer) clearInterval(S.agentPaintTimer);
  S.agentWatchTimer = null;
  S.agentPaintTimer = null;
  S.agentWatchProject = null;
  S.agentJobFingerprint = null;
  S.agentSyncBusy = false;
}

function runPresentationBehind() {
  const map = $('#main .intelligence-run');
  if (!map) return false;
  return Number(map.dataset.runDisplay || 0) < Number(map.dataset.runActual || 0);
}

function maybeLeaveCompletedRun(projectId, job) {
  const terminal = job && job.kind === 'analysis' && job.status === 'done';
  if (!terminal || runPresentationBehind() || S.view !== 'agent' ||
      S.project !== projectId) {
    clearTimeout(S.agentCompletionTimer);
    S.agentCompletionTimer = null;
    return;
  }
  if (S.agentCompletionTimer) return;
  S.agentCompletionTimer = setTimeout(() => {
    S.agentCompletionTimer = null;
    if (S.view === 'agent' && S.project === projectId) go('overview');
  }, 1800);
}

async function pollAgentState(projectId) {
  if (S.agentSyncBusy || S.view !== 'agent' || S.project !== projectId) return;
  S.agentSyncBusy = true;
  try {
    const [jobs, activity] = await Promise.all([
      api('/projects/' + projectId + '/jobs?limit=1'),
      api('/projects/' + projectId + '/agent-activity?limit=1'),
    ]);
    if (S.view !== 'agent' || S.project !== projectId) return;
    const job = jobs.jobs && jobs.jobs[0];
    const latest = activity.activity && activity.activity[0];
    const fingerprint = [job && job.id, job && job.status, job && job.phase,
      job && job.finished_at, latest && latest.id, latest && latest.created_at,
      latest && latest.label].join('|');
    if (fingerprint !== S.agentJobFingerprint || runPresentationBehind()) {
      S.agentJobFingerprint = fingerprint;
      await render();
      if (S.view === 'agent' && S.project === projectId) {
        if (job && ['done', 'failed', 'cancelled'].includes(job.status)) {
          await refreshCounts();
        }
        maybeLeaveCompletedRun(projectId, job);
      }
    }
  } catch (_) {
    // The SSE reconnect path and next interval both retry durable state.
  } finally {
    S.agentSyncBusy = false;
  }
}

function syncAgentWatchdog() {
  if (S.view !== 'agent' || !S.project) {
    stopAgentWatchdog();
    return;
  }
  if (S.agentWatchTimer && S.agentWatchProject === S.project) return;
  stopAgentWatchdog();
  S.agentWatchProject = S.project;
  const projectId = S.project;
  // Two separate clocks. The stage animation is presentation only, so it
  // repaints locally at the playback cadence and never touches the network.
  // Durable job/activity state is reconciled on a slower beat, because SSE is
  // the fast path and this only has to cover a suspended tab or a dropped
  // connection.
  S.agentPaintTimer = setInterval(() => repaintRunPresentation(projectId), 320);
  S.agentWatchTimer = setInterval(() => pollAgentState(projectId), 1500);
}

function repaintRunPresentation(projectId) {
  if (S.view !== 'agent' || S.project !== projectId) return;
  if (!runPresentationBehind()) return;
  // Local repaint from the payload the last full render already fetched.
  if (!VIEWS.paintRun(projectId)) { render(); return; }
  if (!runPresentationBehind()) {
    const snap = VIEWS._agentSnapshot;
    maybeLeaveCompletedRun(projectId, snap && snap.pid === projectId ? snap.job : null);
  }
}

function bindNoProject() {
  const b = $('#createFirst');
  if (b) b.onclick = openNewProjectDialog;
}

/* --------------------------------------------------------- live stream */
function connectStream() {
  if (S.es) S.es.close();
  const streamProject = S.project;
  S.streamProject = streamProject;
  const es = new EventSource('/api/stream' +
    (streamProject ? '?project_id=' + encodeURIComponent(streamProject) : ''));
  S.es = es;
  let pending = null;

  const syncFromServer = async (allowNavigate) => {
    // A stream can reconnect after an event was emitted. Always re-read durable
    // state so UI correctness never depends on catching one transient SSE hint.
    if (streamProject !== S.project || es !== S.es) return;
    await refreshCounts();
    if (streamProject !== S.project || es !== S.es) return;
    const j = S.overview && S.overview.latest_job;
    const terminalAnalysis = j && j.kind === 'analysis' &&
      j.status === 'done';
    if (allowNavigate && terminalAnalysis && S.view === 'agent') {
      await render();
      maybeLeaveCompletedRun(streamProject, j);
      return;
    }
    if (['overview', 'capture', 'attention', 'ask', 'evidence', 'outputs', 'observed',
      'quality', 'activities', 'agent'].includes(S.view)) {
      render();
    }
  };

  es.onopen = () => { syncFromServer(true); };
  es.onmessage = (m) => {
    let d; try { d = JSON.parse(m.data); } catch (e) { return; }
    if (!d.type || (d.project_id && d.project_id !== S.project)) return;
    // Coalesce bursts: the agent emits many steps in quick succession.
    clearTimeout(pending);
    pending = setTimeout(() => syncFromServer(true), 350);
  };
  es.onerror = () => {
    // EventSource reconnects itself; immediately reconcile durable state too.
    syncFromServer(false);
  };
}

/* -------------------------------------------------------- thinking clock
   A "thinking" panel's collapsed headline ticks up like an LLM reasoning
   trace ("Thinking for 12s"). Rather than a per-view timer, one cheap
   app-wide interval refreshes whatever live headline happens to be mounted
   (Execution intelligence or Ask VEDA); the query is a no-op when neither
   view is showing one. fmtDur comes from views.js, loaded before this file. */
function tickThinking() {
  document.querySelectorAll('[data-think-live="1"]').forEach((el) => {
    const first = Number(el.dataset.thinkFirst || 0);
    if (!first) return;
    el.textContent = 'Thinking for ' + fmtDur(Date.now() / 1000 - first);
  });
}

/* ---------------------------------------------------------------- init */
function esc(s) {
  return String(s === null || s === undefined ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
window.esc = esc;
window.api = api; window.post = post; window.toast = toast;

async function init() {
  syncThemeToggle();
  $('#theme-toggle').onclick = () => {
    const current = document.documentElement.dataset.theme || 'dark';
    applyTheme(current === 'dark' ? 'light' : 'dark', true);
  };
  const navToggle = $('#nav-toggle');
  if (navToggle) navToggle.onclick = () => {
    const open = document.body.classList.toggle('nav-open');
    navToggle.setAttribute('aria-expanded', String(open));
  };
  const systemTheme = matchMedia('(prefers-color-scheme: light)');
  systemTheme.addEventListener('change', (e) => {
    let saved = null;
    try { saved = localStorage.getItem('veda-theme'); } catch (_) {}
    if (!saved) applyTheme(e.matches ? 'light' : 'dark', false);
  });
  $('#projpick').onchange = async (e) => {
    const previous = S.project;
    S.project = e.target.value || null;
    try {
      if (S.project) await activateCurrentProject(S.project);
    } catch (err) {
      S.project = previous;
      e.target.value = previous || '';
      return;
    }
    connectStream();
    syncAgentWatchdog();
    await refreshCounts();
    render();
  };
  $('#newproj').onclick = openNewProjectDialog;
  $('#delproj').onclick = openProjectDeleteDialog;
  $('#analyze').onclick = async () => {
    if (!S.project) return toast('Create a project first');
    await activateCurrentProject(S.project);
    await post('/projects/' + S.project + '/analyze');
    toast('Analysis started for the current project.', 'good');
    go('agent');
  };
  // A deep link the browser companion uses to send the operator straight into
  // project creation without needing a project to already exist.
  const consumeNewProjectHash = () => {
    if (location.hash.replace('#', '').split('/')[0] === 'new-project') {
      history.replaceState(null, '', location.pathname + location.search +
        (S.view ? '#' + S.view : ''));
      openNewProjectDialog();
      return true;
    }
    return false;
  };

  window.addEventListener('hashchange', () => {
    if (consumeNewProjectHash()) return;
    const [v, id] = location.hash.replace('#', '').split('/');
    if (v && v !== S.view) { S.view = v; S.params = id ? { id: id } : {};
                             renderRail(); syncAgentWatchdog(); render(); }
  });
  const [v, id] = location.hash.replace('#', '').split('/');
  if (v && v !== 'new-project') { S.view = v; S.params = id ? { id: id } : {}; }
  renderRail();
  await loadProjects();
  // loadProjects owns project selection and therefore the project-scoped stream.
  consumeNewProjectHash();
  refreshHealth();
  setInterval(refreshHealth, 30000);
  setInterval(tickThinking, 1000);
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/service-worker.js').catch(() => {});
  }
  window.addEventListener('focus', () => {
    if (S.project) { refreshCounts().then(() => render()); }
  });
  window.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') { closeProjectDeleteDialog(); closeNewProjectDialog(); }
  });
}
init();
window.S = S;
