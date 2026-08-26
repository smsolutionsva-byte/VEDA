/* VEDA shell: state, routing, live event stream.
   Browsing never invokes the agent - every view reads persisted rows. */

const S = {
  project: null, projects: [], view: 'overview', params: {},
  counts: {}, health: null, es: null, streamProject: null, overview: null,
};

const $ = (s, r) => (r || document).querySelector(s);
const api = async (path, opts) => {
  const r = await fetch('/api' + path, opts);
  if (!r.ok) {
    let msg = r.status + ' ' + r.statusText;
    try { const j = await r.json(); msg = j.detail || msg; } catch (e) {}
    throw new Error(msg);
  }
  return r.json();
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
  ['Project', [
    ['overview', 'Overview'], ['eps', 'EPS'], ['wbs', 'WBS'],
  ]],
  ['Schedule', [
    ['activities', 'Activities', 'activities'], ['milestones', 'Milestones', 'milestones'],
    ['relationships', 'Relationships', 'relationships'], ['critical', 'Critical Path', 'critical'],
    ['quality', 'Schedule QA', 'qa_failed'], ['baselines', 'Baselines'],
    ['resources', 'Resources', 'resources'], ['assignments', 'Assignments', 'assignments'],
    ['timephased', 'Timephased'], ['ev', 'Earned Value'],
  ]],
  ['Field', [
    ['issues', 'Issues', 'issues'], ['risks', 'Risks', 'risks'],
    ['evidence', 'Field Evidence', 'evidence'], ['observed', 'Observed Progress'],
  ]],
  ['Act', [
    ['attention', 'Needs Attention', 'attention'], ['ask', 'Ask VEDA'],
  ]],
  ['Project Data', [
    ['files', 'Files'], ['outputs', 'Outputs'], ['audit', 'Audit'], ['system', 'System / MCP'],
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
  location.hash = view + (params && params.id ? '/' + params.id : '');
  renderRail(); render();
}
window.go = go;

/* ------------------------------------------------------------ render */
async function render() {
  const main = $('#main');
  if (!S.project) {
    main.innerHTML = VIEWS.noproject();
    bindNoProject();
    return;
  }
  const fn = VIEWS[S.view] || VIEWS.overview;
  main.innerHTML = '<div class="empty">Loading…</div>';
  try {
    main.innerHTML = await fn(S.project, S.params);
    if (VIEWS['bind_' + S.view]) VIEWS['bind_' + S.view](S.project, S.params);
  } catch (e) {
    main.innerHTML = '<div class="panel"><div class="body">' +
      '<div class="note danger"><b>Could not load this view.</b><br>' +
      esc(e.message) + '</div></div></div>';
  }
}
window.render = render;

/* ------------------------------------------------------------ header */
async function refreshCounts() {
  if (!S.project) return;
  try {
    const o = await api('/projects/' + S.project + '/overview');
    S.overview = o;
    S.counts = Object.assign({}, o.counts, {
      qa_failed: o.quality.failed,
      attention: Number(o.counts.pending_reviews || 0) + Number(o.counts.pending_proposals || 0) + ((Number(o.counts.unresolved_evidence || 0) > 0 && Number(o.counts.pending_reviews || 0) === 0) ? 1 : 0),
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
  S.project = nextProject;
  if (S.project) sel.value = S.project;
  if (changed && S.project) await activateCurrentProject(S.project);
  if (changed) connectStream();
  await refreshCounts();
  render();
}

async function newProject() {
  const name = prompt('Project name');
  if (!name) return;
  const r = await post('/projects', { name: name });
  toast('Project created. Upload a schedule and project files to begin.', 'good');
  await loadProjects(r.id);
  go('files');
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

function bindNoProject() {
  const b = $('#createFirst');
  if (b) b.onclick = newProject;
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
      go('overview');
      return;
    }
    if (['overview', 'attention', 'ask', 'evidence', 'outputs', 'observed', 'quality', 'activities'].includes(S.view)) {
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
  es.onerror = () => { /* EventSource retries; onopen performs state catch-up. */ };
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
    await refreshCounts();
    render();
  };
  $('#newproj').onclick = newProject;
  $('#delproj').onclick = openProjectDeleteDialog;
  $('#analyze').onclick = async () => {
    if (!S.project) return toast('Create a project first');
    await activateCurrentProject(S.project);
    await post('/projects/' + S.project + '/analyze');
    toast('Analysis started for the current project.', 'good');
    go('agent');
  };
  window.addEventListener('hashchange', () => {
    const [v, id] = location.hash.replace('#', '').split('/');
    if (v && v !== S.view) { S.view = v; S.params = id ? { id: id } : {};
                             renderRail(); render(); }
  });
  const [v, id] = location.hash.replace('#', '').split('/');
  if (v) { S.view = v; S.params = id ? { id: id } : {}; }
  renderRail();
  await loadProjects();
  // loadProjects owns project selection and therefore the project-scoped stream.
  refreshHealth();
  setInterval(refreshHealth, 30000);
  window.addEventListener('focus', () => {
    if (S.project) { refreshCounts().then(() => render()); }
  });
  window.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeProjectDeleteDialog();
  });
}
init();
window.S = S;
