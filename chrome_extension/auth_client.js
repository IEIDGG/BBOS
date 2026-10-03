/* All contexts share independent extension credentials and one refresh queue in the worker. */
(() => {
  'use strict';
  const base = 'https://ieidgg.com';
  const rawFetch = globalThis.fetch.bind(globalThis);
  const worker = typeof document === 'undefined';
  const origin = chrome.runtime.getURL('').replace(/\/$/, '');
  function extensionFetch(input, options = {}) {
    const headers = new Headers(options.headers);
    headers.set('X-Extension-Origin', origin);
    return rawFetch(input, {...options, headers, credentials:'omit'});
  }
  let queue = Promise.resolve();
  const encode = bytes => btoa(String.fromCharCode(...bytes)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  const random = () => encode(crypto.getRandomValues(new Uint8Array(32)));
  async function loadToken(force = false) {
    const {accountGrant: grant} = await chrome.storage.session.get('accountGrant');
    if (!grant || Date.now() >= Date.parse(grant.expires_at)) return null;
    const user = await extensionFetch(base + '/api/user', {credentials:'omit', cache:'no-store', headers:{'X-Auth-Token':grant.access_token}});
    if (user.ok) return grant.access_token;
    if (user.status !== 401) throw new Error('Authentication service unavailable');
    const response = await extensionFetch(base + '/api/auth/extensions/refresh', {method:'POST', credentials:'omit', headers:{'Content-Type':'application/json'}, body:JSON.stringify({refresh_token:grant.refresh_token})});
    if (!response.ok) {if (response.status === 401 || response.status === 403) await chrome.storage.session.remove('accountGrant'); return null;}
    const fresh = await response.json();
    await chrome.storage.session.set({accountGrant:fresh});
    return fresh.access_token;
  }
  function serial(action) {const result = queue.then(action); queue = result.catch(() => {}); return result;}
  async function startConnect() {
    const verifier = random(); const state = random();
    const challenge = encode(new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier))));
    await chrome.storage.session.set({accountHandoff:{verifier, state, expires:Date.now()+300000}});
    const params = new URLSearchParams({extension_id:chrome.runtime.id, challenge, state});
    await chrome.tabs.create({url:base + '/extension-connect?' + params});
    return true;
  }
  async function acceptHandoff(message, sender) {
    const url = new URL(sender.url || '');
    if (sender.id !== chrome.runtime.id || url.origin !== base || url.pathname !== '/extension-connect' || message.extension_id !== chrome.runtime.id) throw new Error('Invalid handoff sender');
    const {accountHandoff: pending} = await chrome.storage.session.get('accountHandoff');
    if (!pending || pending.expires <= Date.now() || pending.state !== message.state || url.searchParams.get('state') !== pending.state || url.searchParams.get('extension_id') !== chrome.runtime.id) throw new Error('Expired handoff');
    await chrome.storage.session.remove('accountHandoff');
    const response = await extensionFetch(base + '/api/auth/extensions/exchange', {method:'POST', credentials:'omit', headers:{'Content-Type':'application/json'}, body:JSON.stringify({code:message.code, verifier:pending.verifier})});
    if (!response.ok) throw new Error('Connect failed. Sign in again and retry.');
    await chrome.storage.session.set({accountGrant:await response.json()});
    return true;
  }
  async function disconnect() {
    const {accountGrant:grant} = await chrome.storage.session.get('accountGrant');
    if (grant) {
      const response = await extensionFetch(base + '/api/auth/extensions/logout', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({refresh_token:grant.refresh_token})});
      const result = await response.json().catch(() => ({}));
      if (!response.ok || result.success !== true) throw new Error('Unable to sign out: server disconnect unavailable. Try again.');
    }
    await chrome.storage.session.remove(['accountGrant','accountHandoff']);
  }
  const message = (type, fields = {}) => chrome.runtime.sendMessage({type, ...fields}).then(result => {
    if (result?.error) throw new Error(result.error);
    return result?.value;
  });
  const getToken = force => worker ? serial(() => loadToken(force)) : message('ieid-auth-token', {force:!!force});
  globalThis.IEIDAuth = {getToken, connect:() => worker ? serial(startConnect) : message('ieid-auth-connect'), disconnect:() => worker ? serial(disconnect) : message('ieid-auth-disconnect')};
  if (worker) chrome.runtime.onMessage.addListener((request, sender, respond) => {
    if (!['ieid-auth-token','ieid-auth-connect','ieid-auth-disconnect','ieid-extension-handoff'].includes(request.type)) return;
    const internal = sender.id === chrome.runtime.id && (sender.url || '').startsWith(chrome.runtime.getURL(''));
    if (request.type !== 'ieid-extension-handoff' && !internal) {respond({error:'Invalid sender'}); return;}
    serial(() => request.type === 'ieid-extension-handoff' ? acceptHandoff(request, sender) : request.type === 'ieid-auth-connect' ? startConnect() : request.type === 'ieid-auth-disconnect' ? disconnect() : loadToken(request.force))
      .then(value => respond({value}), () => respond({error:'Authentication failed. Sign in and connect the extension again.'}));
    return true;
  });
  globalThis.fetch = async (input, options = {}) => {
    const url = new URL(typeof input === 'string' ? input : input.url, base);
    if (url.origin !== base || !url.pathname.startsWith('/api/') || url.pathname.startsWith('/api/auth/extensions/')) return rawFetch(input, options);
    let token = await getToken();
    // The version endpoint is public and must remain available before connecting.
    if (!token && url.pathname !== '/api/order-scraper/version') throw new Error('Sign in to IEID and connect Order Scraper first.');
    const settings = {...options, credentials:'omit', headers:new Headers(options.headers)};
    if (token) settings.headers.set('X-Auth-Token', token);
    let response = await extensionFetch(input, settings);
    if (response.status === 401) {
      const error = await response.clone().json().catch(() => ({}));
      const method = (settings.method || 'GET').toUpperCase();
      if (['GET','HEAD'].includes(method) || error.code === 'auth_required') {
        token = await getToken(true);
        if (token) {settings.headers.set('X-Auth-Token', token); response = await extensionFetch(input, settings);}
      }
    }
    return response;
  };
})();
