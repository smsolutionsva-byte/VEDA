/* Mobile capture controller: durable media + confirmed text + offline outbox. */
(() => {
  const DB = 'veda-field-sync';
  const STORE = 'outbox';
  const state = { files: [], recording: null, chunks: [], recognition: null,
    activity: null, coordinates: null, transcriptDirty: false, timer: null,
    extracted: false, projectId: null, voiceCaptured: false,
    voiceUnavailable: false,
    recognitionError: null, audioDeviceId: '', audioDevices: [],
    deviceChangeBound: false, cctvFeed: 'yard', cctvObservation: 'handling' };

  const CCTV_FEEDS = {
    yard: {src: '/static/staticcams/CCTV_2.mp4', label: 'Pipe laydown yard · CAM-03',
      tracks: '/static/staticcams/detections/CCTV_2.json',
      defaultObservation: 'handling', observations: {
        inventory: {seconds: 5, time: '00:05', label: 'Pipe stock visible', detail: 'Material context · no progress claim',
          activityId: 'PIP-SP1-2002', activityName: 'Stringing 16" API 5L Gr X52', progress: null,
          confidence: 96, note: 'Pipe stock is visible in the laydown yard; record this as material context unless installed quantity is verified.'},
        handling: {seconds: 53, time: '00:53', label: 'Stringing preparation', detail: 'PIP-SP1-2002 · 41% estimate',
          activityId: 'PIP-SP1-2002', activityName: 'Stringing 16" API 5L Gr X52', progress: 41,
          confidence: 91, note: 'Pipe stock and an active handling workfront are visible; verify chainage and installed quantity.'},
        workfront: {seconds: 95, time: '01:35', label: 'Active laydown workfront', detail: 'Worker + pipe context',
          activityId: 'PIP-SP1-2002', activityName: 'Stringing 16" API 5L Gr X52', progress: 41,
          confidence: 86, note: 'Worker movement and pipe handling are visible; retain the existing estimate until quantity is confirmed.'},
      }},
    drilling: {src: '/static/staticcams/CCTV_1.mp4', label: 'Drilling operations · CAM-01',
      tracks: '/static/staticcams/detections/CCTV_1.json',
      defaultObservation: 'handling', observations: {
        inventory: {seconds: 5, time: '00:05', label: 'Rig setup visible', detail: 'Equipment context · 89%',
          activityId: 'CIV-DUL-1005', activityName: 'Pump Foundation Piling', progress: 18,
          confidence: 89, note: 'Rotary drilling equipment is set up; verify pile number and boring-start record.'},
        handling: {seconds: 151, time: '02:31', label: 'Active drilling cycle', detail: 'CIV-DUL-1005 · 54% estimate',
          activityId: 'CIV-DUL-1005', activityName: 'Pump Foundation Piling', progress: 54,
          confidence: 93, note: 'A rotary drilling cycle and field crew are visible; verify bore depth and accepted pile count.'},
        workfront: {seconds: 250, time: '04:10', label: 'Drilling workfront review', detail: 'Rig + crew context',
          activityId: 'CIV-DUL-1005', activityName: 'Pump Foundation Piling', progress: 54,
          confidence: 85, note: 'The rig remains active; retain the estimate until the piling log confirms completed depth.'},
      }},
  };
  let cctvTracker = null;
  let cctvAiEnabled = true;
  const cctvWarnedEvents = new Set();

  const el = (id) => document.getElementById(id);
  const escapeHtml = (value) => window.esc(value);
  const clientId = () => 'fc_' + (crypto.randomUUID ? crypto.randomUUID() :
    Date.now().toString(36) + Math.random().toString(36).slice(2));

  function openDb() {
    return new Promise((resolve, reject) => {
      const request = indexedDB.open(DB, 1);
      request.onupgradeneeded = () => {
        if (!request.result.objectStoreNames.contains(STORE)) {
          request.result.createObjectStore(STORE, {keyPath: 'id'});
        }
      };
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
  }

  async function allQueued() {
    const db = await openDb();
    return new Promise((resolve, reject) => {
      const request = db.transaction(STORE).objectStore(STORE).getAll();
      request.onsuccess = () => resolve(request.result || []);
      request.onerror = () => reject(request.error);
    });
  }

  async function queue(item) {
    const db = await openDb();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE, 'readwrite');
      tx.objectStore(STORE).put(item);
      tx.oncomplete = resolve;
      tx.onerror = () => reject(tx.error);
    });
  }

  async function remove(id) {
    const db = await openDb();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE, 'readwrite');
      tx.objectStore(STORE).delete(id);
      tx.oncomplete = resolve;
      tx.onerror = () => reject(tx.error);
    });
  }

  function formFor(item) {
    const form = new FormData();
    form.append('payload', JSON.stringify(item.payload));
    for (const file of item.attachments || []) {
      form.append('files', file.blob, file.name || 'field-media');
    }
    return form;
  }

  async function send(item) {
    const response = await fetch('/api/projects/' + encodeURIComponent(item.projectId) +
      '/field-captures', {method: 'POST', body: formFor(item)});
    if (!response.ok) {
      let message = 'Capture could not be saved';
      try { message = (await response.json()).detail || message; } catch (_) {}
      const error = new Error(message); error.permanent = response.status < 500;
      throw error;
    }
    return response.json();
  }

  async function flush(projectId) {
    if (!navigator.onLine) return;
    for (const item of (await allQueued()).filter(x => !projectId || x.projectId === projectId)) {
      try { await send({...item, payload: {...item.payload, sync_source: 'offline_outbox'}}); await remove(item.id); }
      catch (error) { if (!error.permanent) break; }
    }
    await updateOutbox(projectId);
  }

  async function updateOutbox(projectId) {
    const items = (await allQueued()).filter(x => !projectId || x.projectId === projectId);
    const count = el('capture-outbox-count');
    if (count) count.textContent = String(items.length);
    const status = el('capture-connectivity');
    if (status) {
      status.className = 'capture-connectivity ' + (navigator.onLine ? 'online' : 'offline');
      status.textContent = navigator.onLine ? (items.length ? 'Online · syncing ' + items.length : 'Online · synced')
        : 'Offline · ' + items.length + ' saved on device';
    }
  }

  function drawFiles() {
    const tray = el('capture-media-tray');
    if (!tray) return;
    tray.innerHTML = state.files.length ? state.files.map((file, index) =>
      '<div class="capture-media-item"><span>' + escapeHtml(file.name) +
      '</span><small>' + Math.max(1, Math.round(file.blob.size / 1024)) +
      ' KB</small><button type="button" data-capture-remove="' + index +
      '" aria-label="Remove ' + escapeHtml(file.name) + '">×</button></div>').join('') :
      '<div class="capture-media-empty">Voice recordings, photos and site videos will appear here.</div>';
    tray.querySelectorAll('[data-capture-remove]').forEach(button => button.onclick = () => {
      state.files.splice(Number(button.dataset.captureRemove), 1); drawFiles();
    });
  }

  function setMicrophoneStatus(message, tone) {
    const status = el('capture-mic-status');
    if (!status) return;
    status.className = 'capture-mic-status' + (tone ? ' ' + tone : '');
    status.textContent = message;
  }

  function renderMicrophoneOptions(devices) {
    const select = el('capture-microphone');
    if (!select) return;
    const selected = state.audioDeviceId || select.value || '';
    const options = ['<option value="">Default microphone</option>'];
    devices.forEach((device, index) => {
      const label = device.label || ('Microphone ' + (index + 1));
      options.push('<option value="' + escapeHtml(device.deviceId) + '"' +
        (device.deviceId === selected ? ' selected' : '') + '>' +
        escapeHtml(label) + '</option>');
    });
    select.innerHTML = options.join('');
    if (selected && devices.some(device => device.deviceId === selected)) {
      select.value = selected; state.audioDeviceId = selected;
    } else {
      select.value = ''; state.audioDeviceId = '';
    }
  }

  async function enumerateMicrophones(requestPermission) {
    if (!navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) {
      setMicrophoneStatus('This browser cannot list microphone inputs.', 'warn');
      return [];
    }
    const refresh = el('capture-mic-refresh');
    if (refresh) { refresh.disabled = true; refresh.textContent = 'Finding…'; }
    try {
      if (requestPermission) {
        const probe = await navigator.mediaDevices.getUserMedia({audio: true});
        probe.getTracks().forEach(track => track.stop());
      }
      const devices = (await navigator.mediaDevices.enumerateDevices())
        .filter(device => device.kind === 'audioinput');
      state.audioDevices = devices;
      renderMicrophoneOptions(devices);
      const named = devices.filter(device => device.label).length;
      setMicrophoneStatus(devices.length
        ? (named ? devices.length + ' microphone input(s) available.'
          : 'Microphone inputs found. Allow access to show their names.')
        : 'No microphone input is available to this browser.', devices.length ? '' : 'warn');
      return devices;
    } catch (error) {
      const denied = error && (error.name === 'NotAllowedError' || error.name === 'SecurityError');
      setMicrophoneStatus(denied
        ? 'Microphone permission was denied. Allow it in the browser/site settings.'
        : 'Could not list microphone inputs. Try the default microphone.', 'warn');
      if (denied) markVoiceUnavailable(
        'Microphone permission was denied. Allow microphone access or type the update below.');
      return [];
    } finally {
      if (refresh) { refresh.disabled = false; refresh.textContent = 'Find microphones'; }
    }
  }

  function addInputFiles(files) {
    for (const file of Array.from(files || [])) {
      state.files.push({name: file.name, type: file.type, blob: file});
    }
    drawFiles();
  }

  function isWorkerWorkspace() {
    return Boolean(window.vedaRole && window.vedaRole() === 'worker');
  }

  function saveButtonLabel() {
    return isWorkerWorkspace() ? 'Submit to Project Controls' : 'Confirm & save update';
  }

  function announceFieldHandoff(projectId, capture) {
    try {
      const channel = new BroadcastChannel('veda-field-handoff');
      channel.postMessage({type: 'field-capture-created', projectId,
        captureId: capture && capture.id, at: Date.now()});
      channel.close();
    } catch (_) { /* Same-page role switching still reads the durable record. */ }
  }

  function eventState() {
    return (document.querySelector('[name="capture-event"]:checked') || {}).value || 'progress';
  }

  function updateEventFields() {
    const value = eventState();
    document.querySelectorAll('.capture-event-option').forEach(option =>
      option.classList.toggle('selected', option.querySelector('input').checked));
    if (el('capture-progress-fields')) el('capture-progress-fields').hidden = value !== 'progress';
    if (el('capture-finish-rule')) el('capture-finish-rule').hidden = value !== 'finish';
  }

  function paintVoiceButton(recording) {
    const button = el('capture-voice');
    if (!button) return;
    button.classList.toggle('recording', Boolean(recording));
    button.setAttribute('aria-pressed', String(Boolean(recording)));
    button.innerHTML = recording
      ? '<i>■</i><b>Stop recording</b><small>Draft transcript is updating</small>'
      : '<i>●</i><b>Record voice</b><small>Audio is kept as evidence</small>';
  }

  function sendCctvCommand(func, args) {
    const player = el('capture-cctv-player');
    if (!player) return;
    if (func === 'seekTo') {
      const seconds = Number((args || [])[0]);
      const seek = () => {
        if (Number.isFinite(seconds) && Number.isFinite(player.duration))
          player.currentTime = Math.min(seconds, Math.max(0, player.duration - .25));
      };
      if (player.readyState >= 1) seek();
      else player.addEventListener('loadedmetadata', seek, {once: true});
    }
    if (func === 'pauseVideo') player.pause();
  }

  function autoplayCctv(video, seconds) {
    if (!video) return;
    video.muted = true;
    const start = () => {
      if (Number.isFinite(seconds) && Number.isFinite(video.duration) && video.duration > 0)
        video.currentTime = Math.min(seconds, Math.max(0, video.duration - .25));
      const attempt = video.play();
      if (attempt && attempt.catch) attempt.catch(() => {
        /* Browser autoplay settings may still require one user gesture. */
      });
    };
    if (video.readyState >= 1) start();
    else video.addEventListener('loadedmetadata', start, {once: true});
  }

  function jumpToCctvFrame() {
    const feed = CCTV_FEEDS[state.cctvFeed] || CCTV_FEEDS.yard;
    const observation = feed.observations[state.cctvObservation] ||
      feed.observations[feed.defaultObservation];
    sendCctvCommand('seekTo', [observation.seconds, true]);
    window.setTimeout(() => sendCctvCommand('pauseVideo'), 350);
  }

  function renderCctvObservation(key, shouldJump) {
    const feed = CCTV_FEEDS[state.cctvFeed] || CCTV_FEEDS.yard;
    const observation = feed.observations[key] || feed.observations[feed.defaultObservation];
    state.cctvObservation = key in feed.observations ? key : feed.defaultObservation;
    if (el('capture-cctv-time')) el('capture-cctv-time').textContent = 'Frame ' + observation.time;
    if (el('capture-cctv-activity-id')) el('capture-cctv-activity-id').value = observation.activityId;
    if (el('capture-cctv-activity-name')) el('capture-cctv-activity-name').value = observation.activityName;
    if (el('capture-cctv-progress')) el('capture-cctv-progress').value = observation.progress;
    if (el('capture-cctv-confidence')) el('capture-cctv-confidence').textContent = 'Checking model tracks at this frame…';
    if (el('capture-cctv-note')) el('capture-cctv-note').value = observation.note;
    document.querySelectorAll('[data-cctv-observation]').forEach(button =>
      button.classList.toggle('selected', button.dataset.cctvObservation === state.cctvObservation));
    if (shouldJump) jumpToCctvFrame();
  }

  function setCctvMode(mode) {
    const ai = mode !== 'raw';
    cctvAiEnabled = ai;
    if (el('capture-cctv-boxes')) el('capture-cctv-boxes').hidden = !ai;
    if (cctvTracker) cctvTracker.setVisible(ai);
    document.querySelectorAll('[data-capture-cctv-mode]').forEach(button =>
      button.classList.toggle('selected', button.dataset.captureCctvMode === (ai ? 'ai' : 'raw')));
    const status = document.querySelector('.cctv-feed-meta > span');
    if (status) status.innerHTML = ai ? '<i></i> AI TRACKING' : '<i></i> RAW CCTV';
  }

  function bindCctvTracker(feed, player) {
    if (cctvTracker) cctvTracker.destroy();
    const layer = el('capture-cctv-boxes');
    layer.innerHTML = '<i class="vision-scan-line"></i>';
    if (!window.VisionTracks) return;
    cctvTracker = window.VisionTracks.bind({video: player, layer, dataUrl: feed.tracks,
      visible: cctvAiEnabled,
      onUpdate: (detections, payload, activeEvents) => {
        const preferred = detections.slice().sort((a, b) =>
          (a.class === 'suspended-load' ? -2 : a.class === 'worker' ? -1 : 0) -
          (b.class === 'suspended-load' ? -2 : b.class === 'worker' ? -1 : 0) ||
          b.confidence - a.confidence)[0];
        if (el('capture-cctv-confidence')) el('capture-cctv-confidence').textContent = preferred
          ? (preferred.review_required ? 'REVIEW · ' : '') +
            Math.round(preferred.confidence * 100) + '% · ' + preferred.label + ' #' + preferred.id
          : 'No supported object at this frame';
        if ((activeEvents || []).length && !cctvWarnedEvents.has(activeEvents[0].id)) {
          cctvWarnedEvents.add(activeEvents[0].id);
          window.toast('Potential safety event in this clip — pause and review the highlighted moment.', 'bad');
        }
      }});
    cctvTracker.ready.catch(() => {
      if (el('capture-cctv-confidence'))
        el('capture-cctv-confidence').textContent = 'Model tracks unavailable';
    });
  }

  function renderCctvFeed(key) {
    const feed = CCTV_FEEDS[key] || CCTV_FEEDS.yard;
    state.cctvFeed = key in CCTV_FEEDS ? key : 'yard';
    state.cctvObservation = feed.defaultObservation;
    const player = el('capture-cctv-player');
    player.pause(); player.muted = true; player.src = feed.src; player.load();
    el('capture-cctv-camera-label').textContent = feed.label;
    el('capture-cctv-download').href = feed.src;
    bindCctvTracker(feed, player);
    document.querySelectorAll('[data-cctv-observation]').forEach(button => {
      const observation = feed.observations[button.dataset.cctvObservation];
      if (!observation) return;
      button.innerHTML = '<time>' + escapeHtml(observation.time) + '</time><span><b>' +
        escapeHtml(observation.label) + '</b><small>' + escapeHtml(observation.detail) +
        '</small></span><i>REVIEW</i>';
    });
    renderCctvObservation(feed.defaultObservation, false);
    autoplayCctv(player, feed.observations[feed.defaultObservation].seconds);
    setCctvMode('ai');
  }

  function openCctvReview() {
    const panel = el('capture-cctv-panel');
    const button = el('capture-cctv');
    const player = el('capture-cctv-player');
    if (!panel || !player) return;
    panel.hidden = false;
    if (button) button.setAttribute('aria-expanded', 'true');
    renderCctvObservation(state.cctvObservation, false);
    autoplayCctv(player, player.currentTime || 0);
    panel.scrollIntoView({behavior: 'smooth', block: 'nearest'});
  }

  function closeCctvReview() {
    sendCctvCommand('pauseVideo');
    const panel = el('capture-cctv-panel');
    if (panel) panel.hidden = true;
    if (el('capture-cctv')) el('capture-cctv').setAttribute('aria-expanded', 'false');
  }

  async function useCctvObservation(projectId) {
    const activityId = el('capture-cctv-activity-id').value.trim();
    const activityName = el('capture-cctv-activity-name').value.trim();
    const progressValue = el('capture-cctv-progress').value.trim();
    const progress = progressValue === '' ? null : Number(progressValue);
    const note = el('capture-cctv-note').value.trim();
    const feed = CCTV_FEEDS[state.cctvFeed] || CCTV_FEEDS.yard;
    const camera = feed.label;
    const observation = feed.observations[state.cctvObservation] ||
      feed.observations[feed.defaultObservation];
    if (!activityId || !activityName) return window.toast('Review the activity ID and description first', 'bad');
    if (progress === null)
      return window.toast('This frame is context only. Add a verified progress value before creating an activity update.', 'bad');
    if (!Number.isFinite(progress) || progress < 0 || progress > 100)
      return window.toast('Visual progress must be between 0 and 100%', 'bad');

    const button = el('capture-cctv-use');
    button.disabled = true; button.textContent = 'Preparing editable draft…';
    const transcript = 'CCTV review (' + camera + ', recorded frame ' + observation.time + '): ' +
      activityId + ' ' + activityName + ' visual progress is estimated at ' + progress + '%. Work remains. ' +
      (note ? note + ' ' : '') +
      'Local CCTV observation; human verification required.';
    state.transcriptDirty = false;
    state.voiceCaptured = false;
    setTranscript(transcript,
      'CCTV review draft · local recorded footage ' + feed.src.split('/').pop() +
      ' · reviewer confirmation required.', false);
    el('capture-confirmed').value = transcript;
    el('capture-location-label').value = camera;
    const progressRadio = document.querySelector('[name="capture-event"][value="progress"]');
    if (progressRadio) progressRadio.checked = true;
    updateEventFields();
    try {
      await interpretEvent(projectId);
      if (progressRadio) progressRadio.checked = true;
      el('capture-progress').value = String(progress);
      updateEventFields();
      const response = await window.api('/projects/' + projectId + '/activities?q=' +
        encodeURIComponent(activityId) + '&milestone=0&limit=8');
      const exact = (response.activities || []).find(activity =>
        String(activity.display_id || '').toLowerCase() === activityId.toLowerCase());
      if (exact) selectActivity(exact);
      closeCctvReview();
      el('capture-structured-card').scrollIntoView({behavior: 'smooth', block: 'start'});
      window.toast('CCTV observation prepared. Review every field, then confirm to save.', 'good');
    } catch (error) {
      window.toast('Could not prepare the CCTV draft: ' + error.message, 'bad');
    } finally {
      button.disabled = false; button.textContent = 'Review & save field data';
    }
  }

  async function consumeVisualCaptureDraft(projectId) {
    let draft = null;
    try { draft = JSON.parse(localStorage.getItem('veda-visual-capture-draft') || 'null'); }
    catch (_) {}
    if (!draft || String(draft.projectId || '') !== String(projectId) || !draft.text) return;
    try { localStorage.removeItem('veda-visual-capture-draft'); } catch (_) {}
    state.transcriptDirty = false;
    state.voiceCaptured = false;
    setTranscript(String(draft.text), String(draft.source || 'Visual evidence review') +
      (draft.mediaName ? ' · source ' + String(draft.mediaName) : '') +
      ' · reviewer confirmation required.', false);
    el('capture-confirmed').value = String(draft.text);
    if (draft.location) el('capture-location-label').value = String(draft.location);
    const progress = Number(draft.progress);
    const progressRadio = document.querySelector('[name="capture-event"][value="progress"]');
    if (progressRadio) progressRadio.checked = true;
    updateEventFields();
    await interpretEvent(projectId);
    if (progressRadio) progressRadio.checked = true;
    if (Number.isFinite(progress) && progress >= 0 && progress <= 100)
      el('capture-progress').value = String(progress);
    updateEventFields();
    if (draft.activityId) {
      const response = await window.api('/projects/' + projectId + '/activities?q=' +
        encodeURIComponent(String(draft.activityId)) + '&milestone=0&limit=8');
      const exact = (response.activities || []).find(activity =>
        String(activity.display_id || '').toLowerCase() === String(draft.activityId).toLowerCase());
      if (exact) selectActivity(exact);
    }
    window.toast('Visual observation prepared. Review it before saving any schedule proposal.', 'good');
    el('capture-structured-card').scrollIntoView({behavior: 'smooth', block: 'start'});
  }

  function updateTranscriptState(extracted) {
    const original = el('capture-original');
    const confirmed = el('capture-confirmed');
    const status = el('capture-transcript-state');
    const note = el('capture-correction-note');
    if (!original || !confirmed) return;
    const raw = original.value.trim();
    const corrected = confirmed.value.trim();
    const changed = Boolean(raw && corrected && raw !== corrected);
    if (status) {
      const emptyLabel = state.voiceCaptured ? 'Voice captured · transcript needed' :
        state.voiceUnavailable ? 'Voice unavailable · type or attach audio' :
          'Waiting for an observation';
      status.className = 'capture-transcript-state ' + (!raw ?
        (state.voiceCaptured ? 'ready' : state.voiceUnavailable ? 'unavailable' : 'empty') :
          changed ? 'corrected' : 'ready');
      status.innerHTML = '<i></i><span>' + (!raw ? emptyLabel : changed
        ? 'Transcript corrected by reporter' : 'Transcript ready for review') + '</span>';
    }
    if (note) note.textContent = !corrected ? 'Confirm the words VEDA should extract.' : changed
      ? (extracted ? 'Your corrected transcript was used for this event card.' :
        'Correction saved locally—extract the event card from these words.')
      : (extracted ? 'The reviewed transcript was used for this event card.' :
        'No transcript corrections yet.');
  }

  function invalidateExtraction(message) {
    state.extracted = false;
    state.activity = null;
    if (el('capture-activity-search')) el('capture-activity-search').value = '';
    if (el('capture-activity-selected')) el('capture-activity-selected').innerHTML = '';
    if (el('capture-activity-results')) el('capture-activity-results').innerHTML = '';
    for (const id of ['capture-structured-card', 'capture-place-card', 'capture-confirm-card']) {
      if (el(id)) el(id).hidden = true;
    }
    const button = el('capture-extract');
    if (button) button.textContent = message || 'Extract editable event card';
    updateTranscriptState(false);
  }

  function setTranscript(text, source, markAsVoice = true) {
    const original = el('capture-original');
    const confirmed = el('capture-confirmed');
    if (original) original.value = text;
    if (confirmed && !state.transcriptDirty) confirmed.value = text;
    const hint = el('capture-transcript-source');
    if (hint) hint.textContent = source;
    if (text.trim() && markAsVoice) { state.voiceCaptured = true; state.voiceUnavailable = false; }
    invalidateExtraction('Extract corrected transcript');
  }

  function markVoiceCaptured(message) {
    state.voiceCaptured = true;
    state.voiceUnavailable = false;
    const hint = el('capture-transcript-source');
    if (hint) hint.textContent = message ||
      'Voice captured. Confirm or type the words below before extraction.';
    updateTranscriptState(false);
  }

  function markVoiceUnavailable(message) {
    state.voiceUnavailable = true;
    const hint = el('capture-transcript-source');
    if (hint) hint.textContent = message ||
      'Voice is unavailable in this browser. Type the update or attach an audio file.';
    updateTranscriptState(false);
  }

  async function toggleRecording() {
    const button = el('capture-voice');
    if (state.recording && state.recording.state === 'recording') {
      state.recording.stop();
      if (state.recognition) { try { state.recognition.stop(); } catch (_) {} }
      paintVoiceButton(false);
      return;
    }
    if (!navigator.mediaDevices || !window.MediaRecorder) {
      el('capture-audio-file').click(); return;
    }
    try {
      const selectedDevice = state.audioDeviceId ||
        (el('capture-microphone') && el('capture-microphone').value) || '';
      const audio = selectedDevice ? {deviceId: {exact: selectedDevice}} : true;
      const stream = await navigator.mediaDevices.getUserMedia({audio});
      state.voiceUnavailable = false; state.recognitionError = null;
      await enumerateMicrophones(false);
      state.chunks = [];
      state.recording = new MediaRecorder(stream);
      state.recording.ondataavailable = (event) => { if (event.data.size) state.chunks.push(event.data); };
      state.recording.onstop = () => {
        const type = state.recording.mimeType || 'audio/webm';
        const blob = new Blob(state.chunks, {type});
        state.files.push({name: 'field-voice-' + Date.now() + '.webm', type, blob});
        stream.getTracks().forEach(track => track.stop()); drawFiles();
        if (!el('capture-original').value.trim()) markVoiceCaptured(
          state.recognitionError
            ? 'Voice captured, but browser transcription was unavailable. Type or paste what you said below.'
            : 'Voice captured. Confirm or type the words below before extraction.');
        setTimeout(() => interpretEvent(state.projectId).catch(error =>
          window.toast('Could not extract the event card: ' + error.message, 'bad')), 250);
      };
      state.recording.start(500);
       paintVoiceButton(true);
      const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
      if (Recognition) {
        const recognition = new Recognition();
        recognition.lang = el('capture-language').value;
        recognition.continuous = true; recognition.interimResults = true;
        let finalText = el('capture-original').value.trim();
        recognition.onresult = (event) => {
          let interim = '';
          for (let i = event.resultIndex; i < event.results.length; i += 1) {
            if (event.results[i].isFinal) finalText += (finalText ? ' ' : '') + event.results[i][0].transcript;
            else interim += event.results[i][0].transcript;
          }
          setTranscript((finalText + (interim ? ' ' + interim : '')).trim(),
            'Live transcript is a draft—confirm it below. The recording remains the source.');
        };
        recognition.onerror = (event) => {
          if (event && event.error === 'aborted') return;
          state.recognitionError = (event && event.error) || 'unavailable';
          if (!el('capture-original').value.trim()) markVoiceCaptured(
            'Voice is recording, but browser transcription is unavailable. Type or paste what you said below.');
        };
        recognition.onend = () => {
          if (state.recording && state.recording.state === 'recording' &&
              !el('capture-original').value.trim()) markVoiceCaptured(
            'Voice is recording, but browser transcription stopped. Type or paste what you said below.');
        };
        try {
          // Keep transcription on the exact live track used by MediaRecorder when
          // the browser supports SpeechRecognition.start(audioTrack). Older
          // implementations may reject the optional track, so fall back to the
          // browser's default recognition path without losing the recording.
          const track = stream.getAudioTracks && stream.getAudioTracks()[0];
          if (track) {
            try { recognition.start(track); }
            catch (_) { recognition.start(); }
          } else {
            recognition.start();
          }
          state.recognition = recognition;
        } catch (_) {
          state.recognition = null;
          state.recognitionError = 'start_failed';
          markVoiceCaptured(
            'Voice is recording, but browser transcription could not start. Type or paste what you said below.');
        }
      } else {
        markVoiceCaptured(
          'Voice is recorded as evidence. This browser has no live transcription—type or paste the words below.');
      }
    } catch (error) { paintVoiceButton(false); state.recording = null;
      if (state.recognition) { try { state.recognition.stop(); } catch (_) {} }
      state.recognition = null;
      markVoiceUnavailable(error && (error.name === 'NotAllowedError' || error.name === 'SecurityError')
        ? 'Microphone permission was denied. Allow microphone access or type the update below.'
        : error && error.name === 'OverconstrainedError'
          ? 'That microphone is no longer available. Choose another input or use the default.'
          : 'Microphone is unavailable in this browser. Type the update or attach an audio file.');
      window.toast('Microphone unavailable: ' + error.message, 'bad'); }
  }

  async function locate() {
    if (!navigator.geolocation) return window.toast('Location is not supported on this device', 'bad');
    const button = el('capture-location'); button.disabled = true; button.textContent = 'Locating…';
    navigator.geolocation.getCurrentPosition((position) => {
      state.coordinates = {latitude: position.coords.latitude,
        longitude: position.coords.longitude,
        location_accuracy_m: position.coords.accuracy, location_source: 'device'};
      el('capture-location-status').textContent = 'Device location attached · ±' +
        Math.round(position.coords.accuracy) + ' m';
      button.disabled = false; button.textContent = 'Refresh location';
    }, (error) => {
      button.disabled = false; button.textContent = 'Use device location';
      window.toast('Location not attached: ' + error.message, 'bad');
    }, {enableHighAccuracy: true, timeout: 12000, maximumAge: 30000});
  }

  async function searchActivities(projectId, query) {
    const list = el('capture-activity-results');
    if (!query.trim()) { list.innerHTML = ''; return; }
    const response = await window.api('/projects/' + projectId + '/activities?q=' +
      encodeURIComponent(query.trim()) + '&milestone=0&limit=8');
    renderActivityCandidates(response.activities || []);
  }

  function selectActivity(activity) {
    state.activity = activity;
    el('capture-activity-search').value = (activity.display_id || '') + ' · ' + activity.name;
    el('capture-activity-results').innerHTML = '';
    el('capture-activity-selected').innerHTML = '<b>Linked to ' +
      escapeHtml(activity.display_id || 'UID ' + activity.uid) + '</b><span>' +
      escapeHtml(activity.name) + '</span><button type="button" id="capture-activity-clear">Change</button>';
    el('capture-activity-clear').onclick = () => { state.activity = null;
      el('capture-activity-search').value = ''; el('capture-activity-selected').innerHTML = ''; };
  }

  function renderActivityCandidates(activities) {
    const list = el('capture-activity-results');
    list.innerHTML = activities.length ? activities.map(activity =>
      '<button type="button" data-capture-activity="' + activity.uid + '">' +
      '<b>' + escapeHtml(activity.display_id || 'UID ' + activity.uid) + '</b>' +
      '<span>' + escapeHtml(activity.name) + '</span><small>' +
      escapeHtml(activity.wbs || '') + ' · ' + escapeHtml(activity.status || '—') +
      '</small></button>').join('') : '<div class="capture-no-result">No matching activities.</div>';
    list.querySelectorAll('[data-capture-activity]').forEach((button, index) =>
      button.onclick = () => selectActivity(activities[index]));
  }

  async function interpretEvent(projectId) {
    const text = el('capture-confirmed').value.trim();
    if (!text) return window.toast('Review and confirm the transcript before extraction', 'bad');
    const button = el('capture-extract'); button.disabled = true; button.textContent = 'Extracting event…';
    let result;
    if (navigator.onLine) {
      const response = await fetch('/api/projects/' + encodeURIComponent(projectId) +
        '/field-captures/interpret', {method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({text, occurred_at: el('capture-occurred').value,
            location_label: el('capture-location-label').value,
            language: el('capture-language').value, adaptive_language: true})});
      if (!response.ok) {
        let message = 'Event extraction failed';
        try { message = (await response.json()).detail || message; } catch (_) {}
        button.disabled = false; button.textContent = 'Extract editable event card';
        throw new Error(message);
      }
      result = await response.json();
    } else {
      const pct = text.match(/\b(100(?:\.0+)?|\d{1,2}(?:\.\d+)?)\s*%/);
      result = {draft: {event_state: /finish|complete|done|khatam|poora|pura|ho\s+g(?:aya|ya|ayi|yi)|पूरा|समाप्त|खत्म|हो\s+गया/i.test(text) ? 'finish' :
        /start|commenc|begin|began|shuru|aarambh|शुरू|आरंभ/i.test(text) ? 'start' : 'progress',
        observed_progress: pct ? Number(pct[1]) : null, confidence: null,
        asset_tags: []}, activity_candidates: []};
    }
    const draft = result.draft || {};
    el('capture-progress').value = '';
    el('capture-remaining').value = '';
    const radio = document.querySelector('[name="capture-event"][value="' +
      (draft.event_state || 'progress') + '"]');
    if (radio) radio.checked = true;
    if (draft.observed_progress !== null && draft.observed_progress !== undefined)
      el('capture-progress').value = draft.observed_progress;
    if (draft.remaining_days !== null && draft.remaining_days !== undefined)
      el('capture-remaining').value = draft.remaining_days;
    if (draft.location_label && !el('capture-location-label').value)
      el('capture-location-label').value = draft.location_label;
    updateEventFields();
    renderActivityCandidates(result.activity_candidates || []);
    const summary = [];
    if (draft.action) summary.push('<span>Action · ' + escapeHtml(draft.action) + '</span>');
    summary.push('<span>Event · ' + escapeHtml(draft.event_state || 'progress') + '</span>');
    if (draft.quantity !== null && draft.quantity !== undefined)
      summary.push('<span>Quantity · ' + escapeHtml(draft.quantity + ' ' + (draft.unit || '')) + '</span>');
    if ((draft.asset_tags || []).length)
      summary.push('<span>Assets · ' + escapeHtml(draft.asset_tags.join(', ')) + '</span>');
    const languagePass = result.language_interpretation || {};
    summary.push('<span>Understanding · ' + escapeHtml(languagePass.label || 'Offline construction rules') + '</span>');
    if (languagePass.attempted && !languagePass.available)
      summary.push('<span>Local language pass unavailable · editable rules draft kept</span>');
    summary.push('<span>Draft only · edit before confirming</span>');
    el('capture-extracted-summary').innerHTML = summary.join('');
    for (const id of ['capture-structured-card', 'capture-place-card', 'capture-confirm-card'])
      el(id).hidden = false;
    state.extracted = true;
    updateTranscriptState(true);
    button.disabled = false; button.textContent = 'Re-extract event card';
  }

  function capturePayload() {
    const occurred = el('capture-occurred').value;
    let occurredWithZone = '';
    if (occurred) {
      const offsetMinutes = -new Date(occurred).getTimezoneOffset();
      const sign = offsetMinutes >= 0 ? '+' : '-';
      const absolute = Math.abs(offsetMinutes);
      occurredWithZone = occurred + sign + String(Math.floor(absolute / 60)).padStart(2, '0') +
        ':' + String(absolute % 60).padStart(2, '0');
    }
    return {
      client_capture_id: el('capture-client-id').value,
      occurred_at: occurredWithZone,
      event_state: eventState(), language: el('capture-language').value,
      reporter: el('capture-reporter').value.trim() || 'Field reporter',
      original_text: el('capture-original').value.trim(),
      confirmed_text: el('capture-confirmed').value.trim(),
      activity_uid: state.activity ? state.activity.uid : null,
      observed_progress: eventState() === 'progress' && el('capture-progress').value !== ''
        ? Number(el('capture-progress').value) : null,
      remaining_days: eventState() === 'progress' && el('capture-remaining').value !== ''
        ? Number(el('capture-remaining').value) : (eventState() === 'finish' ? 0 : null),
      location_label: el('capture-location-label').value.trim(),
      ...(state.coordinates || {}), sync_source: navigator.onLine ? 'online' : 'offline_outbox'
    };
  }

  function reset() {
    state.files = []; state.activity = null; state.coordinates = null;
    state.transcriptDirty = false; state.extracted = false;
    state.voiceCaptured = false; state.voiceUnavailable = false; state.recognitionError = null;
    el('capture-client-id').value = clientId();
    el('capture-original').value = ''; el('capture-confirmed').value = '';
    el('capture-progress').value = ''; el('capture-remaining').value = '';
    el('capture-activity-search').value = ''; el('capture-activity-selected').innerHTML = '';
    el('capture-location-label').value = ''; el('capture-location-status').textContent = 'Location is optional and permission-based.';
    el('capture-extracted-summary').innerHTML = '';
    for (const id of ['capture-structured-card', 'capture-place-card', 'capture-confirm-card'])
      el(id).hidden = true;
    el('capture-extract').textContent = 'Extract editable event card';
    el('capture-transcript-source').textContent = 'Type a note, or record voice for a browser draft transcript.';
    updateTranscriptState(false); paintVoiceButton(false);
    drawFiles();
  }

  async function submit(projectId) {
    const payload = capturePayload();
    if (!state.extracted) return window.toast('Extract and review the editable event card first', 'bad');
    if (!payload.confirmed_text) return window.toast('Confirm the field update text first', 'bad');
    const item = {id: payload.client_capture_id, projectId, payload,
      attachments: state.files.slice(), createdAt: Date.now()};
    const button = el('capture-save'); button.disabled = true;
    button.textContent = navigator.onLine ? 'Saving confirmed update…' : 'Saving on this device…';
    if (navigator.onLine) {
      try {
        const result = await send(item);
        const capture = result.capture || {};
        window.toast(isWorkerWorkspace()
          ? 'Update sent to Project Controls. You can track it in My submissions.'
          : capture.status === 'proposal_ready'
          ? 'Saved. Governed actuals proposals are ready for planner review.'
          : capture.status === 'needs_activity'
            ? 'Saved. A planner still needs to link this update to an activity.'
            : 'Confirmed field update saved.', 'good');
        announceFieldHandoff(projectId, capture);
        reset(); window.refreshCounts(); window.render(); return;
      } catch (error) {
        if (error.permanent) { window.toast(error.message, 'bad'); button.disabled = false;
          button.textContent = saveButtonLabel(); return; }
      }
    }
    await queue(item);
    if ('serviceWorker' in navigator) {
      const registration = await navigator.serviceWorker.ready;
      if (registration.sync) { try { await registration.sync.register('veda-field-captures'); } catch (_) {} }
    }
    window.toast('Saved safely on this device. VEDA will sync it when online.', 'good');
    reset(); await updateOutbox(projectId); button.disabled = false; button.textContent = saveButtonLabel();
  }

  async function bind(projectId) {
    state.files = []; state.activity = null; state.coordinates = null;
    state.transcriptDirty = false; state.extracted = false; state.projectId = projectId;
    state.voiceCaptured = false; state.voiceUnavailable = false; state.recognitionError = null;
    el('capture-client-id').value = clientId();
    const now = new Date(Date.now() - new Date().getTimezoneOffset() * 60000);
    if (!el('capture-occurred').value) el('capture-occurred').value = now.toISOString().slice(0, 16);
    document.querySelectorAll('[name="capture-event"]').forEach(input => input.onchange = updateEventFields);
    updateEventFields(); drawFiles(); updateOutbox(projectId);
    el('capture-cctv').onclick = openCctvReview;
    el('capture-cctv-close').onclick = closeCctvReview;
    el('capture-cctv-jump').onclick = jumpToCctvFrame;
    el('capture-cctv-use').onclick = () => useCctvObservation(projectId);
    el('capture-cctv-photo').onclick = () => el('capture-photo-file').click();
    el('capture-cctv-camera').onchange = (event) => renderCctvFeed(event.target.value);
    document.querySelectorAll('[data-capture-cctv-mode]').forEach(button =>
      button.onclick = () => setCctvMode(button.dataset.captureCctvMode));
    el('capture-cctv-player').ontimeupdate = () => {
      const player = el('capture-cctv-player');
      const clock = el('capture-cctv-clock');
      if (!player || !clock) return;
      const seconds = Math.max(0, Math.round(player.currentTime || 0));
      clock.textContent = 'Frame ' +
        String(Math.floor(seconds / 60)).padStart(2, '0') + ':' + String(seconds % 60).padStart(2, '0');
    };
    document.querySelectorAll('[data-cctv-observation]').forEach(button => {
      button.onclick = () => renderCctvObservation(button.dataset.cctvObservation, true);
    });
    renderCctvFeed(state.cctvFeed);
    el('capture-photo-file').onchange = (event) => { addInputFiles(event.target.files); event.target.value = ''; };
    const mediaUpload = el('capture-media-upload');
    if (mediaUpload) mediaUpload.onclick = () => el('capture-photo-file').click();
    const videoRecord = el('capture-video-record');
    if (videoRecord) videoRecord.onclick = () => el('capture-video-file').click();
    const videoInput = el('capture-video-file');
    if (videoInput) videoInput.onchange = (event) => {
      addInputFiles(event.target.files); event.target.value = '';
    };
    el('capture-audio-file').onchange = (event) => {
      if (event.target.files && event.target.files.length) markVoiceCaptured(
        'Audio attached. This browser did not provide a live transcript—type or paste the words below.');
      addInputFiles(event.target.files); event.target.value = '';
    };
    const mic = el('capture-microphone');
    if (mic) mic.onchange = () => {
      state.audioDeviceId = mic.value || '';
      setMicrophoneStatus(state.audioDeviceId
        ? 'Selected input will feed the recording and browser transcription when supported.'
        : 'The browser default microphone will be used for recording and transcription.');
    };
    const micRefresh = el('capture-mic-refresh');
    if (micRefresh) micRefresh.onclick = () => enumerateMicrophones(true);
    if (navigator.mediaDevices && navigator.mediaDevices.addEventListener && !state.deviceChangeBound) {
      navigator.mediaDevices.addEventListener('devicechange', () => enumerateMicrophones(false));
      state.deviceChangeBound = true;
    }
    enumerateMicrophones(false);
    el('capture-voice').onclick = toggleRecording;
    el('capture-location').onclick = locate;
    el('capture-extract').onclick = () => interpretEvent(projectId).catch(error => {
      el('capture-extract').disabled = false;
      el('capture-extract').textContent = 'Extract editable event card';
      window.toast(error.message, 'bad');
    });
    el('capture-confirmed').oninput = () => {
      state.transcriptDirty = el('capture-confirmed').value !== el('capture-original').value;
      invalidateExtraction('Re-extract corrected transcript');
    };
    el('capture-original').oninput = (event) => {
      if (!state.transcriptDirty) el('capture-confirmed').value = event.target.value;
      el('capture-transcript-source').textContent = 'Typed field note—review and confirm below.';
      invalidateExtraction('Extract corrected transcript');
    };
    el('capture-reset-transcript').onclick = () => {
      el('capture-confirmed').value = el('capture-original').value;
      state.transcriptDirty = false;
      invalidateExtraction('Extract corrected transcript');
      el('capture-confirmed').focus();
    };
    const applyLanguage = () => {
      const language = el('capture-language').value;
      const rtl = /^(ar|ur|fa|he)(-|$)/i.test(language);
      for (const area of [el('capture-original'), el('capture-confirmed')]) {
        area.lang = language; area.dir = rtl ? 'rtl' : 'auto';
      }
    };
    el('capture-language').onchange = applyLanguage;
    applyLanguage();
    updateTranscriptState(false); paintVoiceButton(false);
    el('capture-activity-search').oninput = (event) => {
      clearTimeout(state.timer); state.timer = setTimeout(() =>
        searchActivities(projectId, event.target.value).catch(() => {}), 260);
    };
    el('capture-save').onclick = () => submit(projectId);
    const flushButton = el('capture-sync-now');
    if (flushButton) flushButton.onclick = () => flush(projectId).then(() => window.render());
    window.setTimeout(() => consumeVisualCaptureDraft(projectId).catch(error =>
      window.toast('Could not prepare the visual field draft: ' + error.message, 'bad')), 0);
  }

  function hasUnsavedState() {
    const raw = el('capture-original');
    const confirmed = el('capture-confirmed');
    const cctv = el('capture-cctv-panel');
    return Boolean(state.files.length || (state.recording && state.recording.state === 'recording') ||
      (raw && raw.value.trim()) || (confirmed && confirmed.value.trim()) ||
      (cctv && !cctv.hidden) || state.extracted);
  }

  window.addEventListener('online', () => flush(window.S && window.S.project));
  window.addEventListener('offline', () => updateOutbox(window.S && window.S.project));
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.addEventListener('message', (event) => {
      if (event.data && event.data.type === 'veda-field-sync-complete') {
        updateOutbox(window.S && window.S.project);
        if (window.S && window.S.view === 'capture') window.render();
      }
    });
  }
  window.FieldCapture = {bind, flush, updateOutbox, hasUnsavedState};
})();
