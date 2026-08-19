const API_BASE = 'https://ieidgg.com';
const DB_NAME = 'ieid-order-scraper-updates';
const STAGING_DIR = '.ieid-update-staging';

function logUpdate(message, extra) {
  if (extra) console.info('[IEID update]', message, extra);
  else console.info('[IEID update]', message);
}

function openDb() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, 1);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains('handles')) db.createObjectStore('handles');
      if (!db.objectStoreNames.contains('state')) db.createObjectStore('state');
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

function idbGet(store, key) {
  return openDb().then((db) => new Promise((resolve, reject) => {
    const request = db.transaction(store, 'readonly').objectStore(store).get(key);
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  }));
}

function idbSet(store, key, value) {
  return openDb().then((db) => new Promise((resolve, reject) => {
    const request = db.transaction(store, 'readwrite').objectStore(store).put(value, key);
    request.onsuccess = () => resolve();
    request.onerror = () => reject(request.error);
  }));
}

function idbDelete(store, key) {
  return openDb().then((db) => new Promise((resolve, reject) => {
    const request = db.transaction(store, 'readwrite').objectStore(store).delete(key);
    request.onsuccess = () => resolve();
    request.onerror = () => reject(request.error);
  }));
}

function setStatus(text, isError) {
  const el = document.getElementById('status');
  el.textContent = text;
  el.classList.toggle('error', Boolean(isError));
}

function isAuto() {
  return new URLSearchParams(location.search).get('auto') === '1';
}

async function getAuthToken() {
  const cookie = await chrome.cookies.get({ url: API_BASE, name: 'access_token' });
  if (cookie?.value) return cookie.value;
  const refreshCookie = await chrome.cookies.get({ url: API_BASE, name: 'refresh_token' });
  if (!refreshCookie?.value) return null;
  await fetch(`${API_BASE}/api/refresh-token`, {
    method: 'POST',
    headers: { 'X-Refresh-Token': refreshCookie.value },
  });
  const refreshed = await chrome.cookies.get({ url: API_BASE, name: 'access_token' });
  return refreshed?.value || null;
}

async function ensurePermission(handle) {
  const query = await handle.queryPermission({ mode: 'readwrite' });
  if (query === 'granted') return true;
  const requested = await handle.requestPermission({ mode: 'readwrite' });
  return requested === 'granted';
}

async function readJsonFile(dir, name) {
  const fileHandle = await dir.getFileHandle(name);
  const file = await fileHandle.getFile();
  return JSON.parse(await file.text());
}

async function pickFolder() {
  const handle = await window.showDirectoryPicker({ id: 'ieid-order-scraper', mode: 'readwrite' });
  const manifest = await readJsonFile(handle, 'manifest.json');
  if (!isIeidExtensionManifest(manifest)) {
    throw new Error('That folder is not IEID Order Scraper. Pick the folder shown on chrome://extensions.');
  }
  await idbSet('handles', 'extensionDir', handle);
  await chrome.storage.local.set({ folderGranted: true });
  logUpdate('folder granted');
  return handle;
}

async function getUsableHandle() {
  const handle = await idbGet('handles', 'extensionDir');
  if (!handle) return null;
  try {
    if (await ensurePermission(handle)) return handle;
  } catch (err) {
    logUpdate('handle permission failed', err);
  }
  await idbDelete('handles', 'extensionDir');
  await chrome.storage.local.set({ folderGranted: false });
  return null;
}

async function fetchPackage(token) {
  const response = await fetch(`${API_BASE}/api/order-scraper/package`, {
    cache: 'no-store',
    headers: { 'X-Auth-Token': token },
  });
  if (response.status === 401) {
    const retried = await getAuthToken();
    if (!retried || retried === token) throw new Error('Sign in to IEID to update');
    return fetchPackage(retried);
  }
  if (!response.ok) throw new Error(`Package HTTP ${response.status}`);
  const payload = await response.json();
  if (!payload?.version || !payload.files || Object.keys(payload.files).length === 0) {
    throw new Error('Package file map is empty');
  }
  for (const relative of Object.keys(payload.files)) {
    if (!isSafeRelativePath(relative)) throw new Error(`Unsafe package path ${relative}`);
  }
  return payload;
}

function decodeContent(entry) {
  if (entry.encoding === 'utf-8') return entry.content;
  const binary = atob(entry.content);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

async function writeRelative(root, relative, data) {
  const parts = relative.split('/');
  let dir = root;
  for (let i = 0; i < parts.length - 1; i += 1) {
    dir = await dir.getDirectoryHandle(parts[i], { create: true });
  }
  const fileHandle = await dir.getFileHandle(parts[parts.length - 1], { create: true });
  const writable = await fileHandle.createWritable();
  await writable.write(data);
  await writable.close();
}

async function removeRelative(root, relative) {
  const parts = relative.split('/');
  let dir = root;
  for (let i = 0; i < parts.length - 1; i += 1) {
    try {
      dir = await dir.getDirectoryHandle(parts[i]);
    } catch {
      return;
    }
  }
  try {
    await dir.removeEntry(parts[parts.length - 1]);
  } catch {
    return;
  }
}

async function writeStaging(root, files) {
  try {
    await root.removeEntry(STAGING_DIR, { recursive: true });
  } catch {
    logUpdate('no previous staging dir');
  }
  const staging = await root.getDirectoryHandle(STAGING_DIR, { create: true });
  const names = Object.keys(files).sort((a, b) => {
    if (a === 'manifest.json') return 1;
    if (b === 'manifest.json') return -1;
    return a.localeCompare(b);
  });
  for (const relative of names) {
    await writeRelative(staging, relative, decodeContent(files[relative]));
  }
  logUpdate('staging written', names.length);
  return staging;
}

async function copyStagingToLive(root, staging, files, lastPackageFiles) {
  const names = Object.keys(files).sort((a, b) => {
    if (a === 'manifest.json') return 1;
    if (b === 'manifest.json') return -1;
    return a.localeCompare(b);
  });
  for (const relative of names) {
    const parts = relative.split('/');
    let sourceDir = staging;
    for (let i = 0; i < parts.length - 1; i += 1) {
      sourceDir = await sourceDir.getDirectoryHandle(parts[i]);
    }
    const sourceFile = await (await sourceDir.getFileHandle(parts[parts.length - 1])).getFile();
    const buffer = await sourceFile.arrayBuffer();
    await writeRelative(root, relative, new Uint8Array(buffer));
  }
  const incoming = new Set(Object.keys(files));
  for (const relative of lastPackageFiles || []) {
    if (incoming.has(relative)) continue;
    if ((relative === 'update.html' || relative === 'update.js') && !incoming.has(relative)) {
      continue;
    }
    await removeRelative(root, relative);
  }
  try {
    await root.removeEntry(STAGING_DIR, { recursive: true });
  } catch {
    logUpdate('could not remove staging after copy');
  }
  logUpdate('copy complete');
}

async function applyPackage(handle, payload) {
  const installed = chrome.runtime.getManifest().version;
  if (!isVersionNewer(payload.version, installed)) {
    logUpdate('package is not newer', payload.version);
    return false;
  }
  await idbSet('state', 'pendingPackage', payload);
  await chrome.storage.local.set({
    updateInProgress: true,
    updateTargetVersion: payload.version,
  });
  const staging = await writeStaging(handle, payload.files);
  const lastPackageFiles = (await idbGet('state', 'lastPackageFiles')) || [];
  await copyStagingToLive(handle, staging, payload.files, lastPackageFiles);
  await idbSet('state', 'lastPackageFiles', Object.keys(payload.files));
  await chrome.storage.local.set({
    updateInProgress: false,
    lastAttemptedVersion: payload.version,
  });
  logUpdate('reload', payload.version);
  chrome.runtime.reload();
  return true;
}

async function recoverIfNeeded(handle) {
  const local = await chrome.storage.local.get(['updateInProgress', 'updateTargetVersion']);
  if (!local.updateInProgress) return false;
  const pending = await idbGet('state', 'pendingPackage');
  if (!pending) {
    await chrome.storage.local.set({ updateInProgress: false });
    return false;
  }
  logUpdate('retrying interrupted update', pending.version);
  return applyPackage(handle, pending);
}

async function verifyAfterReload() {
  const local = await chrome.storage.local.get(['updateTargetVersion']);
  if (!local.updateTargetVersion) return;
  const installed = chrome.runtime.getManifest().version;
  if (installed === local.updateTargetVersion) {
    await chrome.storage.local.remove('updateTargetVersion');
    await idbDelete('state', 'pendingPackage');
    logUpdate('update verified', installed);
    setStatus(`Updated to v${installed}. You can close this tab.`);
    return;
  }
  logUpdate('post-reload version mismatch', { installed, target: local.updateTargetVersion });
  await idbDelete('handles', 'extensionDir');
  await chrome.storage.local.set({ folderGranted: false });
  setStatus('The selected folder is not the loaded extension folder. On chrome://extensions, find IEID Order Scraper and select that folder.', true);
  document.getElementById('pickFolderBtn').hidden = false;
}

async function start() {
  logUpdate('starting', { auto: isAuto() });
  const pickBtn = document.getElementById('pickFolderBtn');
  await verifyAfterReload();
  let handle = await getUsableHandle();
  if (!handle) {
    if (isAuto()) {
      logUpdate('auto apply skipped: no folder grant');
      window.close();
      return;
    }
    pickBtn.hidden = false;
    pickBtn.addEventListener('click', async () => {
      try {
        handle = await pickFolder();
        pickBtn.hidden = true;
        await runApply(handle);
      } catch (err) {
        logUpdate('pick failed', err);
        setStatus(err.message || String(err), true);
      }
    });
    setStatus('Select the folder you used with Load unpacked.');
    return;
  }
  await runApply(handle);
}

async function runApply(handle) {
  const tab = await chrome.tabs.getCurrent();
  const local = await chrome.storage.local.get(['updateInProgress']);
  const session = await chrome.storage.session.get('updateOwner');
  if (local.updateInProgress && session.updateOwner && session.updateOwner !== tab?.id) {
    setStatus('Updating…');
    return;
  }
  if (tab?.id) await chrome.storage.session.set({ updateOwner: tab.id });
  if (local.updateInProgress) {
    setStatus('Updating…');
    const recovered = await recoverIfNeeded(handle);
    if (recovered) return;
  }
  try {
    const token = await getAuthToken();
    if (!token) {
      setStatus('Sign in to IEID to update: https://ieidgg.com', true);
      return;
    }
    const payload = await fetchPackage(token);
    logUpdate('package fetched', payload.version);
    setStatus(`Installing v${payload.version}…`);
    await applyPackage(handle, payload);
  } catch (err) {
    logUpdate('apply failed', err);
    await chrome.storage.local.set({ updateInProgress: false });
    setStatus(err.message || String(err), true);
  }
}

document.addEventListener('DOMContentLoaded', () => {
  start().catch((err) => {
    logUpdate('start failed', err);
    setStatus(err.message || String(err), true);
  });
});
