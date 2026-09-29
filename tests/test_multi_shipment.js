const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const core = require('../chrome_extension/scrape_core.js');
const root = path.join(__dirname, '..', 'chrome_extension');
const detail = fs.readFileSync(path.join(root, 'order_detail_scraper.js'), 'utf8');

// Each delivery section owns a purchasedItems block. The first block can
// contain multiple products; later blocks can repeat the same ASIN/item ID.
const rows = [{ name: 'white' }, { name: 'third item' }, { name: 'black' }];
const blocks = [rows.slice(0, 2), rows.slice(2)].map(items => ({ querySelectorAll: () => items }));
const document = {
  querySelector: selector => selector === '[data-component="purchasedItems"]' ? blocks[0] : null,
  querySelectorAll: selector => selector === '[data-component="purchasedItems"]' ? blocks : [],
};
const helpers = vm.runInNewContext(detail.replace('return extractOrderFromDetailPage();',
  'return { findShipmentContainers };'), { document });
assert.strictEqual(helpers.findShipmentContainers().length, 3, 'Scan every purchasedItems block');

// Exercise the real extraction helpers for title/image duplicate anchors,
// repeated line-item IDs, same-ASIN split units, and different-ASIN deliveries.
function item(asin, shipmentId, quantity = 1) {
  const pop = { href: `https://www.amazon.com/your-orders/pop?lineItemId=shareds&shipmentId=${shipmentId}` };
  const product = { href: `https://www.amazon.com/dp/${asin}`, textContent: `Product ${asin}`,
    getAttribute: () => null, querySelector: () => null, closest: () => root };
  const imageLink = { ...product, textContent: '' };
  const root = {
    textContent: `Delivered July 2 Qty: ${quantity}`,
    contains: () => true,
    querySelector(selector) {
      if (selector === '[data-component="unitPrice"]') return { textContent: '$29.99', querySelector: () => null };
      if (selector === 'h2') return { textContent: 'Delivered July 2' };
      return null;
    },
    querySelectorAll(selector) {
      if (selector.includes('a[href*="/dp/"]')) return [imageLink, product];
      if (selector.includes('a[href*="shipmentId"]')) return [pop];
      if (selector.includes('a[href*="ship-track"]')) return [];
      if (selector.includes('a[href*="' + asin + '"]')) return [product];
      return [];
    },
  };
  return root;
}
for (const asins of [['B000000001', 'B000000001'], ['B000000001', 'B000000002']]) {
  const items = asins.map((asin, i) => item(asin, `shipment${i}`, i + 1));
  const doc = { querySelector: () => null,
    querySelectorAll: selector => selector === '[data-component="purchasedItems"]'
      ? items.map(root => ({ querySelectorAll: () => [root] })) : [],
  };
  const extract = vm.runInNewContext(detail.replace('return extractOrderFromDetailPage();',
    'return { extractShipments };'), { ...core, URL, document: doc, location: { href: 'https://www.amazon.com/your-orders/order-details' } });
  const shipments = extract.extractShipments();
  assert.strictEqual(shipments.length, 2, 'Duplicate image/title links collapse, separate shipments survive');
  assert.deepStrictEqual(Array.from(shipments, s => s.shipmentId), ['shipment0', 'shipment1']);
  assert.deepStrictEqual(Array.from(shipments, s => s.asin), asins);
  assert.deepStrictEqual(Array.from(shipments, s => s.quantity), [1, 2]);
  assert.ok(shipments.every(s => s.lineItemId === 'shareds'));
}

// Never borrow tracking from a different shipment with a reused item ID.
assert.strictEqual(core.matchingShipTrack({ shipmentId: 'second', itemId: 'shared' }, [
  { shipmentId: 'first', itemId: 'shared', trackingUrl: 'first URL' },
]), null);

const background = fs.readFileSync(path.join(root, 'background.js'), 'utf8');
const cacheCode = background.slice(background.indexOf('function normalizeTrackingList('),
  background.indexOf('// Create a tab'));
const ctx = vm.createContext({ ...core, Map, Set, log() {}, stats() {},
  scrapeState: { skippedCached: 0, sent: 0, failed: 0 },
  resolveShippingAddress: () => '', normalizeOrderStatus: v => v,
  normalizeShipmentStatus: v => v, normalizeCarrier: v => v,
  progress() {},
});
vm.runInContext(cacheCode, ctx);
const order = { orderId: '111-1111111-1111111', shipments: [
  { asin: 'B000000001', shipmentId: 'first', lineItemId: 'shared', quantity: 1, unitPrice: '$759.99', status: 'Delivered', trackingNumber: '1ZFIRST' },
  { asin: 'B000000001', shipmentId: 'second', lineItemId: 'shared', quantity: 1, unitPrice: '$759.99', status: 'Delivered', trackingNumber: '1ZSECOND' },
  { asin: 'B000000002', shipmentId: 'third', quantity: 2, unitPrice: '$29.99', status: 'Delivered', trackingNumber: 'TBAOTHER' },
] };
const cache = ctx.buildDbShipmentCache([{ order_id: order.orderId, asin: 'B000000001', tracking_number: ['1ZFIRST'] }]);
assert.strictEqual(ctx.applyDbCacheToOrders([order], cache), 0, 'Cached product tracking cannot identify split shipments');
assert.strictEqual(order.shipments[1].trackingNumber, '1ZSECOND');
const multipleCache = ctx.buildDbShipmentCache([{ order_id: order.orderId, asin: 'B000000002', tracking_number: ['TBAOTHER', 'TBAANOTHER'] }]);
assert.strictEqual(ctx.applyDbCacheToOrders([order], multipleCache), 0, 'Multiple cached trackings must not be reduced to the first');

const duplicateCache = ctx.buildDbShipmentCache([
  { order_id: order.orderId, asin: 'B000000002', tracking_number: ['TBAOTHER'] },
  { order_id: order.orderId, asin: 'B000000002', tracking_number: ['TBAANOTHER'] },
]);
assert.strictEqual(ctx.applyDbCacheToOrders([order], duplicateCache), 0);
const uploads = [];
ctx.apiPost = async (url, body) => { uploads.push(JSON.parse(JSON.stringify(body.orders))); return { updated: body.orders.length }; };
vm.runInContext(background.slice(background.indexOf('function parseMoneyAmount('),
  background.indexOf('function applyTrackingResult(')), ctx);
(async () => {
  await ctx.uploadOrdersToApi([order], 'test@example.com');
  assert.strictEqual(uploads[0].length, 2, 'One complete database update per product, avoiding sequential overwrites');
  const laptops = uploads[0].find(row => row.asin === 'B000000001');
  assert.deepStrictEqual(laptops.tracking_number, ['1ZFIRST', '1ZSECOND']);
  assert.strictEqual(laptops.quantity, '2');
  assert.strictEqual(laptops.total_owed, '1519.98');
  assert.strictEqual(laptops.shipment_id, undefined, 'Aggregates must not claim a single shipment identity');
  const other = uploads[0].find(row => row.asin === 'B000000002');
  assert.strictEqual(other.quantity, '2');
  assert.strictEqual(other.total_owed, '59.98');
  await ctx.uploadOrdersToApi([order], 'test@example.com');
  assert.deepStrictEqual(uploads[1], uploads[0], 'Repeat scans do not inflate quantity');
  order.shipments[1].trackingNumber = '';
  await ctx.uploadOrdersToApi([order], 'test@example.com');
  assert.strictEqual(uploads[2][0].tracking_number, undefined,
    'A partial lookup must not replace the database tracking list with a subset');
  assert.strictEqual(uploads[2][0].quantity, '2');
  assert.strictEqual(core.scrapeOutcomeSuccess(ctx.scrapeState), false);
  console.log('multi-shipment extraction, cache and upload tests passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
