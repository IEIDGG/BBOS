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
  const grantStorageReady = worker ? chrome.storage.local.setAccessLevel({accessLevel:'TRUSTED_CONTEXTS'}) : Promise.resolve();
  grantStorageReady.catch(() => {});
  function prepareGrantStorage() {
    return grantStorageReady;
  }
  async function readGrant() {
    await prepareGrantStorage();
    const {accountGrant: durable} = await chrome.storage.local.get('accountGrant');
    const {accountGrant: legacy} = await chrome.storage.session.get('accountGrant');
    if (!durable && legacy) await chrome.storage.local.set({accountGrant:legacy});
    if (legacy) await chrome.storage.session.remove('accountGrant');
    return durable || legacy;
  }
  async function saveGrant(grant) {
    await prepareGrantStorage();
    await chrome.storage.local.set({accountGrant:grant});
    await chrome.storage.session.remove('accountGrant');
  }
  async function removeGrant() {
    await prepareGrantStorage();
    await chrome.storage.local.remove('accountGrant');
    await chrome.storage.session.remove('accountGrant');
  }
  // Include JSON consumption in the deadline. Never retry a rotating POST.
  async function authRequest(path, options = {}, readJson = false) {
    const controller = new AbortController();
    let timer;
    const timeout = new Promise((_, reject) => {
      timer = setTimeout(() => {
        controller.abort();
        reject(new Error('Authentication service timed out. Try connecting again.'));
      }, 10000);
    });
    try {
      return await Promise.race([
        (async () => {
          const response = await extensionFetch(base + path, {...options, signal:controller.signal});
          const data = readJson && response.ok ? await response.json() : null;
          return {response, data};
        })(),
        timeout,
      ]);
    } finally { clearTimeout(timer); }
  }
  function validatedGrant(value) {
    if (!value || typeof value.access_token !== 'string' || !value.access_token || typeof value.refresh_token !== 'string' || !value.refresh_token || !Number.isFinite(Date.parse(value.expires_at)) || Date.parse(value.expires_at) <= Date.now()) {
      throw new Error('Invalid extension session. Connect again.');
    }
    return {access_token:value.access_token, refresh_token:value.refresh_token, expires_at:value.expires_at};
  }
  const encode = bytes => btoa(String.fromCharCode(...bytes)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  const random = () => encode(crypto.getRandomValues(new Uint8Array(32)));
  async function loadToken(force = false) {
    const grant = await readGrant();
    if (!grant || Date.now() >= Date.parse(grant.expires_at)) return null;
    if (grant.refresh_uncertain) throw new Error('Refresh outcome unknown. Connect the extension again.');
    const {response:user} = await authRequest('/api/user', {cache:'no-store', headers:{'X-Auth-Token':grant.access_token}});
    if (user.ok) return grant.access_token;
    if (user.status !== 401) throw new Error('Authentication service unavailable');
    // Persist uncertainty before sending: worker termination can lose a rotated response.
    await saveGrant({...grant, refresh_uncertain:true});
    const {response, data} = await authRequest('/api/auth/extensions/refresh', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({refresh_token:grant.refresh_token})}, true);
    if (!response.ok) {
      if (response.status === 401 || response.status === 403) {await removeGrant(); return null;}
      throw new Error('Authentication service unavailable. Connect again.');
    }
    const fresh = validatedGrant(data);
    await saveGrant(fresh);
    return fresh.access_token;
  }
  function serial(action) {const result = queue.then(action); queue = result.catch(() => {}); return result;}
  async function startConnect() {
    // Reconnection must not abandon the old independently revocable child grant.
    await disconnect();
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
    if (await readGrant()) await revokeGrant();
    await chrome.storage.session.remove('accountHandoff');
    const {response, data} = await authRequest('/api/auth/extensions/exchange', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({code:message.code, verifier:pending.verifier})}, true);
    if (!response.ok) throw new Error('Connect failed. Sign in again and retry.');
    await saveGrant(validatedGrant(data));
    return true;
  }
  async function revokeGrant() {
    const grant = await readGrant();
    if (grant) {
      const {response, data:result} = await authRequest('/api/auth/extensions/logout', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({refresh_token:grant.refresh_token})}, true);
      if (!response.ok || result?.success !== true) throw new Error('Unable to sign out: server disconnect unavailable. Try again.');
    }
    await removeGrant();
  }
  async function disconnect() {
    await revokeGrant();
    await chrome.storage.session.remove('accountHandoff');
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
    // This public endpoint must work even while validation is stalled or unavailable.
    if (url.pathname === '/api/order-scraper/version') {
      const headers = new Headers(options.headers);
      headers.delete('X-Auth-Token');
      return extensionFetch(input, {...options, headers});
    }
    let token = await getToken();
    if (!token) throw new Error('Sign in to IEID and connect Order Scraper first.');
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
