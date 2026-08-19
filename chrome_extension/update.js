const API_BASE = 'https://ieidgg.com';
const STAGING_DIR = '.ieid-update-staging';

function logUpdate(message, extra) {
  if (extra) console.info('[IEID update]', message, extra);
  else console.info('[IEID update]', message);
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
  await chrome.storage.local.remove('lastAttemptedVersion');
  logUpdate('folder granted');
  return handle;
}

async function getUsableHandle(options = {}) {
  const allowPrompt = options.allowPrompt !== false;
  const handle = await idbGet('handles', 'extensionDir');
  if (!handle) return null;
  try {
    const query = await handle.queryPermission({ mode: 'readwrite' });
    if (query === 'granted') return handle;
    if (query === 'denied') {
      await idbDelete('handles', 'extensionDir');
      await chrome.storage.local.set({ folderGranted: false });
      return null;
    }
    if (!allowPrompt) {
      logUpdate('handle needs user gesture');
      return null;
    }
    if (await ensurePermission(handle)) return handle;
    const after = await handle.queryPermission({ mode: 'readwrite' });
    if (after === 'denied') {
      await idbDelete('handles', 'extensionDir');
      await chrome.storage.local.set({ folderGranted: false });
    }
  } catch (err) {
    logUpdate('handle permission failed', err);
  }
  return null;
}

function parsePackagedManifest(payload) {
  const entry = payload.files['manifest.json'];
  if (!entry || entry.encoding !== 'utf-8' || typeof entry.content !== 'string') {
    throw new Error('Package is missing manifest.json');
  }
  let packagedManifest;
  try {
    packagedManifest = JSON.parse(entry.content);
  } catch {
    throw new Error('Package manifest is invalid');
  }
  if (!isIeidExtensionManifest(packagedManifest)) {
    throw new Error('Package is not IEID Order Scraper');
  }
  if (String(packagedManifest.version) !== String(payload.version)) {
    throw new Error('Package version does not match manifest');
  }
  return packagedManifest;
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
  parsePackagedManifest(payload);
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
  const lastPackageFiles = (await idbGet('state', 'lastPackageFiles')) || [];
  const previousPending = await idbGet('state', 'pendingPackage');
  const previousPendingFiles = previousPending?.files ? Object.keys(previousPending.files) : [];
  await idbSet('state', 'pendingPackage', payload);
  await chrome.storage.local.set({
    updateInProgress: true,
    updateTargetVersion: payload.version,
    updateReloadPending: false,
    updateReloadAttempts: 0,
  });
  const staging = await writeStaging(handle, payload.files);
  const knownFiles = [...new Set([...lastPackageFiles, ...previousPendingFiles])];
  await copyStagingToLive(handle, staging, payload.files, knownFiles);
  await idbSet('state', 'lastPackageFiles', Object.keys(payload.files));
  logUpdate('reload', payload.version);
  await requestExtensionReload();
  return true;
}

async function recoverIfNeeded(handle) {
  const local = await chrome.storage.local.get(['updateInProgress', 'updateReloadPending']);
  if (local.updateReloadPending) {
    const session = await chrome.storage.session.get('expectingReload');
    if (session.expectingReload) {
      logUpdate('retrying extension reload');
      await requestExtensionReload();
      return true;
    }
    return false;
  }
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
  const result = await settleUpdateAfterReload();
  if (result.status === 'verified') {
    setStatus(`Updated to v${result.installed}. You can close this tab.`);
    return true;
  }
  if (result.status === 'mismatch') {
    setStatus('The selected folder is not the loaded extension folder. On chrome://extensions, find IEID Order Scraper and select that folder.', true);
    document.getElementById('pickFolderBtn').hidden = false;
    return true;
  }
  if (result.status === 'reload-pending') {
    setStatus('Updating…');
    await requestExtensionReload();
    return true;
  }
  return false;
}

async function start() {
  logUpdate('starting', { auto: isAuto() });
  const pickBtn = document.getElementById('pickFolderBtn');
  if (await verifyAfterReload()) return;
  let handle = await getUsableHandle({ allowPrompt: !isAuto() });
  if (!handle) {
    if (isAuto()) {
      logUpdate('auto apply skipped: no folder grant');
      window.close();
      return;
    }
    pickBtn.hidden = false;
    pickBtn.addEventListener('click', async () => {
      try {
        handle = await getUsableHandle({ allowPrompt: true });
        if (!handle) handle = await pickFolder();
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

async function ownerTabIsAlive(ownerId) {
  if (!ownerId) return false;
  try {
    await chrome.tabs.get(ownerId);
    return true;
  } catch {
    return false;
  }
}

async function runApply(handle) {
  const tab = await chrome.tabs.getCurrent();
  const local = await chrome.storage.local.get(['updateInProgress', 'updateReloadPending']);
  const session = await chrome.storage.session.get('updateOwner');
  if (local.updateInProgress && session.updateOwner && session.updateOwner !== tab?.id) {
    if (await ownerTabIsAlive(session.updateOwner)) {
      setStatus('Updating…');
      return;
    }
    logUpdate('stale update owner, taking over', session.updateOwner);
  }
  if (tab?.id) await chrome.storage.session.set({ updateOwner: tab.id });
  if (local.updateReloadPending || local.updateInProgress) {
    setStatus('Updating…');
    const recovered = await recoverIfNeeded(handle);
    if (recovered) return;
  }
  try {
    const token = await getAuthToken();
    if (!token) {
      setStatus('Sign in to IEID to update: https://ieidgg.com', true);
      if (isAuto()) window.close();
      return;
    }
    const payload = await fetchPackage(token);
    logUpdate('package fetched', payload.version);
    setStatus(`Installing v${payload.version}…`);
    const applied = await applyPackage(handle, payload);
    if (!applied) setStatus('Already up to date.');
  } catch (err) {
    logUpdate('apply failed', err);
    let pending = null;
    try {
      pending = await idbGet('state', 'pendingPackage');
    } catch (stateErr) {
      logUpdate('pending package lookup failed', stateErr);
    }
    await chrome.storage.local.remove('updateTargetVersion');
    if (!pending) await chrome.storage.local.set({ updateInProgress: false, updateReloadPending: false });
    setStatus(err.message || String(err), true);
    if (isAuto()) window.close();
  }
}

document.addEventListener('DOMContentLoaded', () => {
  start().catch((err) => {
    logUpdate('start failed', err);
    setStatus(err.message || String(err), true);
  });
});
