const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const root = path.join(__dirname, '..', 'chrome_extension');
const manifest = JSON.parse(fs.readFileSync(path.join(root, 'manifest.json'), 'utf8'));
const pageScript = fs.readFileSync(path.join(root, 'order_page.js'), 'utf8');
const orderId = '111-1111111-1111111';

for (const host of ['www.amazon.com', 'amazon.com']) {
  for (const pathname of ['/gp/your-account/order-details', '/your-orders/order-details']) {
    const url = new URL(`https://${host}${pathname}?orderID=${orderId}`);
    const matched = manifest.content_scripts.some(entry => entry.js.includes('order_page.js')
      && entry.matches.some(pattern => new RegExp('^' + pattern.split('*').map(part =>
        part.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('.*') + '$').test(url.href)));
    assert.ok(matched, `Button content script must load on ${url.href}`);
    const buttons = [];
    const messages = [];
    const document = {
      readyState: 'complete',
      body: { innerText: '', appendChild(button) { buttons.push(button); } },
      getElementById(id) { return buttons.find(button => button.id === id); },
      createElement() {
        return { style: {}, listeners: {}, addEventListener(event, callback) { this.listeners[event] = callback; } };
      },
    };
    const context = vm.createContext({ document, location: url, URLSearchParams, console,
      chrome: { storage: { local: { set(data, callback) { callback(); } } },
        runtime: { sendMessage(message, callback) { messages.push(message); callback(); } } },
    });
    vm.runInContext(pageScript, context);
    assert.strictEqual(buttons.length, 1);
    assert.strictEqual(buttons[0].textContent, 'Scan with IEID');
    buttons[0].listeners.click();
    assert.strictEqual(messages[0].action, 'prepare_single_order_scan');
    assert.strictEqual(messages[0].orderId, orderId);
    vm.runInContext(pageScript, context);
    assert.strictEqual(buttons.length, 1, 'Do not add duplicate scan buttons');
  }
}

// A single-order refresh must fetch tracking even when bulk settings disable
// it, enable cached tracking, or contain a different ZIP filter.
const background = fs.readFileSync(path.join(root, 'background.js'), 'utf8');
const singleCode = background.slice(background.indexOf('async function runSingleOrderScrape('),
  background.indexOf('// --- Main scrape logic ---'));
const extracted = { orderId, zipCode: '11779', shipments: [{ asin: 'B000000001', productTitle: 'Headphones', quantity: 3 }] };
let trackingCalls = 0;
let uploaded;
let completed;
const context = vm.createContext({
  scrapeOutcomeSuccess: require('../chrome_extension/scrape_core.js').scrapeOutcomeSuccess,
  normalizeZipFilters: () => ['03063'],
  clearScrapeLogs() {}, startScrapeKeepAlive() {}, stopScrapeKeepAlive() {}, openLogTab() {},
  log() {}, progress() {}, stats() {}, dedupeOrderShipments() {},
  async getAuthCookie() { return 'test'; },
  async loadDbShipmentCache() { throw new Error('Single-order refresh must bypass tracking cache'); },
  async detectAmazonAccountEmail() { return 'test@example.com'; },
  buildOrderDetailUrl: id => `https://www.amazon.com/your-orders/order-details?orderID=${id}`,
  async openTab() { return 1; }, async sleep() {}, async closeTab() {},
  async injectAndRun() { return { orders: [extracted] }; },
  filterOrdersByZip() { return { keptOrders: [], skipped: 1 }; },
  async fetchTrackingForOrders(orders, start, end, cache) {
    assert.strictEqual(cache, null);
    trackingCalls++;
    orders[0].shipments[0].trackingNumber = 'TBA123456789012';
  },
  async uploadOrdersToApi(orders) { uploaded = orders; },
  scrapeDone(message, success) { completed = success; },
  chrome: { storage: { local: { remove() {} } } },
});
vm.runInContext(singleCode, context);
context.runSingleOrderScrape({ orderId, fetchTracking: false, useDbCache: true, zipFilters: '03063' }).then(() => {
  assert.strictEqual(completed, true);
  assert.strictEqual(trackingCalls, 1);
  assert.strictEqual(uploaded[0].orderId, orderId);
  assert.strictEqual(uploaded[0].shipments[0].trackingNumber, 'TBA123456789012');
  assert.strictEqual(uploaded[0].shipments[0].quantity, 3);
  console.log('single-order button and fresh tracking refresh tests passed');
}).catch(error => { console.error(error); process.exitCode = 1; });
