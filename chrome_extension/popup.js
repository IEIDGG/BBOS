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
    const stored = await chrome.storage.local.get(['updateDismissedVersion', 'folderNeedsReconnect']);
    const reconnectBanner = $('reconnectBanner');
    if (reconnectBanner) {
      reconnectBanner.classList.toggle('hidden', !stored.folderNeedsReconnect);
    }

    const resp = await fetch(`${API_BASE}/api/order-scraper/version`, { cache: 'no-store' });
    if (!resp.ok) return;

    const data = await resp.json();
    const latestVersion = data?.version;
    if (!latestVersion || !isVersionNewer(latestVersion, currentVersion)) return;
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
  const updateBtn = $('updateBtn');
  if (updateBtn) {
    updateBtn.disabled = running;
    updateBtn.textContent = running ? 'Wait for scrape' : 'Update';
  }
}

async function getAuthToken(forceRefresh = false) { return IEIDAuth.getToken(forceRefresh); }

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
    let token = await getAuthToken();
    if (!token) {
      showZipImportStatus('Sign in to IEID first', 'error');
      return;
    }

    const fetchMonitor = (authToken) => fetch(`${API_BASE}/api/settings/monitor`, {
      credentials: 'omit',
      headers: { 'X-Auth-Token': authToken },
    });

    let resp = await fetchMonitor(token);
    if (resp.status === 401) {
      const retried = await getAuthToken(true);
      if (!retried || retried === token) {
        showZipImportStatus('Session expired. Sign in to IEID again.', 'error');
        return;
      }
      resp = await fetchMonitor(retried);
    }
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
    const token = await IEIDAuth.getToken();
    if (!token) { showSignedOut(); return null; }
    const response = await fetch(`${API_BASE}/api/user`);
    if (!response.ok) { showSignedOut(); return null; }
    const user = await response.json(); showSignedIn(user); return user;
  } catch { showSignedOut(); return null; }
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

$('signInBtn').addEventListener('click', async () => {
  $('authStatus').textContent = '';
  try {
    await IEIDAuth.connect();
    const interval = setInterval(async () => {if (await checkAuth()) clearInterval(interval);}, 2000);
    setTimeout(() => clearInterval(interval), 300000);
  } catch { $('authStatus').textContent = 'Unable to connect on the server. Try again.'; }
});

$('signOutBtn').addEventListener('click', async () => {
  const button = $('signOutBtn'); button.disabled = true;
  $('authStatus').textContent = '';
  try { await IEIDAuth.disconnect(); showSignedOut(); }
  catch { $('authStatus').textContent = 'Unable to sign out on the server. Try again.'; }
  finally { button.disabled = false; }
});

// --- Settings ---
const SETTINGS_KEYS = ['yearFilter', 'maxPages', 'fetchTracking', 'useDbCache', 'useShipmentCache', 'zipFilters', 'lastAmazonEmail'];

async function loadSettings() {
  const data = await chrome.storage.local.get(SETTINGS_KEYS);
  const currentYear = new Date().getFullYear();
  const savedYear = /^year-(\d{4})$/.exec(data.yearFilter || '')?.[1];
  const oldestYear = Math.min(currentYear - 12, Number(savedYear) || currentYear);
  for (let year = currentYear; year >= oldestYear; year--) {
    const option = document.createElement('option');
    option.value = `year-${year}`;
    option.textContent = String(year);
    $('yearFilter').appendChild(option);
  }
  if (data.yearFilter) $('yearFilter').value = data.yearFilter;
  if (data.maxPages !== undefined) $('maxPages').value = data.maxPages;
  if (data.fetchTracking !== undefined) $('fetchTracking').checked = data.fetchTracking;
  if (data.useDbCache !== undefined) $('useDbCache').checked = data.useDbCache;
  if (data.useShipmentCache !== undefined) $('useShipmentCache').checked = data.useShipmentCache;
  if (data.zipFilters !== undefined) $('zipFilters').value = data.zipFilters;
  if (data.lastAmazonEmail) $('amazonAccountEmail').textContent = data.lastAmazonEmail;
  updateHistoryRangeHint();
}

function updateHistoryRangeHint() {
  const limited = Number($('maxPages').value) > 0;
  $('historyRangeHint').textContent = limited
    ? `Limited to ${$('maxPages').value} pages across the range. Set 0 to fetch the entire selected range.`
    : $('yearFilter').value === 'months-12'
    ? "Scans both calendar years for the past 12 months. Amazon's 3-month page default does not apply."
    : 'Scans every page in the selected calendar year.';
}

$('maxPages').addEventListener('input', updateHistoryRangeHint);
$('yearFilter').addEventListener('change', updateHistoryRangeHint);

function saveSettings() {
  chrome.storage.local.set({
    yearFilter: $('yearFilter').value,
    maxPages: parseInt($('maxPages').value) || 0,
    fetchTracking: $('fetchTracking').checked,
    useDbCache: $('useDbCache').checked,
    useShipmentCache: $('useShipmentCache').checked,
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
async function sendScanCommand(message) {
  try {
    const response = await chrome.runtime.sendMessage(message);
    if (!response?.ok) {
      setScrapingUi(Boolean(response?.running));
      log(response?.error || 'Unable to start the order scan. Try again.', 'error');
      return;
    }
    setScrapingUi(Boolean(response.running));
  } catch (err) {
    setScrapingUi(false);
    log(err.message || String(err), 'error');
  }
}

$('startBtn').addEventListener('click', async () => {
  saveSettings();
  setScrapingUi(true);
  $('log').innerHTML = '';
  $('log').style.display = 'block';

  await sendScanCommand({
    action: 'start_scrape',
    config: {
      yearFilter: $('yearFilter').value,
      maxPages: parseInt($('maxPages').value) || 0,
      fetchTracking: $('fetchTracking').checked,
      useDbCache: $('useDbCache').checked,
    useShipmentCache: $('useShipmentCache').checked,
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

  await sendScanCommand({
    action: 'start_single_order_scrape',
    config: {
      orderId: pendingSingleOrderId,
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
  chrome.runtime.sendMessage({ action: 'scrape_status' }, (resp) => {
    if (chrome.runtime.lastError) {
      chrome.tabs.create({ url: chrome.runtime.getURL('update.html') });
      return;
    }
    if (resp?.running) {
      $('updateBtn').disabled = true;
      $('updateBtn').textContent = 'Wait for scrape';
      return;
    }
    chrome.tabs.create({ url: chrome.runtime.getURL('update.html') });
  });
});

$('reconnectFolderBtn')?.addEventListener('click', () => {
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

// Native buttons keep explanations accessible by keyboard and touch.
document.querySelectorAll('.info-button').forEach(button => {
  button.addEventListener('click', () => {
    const panel = document.getElementById(button.getAttribute('aria-controls'));
    const expanded = button.getAttribute('aria-expanded') === 'true';
    button.setAttribute('aria-expanded', String(!expanded));
    panel.hidden = expanded;
  });
});
