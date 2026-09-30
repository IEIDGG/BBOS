const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const core = require('../chrome_extension/scrape_core.js');
const source = fs.readFileSync(require.resolve('../chrome_extension/background.js'), 'utf8');
const queue = source.slice(source.indexOf('function buildTrackingUrl('), source.indexOf('function normalizeComparable('));
const detailCode = source.slice(source.indexOf('function validateDetailedOrder('), source.indexOf('async function fetchTrackingForOrders('));
const closed = [];
const opened = [];
const old = { orderId: 'old', shipments: [{ asin: 'SAME', productTitle: 'Laptop', quantity: 2 }] };
const recent = { orderId: 'recent', shipments: [{ asin: 'OTHER', shipmentId: 'recent-shipment', itemId: 'item' }] };
const single = { orderId: 'single', detailsScanned: true, shipments: [{ asin: 'SINGLE' }] };
const failed = { orderId: 'failed', shipments: [{ asin: 'KEEP' }] };
const splitPartial = { orderId: 'splitPartial', shipments: [{ asin: 'KEEP1', quantity: 2 }] };
const partial = { orderId: 'partial', shipments: [{ asin: 'KEEP1' }, { asin: 'KEEP2' }] };
const ctx = vm.createContext({ ...core, URL, URLSearchParams,
  normalizeTrackingUrlForKey: value => value, scrapeState: { stopped: false },
  log() {}, stats() {}, buildOrderDetailUrl: id => id,
  async openTab(id) { opened.push(id); return id; },
  async closeTab(id) { closed.push(id); }, async waitForTabReady() {},
  dedupeOrderShipments() {},
  async injectAndRun(id, file) {
    assert.strictEqual(file, 'order_detail_scraper.js');
    if (id === 'failed') throw new Error('Amazon verification required');
    if (id === 'partial' || id === 'splitPartial') return { orders: [{ orderId: id, shipments: [{ asin: 'KEEP1' }] }] };
    return { orders: [{ orderId: id, shipments: [
      { asin: 'SAME', quantity: 1, shipmentId: 'first', lineItemId: 'shareds' },
      { asin: 'SAME', quantity: 1, shipmentId: 'second', lineItemId: 'shareds' },
    ] }] };
  },
});
ctx.readAmazonPage = async (url, kind, accept) => {
  const id = await ctx.openTab(url);
  try { return await ctx.injectAndRun(id, 'order_detail_scraper.js'); }
  finally { await ctx.closeTab(id); }
};
vm.runInContext(queue + detailCode, ctx);
(async () => {
  assert.strictEqual(typeof ctx.discoverMissingTracking, 'function', 'Bulk scans need order-detail fallback');
  await ctx.discoverMissingTracking([old, recent, single, failed, partial, splitPartial]);
  assert.deepStrictEqual(opened.sort(), ['failed', 'old', 'partial', 'splitPartial']);
  assert.deepStrictEqual(closed.sort(), opened);
  assert.strictEqual(old.shipments.length, 2, 'Discover split shipments behind the list summary');
  const groups = ctx.buildTrackingFetchGroups([old, recent, single]);
  assert.strictEqual(groups.groups.length, 3);
  assert.strictEqual(groups.noUrlTargets.length, 1, 'Missing tracking must be reported, not silently dropped');
  assert.strictEqual(failed.shipments[0].asin, 'KEEP');
  assert.strictEqual(partial.shipments.length, 2, 'Incomplete details must not drop list items');
  assert.strictEqual(splitPartial.shipments[0].quantity, 2, 'Partial same-ASIN details cannot drop units or tracking');
  assert.strictEqual(ctx.scrapeState.extractionIncomplete, true);
  assert.ok(groups.groups.some(g => new URL(g.trackUrl).searchParams.get('shipmentId') === 'second'));
  console.log('bulk hidden-tracking detail fallback tests passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
