/* Page-to-extension code bridge. The PKCE verifier stays exclusively in the worker. */
window.addEventListener('message', event => {
  if (event.source !== window || event.origin !== 'https://ieidgg.com' || location.pathname !== '/extension-connect') return;
  const message = event.data;
  const params = new URLSearchParams(location.search);
  if (!message || message.type !== 'ieid-extension-handoff' || message.extension_id !== chrome.runtime.id || message.state !== params.get('state') || !/^[A-Za-z0-9_-]{43}$/.test(message.code || '')) return;
  chrome.runtime.sendMessage(message).catch(() => {});
});
