// Cache shipment identities only after every shipment returned tracking. Never
// use another Amazon account's entries or reuse previously fetched tracking.
function shipmentDiscoverySignature(order) {
  const totals = new Map();
  for (const shipment of order.shipments || []) {
    const key = `${shipment.asin || shipment.productTitle || ''}|${shipment.status || ''}`;
    totals.set(key, (totals.get(key) || 0) + (parseInt(shipment.quantity, 10) || 1));
  }
  return JSON.stringify([...totals].sort(([a], [b]) => a.localeCompare(b)));
}

function shipmentDiscoveryCacheKey(account) {
  return account ? `amazonShipmentDiscovery:v1:${String(account).trim().toLowerCase()}` : '';
}

async function restoreShipmentDiscovery(allOrders, account) {
  const key = shipmentDiscoveryCacheKey(account);
  for (const order of allOrders) order.discoverySignature = shipmentDiscoverySignature(order);
  if (!key) return;
  try {
    const entries = (await chrome.storage.local.get(key))[key] || {};
    for (const order of allOrders) {
      if (order.detailsScanned || order.shipments.every(shipment => buildTrackingUrl(order, shipment))) continue;
      const entry = entries[order.orderId];
      if (!entry || entry.expiresAt <= Date.now() || entry.signature !== order.discoverySignature) continue;
      const result = { orders: [{ orderId: order.orderId, shipments: entry.shipments }] };
      const detail = validateDetailedOrder(result, order);
      if (!detail.shipments.every(shipment => buildTrackingUrl(order, shipment))) continue;
      order.shipments = detail.shipments.map(shipment => ({ ...shipment, trackingNumber: '', skipTrackingFetch: false }));
      order.detailsScanned = true;
      log(`${order.orderId}: reused saved shipment links for this Amazon account`, 'info');
    }
  } catch (err) {
    log(`Shipment-link cache unavailable: ${err.message}`, 'info');
  }
}

async function saveShipmentDiscovery(allOrders, account) {
  const key = shipmentDiscoveryCacheKey(account);
  if (!key || scrapeState.stopped) return;
  try {
    const entries = (await chrome.storage.local.get(key))[key] || {};
    for (const order of allOrders) {
      if (!order.detailsScanned || !order.shipments.length
          || !order.shipments.every(shipment => shipment.trackingNumber && buildTrackingUrl(order, shipment))) continue;
      entries[order.orderId] = {
        signature: order.discoverySignature || shipmentDiscoverySignature(order),
        expiresAt: Date.now() + 7 * 24 * 60 * 60 * 1000,
        shipments: order.shipments.map(({ trackingNumber, trackingEvents, skipTrackingFetch, ...shipment }) => shipment),
      };
    }
    const bounded = Object.fromEntries(Object.entries(entries).filter(([, value]) => value.expiresAt > Date.now())
      .sort(([, a], [, b]) => b.expiresAt - a.expiresAt).slice(0, 200));
    await chrome.storage.local.set({ [key]: bounded });
  } catch (err) {
    log(`Could not save shipment links: ${err.message}`, 'info');
  }
}
