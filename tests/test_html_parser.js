const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const path = require('path');
const { DOMParser, parseHTML } = require('linkedom');
const root = path.join(__dirname, '../chrome_extension');
let listener;
const ctx = vm.createContext({ URL, URLSearchParams, DOMParser, Node: parseHTML('<html></html>').Node,
  chrome: { runtime: { id: 'test', onMessage: { addListener(fn) { listener = fn; } } } },
});
for (const file of ['amazon_parser.js', 'scrape_core.js', 'order_detail_scraper.js', 'tracking_scraper.js']) {
  vm.runInContext(fs.readFileSync(path.join(root, file), 'utf8'), ctx);
}
function parse(kind, html, url) {
  let response;
  listener({ target: 'ieid-html-parser', kind, html, url }, { id: 'test' }, value => { response = value; });
  return response;
}
const detailUrl = 'https://www.amazon.com/your-orders/order-details?orderID=112-9246572-5333850';
const html = fs.readFileSync(path.join(__dirname, 'fixtures/amazon/request-detail.html'), 'utf8');
const detail = parse('detail', html, detailUrl);
assert.ok(!detail.error, detail.error);
assert.strictEqual(detail.result.orders[0].shipments.length, 2);
assert.deepStrictEqual(Array.from(detail.result.orders[0].shipments, s => s.shipmentId), ['first', 'second']);
assert.deepStrictEqual(Array.from(detail.result.orders[0].shipments, s => s.quantity), [1, 1]);
assert.strictEqual(ctx.remoteExecuted, undefined, 'Remote scripts must remain inert');
assert.ok(parse('detail', '<html><body>Sign in</body></html>', detailUrl).error);
assert.ok(parse('detail', html.replaceAll('112-9246572-5333850', '111-1111111-1111111'), detailUrl).error);
const trackingUrl = 'https://www.amazon.com/progress-tracker/package?orderId=112-9246572-5333850&shipmentId=first';
for (const id of ['1ZY469E40307962229', 'TBA332296109428', '9339589725268856240313']) {
  const parsed = parse('tracking', `<html><body><h2>Shipped with USPS</h2><div class="pt-delivery-card-trackingId">Tracking ID: ${id}</div></body></html>`, trackingUrl);
  assert.strictEqual(parsed.result.trackingId, id);
}
const challenge = parse('tracking', '<html><body>Enter the characters you see below</body></html>', trackingUrl);
assert.strictEqual(challenge.result.issue, 'Amazon verification page');
assert.strictEqual(parse('tracking', '<html><body>Loading...</body></html>', trackingUrl).result.trackingId, '');
console.log('detached HTML detail/tracking parser tests passed');
