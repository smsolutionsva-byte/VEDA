/* Persistent extension state (chrome.storage.local).

   Shape:
   {
     baseUrl: string,               // VEDA backend origin
     token: string | null,          // bearer token from pairing (secret)
     tokenId: string | null,
     account: object | null,         // { workspace, data_dir, host }
     enabled: boolean,               // mirror of the server-side switch
     projects: [{id,name,client,location}],
     defaultProjectId: string | null,
     activeProjectId: string | null, // the operator's current choice (local)
     siteAccess: { mode, allowed_sites: [] },
     captureMetadataDefaults: { include_url, include_title, include_source_app },
     serverVersion: string | null,
     lastSync: number | null
   }
*/
import { STORAGE_KEY, DEFAULT_BASE_URL } from './constants.js';

const DEFAULT_STATE = {
  baseUrl: DEFAULT_BASE_URL,
  token: null,
  tokenId: null,
  account: null,
  enabled: false,
  projects: [],
  defaultProjectId: null,
  activeProjectId: null,
  siteAccess: { mode: 'selected', allowed_sites: [] },
  captureMetadataDefaults: { include_url: false, include_title: false, include_source_app: false },
  serverVersion: null,
  lastSync: null,
};

export async function getState() {
  const raw = await chrome.storage.local.get(STORAGE_KEY);
  return { ...DEFAULT_STATE, ...(raw[STORAGE_KEY] || {}) };
}

export async function setState(patch) {
  const current = await getState();
  const next = { ...current, ...patch };
  await chrome.storage.local.set({ [STORAGE_KEY]: next });
  return next;
}

export async function clearAuth() {
  return setState({
    token: null, tokenId: null, account: null, enabled: false,
    projects: [], defaultProjectId: null, activeProjectId: null,
    serverVersion: null, lastSync: null,
  });
}

export function isConnected(state) {
  return Boolean(state && state.token);
}

/** The project the extension will act on: explicit local choice, else server default, else first. */
export function resolveActiveProjectId(state) {
  if (!state) return null;
  const ids = new Set((state.projects || []).map((p) => p.id));
  if (state.activeProjectId && ids.has(state.activeProjectId)) return state.activeProjectId;
  if (state.defaultProjectId && ids.has(state.defaultProjectId)) return state.defaultProjectId;
  return (state.projects && state.projects[0] && state.projects[0].id) || null;
}

export function onStateChanged(handler) {
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area === 'local' && changes[STORAGE_KEY]) {
      handler(changes[STORAGE_KEY].newValue || {});
    }
  });
}
