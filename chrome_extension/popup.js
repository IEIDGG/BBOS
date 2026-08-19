const $ = (id) => document.getElementById(id);
const API_BASE = 'https://ieidgg.com';
let pendingSingleOrderId = '';

function showExtensionVersion() {
  const versionEl = $('extensionVersion');
  const version = chrome.runtime.getManifest()?.version;
  if (versionEl && version) versionEl.textContent = `v${version}`;
}

async function checkForExtensionUpdate() {
  const currentVersion = chrome.runtime.getManifest()?.version;
  if (!currentVersion) return;

  try {
    const resp = await fetch(`${API_BASE}/api/order-scraper/version`, { cache: 'no-store' });
    if (!resp.ok) return;

    const data = await resp.json();
    const latestVersion = data?.version;
    if (!latestVersion || !isVersionNewer(latestVersion, currentVersion)) return;

    const stored = await chrome.storage.local.get('updateDismissedVersion');
    if (stored.updateDismissedVersion === latestVersion) return;

    const banner = $('updateBanner');
    const versionEl = $('updateLatestVersion');
    if (!banner || !versionEl) return;

    versionEl.textContent = latestVersion;
    banner.classList.remove('hidden');
  } catch (err) {
    console.error('Extension update check failed:', err);
  }
}

function showSingleOrderSection(orderId) {
  pendingSingleOrderId = orderId;
  $('pendingOrderId').textContent = orderId;
  $('singleOrderSection').classList.remove('hidden');
  $('bulkScrapeDivider').classList.remove('hidden');
  $('bulkScrapeLabel').classList.remove('hidden');
}

function hideSingleOrderSection(clearPending = true) {
  pendingSingleOrderId = '';
  $('singleOrderSection').classList.add('hidden');
  $('bulkScrapeDivider').classList.add('hidden');
  $('bulkScrapeLabel').classList.add('hidden');
  if (clearPending) {
    chrome.runtime.sendMessage({ action: 'clear_pending_single_order' });
  }
}

async function checkPendingSingleOrder() {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage({ action: 'get_pending_single_order' }, (resp) => {
      if (resp?.orderId) {
        showSingleOrderSection(resp.orderId);
      }
      resolve(resp?.orderId || '');
    });
  });
}

function setScrapingUi(running) {
  $('startBtn').disabled = running;
  $('startBtn').textContent = running ? 'Scraping...' : 'Start Scraping';
  $('scanSingleOrderBtn').disabled = running;
  $('scanSingleOrderBtn').textContent = running ? 'Scraping...' : 'Scan This Order';
  $('stopBtn').style.display = running ? 'block' : 'none';
}

async function getAuthToken() {
  const cookie = await chrome.cookies.get({ url: API_BASE, name: 'access_token' });
  if (cookie) return cookie.value;

  const refreshCookie = await chrome.cookies.get({ url: API_BASE, name: 'refresh_token' });
  if (!refreshCookie) return null;

  const refreshResp = await fetch(`${API_BASE}/api/refresh-token`, {
    method: 'POST',
    headers: { 'X-Refresh-Token': refreshCookie.value },
  });
  if (!refreshResp.ok) return null;

  const newCookie = await chrome.cookies.get({ url: API_BASE, name: 'access_token' });
  return newCookie?.value || null;
}

function showZipImportStatus(message, type = '') {
  const el = $('zipImportStatus');
  el.textContent = message || '';
  el.className = `zip-import-status${type ? ` ${type}` : ''}`;
}

async function importZipMappingsFromIeid() {
  const btn = $('importZipMappingsBtn');
  btn.disabled = true;
  showZipImportStatus('Loading zip mappings...', '');

  try {
    const token = await getAuthToken();
    if (!token) {
      showZipImportStatus('Sign in to IEID first', 'error');
      return;
    }

    const resp = await fetch(`${API_BASE}/api/settings/monitor`, {
      headers: { 'X-Auth-Token': token },
    });

    if (resp.status === 401) {
      showZipImportStatus('Session expired. Sign in to IEID again.', 'error');
      return;
    }
    if (!resp.ok) {
      showZipImportStatus('Could not load IEID zip mappings', 'error');
      return;
    }

    const data = await resp.json();
    const mappings = data.settings?.zip_mappings || {};
    const zipCodes = Object.keys(mappings)
      .map((zip) => zip.trim())
      .filter((zip) => /^\d{5}(?:-\d{4})?$/.test(zip))
      .sort();

    if (!zipCodes.length) {
      showZipImportStatus('No zip mappings found in IEID Settings', 'error');
      return;
    }

    $('zipFilters').value = zipCodes.join(', ');
    saveSettings();
    showZipImportStatus(`Imported ${zipCodes.length} zip code${zipCodes.length === 1 ? '' : 's'} from IEID`, 'success');
  } catch (error) {
    showZipImportStatus(`Error: ${error.message}`, 'error');
  } finally {
    btn.disabled = false;
  }
}

// --- Auth ---
async function checkAuth() {
  try {
    // Read cookies from ieidgg.com and pass to API
    const cookie = await chrome.cookies.get({ url: API_BASE, name: 'access_token' });
    if (!cookie) {
      showSignedOut();
      return null;
    }

    const resp = await fetch(`${API_BASE}/api/user`, {
      headers: { 'X-Auth-Token': cookie.value },
    });

    if (!resp.ok) {
      // Try refresh
      const refreshCookie = await chrome.cookies.get({ url: API_BASE, name: 'refresh_token' });
      if (refreshCookie) {
        const refreshResp = await fetch(`${API_BASE}/api/refresh-token`, {
          method: 'POST',
          headers: { 'X-Refresh-Token': refreshCookie.value },
        });
        if (refreshResp.ok) {
          // Re-check after refresh
          const newCookie = await chrome.cookies.get({ url: API_BASE, name: 'access_token' });
          if (newCookie) {
            const retryResp = await fetch(`${API_BASE}/api/user`, {
              headers: { 'X-Auth-Token': newCookie.value },
            });
            if (retryResp.ok) {
              const user = await retryResp.json();
              showSignedIn(user);
              return user;
            }
          }
        }
      }
      showSignedOut();
      return null;
    }

    const user = await resp.json();
    showSignedIn(user);
    return user;
  } catch (e) {
    console.error('Auth check failed:', e);
    showSignedOut();
    return null;
  }
}

function showSignedIn(user) {
  $('authSection').classList.add('hidden');
  $('userInfo').classList.remove('hidden');
  $('scrapeSection').style.display = 'block';
  $('userEmail').textContent = user.email || user.name || 'Signed in';
}

function showSignedOut() {
  $('authSection').classList.remove('hidden');
  $('userInfo').classList.add('hidden');
  $('scrapeSection').style.display = 'none';
}

$('signInBtn').addEventListener('click', () => {
  chrome.tabs.create({ url: `${API_BASE}/login` }, (tab) => {
    // Poll for login completion
    const interval = setInterval(async () => {
      const cookie = await chrome.cookies.get({ url: API_BASE, name: 'access_token' });
      if (cookie) {
        clearInterval(interval);
        checkAuth();
      }
    }, 2000);
    // Stop polling after 5 minutes
    setTimeout(() => clearInterval(interval), 300000);
  });
});

$('signOutBtn').addEventListener('click', async () => {
  await chrome.cookies.remove({ url: API_BASE, name: 'access_token' });
  await chrome.cookies.remove({ url: API_BASE, name: 'refresh_token' });
  showSignedOut();
});

// --- Settings ---
const SETTINGS_KEYS = ['yearFilter', 'maxPages', 'fetchTracking', 'useDbCache', 'zipFilters', 'lastAmazonEmail'];

async function loadSettings() {
  const data = await chrome.storage.local.get(SETTINGS_KEYS);
  if (data.yearFilter) $('yearFilter').value = data.yearFilter;
  if (data.maxPages !== undefined) $('maxPages').value = data.maxPages;
  if (data.fetchTracking !== undefined) $('fetchTracking').checked = data.fetchTracking;
  if (data.useDbCache !== undefined) $('useDbCache').checked = data.useDbCache;
  if (data.zipFilters !== undefined) $('zipFilters').value = data.zipFilters;
  if (data.lastAmazonEmail) $('amazonAccountEmail').textContent = data.lastAmazonEmail;
}

function saveSettings() {
  chrome.storage.local.set({
    yearFilter: $('yearFilter').value,
    maxPages: parseInt($('maxPages').value) || 0,
    fetchTracking: $('fetchTracking').checked,
    useDbCache: $('useDbCache').checked,
    zipFilters: $('zipFilters').value,
  });
}

// --- Logging & Progress ---
function renderLogEntry(msg, type = '', time) {
  const el = $('log');
  el.style.display = 'block';
  const entry = document.createElement('div');
  entry.className = `log-entry ${type}`;
  const timeStr = (time ? new Date(time) : new Date()).toLocaleTimeString();
  entry.textContent = `${timeStr} ${msg}`;
  el.appendChild(entry);
  el.scrollTop = el.scrollHeight;
}

function renderLogs(logs) {
  const el = $('log');
  if (!logs?.length) return;
  el.innerHTML = '';
  el.style.display = 'block';
  for (const entry of logs) {
    renderLogEntry(entry.text, entry.level || '', entry.time);
  }
  el.scrollTop = el.scrollHeight;
}

function log(msg, type = '') {
  renderLogEntry(msg, type);
}

function updateProgress(pct, text) {
  $('progress').style.display = 'block';
  $('progressFill').style.width = `${pct}%`;
  $('progressText').textContent = text;
}

function updateStats(orders, shipments, tracked, sent, cancelled, skippedCached) {
  $('stats').style.display = 'grid';
  $('statOrders').textContent = orders;
  $('statShipments').textContent = shipments;
  $('statTracking').textContent = tracked;
  $('statSent').textContent = sent;
  $('statCancelled').textContent = cancelled || 0;
  $('statSkipped').textContent = skippedCached || 0;
}

// --- Messages from background ---
chrome.runtime.onMessage.addListener((msg) => {
  if (msg.type === 'scrape_log') log(msg.text, msg.level || '');
  if (msg.type === 'scrape_progress') updateProgress(msg.pct, msg.text);
  if (msg.type === 'scrape_stats') updateStats(msg.orders, msg.shipments, msg.tracked, msg.sent, msg.cancelled, msg.skippedCached);
  if (msg.type === 'amazon_account') {
    $('amazonAccountEmail').textContent = msg.email || 'Not detected';
    if (msg.email) chrome.storage.local.set({ lastAmazonEmail: msg.email });
  }
  if (msg.type === 'scrape_done') {
    setScrapingUi(false);
    if (msg.success) {
      hideSingleOrderSection(true);
    }
  }
});

// --- Start / Stop ---
$('startBtn').addEventListener('click', async () => {
  saveSettings();
  setScrapingUi(true);
  $('log').innerHTML = '';
  $('log').style.display = 'block';

  chrome.runtime.sendMessage({
    action: 'start_scrape',
    config: {
      yearFilter: $('yearFilter').value,
      maxPages: parseInt($('maxPages').value) || 0,
      fetchTracking: $('fetchTracking').checked,
      useDbCache: $('useDbCache').checked,
      zipFilters: $('zipFilters').value,
    },
  });
});

$('scanSingleOrderBtn').addEventListener('click', async () => {
  if (!pendingSingleOrderId) return;

  saveSettings();
  setScrapingUi(true);
  $('log').innerHTML = '';
  $('log').style.display = 'block';

  chrome.runtime.sendMessage({
    action: 'start_single_order_scrape',
    config: {
      orderId: pendingSingleOrderId,
      fetchTracking: $('fetchTracking').checked,
      useDbCache: $('useDbCache').checked,
      zipFilters: $('zipFilters').value,
    },
  });
});

$('dismissSingleOrderBtn').addEventListener('click', () => {
  hideSingleOrderSection(true);
});

$('viewLogBtn').addEventListener('click', () => {
  chrome.runtime.sendMessage({ action: 'open_log_tab' });
});

$('importZipMappingsBtn').addEventListener('click', () => {
  importZipMappingsFromIeid();
});

$('stopBtn').addEventListener('click', () => {
  chrome.runtime.sendMessage({ action: 'stop_scrape' });
  setScrapingUi(false);
});

$('updateBtn').addEventListener('click', () => {
  chrome.tabs.create({ url: chrome.runtime.getURL('update.html') });
});

$('dismissUpdateBtn').addEventListener('click', async () => {
  const banner = $('updateBanner');
  const latestVersion = $('updateLatestVersion')?.textContent;
  banner.classList.add('hidden');
  if (latestVersion) {
    await chrome.storage.local.set({ updateDismissedVersion: latestVersion });
  }
});

showExtensionVersion();
checkForExtensionUpdate();
loadSettings();
checkAuth();
checkPendingSingleOrder();

chrome.runtime.sendMessage({ action: 'scrape_status' }, (resp) => {
  if (!resp) return;

  if (resp.logs?.length) {
    renderLogs(resp.logs);
  }

  if (resp.pct || resp.statusText) {
    updateProgress(resp.pct || 0, resp.statusText || '');
  }

  if (resp.orders || resp.shipments || resp.tracked || resp.sent || resp.cancelled || resp.skippedCached) {
    updateStats(resp.orders || 0, resp.shipments || 0, resp.tracked || 0, resp.sent || 0, resp.cancelled || 0, resp.skippedCached || 0);
  }

  if (resp.running) {
    setScrapingUi(true);
  }
});
