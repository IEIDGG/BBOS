importScripts('update_helpers.js');

const API_BASE = 'https://ieidgg.com';
const UPDATE_CHECK_ALARM = 'extensionUpdateCheck';

async function checkExtensionVersion() {
  try {
    const response = await fetch(`${API_BASE}/api/order-scraper/version`, { cache: 'no-store' });
    if (!response.ok) {
      console.info('[IEID update] version check skipped', response.status);
      return null;
    }
    const data = await response.json();
    return data.version || null;
  } catch (err) {
    console.info('[IEID update] version check failed', err);
    return null;
  }
}

async function maybeAutoApplyUpdate() {
  const latest = await checkExtensionVersion();
  const current = chrome.runtime.getManifest().version;
  if (!latest || !isVersionNewer(latest, current)) {
    await chrome.action.setBadgeText({ text: '' });
    return;
  }
  await chrome.action.setBadgeText({ text: '1' });
  await chrome.action.setBadgeBackgroundColor({ color: '#7a6520' });
  const stored = await chrome.storage.local.get([
    'folderGranted',
    'updateInProgress',
    'lastAttemptedVersion',
  ]);
  if (scrapeState.running) {
    console.info('[IEID update] deferring apply while scrape running');
    return;
  }
  if (!stored.folderGranted || stored.updateInProgress) return;
  if (stored.lastAttemptedVersion === latest) return;
  console.info('[IEID update] opening auto apply tab', latest);
  chrome.tabs.create({ url: chrome.runtime.getURL('update.html?auto=1'), active: false });
}

const MAX_SCRAPE_LOGS = 500;
const TRACKING_TAB_CONCURRENCY = 4;
const TRACKING_TAB_CONCURRENCY_REDUCED = 2;
const TRACKING_BATCH_TIMEOUT_MS = 45000;
const TAB_LOAD_BUFFER_MS = 700;
const ORDER_PAGE_DELAY_MIN_MS = 400;
const ORDER_PAGE_DELAY_MAX_MS = 800;
const KEEP_ALIVE_ALARM = 'scrapeKeepAlive';
const LOG_PAGE = 'log.html';

let scrapeState = { running: false, stopped: false, pct: 0, statusText: '', orders: 0, shipments: 0, tracked: 0, sent: 0, failed: 0, cancelled: 0, skippedCached: 0 };
let scrapeLogs = [];
let logTabId = null;
async function ensureUpdateCheckAlarm() {
  try {
    const alarm = await chrome.alarms.get(UPDATE_CHECK_ALARM);
    if (!alarm) {
      await chrome.alarms.create(UPDATE_CHECK_ALARM, { periodInMinutes: 60 });
      console.info('[IEID update] update check alarm created');
    }
  } catch (err) {
    console.info('[IEID update] update check alarm setup failed', err);
  }
}

ensureUpdateCheckAlarm();
maybeAutoApplyUpdate();

const scrapeLogsReady = chrome.storage.session.get('scrapeLogs').then((data) => {
  scrapeLogs = data.scrapeLogs || [];
});

function notify(type, data) {
  chrome.runtime.sendMessage({ type, ...data }).catch(() => {});
}

async function saveScrapeLogs() {
  try {
    await chrome.storage.session.set({ scrapeLogs });
  } catch (err) {
    console.error('Failed to save scrape logs:', err);
  }
}

function clearScrapeLogs() {
  scrapeLogs = [];
  saveScrapeLogs();
}

function log(text, level = '') {
  scrapeLogs.push({ time: Date.now(), text, level });
  if (scrapeLogs.length > MAX_SCRAPE_LOGS) {
    scrapeLogs = scrapeLogs.slice(-MAX_SCRAPE_LOGS);
  }
  saveScrapeLogs();
  notify('scrape_log', { text, level });
}

function scrapeDone(text, success) {
  log(text, success ? 'success' : 'error');
  notify('scrape_done', { text, success });
  stopScrapeKeepAlive();
  scrapeState.running = false;
  maybeAutoApplyUpdate();
}

function progress(pct, text) {
  scrapeState.pct = pct;
  scrapeState.statusText = text;
  notify('scrape_progress', { pct, text });
}

function stats() {
  notify('scrape_stats', {
    orders: scrapeState.orders,
    shipments: scrapeState.shipments,
    tracked: scrapeState.tracked,
    sent: scrapeState.sent,
    cancelled: scrapeState.cancelled,
    skippedCached: scrapeState.skippedCached,
  });
}

function withTimeout(promise, ms, label) {
  return Promise.race([
    promise,
    new Promise((_, reject) => {
      setTimeout(() => reject(new Error(`${label} timed out after ${Math.round(ms / 1000)}s`)), ms);
    }),
  ]);
}

function startScrapeKeepAlive() {
  chrome.alarms.create(KEEP_ALIVE_ALARM, { periodInMinutes: 1 });
}

function stopScrapeKeepAlive() {
  chrome.alarms.clear(KEEP_ALIVE_ALARM);
}

async function openLogTab() {
  const logUrl = chrome.runtime.getURL(LOG_PAGE);

  if (logTabId) {
    try {
      const tab = await chrome.tabs.get(logTabId);
      if (tab?.id) {
        await chrome.tabs.update(logTabId, { active: false, url: logUrl });
        return;
      }
    } catch {
      logTabId = null;
    }
  }

  return new Promise((resolve) => {
    chrome.tabs.create({ url: logUrl, active: false }, (tab) => {
      if (chrome.runtime.lastError || !tab?.id) {
        console.error('[IEID] Could not open log tab:', chrome.runtime.lastError?.message);
        resolve(null);
        return;
      }
      logTabId = tab.id;
      resolve(tab.id);
    });
  });
}

// Get the access_token cookie for authenticated API calls
async function getAuthCookie() {
  const cookie = await chrome.cookies.get({ url: API_BASE, name: 'access_token' });
  if (cookie) return cookie.value;

  // Try refresh
  const refreshCookie = await chrome.cookies.get({ url: API_BASE, name: 'refresh_token' });
  if (!refreshCookie) return null;

  try {
    await fetch(`${API_BASE}/api/refresh-token`, {
      method: 'POST',
      headers: { 'X-Refresh-Token': refreshCookie.value },
    });
    const newCookie = await chrome.cookies.get({ url: API_BASE, name: 'access_token' });
    return newCookie?.value || null;
  } catch {
    return null;
  }
}

async function apiPost(path, body) {
  const token = await getAuthCookie();
  if (!token) throw new Error('Not authenticated. Please sign in again.');

  const resp = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Auth-Token': token,
    },
    body: JSON.stringify(body),
  });

  if (resp.status === 401) throw new Error('Session expired. Please sign in again.');
  if (!resp.ok) {
    const errText = await resp.text();
    throw new Error(`API ${resp.status}: ${errText}`);
  }
  return resp.json();
}

async function apiGet(path) {
  const token = await getAuthCookie();
  if (!token) throw new Error('Not authenticated. Please sign in again.');

  const resp = await fetch(`${API_BASE}${path}`, {
    headers: { 'X-Auth-Token': token },
  });

  if (resp.status === 401) throw new Error('Session expired. Please sign in again.');
  if (!resp.ok) {
    const errText = await resp.text();
    throw new Error(`API ${resp.status}: ${errText}`);
  }
  return resp.json();
}

function normalizeTrackingList(value) {
  if (!value) return [];
  if (Array.isArray(value)) {
    return value.map((entry) => String(entry || '').trim()).filter(Boolean);
  }
  return String(value).split(/[;,\n]/).map((entry) => entry.trim()).filter(Boolean);
}

function buildDbCacheKey(orderId, asin, productName) {
  const oid = String(orderId || '').trim();
  const asinNorm = String(asin || '').trim().toUpperCase();
  if (oid && asinNorm) return `${oid}|${asinNorm}`;
  const name = normalizeComparable(productName || '');
  if (oid && name) return `${oid}|name:${name}`;
  return oid;
}

function buildDbShipmentCache(orders) {
  const cache = new Map();
  for (const row of orders || []) {
    const tracking = normalizeTrackingList(row.tracking_number);
    if (!tracking.length) continue;
    const key = buildDbCacheKey(row.order_id, row.asin, row.product_name);
    if (!key) continue;
    if (!cache.has(key)) {
      cache.set(key, {
        tracking_number: tracking[0],
        carrier: row.carrier || '',
        order_status: row.order_status || '',
        shipment_status: row.shipment_status || '',
      });
    }
  }
  return cache;
}

async function loadDbShipmentCache() {
  try {
    const result = await apiGet('/api/orders/amazon');
    const orders = result.orders || [];
    const cache = buildDbShipmentCache(orders);
    log(`Loaded ${cache.size} tracked shipments from IEID cache (${orders.length} rows)`, 'info');
    return cache;
  } catch (err) {
    log(`Could not load IEID cache: ${err.message}. Scanning all shipments.`, 'error');
    return null;
  }
}

function applyDbCacheToShipment(order, shipment, cache) {
  if (!cache?.size) return false;
  const key = buildDbCacheKey(order.orderId, shipment.asin, shipment.productTitle);
  const cached = cache.get(key);
  if (!cached?.tracking_number) return false;

  shipment.trackingNumber = cached.tracking_number;
  if (cached.carrier && !shipment.carrier) shipment.carrier = cached.carrier;
  shipment.skipTrackingFetch = true;
  scrapeState.skippedCached++;

  const asinLabel = shipment.asin ? ` ${shipment.asin}` : '';
  log(`  ${order.orderId}${asinLabel} -> skipped (cached tracking ${cached.tracking_number})`, 'info');
  return true;
}

function applyDbCacheToOrders(allOrders, cache) {
  if (!cache?.size) return 0;

  scrapeState.skippedCached = 0;
  let applied = 0;
  for (const order of allOrders) {
    for (const shipment of order.shipments || []) {
      if (applyDbCacheToShipment(order, shipment, cache)) applied++;
    }
  }
  stats();
  return applied;
}

// Create a tab navigated to a URL and wait for it to load
function openTab(url) {
  return new Promise((resolve, reject) => {
    chrome.tabs.create({ url, active: false }, (tab) => {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message));
        return;
      }
      if (!tab?.id) {
        reject(new Error('Failed to create tab'));
        return;
      }

      const tabId = tab.id;
      let settled = false;

      function finish(result) {
        if (settled) return;
        settled = true;
        chrome.tabs.onUpdated.removeListener(onUpdated);
        resolve(result);
      }

      function onUpdated(updatedId, info) {
        if (updatedId === tabId && info.status === 'complete') {
          finish(tabId);
        }
      }

      chrome.tabs.onUpdated.addListener(onUpdated);
      setTimeout(() => finish(tabId), 15000);
    });
  });
}

function closeTab(tabId) {
  return new Promise((resolve) => {
    if (!tabId) {
      resolve();
      return;
    }
    chrome.tabs.remove(tabId, () => {
      if (chrome.runtime.lastError) {
        console.error('[IEID] closeTab failed:', chrome.runtime.lastError.message);
      }
      resolve();
    });
  });
}

async function injectAndRun(tabId, file) {
  const results = await chrome.scripting.executeScript({
    target: { tabId },
    files: [file],
  });
  return results?.[0]?.result;
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

async function waitForTabReady() {
  await sleep(TAB_LOAD_BUFFER_MS);
}

function randomOrderPageDelay() {
  return ORDER_PAGE_DELAY_MIN_MS + Math.random() * (ORDER_PAGE_DELAY_MAX_MS - ORDER_PAGE_DELAY_MIN_MS);
}

function isShipTrackUrl(url) {
  if (!url) return false;
  try {
    const parsed = new URL(url);
    return parsed.hostname.includes('amazon.com') && parsed.pathname.includes('ship-track');
  } catch {
    return false;
  }
}

function normalizeTrackingUrl(url) {
  if (!url) return '';

  try {
    const trackingUrl = new URL(url);
    if (!trackingUrl.hostname.includes('amazon.com') || !trackingUrl.pathname.includes('ship-track')) {
      return '';
    }
    if (trackingUrl.pathname.includes('/your-orders/pop')) {
      return '';
    }
    trackingUrl.searchParams.set('ref', 'ppx_yo2ov_dt_b_track_package');
    trackingUrl.searchParams.set('noPtRedirect', '1');
    return trackingUrl.toString();
  } catch {
    return '';
  }
}

function getTrackingItemId(shipment) {
  if (shipment.itemId) return shipment.itemId;
  if (!shipment.lineItemId) return '';
  return shipment.lineItemId.endsWith('s') ? shipment.lineItemId.slice(0, -1) : shipment.lineItemId;
}

function buildTrackingUrl(order, shipment) {
  const normalizedExistingUrl = normalizeTrackingUrl(shipment.trackingUrl);
  if (normalizedExistingUrl) return normalizedExistingUrl;

  const itemId = getTrackingItemId(shipment);
  if (!itemId || !shipment.shipmentId) return '';

  const params = new URLSearchParams({
    itemId,
    orderId: order.orderId,
    shipmentId: shipment.shipmentId,
    packageIndex: '0',
    noPtRedirect: '1',
    ref: 'ppx_yo2ov_dt_b_track_package',
  });

  return `https://www.amazon.com/gp/your-account/ship-track?${params.toString()}`;
}

function getTrackingFetchKey(order, shipment, trackUrl) {
  const normalized = normalizeTrackingUrlForKey(trackUrl);
  try {
    const parsed = new URL(normalized.includes('://') ? normalized : `https://www.amazon.com${normalized}`);
    const orderId = parsed.searchParams.get('orderId') || order.orderId || '';
    const shipmentId = parsed.searchParams.get('shipmentId') || shipment.shipmentId || '';
    if (orderId && shipmentId) return `shipment:${orderId}|${shipmentId}`;
  } catch {}

  return normalized || trackUrl;
}

function buildTrackingFetchGroups(allOrders) {
  const noUrlTargets = [];
  const groupMap = new Map();
  let shipmentIndex = 0;

  for (const order of allOrders) {
    for (const shipment of order.shipments) {
      if (shipment.skipTrackingFetch) continue;
      if (!(shipment.trackingUrl || (shipment.shipmentId && (shipment.lineItemId || shipment.itemId)))) {
        continue;
      }

      const target = { order, shipment, shipmentIndex };
      shipmentIndex++;

      const trackUrl = buildTrackingUrl(order, shipment);
      if (!trackUrl) {
        noUrlTargets.push(target);
        continue;
      }

      const key = getTrackingFetchKey(order, shipment, trackUrl);
      let group = groupMap.get(key);
      if (!group) {
        group = { trackUrl, targets: [] };
        groupMap.set(key, group);
      }
      group.targets.push(target);
    }
  }

  return { groups: Array.from(groupMap.values()), noUrlTargets, shipmentCount: shipmentIndex };
}

function normalizeComparable(value) {
  return String(value || '').replace(/\s+/g, ' ').trim().toLowerCase();
}

function normalizeTrackingUrlForKey(value) {
  if (!value) return '';

  try {
    const trackingUrl = new URL(value);
    if (trackingUrl.hostname.includes('amazon.com') && trackingUrl.pathname.includes('/gp/your-account/ship-track')) {
      const params = new URLSearchParams();
      for (const key of ['orderId', 'shipmentId', 'lineItemId', 'itemId', 'packageId', 'packageIndex']) {
        const paramValue = trackingUrl.searchParams.get(key);
        if (paramValue) params.set(key, paramValue);
      }
      return `${trackingUrl.origin}${trackingUrl.pathname}?${params.toString()}`;
    }
    trackingUrl.hash = '';
    return trackingUrl.toString();
  } catch {
    return normalizeComparable(value);
  }
}

function getShipmentIdentity(order, shipment) {
  if (shipment.asin) {
    const itemId = getTrackingItemId(shipment);
    const shipmentPart = shipment.shipmentId || shipment.packageId || '';
    if (shipmentPart || itemId) {
      return ['line', order.orderId || '', shipment.asin, shipmentPart, itemId].join('|');
    }
    return ['line', order.orderId || '', shipment.asin].join('|');
  }

  const trackingUrl = normalizeTrackingUrlForKey(shipment.trackingUrl || '');
  if (trackingUrl) return ['tracking-url', order.orderId || '', trackingUrl].join('|');

  const trackingNumber = normalizeComparable(shipment.trackingNumber || '');
  if (trackingNumber) return ['tracking-number', order.orderId || '', trackingNumber].join('|');

  return [
    'product',
    order.orderId || '',
    normalizeComparable(shipment.productTitle || ''),
  ].join('|');
}

function mergeShipment(existing, incoming) {
  if (incoming.quantity > (existing.quantity || 1)) existing.quantity = incoming.quantity;
  if (!existing.status && incoming.status) existing.status = incoming.status;
  if (!existing.statusDetail && incoming.statusDetail) existing.statusDetail = incoming.statusDetail;
  if (!existing.asin && incoming.asin) existing.asin = incoming.asin;
  if (!existing.productTitle && incoming.productTitle) existing.productTitle = incoming.productTitle;
  if (!existing.itemImage && incoming.itemImage) existing.itemImage = incoming.itemImage;
  if (!existing.unitPrice && incoming.unitPrice) existing.unitPrice = incoming.unitPrice;
  if (!existing.trackingUrl && incoming.trackingUrl) existing.trackingUrl = incoming.trackingUrl;
  if (!existing.trackingNumber && incoming.trackingNumber) existing.trackingNumber = incoming.trackingNumber;
  if (!existing.carrier && incoming.carrier) existing.carrier = incoming.carrier;
  if (!existing.shipmentId && incoming.shipmentId) existing.shipmentId = incoming.shipmentId;
  if (!existing.itemId && incoming.itemId) existing.itemId = incoming.itemId;
  if (!existing.lineItemId && incoming.lineItemId) existing.lineItemId = incoming.lineItemId;
  if (!existing.packageId && incoming.packageId) existing.packageId = incoming.packageId;
  if ((!existing.trackingEvents || !existing.trackingEvents.length) && incoming.trackingEvents?.length) {
    existing.trackingEvents = incoming.trackingEvents;
  }
}

function dedupeOrderShipments(order) {
  const shipments = order.shipments || [];
  const deduped = [];
  const byKey = new Map();

  for (const shipment of shipments) {
    const key = getShipmentIdentity(order, shipment);
    const existing = byKey.get(key);
    if (existing) {
      mergeShipment(existing, shipment);
      continue;
    }

    byKey.set(key, shipment);
    deduped.push(shipment);
  }

  order.shipments = deduped;
  return shipments.length - deduped.length;
}

function dedupePayloadLineItems(rows) {
  const byKey = new Map();

  for (const row of rows) {
    const key = `${row.order_id}|${row.asin || row.product_name || ''}`;
    const existing = byKey.get(key);
    if (!existing) {
      byKey.set(key, { ...row });
      continue;
    }

    const existingQty = parseInt(existing.quantity, 10) || 1;
    const incomingQty = parseInt(row.quantity, 10) || 1;
    existing.quantity = String(Math.max(existingQty, incomingQty));
    if (!existing.total_owed && row.total_owed) existing.total_owed = row.total_owed;
    if (!existing.tracking_number && row.tracking_number) existing.tracking_number = row.tracking_number;
    if (!existing.item_image && row.item_image) existing.item_image = row.item_image;
    if (!existing.carrier && row.carrier) existing.carrier = row.carrier;
  }

  return Array.from(byKey.values());
}

function getAccountSwitcherUrl() {
  const identifierSelect = 'http://specs.openid.net/auth/2.0/identifier_select';
  const params = new URLSearchParams({
    'openid.pape.max_auth_age': '0',
    'openid.return_to': 'https://www.amazon.com/gp/css/order-history?ref_=nav_youraccount_switchacct',
    'openid.identity': identifierSelect,
    'openid.assoc_handle': 'usflex',
    'openid.mode': 'checkid_setup',
    marketPlaceId: 'ATVPDKIKX0DER',
    'openid.claimed_id': identifierSelect,
    'openid.ns': 'http://specs.openid.net/auth/2.0',
    switch_account: 'picker',
    ignoreAuthState: '1',
    _encoding: 'UTF8',
  });

  return `https://www.amazon.com/ap/signin?${params.toString()}`;
}

function normalizeZipCode(value) {
  const match = String(value || '').match(/\d{5}(?:-\d{4})?/);
  if (!match) return '';
  return match[0];
}

function normalizeZipFilters(value) {
  return [...new Set(String(value || '')
    .split(/[\s,;]+/)
    .map(normalizeZipCode)
    .filter(Boolean))];
}

function extractZipCodesFromText(text) {
  if (!isValidShippingAddress(text)) return [];
  const matches = String(text || '').match(/\b\d{5}(?:-\d{4})?\b/g) || [];
  return [...new Set(matches.map(normalizeZipCode).filter(Boolean))];
}

function isValidShippingAddress(text) {
  const compact = String(text || '').replace(/\s+/g, ' ').trim();
  if (!compact || compact.length < 10) return false;
  if (/payment method|prime visa|ending in \d{4}|view related transaction|earns \d+% back|no-rush delivery|billing address/i.test(compact)) {
    return false;
  }
  if (/\b\d{5}(?:-\d{4})?\b/.test(compact)) return true;
  return /\b(united states|usa)\b/i.test(compact) && /,\s*[A-Z]{2}\b/.test(compact);
}

function resolveShippingAddress(order) {
  if (isValidShippingAddress(order.shippingAddress)) return order.shippingAddress;
  return '';
}

function zipMatchesFilter(order, zipFilters) {
  if (!zipFilters.length) return true;

  const allowed = new Set(zipFilters);
  const allowedBase = new Set(zipFilters.map(zip => zip.slice(0, 5)));
  const candidates = [
    order.zipCode,
    ...extractZipCodesFromText(order.shippingAddress || ''),
  ].map(normalizeZipCode).filter(Boolean);

  return candidates.some(zip => allowed.has(zip) || allowedBase.has(zip.slice(0, 5)));
}

async function detectAmazonAccountEmail() {
  let tabId = null;

  try {
    tabId = await openTab(getAccountSwitcherUrl());
    await sleep(2000);
    const result = await injectAndRun(tabId, 'account_scraper.js');
    const email = result?.email || '';

    notify('amazon_account', { email });
    if (email) {
      log(`Amazon account detected: ${email}`, 'info');
    } else if (result?.issue) {
      log(result.issue, 'error');
    } else {
      log('Could not detect the current Amazon account email.', 'error');
    }

    return email;
  } catch (err) {
    log(`Could not detect Amazon account email: ${err.message}`, 'error');
    notify('amazon_account', { email: '' });
    return '';
  } finally {
    await closeTab(tabId);
  }
}

function filterOrdersByZip(orders, zipFilters) {
  if (!zipFilters.length) return { keptOrders: orders, skipped: 0 };

  const keptOrders = [];
  let skipped = 0;

  for (const order of orders) {
    order.zipCode = normalizeZipCode(order.zipCode || extractZipCodesFromText(order.shippingAddress || '')[0] || '');

    if (zipMatchesFilter(order, zipFilters)) {
      keptOrders.push(order);
      log(`${order.orderId}: keeping ZIP ${order.zipCode || 'matched address'}`, 'success');
    } else {
      skipped++;
      log(`${order.orderId}: skipped${order.zipCode ? ` ZIP ${order.zipCode}` : ' (no matching ZIP found)'}`, 'info');
    }
  }

  return { keptOrders, skipped };
}

function filterCancelledOrdersByZip(cancelledOrders, zipFilters) {
  if (!zipFilters.length) return cancelledOrders;

  return cancelledOrders.filter((order) => {
    order.zipCode = normalizeZipCode(order.zipCode || extractZipCodesFromText(order.shippingAddress || '')[0] || '');
    return zipMatchesFilter(order, zipFilters);
  });
}

function mergeCancelledOrders(target, incoming) {
  const seen = new Set(target.map((order) => order.orderId));
  for (const order of incoming) {
    if (!order.orderId || seen.has(order.orderId)) continue;
    seen.add(order.orderId);
    target.push(order);
  }
}

async function uploadCancelledOrdersToApi(cancelledOrders, amazonEmail) {
  if (!cancelledOrders.length) return;

  const payload = cancelledOrders.map((order) => ({
    order_id: order.orderId,
    order_date: order.orderDate || '',
    order_status: 'Cancelled',
    shipment_status: 'Cancelled',
    email_address: amazonEmail,
  }));

  log(`Sending ${payload.length} cancelled order${payload.length === 1 ? '' : 's'} to API...`, 'info');

  const batchSize = 50;
  for (let i = 0; i < payload.length; i += batchSize) {
    if (scrapeState.stopped) break;
    const batch = payload.slice(i, i + batchSize);

    try {
      const result = await apiPost('/api/orders/amazon/scrape', { orders: batch });
      const updated = (result.inserted || 0) + (result.updated || 0);
      scrapeState.sent += updated;
      scrapeState.failed += (result.failed || 0);
      stats();
      log(`Cancelled batch ${Math.floor(i / batchSize) + 1}: ${result.inserted || 0} inserted, ${result.updated || 0} updated, ${result.failed || 0} failed`, result.failed ? 'error' : 'success');
    } catch (err) {
      log(`Cancelled API error (batch ${Math.floor(i / batchSize) + 1}): ${err.message}`, 'error');
    }
  }
}

function reportCancelledOrders(cancelledOrders, zipFilters) {
  const filtered = filterCancelledOrdersByZip(cancelledOrders, zipFilters);
  for (const order of filtered) {
    log(`${order.orderId}: cancelled (reporting to server)`, 'info');
  }
  scrapeState.cancelled = filtered.length;
  stats();
  return filtered;
}

function buildOrderDetailUrl(orderId) {
  const params = new URLSearchParams({
    orderID: orderId,
    ref: 'ppx_yo2ov_dt_b_fed_order_details',
  });
  return `https://www.amazon.com/your-orders/order-details?${params.toString()}`;
}

function parseMoneyAmount(value) {
  const cleaned = String(value || '').replace(/,/g, '').match(/(\d+(?:\.\d{2})?)/);
  if (!cleaned) return null;
  const amount = parseFloat(cleaned[1]);
  return Number.isFinite(amount) ? amount : null;
}

function formatMoneyAmount(amount) {
  return amount.toFixed(2);
}

function getShipmentTotalOwed(order, shipment) {
  const unitPrice = parseMoneyAmount(shipment.unitPrice);
  const quantity = parseInt(shipment.quantity, 10) || 1;
  if (unitPrice !== null) {
    return formatMoneyAmount(unitPrice * quantity);
  }

  const shipments = order.shipments || [];
  if (shipments.length === 1) {
    return String(order.total || '').replace(/^\$/, '');
  }

  return '';
}

async function uploadOrdersToApi(allOrders, amazonEmail) {
  const payload = dedupePayloadLineItems(allOrders.flatMap((order) => {
    return order.shipments.map((shipment) => {
      const rawStatus = shipment.status || '';
      return {
        order_id: order.orderId,
        order_date: order.orderDate || '',
        total_owed: getShipmentTotalOwed(order, shipment),
        shipping_address: resolveShippingAddress(order),
        order_status: normalizeOrderStatus(rawStatus),
        shipment_status: normalizeShipmentStatus(rawStatus),
        asin: shipment.asin || '',
        product_name: shipment.productTitle || '',
        item_image: shipment.itemImage || '',
        quantity: String(shipment.quantity || 1),
        carrier: normalizeCarrier(shipment.carrier || '') || '',
        tracking_number: shipment.trackingNumber || '',
        email_address: amazonEmail,
      };
    });
  }));

  log(`Sending ${payload.length} line items from ${allOrders.length} orders...`, 'info');

  const batchSize = 50;
  for (let i = 0; i < payload.length; i += batchSize) {
    if (scrapeState.stopped) break;
    const batch = payload.slice(i, i + batchSize);

    try {
      const result = await apiPost('/api/orders/amazon/scrape', { orders: batch });
      scrapeState.sent += (result.inserted || 0) + (result.updated || 0);
      scrapeState.failed += (result.failed || 0);
      stats();
      const failed = result.failed || 0;
      const level = failed ? 'error' : 'success';
      log(`Batch ${Math.floor(i / batchSize) + 1}: ${result.inserted || 0} inserted, ${result.updated || 0} updated, ${failed} failed`, level);
      if (failed && Array.isArray(result.errors)) {
        for (const error of result.errors.slice(0, 5)) {
          log(`  ${error.order_id || 'Unknown order'}: ${error.message || 'Import failed'}`, 'error');
        }
      }
    } catch (err) {
      log(`API error (batch ${Math.floor(i / batchSize) + 1}): ${err.message}`, 'error');
    }

    progress(85 + Math.round(((i + batchSize) / payload.length) * 15), `Sent ${Math.min(i + batchSize, payload.length)}/${payload.length}`);
  }
}

function applyTrackingResult(order, shipment, shipmentIndex, trackResult, error) {
  if (error === 'no ship-track URL') {
    log(`  ${order.orderId} shipment ${shipmentIndex + 1} -> no ship-track URL`, 'error');
    return { timedOut: false };
  }
  if (error) {
    log(`  Failed tracking for ${order.orderId}: ${error}`, 'error');
    return { timedOut: false };
  }
  if (!trackResult) return { timedOut: false };

  shipment.carrier = trackResult.carrier || '';
  shipment.trackingNumber = trackResult.trackingId || '';
  shipment.trackingEvents = trackResult.events || [];
  scrapeState.tracked++;

  if (trackResult.trackingId) {
    log(`  ${order.orderId} shipment ${shipmentIndex + 1} -> ${trackResult.trackingId}`, 'success');
    return { timedOut: false };
  }
  if (trackResult.issue) {
    log(`  ${order.orderId} shipment ${shipmentIndex + 1} -> no tracking# (${trackResult.issue})`, 'error');
    return { timedOut: false };
  }
  if (trackResult.cancelled) {
    log(`  ${order.orderId} shipment ${shipmentIndex + 1} -> no tracking# (${trackResult.cancelled})`, 'error');
    return { timedOut: false };
  }
  if (trackResult.noTracking) {
    log(`  ${order.orderId} shipment ${shipmentIndex + 1} -> no tracking# (${trackResult.noTracking})`, 'error');
    return { timedOut: false };
  }
  if (trackResult.timedOut) {
    log(`  ${order.orderId} shipment ${shipmentIndex + 1} -> no tracking# (timeout)`, 'error');
    return { timedOut: true };
  }
  log(`  ${order.orderId} shipment ${shipmentIndex + 1} -> no tracking#`, 'error');
  return { timedOut: false };
}

async function fetchTrackingBatch(batchGroups) {
  if (!batchGroups.length) return { timedOutCount: 0 };

  const tabIds = [];
  let timedOutCount = 0;

  try {
    const openResults = await Promise.all(
      batchGroups.map(async (group) => {
        try {
          return await openTab(group.trackUrl);
        } catch (err) {
          log(`Failed to open tracking tab: ${err.message}`, 'error');
          return null;
        }
      })
    );

    tabIds.push(...openResults.filter(Boolean));
    await waitForTabReady();

    const scrapeResults = await Promise.all(
      batchGroups.map(async (group, index) => {
        const tabId = openResults[index];
        if (!tabId) {
          return { group, trackResult: null, error: 'Failed to open tab' };
        }
        try {
          const trackResult = await injectAndRun(tabId, 'tracking_scraper.js');
          return { group, trackResult, error: null };
        } catch (err) {
          return { group, trackResult: null, error: err.message };
        }
      })
    );

    for (const { group, trackResult, error } of scrapeResults) {
      for (const target of group.targets) {
        const result = applyTrackingResult(target.order, target.shipment, target.shipmentIndex, trackResult, error);
        if (result.timedOut) timedOutCount++;
      }
    }
  } finally {
    await Promise.all(tabIds.map((tabId) => closeTab(tabId)));
  }

  return { timedOutCount };
}

async function fetchTrackingForOrders(allOrders, progressStart, progressEnd, dbCache = null) {
  if (dbCache) {
    const skipped = applyDbCacheToOrders(allOrders, dbCache);
    if (skipped) {
      log(`Cache: skipping ${skipped} tracking fetch${skipped === 1 ? '' : 'es'} already in IEID`, 'info');
    }
  }

  const { groups, noUrlTargets, shipmentCount } = buildTrackingFetchGroups(allOrders);

  for (const target of noUrlTargets) {
    applyTrackingResult(target.order, target.shipment, target.shipmentIndex, null, 'no ship-track URL');
  }

  if (!groups.length) return;

  let concurrency = TRACKING_TAB_CONCURRENCY;
  let timeoutBatchStreak = 0;
  let successBatchStreak = 0;

  const uniqueFetches = groups.length;
  const trackedShipments = shipmentCount - noUrlTargets.length;

  if (trackedShipments > uniqueFetches) {
    log(`Deduped tracking: ${trackedShipments} shipments -> ${uniqueFetches} unique fetches`, 'info');
  }

  log(`Fetching tracking for ${trackedShipments} shipments (${uniqueFetches} URLs, ${concurrency} tabs at a time)...`, 'info');

  let processedShipments = noUrlTargets.length;
  let batchNumber = 0;

  for (let batchStart = 0; batchStart < groups.length; batchStart += concurrency) {
    if (scrapeState.stopped) break;

    batchNumber++;
    const batchGroups = groups.slice(batchStart, batchStart + concurrency);
    const batchShipmentStart = processedShipments + 1;
    const batchShipmentEnd = processedShipments + batchGroups.reduce((n, group) => n + group.targets.length, 0);
    log(`Tracking batch ${batchNumber} (shipments ${batchShipmentStart}-${batchShipmentEnd})...`, 'info');

    try {
      const { timedOutCount } = await withTimeout(
        fetchTrackingBatch(batchGroups),
        TRACKING_BATCH_TIMEOUT_MS,
        `Tracking batch ${batchNumber}`
      );

      if (timedOutCount === batchGroups.reduce((n, group) => n + group.targets.length, 0)) {
        timeoutBatchStreak++;
        successBatchStreak = 0;
      } else if (timedOutCount > 0) {
        timeoutBatchStreak++;
        successBatchStreak = 0;
      } else {
        successBatchStreak++;
        timeoutBatchStreak = 0;
      }
    } catch (err) {
      log(`Tracking batch ${batchNumber} failed: ${err.message}`, 'error');
      timeoutBatchStreak++;
      successBatchStreak = 0;
    }

    if (timeoutBatchStreak >= 3 && concurrency > TRACKING_TAB_CONCURRENCY_REDUCED) {
      concurrency = TRACKING_TAB_CONCURRENCY_REDUCED;
      log(`Reduced tracking concurrency to ${concurrency} after repeated timeouts`, 'info');
    } else if (successBatchStreak >= 2 && concurrency < TRACKING_TAB_CONCURRENCY) {
      concurrency = TRACKING_TAB_CONCURRENCY;
      log(`Restored tracking concurrency to ${concurrency}`, 'info');
    }

    processedShipments += batchGroups.reduce((n, group) => n + group.targets.length, 0);
    stats();
    progress(
      progressStart + Math.round((processedShipments / shipmentCount) * (progressEnd - progressStart)),
      `Tracking ${processedShipments}/${shipmentCount}`
    );

    if (batchStart + concurrency < groups.length && !scrapeState.stopped) {
      const backoff = timeoutBatchStreak >= 3 ? 2000 + Math.random() * 2000 : 500 + Math.random() * 750;
      await sleep(backoff);
    }
  }

  const postTrackingDuplicateShipments = allOrders.reduce((count, order) => count + dedupeOrderShipments(order), 0);
  if (postTrackingDuplicateShipments) {
    scrapeState.shipments = allOrders.reduce((n, o) => n + o.shipments.length, 0);
    stats();
    log(`Removed ${postTrackingDuplicateShipments} duplicate shipment${postTrackingDuplicateShipments === 1 ? '' : 's'} after tracking lookup`, 'info');
  }
}

async function runSingleOrderScrape(config) {
  const { orderId, fetchTracking, useDbCache } = config;
  const zipFilters = normalizeZipFilters(config.zipFilters);

  if (!orderId) {
    scrapeDone('No order ID provided.', false);
    return;
  }

  scrapeState = { running: true, stopped: false, pct: 0, statusText: '', orders: 0, shipments: 0, tracked: 0, sent: 0, failed: 0, cancelled: 0, skippedCached: 0 };
  clearScrapeLogs();
  startScrapeKeepAlive();
  openLogTab();

  let dbCache = null;

  try {
    const token = await getAuthCookie();
    if (!token) {
      scrapeDone('Not authenticated. Please sign in first.', false);
      scrapeState.running = false;
      return;
    }

    if (useDbCache) {
      dbCache = await loadDbShipmentCache();
    }

    const amazonEmail = await detectAmazonAccountEmail();

    log(`Starting single order scan for ${orderId}...`, 'info');
    progress(15, `Loading order ${orderId}...`);

    const url = buildOrderDetailUrl(orderId);
    const tabId = await openTab(url);
    await sleep(2000);
    const result = await injectAndRun(tabId, 'order_detail_scraper.js');
    await closeTab(tabId);

    if (result?.issue) {
      scrapeDone(result.issue, false);
      scrapeState.running = false;
      return;
    }

    if (!result?.orders?.length && !result?.cancelledOrders?.length) {
      scrapeDone(`Could not extract order ${orderId}.`, false);
      scrapeState.running = false;
      return;
    }

    let allOrders = result.orders || [];
    let cancelledToReport = [];

    if (result.cancelledOrders?.length) {
      cancelledToReport = reportCancelledOrders(result.cancelledOrders, zipFilters);
    }

    for (const order of allOrders) {
      dedupeOrderShipments(order);
    }

    if (zipFilters.length && allOrders.length) {
      const { keptOrders, skipped } = filterOrdersByZip(allOrders, zipFilters);
      allOrders = keptOrders;
      if (skipped) {
        log(`Order ${orderId} did not match ZIP filter`, 'info');
      }
    }

    scrapeState.orders = allOrders.length;
    scrapeState.shipments = allOrders.reduce((n, o) => n + o.shipments.length, 0);
    stats();
    progress(50, `Extracted order ${orderId}`);

    if (scrapeState.stopped) {
      scrapeDone('Scrape stopped by user', false);
      scrapeState.running = false;
      return;
    }

    if (!allOrders.length && !cancelledToReport.length) {
      progress(100, 'No matching order');
      scrapeDone(`Order ${orderId} did not match the selected ZIP filters.`, false);
      scrapeState.running = false;
      return;
    }

    if (allOrders.length) {
      log(`Extracted ${allOrders.length} order with ${scrapeState.shipments} shipments`, 'success');
    }

    if (fetchTracking && allOrders.length) {
      await fetchTrackingForOrders(allOrders, 50, 80, useDbCache ? dbCache : null);
    }

    if (scrapeState.stopped) {
      scrapeDone('Scrape stopped by user', false);
      scrapeState.running = false;
      return;
    }

    if (allOrders.length) {
      log('Sending data to API...', 'info');
      progress(85, 'Sending to API...');
      await uploadOrdersToApi(allOrders, amazonEmail);
    }

    if (cancelledToReport.length) {
      await uploadCancelledOrdersToApi(cancelledToReport, amazonEmail);
    }

    progress(100, 'Done!');
    const parts = [];
    if (allOrders.length) parts.push(`${allOrders.length} order`);
    if (cancelledToReport.length) parts.push(`${cancelledToReport.length} cancelled`);
    parts.push(`${scrapeState.sent} saved`);
    if (scrapeState.failed) parts.push(`${scrapeState.failed} failed`);
    const doneText = `Complete: ${parts.join(', ')}`;
    scrapeDone(doneText, scrapeState.failed === 0);
    chrome.storage.local.remove('pendingSingleOrderId');
  } catch (err) {
    scrapeDone(`Error: ${err.message}`, false);
  } finally {
    stopScrapeKeepAlive();
    scrapeState.running = false;
  }
}

// --- Main scrape logic ---
async function runScrape(config) {
  const { yearFilter, maxPages, fetchTracking, useDbCache } = config;
  const zipFilters = normalizeZipFilters(config.zipFilters);
  scrapeState = { running: true, stopped: false, pct: 0, statusText: '', orders: 0, shipments: 0, tracked: 0, sent: 0, failed: 0, cancelled: 0, skippedCached: 0 };
  clearScrapeLogs();
  startScrapeKeepAlive();
  openLogTab();

  const allOrders = [];
  const allCancelledOrders = [];
  let totalPages = 1;
  let page = 1;
  let totalZipSkipped = 0;
  let dbCache = null;

  try {
    const token = await getAuthCookie();
    if (!token) {
      scrapeDone('Not authenticated. Please sign in first.', false);
      scrapeState.running = false;
      return;
    }

    if (useDbCache) {
      dbCache = await loadDbShipmentCache();
    }

    const amazonEmail = await detectAmazonAccountEmail();

    // Phase 1: Scrape order list pages
    log('Starting order list scrape...', 'info');
    if (zipFilters.length) {
      log(`Keeping only orders for ZIP ${zipFilters.join(', ')} during list scan`, 'info');
    }

    while (page <= totalPages) {
      if (scrapeState.stopped) break;
      if (maxPages > 0 && page > maxPages) break;

      const startIndex = (page - 1) * 10;
      const url = `https://www.amazon.com/your-orders/orders?orderFilter=${yearFilter}&startIndex=${startIndex}`;

      progress(0, `Loading page ${page}...`);
      log(`Scraping page ${page}...`);

      const tabId = await openTab(url);
      await waitForTabReady();

      const result = await injectAndRun(tabId, 'scraper.js');
      await closeTab(tabId);

      if (result?.issue) {
        log(result.issue, 'error');
        break;
      }

      if (!result || (!result.orders && !result.cancelledOrders)) {
        log(`Failed to extract page ${page}`, 'error');
        break;
      }

      if (page === 1) {
        totalPages = result.maxPage || 1;
        const effectivePages = maxPages > 0 ? Math.min(maxPages, totalPages) : totalPages;
        log(`Found ${totalPages} total pages, will scrape ${effectivePages}`, 'info');
      }

      let pageOrders = result.orders || [];
      let pageCancelled = result.cancelledOrders || [];

      if (zipFilters.length) {
        const { keptOrders, skipped } = filterOrdersByZip(pageOrders, zipFilters);
        pageOrders = keptOrders;
        totalZipSkipped += skipped;
        pageCancelled = filterCancelledOrdersByZip(pageCancelled, zipFilters);
      }

      mergeCancelledOrders(allCancelledOrders, pageCancelled);

      let duplicateShipments = 0;
      for (const order of pageOrders) {
        duplicateShipments += dedupeOrderShipments(order);
        if (!allOrders.some(existing => existing.orderId === order.orderId)) {
          allOrders.push(order);
        }
      }
      if (duplicateShipments) {
        log(`Removed ${duplicateShipments} duplicate shipment${duplicateShipments === 1 ? '' : 's'} from page ${page}`, 'info');
      }
      scrapeState.orders = allOrders.length;
      scrapeState.shipments = allOrders.reduce((n, o) => n + o.shipments.length, 0);
      stats();

      const effectiveTotal = maxPages > 0 ? Math.min(maxPages, totalPages) : totalPages;
      progress(Math.round((page / effectiveTotal) * 50), `Page ${page}/${effectiveTotal} done (${allOrders.length} orders)`);

      page++;
      if (page <= effectiveTotal) {
        await sleep(randomOrderPageDelay());
      }
    }

    if (scrapeState.stopped) {
      scrapeDone('Scrape stopped by user', false);
      scrapeState.running = false;
      return;
    }

    log(`Scraped ${allOrders.length} orders with ${scrapeState.shipments} shipments`, 'success');
    if (zipFilters.length) {
      log(`ZIP filter kept ${allOrders.length} orders and skipped ${totalZipSkipped}`, totalZipSkipped ? 'info' : 'success');
    }

    const finalDuplicateShipments = allOrders.reduce((count, order) => count + dedupeOrderShipments(order), 0);
    if (finalDuplicateShipments) {
      scrapeState.shipments = allOrders.reduce((n, o) => n + o.shipments.length, 0);
      stats();
      log(`Removed ${finalDuplicateShipments} duplicate shipment${finalDuplicateShipments === 1 ? '' : 's'} before tracking`, 'info');
    }

    const cancelledToReport = reportCancelledOrders(allCancelledOrders, zipFilters);

    if (allOrders.length === 0 && !cancelledToReport.length) {
      progress(100, 'No orders found');
      scrapeDone(zipFilters.length ? 'No Amazon orders matched the selected ZIP filters.' : 'No Amazon orders were found for the selected filter.', false);
      scrapeState.running = false;
      return;
    }

    if (allOrders.length === 0 && cancelledToReport.length) {
      log(`Found ${cancelledToReport.length} cancelled order${cancelledToReport.length === 1 ? '' : 's'}`, 'info');
    }

    if (fetchTracking && allOrders.length) {
      await fetchTrackingForOrders(allOrders, 50, 80, useDbCache ? dbCache : null);
    }

    if (allOrders.length) {
      log('Sending data to API...', 'info');
      progress(85, 'Sending to API...');
      await uploadOrdersToApi(allOrders, amazonEmail);
    }

    if (cancelledToReport.length) {
      await uploadCancelledOrdersToApi(cancelledToReport, amazonEmail);
    }

    progress(100, 'Done!');
    const parts = [];
    if (allOrders.length) parts.push(`${allOrders.length} orders`);
    if (cancelledToReport.length) parts.push(`${cancelledToReport.length} cancelled`);
    parts.push(`${scrapeState.sent} saved`);
    if (scrapeState.failed) parts.push(`${scrapeState.failed} failed`);
    const doneText = `Complete: ${parts.join(', ')}`;
    scrapeDone(doneText, scrapeState.failed === 0);
  } catch (err) {
    scrapeDone(`Error: ${err.message}`, false);
  } finally {
    stopScrapeKeepAlive();
    scrapeState.running = false;
  }
}

function normalizeCarrier(raw) {
  const lower = raw.toLowerCase();
  if (lower.includes('amazon')) return 'Amazon';
  if (lower.includes('ups')) return 'UPS';
  if (lower.includes('usps')) return 'USPS';
  if (lower.includes('fedex')) return 'FedEx';
  if (lower.includes('ontrac')) return 'OnTrac';
  if (lower.includes('dhl')) return 'DHL';
  return raw;
}

// Map Amazon status text to database order_status values
function normalizeOrderStatus(raw) {
  const lower = raw.toLowerCase();
  if (lower.includes('cancel')) return 'Cancelled';
  if (lower.includes('delivered')) return 'Closed';
  if (lower.includes('returning') || lower.includes('refund')) return 'Closed';
  if (lower.includes('arriving') || lower.includes('expected') || lower.includes('out for delivery')) return 'Open';
  if (lower.includes('shipped') || lower.includes('on the way')) return 'Open';
  return 'Open';
}

function normalizeShipmentStatus(raw) {
  const lower = raw.toLowerCase();
  if (lower.includes('cancel')) return 'Cancelled';
  if (lower.includes('delivered')) return 'Delivered';
  if (lower.includes('arriving') || lower.includes('expected') || lower.includes('out for delivery')) return 'Shipped';
  if (lower.includes('shipped') || lower.includes('on the way')) return 'Shipped';
  return raw;
}

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === KEEP_ALIVE_ALARM && scrapeState.running) {
    console.log('[IEID] scrape keep-alive');
  }
  if (alarm.name === UPDATE_CHECK_ALARM) {
    maybeAutoApplyUpdate();
  }
});

chrome.runtime.onInstalled.addListener(() => {
  ensureUpdateCheckAlarm();
  maybeAutoApplyUpdate();
});

chrome.runtime.onStartup.addListener(() => {
  ensureUpdateCheckAlarm();
  maybeAutoApplyUpdate();
});

chrome.tabs.onRemoved.addListener((tabId) => {
  if (tabId === logTabId) logTabId = null;
});

// Message handler
chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg.action === 'start_scrape') {
    if (!scrapeState.running) {
      runScrape(msg.config);
    }
    sendResponse({ ok: true });
  } else if (msg.action === 'start_single_order_scrape') {
    if (!scrapeState.running) {
      runSingleOrderScrape(msg.config);
    }
    sendResponse({ ok: true });
  } else if (msg.action === 'prepare_single_order_scan') {
    if (msg.orderId) {
      chrome.storage.local.set({ pendingSingleOrderId: msg.orderId });
    }
    chrome.action.openPopup().catch((err) => {
      console.log('[IEID] Could not open popup automatically:', err?.message || err);
    });
    sendResponse({ ok: true });
  } else if (msg.action === 'get_pending_single_order') {
    chrome.storage.local.get('pendingSingleOrderId', (data) => {
      sendResponse({ orderId: data.pendingSingleOrderId || '' });
    });
  } else if (msg.action === 'clear_pending_single_order') {
    chrome.storage.local.remove('pendingSingleOrderId');
    sendResponse({ ok: true });
  } else if (msg.action === 'open_log_tab') {
    openLogTab();
    sendResponse({ ok: true });
  } else if (msg.action === 'stop_scrape') {
    scrapeState.stopped = true;
    log('Stopped by user', 'error');
    sendResponse({ ok: true });
  } else if (msg.action === 'scrape_status') {
    scrapeLogsReady.then(() => {
      sendResponse({ running: scrapeState.running, ...scrapeState, logs: scrapeLogs });
    });
  }
  return true;
});
