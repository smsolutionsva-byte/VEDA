const CACHE = 'veda-shell-1.29';
const SHELL = [
  '/', '/manifest.webmanifest', '/static/favicon.svg',
  '/static/app.css?v=1.29', '/static/views.js?v=1.29',
  '/static/app.js?v=1.29', '/static/field-capture.js?v=1.29'
];
const DB = 'veda-field-sync';
const STORE = 'outbox';

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(caches.keys().then((keys) => Promise.all(
    keys.filter((key) => key.startsWith('veda-shell-') && key !== CACHE)
      .map((key) => caches.delete(key)))));
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  if (event.request.method !== 'GET' || new URL(event.request.url).origin !== location.origin) return;
  const url = new URL(event.request.url);
  if (url.pathname.startsWith('/api/')) return;
  event.respondWith(fetch(event.request).then((response) => {
    if (response.ok && (url.pathname === '/' || url.pathname.startsWith('/static/'))) {
      const copy = response.clone();
      caches.open(CACHE).then((cache) => cache.put(event.request, copy));
    }
    return response;
  }).catch(() => caches.match(event.request).then((cached) => cached || caches.match('/'))));
});

function openDb() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB, 1);
    request.onupgradeneeded = () => {
      if (!request.result.objectStoreNames.contains(STORE)) {
        request.result.createObjectStore(STORE, { keyPath: 'id' });
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function records(db) {
  return new Promise((resolve, reject) => {
    const request = db.transaction(STORE).objectStore(STORE).getAll();
    request.onsuccess = () => resolve(request.result || []);
    request.onerror = () => reject(request.error);
  });
}

async function remove(db, id) {
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, 'readwrite');
    tx.objectStore(STORE).delete(id);
    tx.oncomplete = resolve;
    tx.onerror = () => reject(tx.error);
  });
}

async function flushOutbox() {
  const db = await openDb();
  for (const item of await records(db)) {
    const form = new FormData();
    form.append('payload', JSON.stringify({...item.payload, sync_source: 'offline_outbox'}));
    for (const file of item.attachments || []) {
      form.append('files', file.blob, file.name || 'field-media');
    }
    try {
      const response = await fetch('/api/projects/' + encodeURIComponent(item.projectId) +
        '/field-captures', {method: 'POST', body: form});
      if (response.ok) await remove(db, item.id);
    } catch (_) { break; }
  }
  for (const client of await self.clients.matchAll({includeUncontrolled: true})) {
    client.postMessage({type: 'veda-field-sync-complete'});
  }
}

self.addEventListener('sync', (event) => {
  if (event.tag === 'veda-field-captures') event.waitUntil(flushOutbox());
});
