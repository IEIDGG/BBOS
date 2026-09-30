const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync(require.resolve('../chrome_extension/scraper.js'), 'utf8');
const core = require('../chrome_extension/scrape_core.js');
function link(startIndex, extra = {}) {
  return { textContent: '', href: `https://www.amazon.com/your-orders/orders?orderFilter=year-2026&startIndex=${startIndex}`,
    getAttribute(name) { return extra[name] || null; }, ...extra };
}
function extract({ links = [], old = [], roots = [], start = 0, href }) {
  const document = {
    querySelector: () => null,
    querySelectorAll(selector) {
      if (selector === '.a-pagination li, .a-pagination a, [aria-label*="page" i]') return old;
      if (selector.includes('a[href*="startIndex="]')) return links;
      return roots;
    },
  };
  return vm.runInNewContext(source.replace('return extractOrdersFromPage();', 'return extractMaxPage();'), {
    ...core, document, URL, location: { href: href || `https://www.amazon.com/your-orders/orders?orderFilter=year-2026&startIndex=${start}` },
  });
}
assert.strictEqual(extract({ links: [link(10), link(150)] }), 16, 'Last-page URL works without the old CSS class');
assert.strictEqual(extract({ links: [link(10, { 'aria-label': 'Next page' })] }), 2);
assert.strictEqual(extract({ links: [link(20)], start: 10 }), 3, 'Each next-page link extends the scan');
assert.strictEqual(extract({ start: 150 }), 16, 'Last page remains known without a next link');
assert.strictEqual(extract({ links: [link(150, { href: 'https://evilamazon.com/your-orders/orders?startIndex=150' }),
  link(990, { href: 'https://www.amazon.com/s?startIndex=990' }),
  link(990, { href: 'https://www.amazon.com/your-orders/orders?orderFilter=year-2025&startIndex=990' })] }), 1);
const root = { textContent: 'Previous 1 2 3 4 5 6 7 8 … 16 Next', querySelectorAll: () => [
  { textContent: 'Next', getAttribute: name => name === 'aria-label' ? 'Page 16' : null },
] };
assert.strictEqual(extract({ roots: [root] }), 16, 'Read page labels in modern pagination controls');
const modern = 'https://www.amazon.com/your-orders/orders?timeFilter=year-2026';
assert.strictEqual(extract({ href: modern, links: [link(0, { href: modern + '&page=15' })] }), 16);
assert.strictEqual(extract({ href: modern + '&page=15' }), 16);
assert.strictEqual(extract({ href: modern, links: [link(0, { href: modern.replace('2026', '2025') + '&page=99' })] }), 1);
console.log('order pagination tests passed');

// Run the actual list-scan loop with a sliding pager that reveals only the
// next page. ZIP filtering must not end traversal when a page keeps no orders.
const background = fs.readFileSync(require.resolve('../chrome_extension/background.js'), 'utf8');
const loop = background.slice(background.indexOf('    while (page <= totalPages)'),
  background.indexOf('      if (!scrapeState.stopped && !scrapeState.extractionIncomplete)'));
async function traverse(limit) {
  const visited = [];
  const ctx = vm.createContext({
    page: 1, totalPages: 1, maxPages: limit, yearFilter: 'year-2026',
    zipFilters: ['03063'], totalZipSkipped: 0, allOrders: [], allCancelledOrders: [],
    scrapeState: { stopped: false },
    progress() {}, log() {}, stats() {}, snapshot: () => ({}),
    async readAmazonPage(url, kind, accept) { assert.strictEqual(kind, 'list'); const params = new URL(url).searchParams; assert.strictEqual(params.get('timeFilter'), 'year-2026'); const page = Number(params.get('page')) + 1; visited.push(page); const result = { orders: [{ orderId: `order-${page}` }], cancelledOrders: [], maxPage: Math.min(page + 1, 16) }; assert.ok(accept(result)); return result; },
    async sleep() {}, async persistScrapeCheckpoint() {}, randomOrderPageDelay: () => 0,
    filterOrdersByZip: () => ({ keptOrders: [], skipped: 1 }),
    mergeCancelledOrders() {}, dedupeOrderShipments() {},
  });
  await vm.runInContext(`(async () => { ${loop} })()`, ctx);
  return visited;
}
(async () => {
  assert.deepStrictEqual(await traverse(0), Array.from({ length: 16 }, (_, i) => i + 1));
  assert.deepStrictEqual(await traverse(2), [1, 2], 'Respect an explicit maximum-page limit');
  console.log('sliding pagination and maximum-page limit tests passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
