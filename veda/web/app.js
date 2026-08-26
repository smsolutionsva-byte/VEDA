/* VEDA shell: state, routing, live event stream.
   Browsing never invokes the agent - every view reads persisted rows. */

const S = {
  project: null, projects: [], view: 'overview', params: {},
  counts: {}, health: null, es: null,
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
    ['overview', 'Overview'],
    ['eps', 'EPS'],
    ['wbs', 'WBS'],
  ]],
  ['Schedule', [
    ['activities', 'Activities', 'activities'],
    ['milestones', 'Milestones', 'milestones'],
    ['relationships', 'Relationships', 'relationships'],
    ['critical', 'Critical Path', 'critical'],
    ['quality', 'Schedule Quality', 'qa_failed'],
    ['baselines', 'Baselines'],
    ['resources', 'Resources', 'resources'],
    ['assignments', 'Assignments', 'assignments'],
    ['timephased', 'Timephased'],
    ['ev', 'Earned Value'],
  ]],
  ['Field', [
    ['issues', 'Issues', 'issues'],
    ['risks', 'Risks', 'risks'],
    ['evidence', 'Field Evidence', 'evidence'],
    ['review-evidence', 'Review Evidence', 'evidence_review'],
    ['observed', 'Observed Progress'],
  ]],
  ['Decide', [
    ['reviews', 'Human Review', 'pending_reviews'],
    ['proposals', 'Proposed Changes', 'pending_proposals'],
    ['ask', 'Ask VEDA'],
  ]],
  ['System', [
    ['agent', 'Agent Activity'],
    ['jobs', 'Job Status'],
    ['files', 'Files'],
    ['outputs', 'Outputs'],
    ['audit', 'Audit'],
    ['system', 'System / MCP'],
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
      const alert = (key === 'pending_reviews' || key === 'pending_proposals' ||
                     key === 'evidence_review') && n > 0;
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
      evidence_review: 0,
    });
    const ev = await api('/projects/' + S.project +
                         '/evidence?state=needs_review&limit=1');
    S.counts.evidence_review = ev.total;
    renderRail();
    const j = o.latest_job;
    const chip = $('#chip-job');
    const running = j && (j.status === 'running' || j.status === 'queued');
    chip.className = 'chip ' + (running ? 'busy'
      : (j && j.status === 'failed' ? 'bad' : (j ? 'ok' : '')));
    chip.querySelector('span').textContent = j
      ? (j.kind + ' · ' + j.status) : 'idle';
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
    ca.querySelector('span').textContent = (a.label || h.active_provider) +
      (a.ok ? '' : ' offline');
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
  S.project = selectId || (r.projects[0] && r.projects[0].id) || null;
  if (S.project) sel.value = S.project;
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

function bindNoProject() {
  const b = $('#createFirst');
  if (b) b.onclick = newProject;
}

/* --------------------------------------------------------- live stream */
function connectStream() {
  if (S.es) S.es.close();
  const es = new EventSource('/api/stream' +
    (S.project ? '?project_id=' + S.project : ''));
  S.es = es;
  let pending = null;
  es.onmessage = (m) => {
    let d; try { d = JSON.parse(m.data); } catch (e) { return; }
    if (!d.type) return;
    if (d.type === 'ui:activity' && S.view === 'agent') { render(); }
    // Coalesce bursts: the agent emits many steps in quick succession.
    clearTimeout(pending);
    pending = setTimeout(() => {
      refreshCounts();
      if (['overview', 'agent', 'jobs', 'reviews', 'proposals',
           'evidence'].includes(S.view)) render();
    }, 700);
  };
  es.onerror = () => { /* EventSource retries on its own */ };
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
  $('#projpick').onchange = (e) => {
    S.project = e.target.value || null;
    connectStream(); refreshCounts(); render();
  };
  $('#newproj').onclick = newProject;
  $('#analyze').onclick = async () => {
    if (!S.project) return toast('Create a project first');
    await post('/projects/' + S.project + '/analyze');
    toast('Analysis queued. The agent wakes on the event.', 'good');
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
  connectStream();
  refreshHealth();
  setInterval(refreshHealth, 30000);
}
init();
window.S = S;
