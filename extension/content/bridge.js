/* VEDA web-app bridge - injected ONLY on the VEDA origin (see manifest matches).

   Its single job: let the VEDA Anywhere settings page detect that the companion
   is installed, so it can show "Connect extension" instead of the install steps.

   It does NOT read page content, and it deliberately does NOT complete pairing.
   Pairing happens only when the operator enters the code into the extension
   popup - there is no automatic hand-off.
*/
(() => {
  const CHANNEL = 'veda-anywhere';
  const VERSION = chrome.runtime.getManifest().version;

  try {
    document.documentElement.setAttribute('data-veda-anywhere', VERSION);
  } catch (_) { /* ignore */ }

  const announce = (type) => {
    try {
      window.postMessage({ source: 'veda-anywhere', channel: CHANNEL, type, version: VERSION },
        window.location.origin);
    } catch (_) { /* ignore */ }
  };
  announce('hello');

  window.addEventListener('message', (event) => {
    if (event.source !== window) return;
    if (event.origin !== window.location.origin) return;
    const data = event.data;
    if (!data || data.channel !== CHANNEL || data.source !== 'veda-web') return;
    if (data.type === 'ping') {
      try { document.documentElement.setAttribute('data-veda-anywhere', VERSION); } catch (_) {}
      announce('pong');
    }
  });

  if (document.readyState !== 'complete') {
    window.addEventListener('load', () => announce('hello'), { once: true });
  }
})();
