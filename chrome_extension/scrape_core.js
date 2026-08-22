const AMAZON_HOST_RE = /(?:^|\.)amazon\.com$/i;
const CHROME_VERSION_COMPONENT_MAX = 65535;
const UPDATER_FILES = ['update.js', 'update.html', 'update_helpers.js'];

function isApprovedAmazonHost(hostname) {
  const host = String(hostname || '').replace(/\.$/, '').toLowerCase();
  return AMAZON_HOST_RE.test(host);
}

function isApprovedAmazonUrl(value) {
  if (!value) return false;
  try {
    const parsed = new URL(value, 'https://www.amazon.com');
    return parsed.protocol === 'https:' && isApprovedAmazonHost(parsed.hostname);
  } catch {
    return false;
  }
}

function isShipTrackUrl(url) {
  if (!isApprovedAmazonUrl(url)) return false;
  try {
    const parsed = new URL(url);
    if (parsed.pathname.includes('/your-orders/pop')) return false;
    return parsed.pathname.includes('/gp/your-account/ship-track') || parsed.pathname.includes('ship-track');
  } catch {
    return false;
  }
}

function normalizeTrackingUrl(url) {
  if (!isShipTrackUrl(url)) return '';
  try {
    const trackingUrl = new URL(url);
    trackingUrl.searchParams.set('ref', 'ppx_yo2ov_dt_b_track_package');
    trackingUrl.searchParams.set('noPtRedirect', '1');
    trackingUrl.hash = '';
    return trackingUrl.toString();
  } catch {
    return '';
  }
}

function normalizeComparable(value) {
  return String(value || '').replace(/\s+/g, ' ').trim().toLowerCase();
}

function getTrackingItemId(shipment) {
  if (shipment.itemId) return shipment.itemId;
  if (!shipment.lineItemId) return '';
  return shipment.lineItemId.endsWith('s') ? shipment.lineItemId.slice(0, -1) : shipment.lineItemId;
}

function matchingShipTrack(ids, links) {
  const list = Array.isArray(links) ? links : [];
  const shipmentId = ids?.shipmentId || ids?.shipment_id || '';
  const itemId = ids?.itemId || ids?.item_id || '';
  const lineItemId = ids?.lineItemId || ids?.line_item_id || '';
  if (shipmentId) {
    const match = list.find((entry) => (
      entry.shipmentId === shipmentId
      && (!itemId || !entry.itemId || entry.itemId === itemId)
    ));
    if (match) return match;
  }
  if (itemId) {
    const match = list.find((entry) => entry.itemId === itemId);
    if (match) return match;
  }
  if (lineItemId) {
    const match = list.find((entry) => entry.lineItemId === lineItemId);
    if (match) return match;
  }
  return null;
}

function getShipmentIdentity(order, shipment) {
  const orderId = order.orderId || order.order_id || '';
  const shipmentId = shipment.shipmentId || shipment.shipment_id || '';
  const packageId = shipment.packageId || shipment.package_id || '';
  const itemId = getTrackingItemId(shipment);
  const lineItemId = shipment.lineItemId || shipment.line_item_id || '';
  if (shipmentId || packageId || itemId || lineItemId) {
    return ['ids', orderId, shipmentId, packageId, itemId, lineItemId, shipment.asin || ''].join('|');
  }
  const trackingUrl = shipment.trackingUrl || '';
  if (isShipTrackUrl(trackingUrl)) return ['tracking-url', orderId, normalizeTrackingUrl(trackingUrl)].join('|');
  const trackingNumber = normalizeComparable(shipment.trackingNumber || shipment.tracking_number || '');
  if (trackingNumber) return ['tracking-number', orderId, trackingNumber].join('|');
  return [
    'product',
    orderId,
    String(shipment.asin || '').toUpperCase(),
    normalizeComparable(shipment.productTitle || shipment.product_name || ''),
  ].join('|');
}

function scrapeValuePresent(value) {
  if (value == null) return false;
  if (typeof value === 'string') return value.trim() !== '';
  if (Array.isArray(value)) return value.length > 0;
  return true;
}

function compactScrapeRow(row) {
  const compact = {};
  Object.keys(row).forEach((key) => {
    if (scrapeValuePresent(row[key])) compact[key] = row[key];
  });
  return compact;
}

function payloadLineItemKey(row) {
  return [
    row.order_id || '',
    row.shipment_id || '',
    row.line_item_id || '',
    row.asin || '',
    row.tracking_number || '',
  ].join('|');
}

function dedupePayloadLineItems(rows) {
  const byKey = new Map();
  for (const row of rows) {
    const key = payloadLineItemKey(row);
    const existing = byKey.get(key);
    if (!existing) {
      byKey.set(key, { ...row });
      continue;
    }
    const existingQty = parseInt(existing.quantity, 10) || 0;
    const incomingQty = parseInt(row.quantity, 10) || 0;
    existing.quantity = String(existingQty + incomingQty || 1);
    if (!existing.total_owed && row.total_owed) existing.total_owed = row.total_owed;
    if (!existing.tracking_number && row.tracking_number) existing.tracking_number = row.tracking_number;
    if (!existing.item_image && row.item_image) existing.item_image = row.item_image;
    if (!existing.carrier && row.carrier) existing.carrier = row.carrier;
  }
  return Array.from(byKey.values());
}

function buildCancelledPayload(order, amazonEmail) {
  return compactScrapeRow({
    order_id: order.orderId || order.order_id,
    order_date: order.orderDate || order.order_date || '',
    order_status: 'Cancelled',
    shipment_status: 'Cancelled',
    email_address: amazonEmail || '',
  });
}

function referencedManifestFiles(manifest) {
  const paths = ['manifest.json'];
  const worker = manifest?.background?.service_worker;
  if (worker) paths.push(String(worker));
  const popup = manifest?.action?.default_popup;
  if (popup) paths.push(String(popup));
  const actionIcons = manifest?.action?.default_icon;
  if (actionIcons && typeof actionIcons === 'object') {
    Object.values(actionIcons).forEach((value) => {
      if (value) paths.push(String(value));
    });
  }
  const icons = manifest?.icons;
  if (icons && typeof icons === 'object') {
    Object.values(icons).forEach((value) => {
      if (value) paths.push(String(value));
    });
  }
  for (const script of manifest?.content_scripts || []) {
    for (const value of script.js || []) paths.push(String(value));
    for (const value of script.css || []) paths.push(String(value));
  }
  return [...new Set(paths)];
}

function validatePackagePayload(payload) {
  if (!payload?.version || !payload.files || typeof payload.files !== 'object') {
    throw new Error('Package file map is empty');
  }
  const entry = payload.files['manifest.json'];
  if (!entry || entry.encoding !== 'utf-8' || typeof entry.content !== 'string') {
    throw new Error('Package is missing manifest.json');
  }
  let manifest;
  try {
    manifest = JSON.parse(entry.content);
  } catch {
    throw new Error('Package manifest is invalid');
  }
  if (!manifest || manifest.name !== 'IEID Order Scraper') {
    throw new Error('Package is not IEID Order Scraper');
  }
  if (String(manifest.version) !== String(payload.version)) {
    throw new Error('Package version does not match manifest');
  }
  const missing = referencedManifestFiles(manifest).filter((path) => !payload.files[path]);
  if (missing.length) {
    throw new Error(`Package is missing required files: ${missing.join(', ')}`);
  }
  const updaterMissing = UPDATER_FILES.filter((path) => !payload.files[path]);
  if (updaterMissing.length) {
    throw new Error(`Package is missing updater files: ${updaterMissing.join(', ')}`);
  }
  return manifest;
}

function nextPatchVersion(version) {
  const parts = String(version).split('.');
  if (!parts.length || parts.length > 4 || !parts.every((part) => /^\d+$/.test(part))) {
    throw new Error(`Invalid Chrome extension version: ${version}`);
  }
  const next = parts.map((part) => Number(part));
  next[next.length - 1] += 1;
  if (next.some((part) => part > CHROME_VERSION_COMPONENT_MAX)) {
    throw new Error(`Chrome extension version component exceeds ${CHROME_VERSION_COMPONENT_MAX}: ${version}`);
  }
  return next.join('.');
}

function scrapeOutcomeSuccess(state) {
  return Boolean(
    state
    && !state.stopped
    && !state.extractionIncomplete
    && (state.failed || 0) === 0
  );
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    AMAZON_HOST_RE,
    CHROME_VERSION_COMPONENT_MAX,
    UPDATER_FILES,
    isApprovedAmazonHost,
    isApprovedAmazonUrl,
    isShipTrackUrl,
    normalizeTrackingUrl,
    getTrackingItemId,
    matchingShipTrack,
    getShipmentIdentity,
    scrapeValuePresent,
    compactScrapeRow,
    payloadLineItemKey,
    dedupePayloadLineItems,
    buildCancelledPayload,
    referencedManifestFiles,
    validatePackagePayload,
    nextPatchVersion,
    scrapeOutcomeSuccess,
  };
}
