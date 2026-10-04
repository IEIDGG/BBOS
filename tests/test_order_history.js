const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const path = require('path');
const root = path.join(__dirname, '../chrome_extension');
const history = require('../chrome_extension/order_history.js');

const plan = history.createOrderHistoryPlan('months-12', new Date(2026, 9, 1));
assert.deepStrictEqual(plan.filters, ['year-2026', 'year-2025']);
assert.strictEqual(plan.cutoffDate, '2025-10-01');
assert.deepStrictEqual(history.createOrderHistoryPlan('year-2024').filters, ['year-2024']);
assert.strictEqual(history.createOrderHistoryPlan('months-12', new Date(2024, 1, 29)).cutoffDate, '2023-02-28');
assert.throws(() => history.createOrderHistoryPlan('months-3'), /Unsupported/);
assert.deepStrictEqual(history.filterOrderHistory([
  { orderId: 'keep', orderDate: 'October 1, 2025' },
  { orderId: 'old', orderDate: 'September 30, 2025' },
  { orderId: 'iso', orderDate: '2026-01-01' },
], plan).map(o => o.orderId), ['keep', 'iso']);
assert.throws(() => history.filterOrderHistory([{ orderDate: '' }], plan), /order date/i);

// Exercise the real bulk orchestration, including checkpoint resume and the
// transition from the current year to the previous year. No browser or API writes.
const background = fs.readFileSync(path.join(root, 'background.js'), 'utf8');
const bulk = background.slice(background.indexOf('async function runScrape('), background.indexOf('function normalizeCarrier('));
async function scan(limit = 0, checkpoint = null, tracking = false, now = [2026, 9, 1]) {
  const visited = [], saved = [], uploaded = [], completions = [], detailRecovery = [];
  const ctx = vm.createContext({ ...history, createOrderHistoryPlan: filter => history.createOrderHistoryPlan(filter, new Date(...now)),
  scrapeOutcomeSuccess: require('../chrome_extension/scrape_core.js').scrapeOutcomeSuccess,
  withExtensionOperation: (_kind, work) => work(),
  chrome: {}, normalizeZipFilters: () => [], clearScrapeLogs() {}, startScrapeKeepAlive() {},
  stopScrapeKeepAlive() {}, openLogTab() {}, log() {}, progress() {}, stats() {},
  async getAuthCookie() { return 'test'; }, async detectAmazonAccountEmail() { return 'test@example.com'; },
  async persistScrapeCheckpoint(value) { saved.push(JSON.parse(JSON.stringify(value))); },
  async sleep() {}, randomOrderPageDelay: () => 0, dedupeOrderShipments: () => 0,
  mergeCancelledOrders(target, incoming) { target.push(...incoming); }, reportCancelledOrders: orders => orders,
  async uploadCancelledOrdersToApi(orders) { uploaded.push(...orders); },
  async uploadOrdersToApi(orders) { uploaded.push(...orders); ctx.scrapeState.sent = orders.length; },
  async discoverMissingTracking(orders) { detailRecovery.push(orders.map(order => order.orderId)); },
  async readAmazonPage(url, kind, accept) {
    if (kind === 'tracking') { const result = { unavailable: 'Amazon tracking information unavailable for this shipment' }; assert.ok(accept(result)); return result; }
    const params = new URL(url).searchParams, year = params.get('timeFilter');
    const page = Number(params.get('page')) + 1;
    visited.push(`${year}:${page}`);
    const previous = year === 'year-2025';
    const result = { orders: [{ orderId: `${year}-${page}`, orderDate: previous && page === 2 ? 'September 1, 2025' : previous ? 'November 1, 2025' : 'January 1, 2026', shipments: [{ asin: 'TEST' }] }],
      cancelledOrders: previous ? [{ orderId: `cancel-${page}`, orderDate: page === 2 ? 'September 1, 2025' : 'October 1, 2025' }] : [], maxPage: Math.min(page + 1, 2) };
    assert.ok(accept(result)); return result;
  }, maybeAutoApplyUpdate() {}, scrapeDone(message, success) { completions.push({ message, success }); } });
  vm.runInContext(bulk, ctx);
  vm.runInContext(background.slice(background.indexOf('function applyTrackingResult('), background.indexOf('function validateDetailedOrder(')), ctx);
  ctx.fetchTrackingForOrders = async orders => {
    await ctx.fetchTrackingBatch(orders.map((order, shipmentIndex) => ({ trackUrl: 'https://www.amazon.com/progress-tracker/package', targets: [{ order, shipment: order.shipments[0], shipmentIndex }] })));
  };
  await ctx.runScrape({ yearFilter: 'months-12', maxPages: limit, fetchTracking: tracking }, checkpoint);
  return { visited, saved, uploaded, completions, detailRecovery };
}
(async () => {
  const all = await scan();
  assert.deepStrictEqual(all.visited, ['year-2026:1', 'year-2026:2', 'year-2025:1', 'year-2025:2']);
  assert.strictEqual(all.completions[0].success, true, all.completions[0].message);
  assert.strictEqual(all.detailRecovery.length, 1, 'Retrieve missing product costs even with tracking disabled');
  assert.deepStrictEqual(all.uploaded.map(o => o.orderId), ['year-2026-1', 'year-2026-2', 'year-2025-1', 'cancel-1']);
  const resumed = await scan(0, all.saved.find(s => s.filterIndex === 1 && s.page === 1 && s.phase === 'list'), false, [2027, 0, 1]);
  assert.deepStrictEqual(resumed.visited, ['year-2025:1', 'year-2025:2']);
  assert.strictEqual(resumed.completions[0].success, true);
  const uploadResume = await scan(0, all.saved.find(s => s.phase === 'upload'));
  assert.strictEqual(uploadResume.detailRecovery.length, 1, 'An upload checkpoint still retrieves missing prices');
  const limited = await scan(2);
  assert.deepStrictEqual(limited.visited, ['year-2026:1', 'year-2026:2']);
  assert.match(limited.completions[0].message, /limit/i, 'Do not label limited coverage as a full history');
  const unavailable = await scan(0, null, true);
  assert.strictEqual(unavailable.completions[0].success, false);
  assert.match(unavailable.completions[0].message, /3 tracking unavailable from Amazon/);
  assert.strictEqual(unavailable.uploaded.length, 4, 'Orders still import when Amazon cannot provide old tracking');
  const popup = fs.readFileSync(path.join(root, 'popup.html'), 'utf8');
  assert.match(popup, /value="months-12" selected/);
  assert.match(popup, /id="maxPages" value="0"/);
  console.log('rolling year, cutoff, full traversal and resume tests passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
