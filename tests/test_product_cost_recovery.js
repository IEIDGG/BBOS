const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const core = require('../chrome_extension/scrape_core.js');
const source = fs.readFileSync(require.resolve('../chrome_extension/background.js'), 'utf8');
const requests = [];
const uploads = [];
let omitPrices = false;
let detailOverride;
const order = { orderId: '111-1111111-1111111', total: '$2399.94', shipments: [
  { asin: 'B000000001', quantity: 3, shipmentId: 'shared', packageId: 'package-a', itemId: 'item', trackingNumber: 'TBA123456789012' },
  { asin: 'B000000002', quantity: 3, shipmentId: 'shared', itemId: 'item', trackingNumber: 'TBA123456789012' },
] };
const ctx = vm.createContext({ ...core, URL, URLSearchParams, Map, Set,
  scrapeState: { stopped: false, sent: 0, failed: 0 }, log() {}, stats() {}, progress() {},
  normalizeTrackingUrlForKey: v => v, dedupeOrderShipments() {},
  resolveShippingAddress: () => '', normalizeOrderStatus: v => v,
  normalizeShipmentStatus: v => v, normalizeCarrier: v => v,
  async readAmazonPage(url, kind, accept) {
    requests.push(url);
    if (detailOverride) return detailOverride;
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
vm.runInContext(source.slice(source.indexOf('function applyTrackingResult('), source.indexOf('async function fetchTrackingBatch(')), ctx);

// These rows have the same order/ASIN: the manifest must preserve the actual
// quantities per package, including distinct items sharing one tracking number.
const manifestRows = [
  { order_id: 'manifest', asin: 'A', shipment_id: 's', line_item_id: 'l1', package_id: 'p1', quantity: '1', tracking_number: 'SHARED' },
  { order_id: 'manifest', asin: 'A', shipment_id: 's', line_item_id: 'l2', package_id: 'p2', quantity: '2', tracking_number: 'SHARED' },
];
const manifest = JSON.parse(JSON.stringify(ctx.aggregateProductPayload(manifestRows)[0]));
assert.deepStrictEqual(manifest.shipments, [
  { shipment_id: 's', line_item_id: 'l1', package_id: 'p1', tracking_number: 'SHARED', quantity: 1 },
  { shipment_id: 's', line_item_id: 'l2', package_id: 'p2', tracking_number: 'SHARED', quantity: 2 },
]);
assert.strictEqual(manifest.shipments_complete, true);
assert.strictEqual(manifest.quantity, '3');
assert.deepStrictEqual(JSON.parse(JSON.stringify(ctx.aggregateProductPayload(manifestRows)[0])), manifest,
  'Repeat aggregation must not mutate source rows or inflate shipment quantities');
for (const field of ['shipment_id', 'line_item_id', 'package_id']) {
  const onlyId = { order_id: 'untracked', asin: 'A', quantity: '2', [field]: 'stable' };
  const result = JSON.parse(JSON.stringify(ctx.aggregateProductPayload([onlyId])[0]));
  assert.deepStrictEqual(result.shipments, [{ shipment_id: '', line_item_id: '', package_id: '',
    [field]: 'stable', tracking_number: '', quantity: 2 }], 'Retain identified unshipped quantities');
  assert.strictEqual(result.shipments_complete, true);
}
for (const invalid of [0, -1, 1.5, '2units', '1.5', '', null, undefined, true, Number.MAX_SAFE_INTEGER + 1]) {
  const result = ctx.aggregateProductPayload([{ ...manifestRows[0], quantity: invalid }])[0];
  assert.strictEqual(result.shipments?.length || 0, 0, `Do not invent a package quantity from ${String(invalid)}`);
  assert.strictEqual(result.shipments_complete, false);
}
for (const tracking of [['FIRST', 'SECOND'], 'FIRST;SECOND', ['FIRST', 'FIRST'], ['FIRST;SECOND']]) {
  const result = ctx.aggregateProductPayload([{ ...manifestRows[0], tracking_number: tracking }])[0];
  assert.strictEqual(result.shipments?.length || 0, 0, 'An aggregate tracking list cannot assign quantities to individual packages');
  assert.strictEqual(result.shipments_complete, false);
}
const unknown = ctx.aggregateProductPayload([{ order_id: 'unknown', asin: 'A', quantity: '2' }])[0];
assert.strictEqual(unknown.shipments?.length || 0, 0, 'An untracked row without stable IDs cannot identify a saved shipment');
assert.strictEqual(unknown.shipments_complete, false);
const trackingOnly = JSON.parse(JSON.stringify(ctx.aggregateProductPayload([
  { order_id: 'tracking-only', asin: 'A', quantity: '2', tracking_number: [' ONLY '] },
])[0]));
assert.deepStrictEqual(trackingOnly.shipments, [
  { shipment_id: '', line_item_id: '', package_id: '', tracking_number: 'ONLY', quantity: 2 },
]);
assert.strictEqual(trackingOnly.shipments_complete, true);
const ambiguous = ctx.aggregateProductPayload([manifestRows[0], { ...manifestRows[0], quantity: '2' }])[0];
assert.strictEqual(ambiguous.shipments_complete, false, 'Conflicting repeated identities cannot prove complete package coverage');
const conflictingTracking = JSON.parse(JSON.stringify(ctx.aggregateProductPayload([
  manifestRows[0], { ...manifestRows[0], tracking_number: 'CONFLICT' }, manifestRows[1],
])[0]));
assert.strictEqual(conflictingTracking.shipments_complete, false, 'One stable package cannot claim two different tracking numbers in the same snapshot');
assert.deepStrictEqual(conflictingTracking.shipments, [manifest.shipments[1]], 'Reject the conflicting package while retaining unambiguous entries');
const conflictingShipment = JSON.parse(JSON.stringify(ctx.aggregateProductPayload([
  { ...manifestRows[0], package_id: '' },
  { ...manifestRows[0], package_id: '', tracking_number: 'CONFLICT' },
  manifestRows[1],
])[0]));
assert.strictEqual(conflictingShipment.shipments_complete, false, 'Stable shipment and line IDs cannot claim conflicting tracking when no package ID is exposed');
assert.deepStrictEqual(conflictingShipment.shipments, [manifest.shipments[1]], 'Reject the conflicting shipment while retaining unrelated package quantities');
const partialManifest = JSON.parse(JSON.stringify(ctx.aggregateProductPayload([
  manifestRows[0], { order_id: 'manifest', asin: 'A', quantity: '2' },
])[0]));
assert.deepStrictEqual(partialManifest.shipments, [manifest.shipments[0]], 'An ambiguous row must not discard known package quantities');
assert.strictEqual(partialManifest.shipments_complete, false);

(async () => {
  assert.throws(() => ctx.validateDetailedOrder({ orders: [{ ...order, shipments: [
    { asin: 'B000000001', quantity: 6 }, { asin: 'B000000002', quantity: 3 },
  ] }] }, order), /quantit/i, 'A detail response with doubled quantities must be rejected');
  assert.throws(() => ctx.validateDetailedOrder({ orders: [{ ...order, shipments: [
    ...order.shipments, { asin: 'EXTRA', quantity: 1 },
  ] }] }, order), /quantit/i, 'Unexpected detail products must not enter the import');
  assert.doesNotThrow(() => ctx.validateDetailedOrder({ orders: [{ ...order, shipments: [
    { asin: 'B000000001', quantity: 1 }, { asin: 'B000000001', quantity: 2 },
    { asin: 'B000000002', quantity: 3 },
  ] }] }, order), 'Real split shipments preserve the list quantity per product');
  await ctx.discoverMissingTracking([order]);
  assert.strictEqual(requests.length, 1, 'Known tracking must not prevent automatic retrieval of missing product costs');
  assert.ok(order.shipments.every(s => s.trackingNumber === 'TBA123456789012'), 'Cost recovery on an upload checkpoint must retain already fetched tracking');
  await ctx.uploadOrdersToApi([order], 'test@example.test');
  assert.deepStrictEqual(uploads[0].map(row => [row.asin, row.quantity, row.unit_price, row.total_owed]), [
    ['B000000001', '3', '399.99', '1199.97'], ['B000000002', '3', '399.99', '1199.97'],
  ]);
  assert.deepStrictEqual(uploads[0][0].shipments, [
    { shipment_id: 'shared', line_item_id: 'item', package_id: 'package-a', tracking_number: 'TBA123456789012', quantity: 3 },
  ]);
  assert.strictEqual(uploads[0][0].shipments_complete, true);
  ctx.applyTrackingResult(order, order.shipments[0], 0, { timedOut: true }, null);
  await ctx.uploadOrdersToApi([order], 'test@example.test');
  assert.deepStrictEqual(uploads[1][0].shipments, uploads[0][0].shipments, 'A failed refresh keeps the known package quantity and tracking');
  assert.strictEqual(uploads[1][0].shipments_complete, false, 'Known old tracking is not evidence of a complete refresh');
  ctx.applyTrackingResult(order, order.shipments[0], 0, { trackingId: 'TBA123456789012' }, null);
  uploads.splice(1);
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
  const inferred = { orderId: 'inferred', shipments: [{ asin: 'A', quantity: 1, quantityExplicit: false }] };
  detailOverride = { orders: [{ orderId: inferred.orderId, shipments: [
    { asin: 'A', quantity: 1, sourceRowId: 'detail-row:0', unitPrice: '$759.99' },
    { asin: 'A', quantity: 1, sourceRowId: 'detail-row:1', unitPrice: '$759.99' },
  ] }] };
  await ctx.discoverMissingTracking([inferred]);
  await ctx.uploadOrdersToApi([inferred], 'test@example.test');
  assert.deepStrictEqual(uploads.at(-1).map(row => [row.quantity, row.total_owed]), [['2', '1519.98']], 'A missing list badge must not reject or overwrite a valid split detail quantity');
  const disputed = { orderId: 'disputed', shipments: [{ asin: 'A', quantity: 3 }] };
  detailOverride = { orders: [{ orderId: disputed.orderId, shipments: [{ asin: 'A', quantity: 6, unitPrice: '$10.00' }] }] };
  await ctx.discoverMissingTracking([disputed]);
  const beforeDisputedUpload = uploads.length;
  await ctx.uploadOrdersToApi([disputed], 'test@example.test');
  assert.strictEqual(uploads.length, beforeDisputedUpload, 'A disputed quantity must not upload fallback rows');
  const failedDetail = { orderId: 'failed-detail', shipments: [
    { asin: 'A', quantity: 2, shipmentId: 'stable', trackingNumber: 'KNOWN' },
  ] };
  detailOverride = { issue: 'Amazon verification required' };
  await ctx.discoverMissingTracking([failedDetail]);
  await ctx.uploadOrdersToApi([failedDetail], 'test@example.test');
  assert.strictEqual(uploads.at(-1)[0].shipments_complete, false, 'Failed detail discovery cannot prove package coverage');
  failedDetail.shipments[0].trackingLookupIncomplete = true;
  detailOverride = { orders: [{ orderId: failedDetail.orderId, shipments: [
    { asin: 'A', quantity: 2, shipmentId: 'stable', unitPrice: '$10.00' },
  ] }] };
  await ctx.discoverMissingTracking([failedDetail]);
  await ctx.uploadOrdersToApi([failedDetail], 'test@example.test');
  assert.strictEqual(uploads.at(-1)[0].shipments_complete, false, 'Recovering costs must preserve a prior tracking lookup failure');
  assert.strictEqual(uploads.at(-1)[0].shipments[0].tracking_number, 'KNOWN');
  ctx.applyTrackingResult(failedDetail, failedDetail.shipments[0], 0, { trackingId: 'KNOWN' }, null);
  await ctx.uploadOrdersToApi([failedDetail], 'test@example.test');
  assert.strictEqual(uploads.at(-1)[0].shipments_complete, true, 'Successful detail and tracking retries restore a complete manifest');
  for (const invalid of [0, undefined]) {
    await ctx.uploadOrdersToApi([{ orderId: 'invalid', shipments: [
      { asin: 'A', shipmentId: 'stable', quantity: invalid, trackingNumber: 'KNOWN' },
    ] }], 'test@example.test');
    assert.deepStrictEqual(uploads.at(-1)[0].shipments, [], 'Upload defaults must not manufacture a known per-package quantity');
    assert.strictEqual(uploads.at(-1)[0].shipments_complete, false);
  }
  console.log('automatic product cost recovery and upload tests passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
