/* Thin VEDA REST client.

   Every network call the extension makes lives here, and every call is a direct,
   single request triggered by an explicit user action. There is no polling of
   pages, no telemetry, no background sync of anything except the operator's own
   session/project list.

   Endpoints (all under <baseUrl>/api):
     POST /anywhere/pair/complete      { code }                 -> session + token
     GET  /anywhere/session                                     -> session
     POST /anywhere/disconnect                                  -> {ok}
     POST /anywhere/ask                 { project_id, text, ... } -> { job_id }
     GET  /anywhere/ask/{job_id}?project_id=                    -> { status, answer? }
     POST /anywhere/capture/detect      { project_id, text }     -> { detection, injection }
     POST /anywhere/capture             { project_id, text, ... }-> capture result
*/

export class VedaApiError extends Error {
  constructor(message, status, data) {
    super(message);
    this.name = 'VedaApiError';
    this.status = status;
    this.data = data || {};
  }
}

function joinUrl(baseUrl, path) {
  return String(baseUrl || '').replace(/\/+$/, '') + '/api' + path;
}

async function request(baseUrl, path, { method = 'GET', token, body, signal, timeoutMs = 15000 } = {}) {
  const headers = {};
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (token) headers['Authorization'] = 'Bearer ' + token;

  // Never let a hung connection wedge the extension. Chain any caller signal
  // with our own timeout.
  const ctrl = new AbortController();
  const onAbort = () => ctrl.abort();
  if (signal) {
    if (signal.aborted) ctrl.abort();
    else signal.addEventListener('abort', onAbort, { once: true });
  }
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);

  let res;
  try {
    res = await fetch(joinUrl(baseUrl, path), {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: ctrl.signal,
      credentials: 'omit',
      cache: 'no-store',
    });
  } catch (err) {
    const aborted = err && (err.name === 'AbortError');
    throw new VedaApiError(
      aborted
        ? 'VEDA did not respond in time.'
        : 'Could not reach VEDA at ' + baseUrl + '. Is the VEDA app running?',
      0, {});
  } finally {
    clearTimeout(timer);
    if (signal) signal.removeEventListener('abort', onAbort);
  }

  const raw = await res.text();
  let data = {};
  if (raw) {
    try { data = JSON.parse(raw); } catch (_) { data = { detail: raw }; }
  }
  if (!res.ok) {
    throw new VedaApiError(data.detail || (res.status + ' ' + res.statusText), res.status, data);
  }
  return data;
}

export const api = {
  completePairing(baseUrl, code) {
    return request(baseUrl, '/anywhere/pair/complete', { method: 'POST', body: { code } });
  },
  session(baseUrl, token) {
    return request(baseUrl, '/anywhere/session', { token });
  },
  disconnect(baseUrl, token) {
    return request(baseUrl, '/anywhere/disconnect', { method: 'POST', token });
  },
  ask(baseUrl, token, payload) {
    return request(baseUrl, '/anywhere/ask', { method: 'POST', token, body: payload });
  },
  askStatus(baseUrl, token, jobId, projectId) {
    const q = projectId ? '?project_id=' + encodeURIComponent(projectId) : '';
    return request(baseUrl, '/anywhere/ask/' + encodeURIComponent(jobId) + q, { token });
  },
  detect(baseUrl, token, payload) {
    return request(baseUrl, '/anywhere/capture/detect', { method: 'POST', token, body: payload });
  },
  capture(baseUrl, token, payload) {
    return request(baseUrl, '/anywhere/capture', { method: 'POST', token, body: payload });
  },
};
