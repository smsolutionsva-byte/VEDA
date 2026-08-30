/* VEDA Anywhere - shared constants for the module contexts (background, popup,
   options). Content scripts (content/bridge.js, content/overlay.js) cannot use
   ES imports, so they re-declare the few string literals they need. Keep the
   MSG values here identical to the copies in those files. */

export const DEFAULT_BASE_URL = 'http://127.0.0.1:8770';

// chrome.storage.local key holding the whole extension state.
export const STORAGE_KEY = 'veda_anywhere';

// Messages over chrome.runtime: background <-> popup / overlay / bridge.
export const MSG = {
  PAIR: 'veda:pair',                 // bridge/popup -> background: exchange a pairing code
  SESSION_GET: 'veda:session:get',   // -> background: cached (redacted) state
  SESSION_REFRESH: 'veda:session:refresh', // -> background: re-fetch /anywhere/session
  SET_ACTIVE_PROJECT: 'veda:project:set',
  ASK: 'veda:ask',                   // -> background: start an Ask VEDA question
  ASK_POLL: 'veda:ask:poll',         // -> background: one poll of the answer job
  DETECT: 'veda:detect',             // -> background: read-only activity detection
  CAPTURE: 'veda:capture',           // -> background: create the evidence capture
  DISCONNECT: 'veda:disconnect',
  GET_SELECTION: 'veda:selection:get',
  OPEN_OVERLAY: 'veda:overlay:open', // -> background: inject the selection UI
  OPEN_APP: 'veda:app:open',         // -> background: open the VEDA web app
  STATE_CHANGED: 'veda:state:changed', // background -> popup/options: re-render
};

export const EXTENSION_VERSION = chrome.runtime.getManifest().version;
