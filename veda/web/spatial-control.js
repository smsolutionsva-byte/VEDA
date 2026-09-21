import * as THREE from '/static/vendor/three/three.module.min.js?v=1.75';
import { OrbitControls } from '/static/vendor/three/OrbitControls.js?v=1.75';

let active = null;

const COLORS = {
  teal: 0x1aa58f, cyan: 0x5de8d7, steel: 0x607b83, dark: 0x102c2b,
  ground: 0xd8e3df, amber: 0xe2a63b, red: 0xd55a52, ghost: 0x42e6d1,
};

function disposeTree(root) {
  root.traverse(object => {
    if (object.geometry) object.geometry.dispose();
    if (object.material) {
      const materials = Array.isArray(object.material) ? object.material : [object.material];
      materials.forEach(material => material.dispose());
    }
  });
}

function mount(hostId, payload) {
  if (active) active.destroy();
  const host = document.getElementById(hostId);
  if (!host) return;

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x071514);
  scene.fog = new THREE.Fog(0x071514, 32, 78);
  const camera = new THREE.PerspectiveCamera(43, 1, 0.1, 180);
  camera.position.set(25, 19, 29);
  const renderer = new THREE.WebGLRenderer({antialias: true, powerPreference: 'high-performance'});
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.75));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFShadowMap;
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;
  host.replaceChildren(renderer.domElement);

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.06;
  controls.enableRotate = true;
  controls.enablePan = true;
  controls.screenSpacePanning = true;
  controls.minDistance = 12;
  controls.maxDistance = 62;
  controls.minPolarAngle = Math.PI * 0.06;
  controls.maxPolarAngle = Math.PI * 0.49;
  controls.mouseButtons.LEFT = THREE.MOUSE.ROTATE;
  controls.mouseButtons.MIDDLE = THREE.MOUSE.DOLLY;
  controls.mouseButtons.RIGHT = THREE.MOUSE.PAN;
  controls.touches.ONE = THREE.TOUCH.ROTATE;
  controls.touches.TWO = THREE.TOUCH.DOLLY_PAN;
  controls.target.set(0, 3.2, 0);

  scene.add(new THREE.HemisphereLight(0xbcece5, 0x18302e, 2.2));
  const sun = new THREE.DirectionalLight(0xffffff, 3.4);
  sun.position.set(18, 28, 12); sun.castShadow = true;
  sun.shadow.mapSize.set(1024, 1024); scene.add(sun);
  const rim = new THREE.PointLight(COLORS.cyan, 26, 38, 2);
  rim.position.set(-14, 8, -9); scene.add(rim);

  const groundMat = new THREE.MeshStandardMaterial({color: COLORS.ground, roughness: 0.92, metalness: 0.04});
  const ground = new THREE.Mesh(new THREE.PlaneGeometry(70, 46), groundMat);
  ground.rotation.x = -Math.PI / 2; ground.receiveShadow = true; scene.add(ground);
  const grid = new THREE.GridHelper(68, 34, 0x2f7770, 0x31514e);
  grid.position.y = 0.015; grid.material.opacity = 0.34; grid.material.transparent = true; scene.add(grid);

  const selectable = [], phased = [], flow = [];
  const sourceActivities = (payload.activities || []).filter(item => item && (item.start || item.finish));
  const toTime = value => {
    const parsed = value ? Date.parse(String(value).slice(0, 10) + 'T00:00:00Z') : NaN;
    return Number.isFinite(parsed) ? parsed : null;
  };
  const dated = sourceActivities.flatMap(item => [toTime(item.start), toTime(item.finish)]).filter(Number.isFinite);
  const rangeStart = toTime(payload.rangeStart) ?? (dated.length ? Math.min(...dated) : Date.now());
  const rangeFinish = Math.max(rangeStart + 86400000,
    toTime(payload.rangeFinish) ?? (dated.length ? Math.max(...dated) : rangeStart + 100 * 86400000));
  const rangeSpan = rangeFinish - rangeStart;
  const phaseAt = (value, fallback) => {
    const time = toTime(value);
    return time === null ? fallback : Math.max(0, Math.min(100, (time - rangeStart) * 100 / rangeSpan));
  };
  const standard = (color, extra = {}) => new THREE.MeshStandardMaterial({
    color, roughness: 0.34, metalness: 0.62, ...extra,
  });
  const box = (size, position, color, meta, phase = 0) => {
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(...size), standard(color));
    mesh.position.set(...position); mesh.castShadow = true; mesh.receiveShadow = true;
    mesh.userData = meta || {}; scene.add(mesh);
    if (meta) selectable.push(mesh);
    phased.push({object: mesh, startPhase: meta?.startPhase ?? phase, finishPhase: meta?.finishPhase ?? 100, meta});
    return mesh;
  };
  const pipe = (x, y, z, length, radius, color, meta, phase = 0, rotation = 0) => {
    const mesh = new THREE.Mesh(new THREE.CylinderGeometry(radius, radius, length, 24), standard(color));
    mesh.rotation.z = Math.PI / 2; mesh.rotation.y = rotation;
    mesh.position.set(x, y, z); mesh.castShadow = true; mesh.userData = meta || {};
    scene.add(mesh); selectable.push(mesh);
    phased.push({object: mesh, startPhase: meta?.startPhase ?? phase, finishPhase: meta?.finishPhase ?? 100, meta});
    return mesh;
  };
  const activity = (index, fallback) => {
    const source = (payload.activities || [])[index] || {};
    const startPhase = phaseAt(source.start || source.finish, Math.min(92, index * 8));
    const finishPhase = Math.max(startPhase, phaseAt(source.finish || source.start, Math.min(100, startPhase + 10)));
    return {
      kind: 'activity', uid: source.uid || '', title: source.name || fallback,
      status: source.readiness || (index === 1 ? 'Constrained' : index === 2 ? 'Planned' : 'Active workfront'),
      start: source.start || '', finish: source.finish || '', startPhase, finishPhase,
      detail: source.start && source.finish ? `${String(source.start).slice(0, 10)} → ${String(source.finish).slice(0, 10)}` :
        'Illustrative work package · connect a BIM identifier for exact model linkage',
    };
  };

  // Pipe rack structure.
  for (let x = -15; x <= 15; x += 6) {
    box([0.34, 6, 0.34], [x, 3, -5], COLORS.steel, null);
    box([0.34, 6, 0.34], [x, 3, 5], COLORS.steel, null);
    box([0.42, 0.32, 10.4], [x, 5.8, 0], COLORS.steel, null);
    box([0.42, 0.26, 10.4], [x, 3.2, 0], COLORS.steel, null);
  }
  const activityMetas = Array.from({length: Math.max(6, sourceActivities.length)}, (_, index) =>
    activity(index, `Work package ${index + 1}`));
  const metas = activityMetas.slice(0, 3);
  [-2.8, 0, 2.8].forEach((z, index) => {
    pipe(0, 6.55 - index * 0.72, z, 34, index === 0 ? 0.56 : 0.42,
      index === 1 ? COLORS.amber : index === 2 ? COLORS.steel : COLORS.teal, metas[index], metas[index].startPhase);
  });

  // Spool yard, equipment pads, trench and crane silhouette.
  for (let row = 0; row < 3; row++) for (let col = 0; col < 4; col++)
    pipe(-10 + col * 2.2, 0.55 + row * 0.42, 12 + row * 1.25, 1.7, 0.2,
      row === 2 ? COLORS.amber : COLORS.teal, activityMetas[3 + ((row * 4 + col) % Math.max(1, activityMetas.length - 3))], 15 + col * 7);
  box([8, 0.35, 6], [10, 0.18, 12], 0x81918d, activityMetas[4], activityMetas[4].startPhase);
  box([4.2, 3.4, 4.2], [10, 1.9, 12], 0x355f5b, activityMetas[4], activityMetas[4].startPhase);
  box([22, 0.22, 4.2], [-4, -0.05, -13], 0x274c49, activityMetas[5], activityMetas[5].startPhase);
  box([0.55, 12, 0.55], [-18, 6, 10], COLORS.amber, null);
  box([10, 0.35, 0.35], [-13, 11.3, 10], COLORS.amber, null);
  box([0.15, 8, 0.15], [-8.2, 7.5, 10], COLORS.amber, null);

  // Holographic proposed route.
  const ghost = new THREE.Group();
  const ghostMat = standard(COLORS.ghost, {transparent: true, opacity: 0.24, emissive: COLORS.ghost, emissiveIntensity: 0.8});
  const ghostPipe = new THREE.Mesh(new THREE.CylinderGeometry(0.48, 0.48, 34, 18), ghostMat);
  ghostPipe.rotation.z = Math.PI / 2; ghostPipe.position.set(0, 8.2, -1.1); ghost.add(ghostPipe);
  const ghostLeg = new THREE.Mesh(new THREE.CylinderGeometry(0.48, 0.48, 10, 18), ghostMat);
  ghostLeg.position.set(15.5, 3.4, -1.1); ghost.add(ghostLeg); ghost.visible = false; scene.add(ghost);

  // Flow markers add readable motion without heavy post-processing.
  for (let i = 0; i < 12; i++) {
    const bead = new THREE.Mesh(new THREE.SphereGeometry(0.12, 10, 10),
      new THREE.MeshBasicMaterial({color: COLORS.cyan}));
    bead.position.set(-16 + i * 2.8, 6.55, -2.8); bead.userData.offset = i / 12; scene.add(bead); flow.push(bead);
  }

  const raycaster = new THREE.Raycaster(), pointer = new THREE.Vector2();
  let selected = null, mode = 'site', phase = 100, raf = 0, running = true;
  const inspector = document.getElementById('spatial-inspector');
  const phaseLabel = document.getElementById('spatial-phase-label');
  const setInspector = meta => {
    if (!inspector) return;
    inspector.innerHTML = meta ? `<span>SELECTED WORK PACKAGE</span><b>${escapeHtml(meta.title)}</b>` +
      `<small>${escapeHtml(meta.detail)}</small><div><em>${escapeHtml(meta.status)}</em>` +
      (meta.uid ? `<button type="button" data-spatial-activity="${escapeHtml(meta.uid)}">Open activity →</button>` : '') + '</div>'
      : '<span>SPATIAL INSPECTOR</span><b>Select a pipe, spool or work zone</b><small>Drag to orbit · scroll to zoom · tap an object to inspect</small>';
    const open = inspector.querySelector('[data-spatial-activity]');
    if (open) open.onclick = () => window.go && window.go('activity', {id: Number(open.dataset.spatialActivity)});
  };
  const escapeHtml = value => String(value || '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  setInspector(null);

  renderer.domElement.addEventListener('pointerup', event => {
    const rect = renderer.domElement.getBoundingClientRect();
    pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
    raycaster.setFromCamera(pointer, camera);
    const hit = raycaster.intersectObjects(selectable, false)[0];
    if (!hit) return;
    if (selected && selected.material && selected.userData.baseEmissive !== undefined)
      selected.material.emissive.setHex(selected.userData.baseEmissive);
    selected = hit.object;
    selected.userData.baseEmissive = selected.material.emissive.getHex();
    selected.material.emissive.setHex(COLORS.cyan);
    selected.material.emissiveIntensity = 0.55;
    setInspector(selected.userData);
  });

  const setMode = next => {
    mode = next; ghost.visible = mode === 'scenario';
    document.querySelectorAll('[data-spatial-mode]').forEach(button =>
      button.classList.toggle('on', button.dataset.spatialMode === mode));
    if (mode === 'workfront') { camera.position.set(16, 10, 18); controls.target.set(0, 5, 0); }
    else if (mode === 'scenario') { camera.position.set(27, 17, 27); controls.target.set(2, 4, 0); }
    else { camera.position.set(25, 19, 29); controls.target.set(0, 3.2, 0); }
  };
  document.querySelectorAll('[data-spatial-mode]').forEach(button => button.onclick = () => setMode(button.dataset.spatialMode));
  const setCamera = view => {
    if (view === 'top') { camera.position.set(0.01, 43, 0.01); controls.target.set(0, 0, 0); }
    else if (view === 'ground') { camera.position.set(25, 4.8, 24); controls.target.set(0, 3.2, 0); }
    else { camera.position.set(25, 19, 29); controls.target.set(0, 3.2, 0); }
    controls.update();
    document.querySelectorAll('[data-spatial-camera]').forEach(button =>
      button.classList.toggle('on', button.dataset.spatialCamera === view));
  };
  document.querySelectorAll('[data-spatial-camera]').forEach(button =>
    button.onclick = () => setCamera(button.dataset.spatialCamera));
  setCamera('orbit');
  const slider = document.getElementById('spatial-phase');
  const play = document.getElementById('spatial-play');
  const sourceNote = document.getElementById('spatial-source-note');
  let playTimer = 0;
  const displayDate = value => new Date(rangeStart + rangeSpan * value / 100).toISOString().slice(0, 10);
  const setPhase = value => {
    phase = Math.max(0, Math.min(100, Number(value) || 0));
    const activeCount = sourceActivities.filter((item, index) => {
      const start = phaseAt(item.start || item.finish, Math.min(92, index * 8));
      const finish = Math.max(start, phaseAt(item.finish || item.start, Math.min(100, start + 10)));
      return start <= phase && finish >= phase;
    }).length;
    phased.forEach(item => { item.object.visible = item.startPhase <= phase; });
    if (phaseLabel) phaseLabel.textContent = `${displayDate(phase)} · ${activeCount} active`;
    if (slider) slider.value = String(phase);
  };
  const stopPlayback = () => {
    if (playTimer) clearInterval(playTimer); playTimer = 0;
    if (play) play.textContent = '▶ Play';
  };
  if (slider) slider.oninput = () => { stopPlayback(); setPhase(slider.value); };
  if (play) play.onclick = () => {
    if (playTimer) { stopPlayback(); return; }
    if (phase >= 100) setPhase(0);
    play.textContent = 'Ⅱ Pause';
    playTimer = setInterval(() => {
      if (phase >= 100) { stopPlayback(); return; }
      setPhase(Math.min(100, phase + 1));
    }, 110);
  };
  if (sourceNote) sourceNote.textContent = sourceActivities.length
    ? `${sourceActivities.length} dated activities · ${displayDate(0)} → ${displayDate(100)}. Geometry is representative${payload.bimCount ? `; ${payload.bimCount} BIM identifiers are linked for future exact model selection.` : ' until a model and exact BIM identifiers are linked.'}`
    : 'No dated activities are available, so this scene remains an illustrative workfront layout.';
  setPhase(100);

  const resize = () => {
    const width = Math.max(1, host.clientWidth), height = Math.max(1, host.clientHeight);
    renderer.setSize(width, height, false); camera.aspect = width / height; camera.updateProjectionMatrix();
  };
  const observer = new ResizeObserver(resize); observer.observe(host); resize();
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const startedAt = performance.now();
  const animate = () => {
    if (!running || !host.isConnected) { destroy(); return; }
    const t = (performance.now() - startedAt) / 1000;
    if (!reduced) flow.forEach((bead, index) => { bead.position.x = -16 + ((t * 2.6 + index * 2.8) % 32); });
    if (selected && selected.material) selected.material.emissiveIntensity = 0.42 + Math.sin(t * 3) * 0.14;
    ghostMat.opacity = mode === 'scenario' ? 0.2 + Math.sin(t * 2) * 0.06 : 0.24;
    controls.update(); renderer.render(scene, camera); raf = requestAnimationFrame(animate);
  };
  const destroy = () => {
    if (!running) return; running = false; stopPlayback(); cancelAnimationFrame(raf); observer.disconnect();
    controls.dispose(); disposeTree(scene); renderer.dispose(); if (active && active.destroy === destroy) active = null;
  };
  active = {destroy}; animate();
}

window.SpatialControl = {mount};
window.addEventListener('veda:spatial-mount', event =>
  mount((event.detail && event.detail.hostId) || 'veda-spatial-canvas', (event.detail && event.detail.payload) || {}));
if (window.__vedaSpatialPending) {
  mount(window.__vedaSpatialPending.hostId || 'veda-spatial-canvas', window.__vedaSpatialPending.payload || {});
  window.__vedaSpatialPending = null;
}
