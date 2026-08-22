const UPDATE_DB_NAME = 'ieid-order-scraper-updates';

function isVersionNewer(latest, current) {
  const parse = (version) => String(version || '0').replace(/^v/, '').split('.').map((part) => parseInt(part, 10) || 0);
  const latestParts = parse(latest);
  const currentParts = parse(current);
  const length = Math.max(latestParts.length, currentParts.length);
  for (let index = 0; index < length; index += 1) {
    const latestValue = latestParts[index] || 0;
    const currentValue = currentParts[index] || 0;
    if (latestValue > currentValue) return true;
    if (latestValue < currentValue) return false;
  }
  return false;
}

function isSafeRelativePath(relative) {
  if (!relative || relative.startsWith('/') || relative.includes('\\')) return false;
  const parts = relative.split('/');
  return parts.every((part) => part && part !== '.' && part !== '..');
}

function isIeidExtensionManifest(manifest) {
  return Boolean(manifest && manifest.name === 'IEID Order Scraper');
}

function openUpdateDb() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(UPDATE_DB_NAME, 1);
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
  return openUpdateDb().then((db) => new Promise((resolve, reject) => {
    const request = db.transaction(store, 'readonly').objectStore(store).get(key);
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  }));
}

function idbSet(store, key, value) {
  return openUpdateDb().then((db) => new Promise((resolve, reject) => {
    const request = db.transaction(store, 'readwrite').objectStore(store).put(value, key);
    request.onsuccess = () => resolve();
    request.onerror = () => reject(request.error);
  }));
}

function idbDelete(store, key) {
  return openUpdateDb().then((db) => new Promise((resolve, reject) => {
    const request = db.transaction(store, 'readwrite').objectStore(store).delete(key);
    request.onsuccess = () => resolve();
    request.onerror = () => reject(request.error);
  }));
}

async function requestExtensionReload() {
  const local = await chrome.storage.local.get([
    'updateReloadAttempts',
    'updateReloadRequestedAt',
  ]);
  const now = Date.now();
  if (local.updateReloadRequestedAt && now - local.updateReloadRequestedAt < 3000) {
    console.info('[IEID update] reload already requested');
    return;
  }
  const attempts = (local.updateReloadAttempts || 0) + 1;
  await chrome.storage.session.set({ expectingReload: true });
  await chrome.storage.local.set({
    updateReloadPending: true,
    updateReloadAttempts: attempts,
    updateReloadRequestedAt: now,
  });
  console.info('[IEID update] runtime reload', attempts);
  chrome.runtime.reload();
}

async function settleUpdateAfterReload() {
  const local = await chrome.storage.local.get([
    'updateTargetVersion',
    'updateInProgress',
    'updateReloadPending',
    'updateReloadAttempts',
    'lastAttemptedVersion',
  ]);
  const target = local.updateTargetVersion;
  if (!target) return { status: 'idle' };
  const installed = chrome.runtime.getManifest().version;
  if (installed === target) {
    await chrome.storage.local.set({
      updateInProgress: false,
      updateReloadPending: false,
      updateReloadAttempts: 0,
      lastAttemptedVersion: installed,
    });
    await chrome.storage.local.remove(['updateTargetVersion', 'updateReloadRequestedAt']);
    try {
      await idbDelete('state', 'pendingPackage');
    } catch (err) {
      console.info('[IEID update] pending package clear failed', err);
    }
    console.info('[IEID update] update verified', installed);
    try {
      await chrome.storage.session.remove('expectingReload');
    } catch (err) {
      console.info('[IEID update] expectingReload clear failed', err);
    }
    return { status: 'verified', installed };
  }
  if (!local.updateReloadPending) {
    return { status: 'in-progress', installed, target };
  }
  let expectingReload = false;
  try {
    const session = await chrome.storage.session.get('expectingReload');
    expectingReload = Boolean(session.expectingReload);
  } catch (err) {
    console.info('[IEID update] expectingReload lookup failed', err);
  }
  const attempts = local.updateReloadAttempts || 0;
  if (expectingReload && attempts < 2) {
    console.info('[IEID update] reload still pending', { installed, target, attempts });
    return { status: 'reload-pending', installed, target };
  }
  console.info('[IEID update] post-reload version mismatch', { installed, target, attempts });
  try {
    await idbDelete('handles', 'extensionDir');
  } catch (err) {
    console.info('[IEID update] handle clear failed', err);
  }
  await chrome.storage.local.set({
    folderGranted: false,
    updateInProgress: false,
    updateReloadPending: false,
    updateReloadAttempts: 0,
    lastAttemptedVersion: target,
  });
  await chrome.storage.local.remove(['updateTargetVersion', 'updateReloadRequestedAt']);
  try {
    await chrome.storage.session.remove('expectingReload');
  } catch (err) {
    console.info('[IEID update] expectingReload clear failed', err);
  }
  return { status: 'mismatch', installed, target };
}
