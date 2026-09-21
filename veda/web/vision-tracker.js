/* Frame-synchronised local computer-vision overlays for recorded CCTV footage. */
(() => {
  const cache = new Map();

  const load = async url => {
    if (!cache.has(url)) cache.set(url, fetch(url, {cache: 'no-store'}).then(async response => {
      if (!response.ok) throw new Error('Vision tracks unavailable (' + response.status + ')');
      const payload = await response.json();
      if (payload.schema !== 'veda.vision.tracks.v1' || !Array.isArray(payload.frames))
        throw new Error('Unsupported vision-track data');
      return payload;
    }).catch(error => { cache.delete(url); throw error; }));
    return cache.get(url);
  };

  const interpolate = (left, right, ratio) => left + (right - left) * ratio;
  const eventsAt = (payload, seconds) => (payload.events || []).filter(event =>
    seconds >= Number(event.start == null ? event.t : event.start) &&
    seconds <= Number(event.end == null ? event.t : event.end));
  const frameAt = (payload, seconds) => {
    const frames = payload.frames;
    if (!frames.length) return [];
    let low = 0, high = frames.length - 1;
    while (low < high) {
      const middle = Math.floor((low + high + 1) / 2);
      if (frames[middle].t <= seconds) low = middle;
      else high = middle - 1;
    }
    const before = frames[low];
    const after = frames[Math.min(low + 1, frames.length - 1)];
    const span = Math.max(.001, after.t - before.t);
    const ratio = Math.max(0, Math.min(1, (seconds - before.t) / span));
    const beforeById = new Map((before.detections || []).map(item => [item.id, item]));
    const afterById = new Map((after.detections || []).map(item => [item.id, item]));
    const ids = new Set([...beforeById.keys(), ...afterById.keys()]);
    const detections = [];
    ids.forEach(id => {
      const first = beforeById.get(id);
      const second = afterById.get(id);
      if (first && second) {
        detections.push({...first,
          confidence: interpolate(first.confidence, second.confidence, ratio),
          x: interpolate(first.x, second.x, ratio), y: interpolate(first.y, second.y, ratio),
          w: interpolate(first.w, second.w, ratio), h: interpolate(first.h, second.h, ratio)});
      } else if (first && ratio < .58) detections.push({...first, opacity: 1 - ratio / .58});
      else if (second && ratio > .42) detections.push({...second, opacity: (ratio - .42) / .58});
    });
    return detections;
  };

  const render = (layer, detections, activeEvents = []) => {
    const present = new Set();
    const alertTracks = new Set(activeEvents.flatMap(event => event.track_ids || []).map(String));
    detections.forEach(detection => {
      const key = String(detection.id);
      present.add(key);
      let box = layer.querySelector('[data-model-track="' + key + '"]');
      if (!box) {
        box = document.createElement('span');
        box.className = 'vision-box model-track ' + (detection.class || 'equipment');
        box.dataset.modelTrack = key;
        box.innerHTML = '<b></b>';
        layer.appendChild(box);
      }
      box.className = 'vision-box model-track ' + (detection.class || 'equipment') +
        (alertTracks.has(key) ? ' safety-alert' : '') +
        (detection.state === 'scene_memory' ? ' scene-memory' : '');
      box.style.setProperty('--x', detection.x.toFixed(3) + '%');
      box.style.setProperty('--y', detection.y.toFixed(3) + '%');
      box.style.setProperty('--w', detection.w.toFixed(3) + '%');
      box.style.setProperty('--h', detection.h.toFixed(3) + '%');
      box.style.opacity = String(detection.opacity == null ? 1 : detection.opacity);
      const detectionDetail = detection.state === 'scene_memory'
        ? (detection.supporting_observations || 0) + ' CONFIRMATIONS'
        : Math.round(detection.confidence * 100) + '%' +
          (detection.review_required ? ' · REVIEW' : '');
      box.querySelector('b').textContent = (detection.label || 'Object').toUpperCase() +
        ' #' + detection.id + ' · ' + detectionDetail;
    });
    layer.querySelectorAll('[data-model-track]').forEach(box => {
      if (!present.has(box.dataset.modelTrack)) box.remove();
    });
  };

  const summarise = payload => {
    const tracks = new Map();
    let detectedFrames = 0;
    (payload.frames || []).forEach(frame => {
      if ((frame.detections || []).length) detectedFrames += 1;
      (frame.detections || []).forEach(item => {
        const key = item.class + ':' + item.id;
        if (!tracks.has(key)) tracks.set(key, item);
      });
    });
    const counts = {};
    tracks.forEach(item => { counts[item.label] = (counts[item.label] || 0) + 1; });
    return {counts, uniqueTracks: tracks.size, detectedFrames,
      totalFrames: (payload.frames || []).length, highlightTime: payload.highlight_time || 0};
  };

  const bind = ({video, layer, dataUrl, visible = true, onUpdate, onStatus}) => {
    let payload = null;
    let destroyed = false;
    let enabled = visible;
    let animationFrame = 0;
    let lastNotice = 0;
    layer.hidden = !enabled;
    const scanLine = layer.querySelector('.vision-scan-line') || document.createElement('i');
    scanLine.className = 'vision-scan-line';
    if (!scanLine.parentNode) layer.appendChild(scanLine);

    const update = timestamp => {
      if (destroyed || !payload) return;
      const seconds = Number(video.currentTime) || 0;
      const detections = frameAt(payload, seconds);
      const activeEvents = eventsAt(payload, seconds);
      render(layer, enabled ? detections : [], enabled ? activeEvents : []);
      layer.classList.toggle('has-safety-alert', enabled && activeEvents.length > 0);
      if (onUpdate && (!timestamp || timestamp - lastNotice > 180)) {
        lastNotice = timestamp || performance.now();
        onUpdate(detections, payload, activeEvents);
      }
    };
    const loop = timestamp => {
      update(timestamp);
      if (!destroyed && !video.paused && !video.ended) animationFrame = requestAnimationFrame(loop);
    };
    const onPlay = () => {
      cancelAnimationFrame(animationFrame);
      animationFrame = requestAnimationFrame(loop);
    };
    const onTime = () => update(performance.now());
    video.addEventListener('play', onPlay);
    video.addEventListener('timeupdate', onTime);
    video.addEventListener('seeked', onTime);

    const ready = load(dataUrl).then(data => {
      if (destroyed) return data;
      payload = data;
      layer.dataset.model = data.model && data.model.name || 'Local detector';
      if (onStatus) onStatus('ready', data, summarise(data));
      update();
      return data;
    }).catch(error => {
      if (!destroyed && onStatus) onStatus('error', error);
      throw error;
    });
    return {
      ready,
      update: onTime,
      setVisible(value) {
        enabled = Boolean(value);
        layer.hidden = !enabled;
        update();
      },
      destroy() {
        destroyed = true;
        cancelAnimationFrame(animationFrame);
        video.removeEventListener('play', onPlay);
        video.removeEventListener('timeupdate', onTime);
        video.removeEventListener('seeked', onTime);
        layer.querySelectorAll('[data-model-track]').forEach(box => box.remove());
      },
    };
  };

  window.VisionTracks = {bind, load, summarise, eventsAt};
})();
