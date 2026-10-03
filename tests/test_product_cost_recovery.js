const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const core = require('../chrome_extension/scrape_core.js');
const source = fs.readFileSync(require.resolve('../chrome_extension/background.js'), 'utf8');
const requests = [];
const uploads = [];
let omitPrices = false;
const order = { orderId: '111-1111111-1111111', total: '$2399.94', shipments: [
  { asin: 'B000000001', quantity: 3, shipmentId: 'shared', itemId: 'item', trackingNumber: 'TBA123456789012' },
  { asin: 'B000000002', quantity: 3, shipmentId: 'shared', itemId: 'item', trackingNumber: 'TBA123456789012' },
] };
const ctx = vm.createContext({ ...core, URL, URLSearchParams, Map, Set,
  scrapeState: { stopped: false, sent: 0, failed: 0 }, log() {}, stats() {}, progress() {},
  normalizeTrackingUrlForKey: v => v, dedupeOrderShipments() {},
  resolveShippingAddress: () => '', normalizeOrderStatus: v => v,
  normalizeShipmentStatus: v => v, normalizeCarrier: v => v,
  async readAmazonPage(url, kind, accept) {
    requests.push(url);
    assert.strictEqual(accept({ orders: [order] }), false, 'A price-free background response must try the rendered detail page');
    const result = { orders: [{ ...order, shipments: order.shipments.map(s => ({ ...s, trackingNumber: '', unitPrice: omitPrices ? '' : '$399.99' })) }] };
    assert.strictEqual(accept(result), !omitPrices);
    return result;
  },
  async apiPost(url, body) { uploads.push(JSON.parse(JSON.stringify(body.orders))); return { updated: body.orders.length }; },
});
vm.runInContext(source.slice(source.indexOf('function buildTrackingUrl('), source.indexOf('function normalizeComparable(')), ctx);
vm.runInContext(source.slice(source.indexOf('function normalizeTrackingList('), source.indexOf('// Create a tab')), ctx);
vm.runInContext(source.slice(source.indexOf('function mergeShipment('), source.indexOf('function dedupeOrderShipments(')), ctx);
vm.runInContext(source.slice(source.indexOf('function buildOrderDetailUrl('), source.indexOf('function applyTrackingResult(')), ctx);
vm.runInContext(source.slice(source.indexOf('function validateDetailedOrder('), source.indexOf('async function fetchTrackingForOrders(')), ctx);
(async () => {
  await ctx.discoverMissingTracking([order]);
  assert.strictEqual(requests.length, 1, 'Known tracking must not prevent automatic retrieval of missing product costs');
  assert.ok(order.shipments.every(s => s.trackingNumber === 'TBA123456789012'), 'Cost recovery on an upload checkpoint must retain already fetched tracking');
  await ctx.uploadOrdersToApi([order], 'test@example.test');
  assert.deepStrictEqual(uploads[0].map(row => [row.asin, row.quantity, row.unit_price, row.total_owed]), [
    ['B000000001', '3', '399.99', '1199.97'], ['B000000002', '3', '399.99', '1199.97'],
  ]);
  await ctx.discoverMissingTracking([order]);
  await ctx.uploadOrdersToApi([order], 'test@example.test');
  assert.strictEqual(requests.length, 1, 'Complete details need no repeated lookup during the same scan');
  assert.deepStrictEqual(uploads[1], uploads[0], 'Rescans keep per-product totals stable');
  const zero = { orderId: 'free', shipments: [{ asin: 'FREE', shipmentId: 's', itemId: 'item', unitPrice: '$0.00' }] };
  await ctx.discoverMissingTracking([zero]);
  assert.strictEqual(requests.length, 1, 'A genuine zero cost is complete');
  const mixed = ctx.aggregateProductPayload([
    { order_id: 'split', asin: 'A', quantity: '1', unit_price: '20.00', total_owed: '20.00', tracking_number: 'one' },
    { order_id: 'split', asin: 'A', quantity: '2', unit_price: '30.00', total_owed: '60.00', tracking_number: 'two' },
  ])[0];
  assert.strictEqual(mixed.total_owed, '80.00');
  assert.strictEqual(mixed.unit_price, '26.67', 'Different prices must replace a stale unit cost with the rounded weighted average; total remains authoritative');
  const cache = { cached: { signature: '[["A|",1]]', expiresAt: Date.now() + 10000,
    shipments: [{ asin: 'A', quantity: 1, shipmentId: 's', itemId: 'item' }] } };
  ctx.Date = Date;
  ctx.chrome = { storage: { local: { async get(key) { return { [key]: cache }; } } } };
  vm.runInContext(fs.readFileSync(require.resolve('../chrome_extension/shipment_cache.js'), 'utf8'), ctx);
  const cachedOrder = { orderId: 'cached', shipments: [{ asin: 'A', quantity: 1 }] };
  await ctx.restoreShipmentDiscovery([cachedOrder], 'test@example.test');
  assert.strictEqual(cachedOrder.detailsScanned, false, 'A legacy shipment-link cache without costs must still fetch details');
  order.detailsScanned = true;
  order.shipments.forEach(s => { s.unitPrice = ''; });
  omitPrices = true;
  await ctx.discoverMissingTracking([order]);
  assert.strictEqual(order.detailsScanned, false, 'Incomplete rendered costs remain retryable on checkpoint resume');
  assert.strictEqual(ctx.scrapeState.extractionIncomplete, true, 'Do not report price-free detail extraction as complete');
  omitPrices = false;
  await ctx.discoverMissingTracking([order]);
  assert.strictEqual(order.detailsScanned, true, 'A later scan recovers newly available prices automatically');
  console.log('automatic product cost recovery and upload tests passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
