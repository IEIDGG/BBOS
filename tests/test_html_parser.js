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
for (const file of ['amazon_parser.js', 'scrape_core.js', 'order_detail_scraper.js', 'tracking_scraper.js', 'scraper.js']) {
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
const archived = parse('tracking', '<html><body>Sorry, we are unable to get the tracking information right now. Redirecting to Order Details in 7 seconds.</body></html>', trackingUrl).result;
assert.match(archived.unavailable || '', /Amazon.*unavailable/i, 'Recognize Amazon unavailable tracking instead of timing out or treating it as not shipped');
assert.strictEqual(archived.noTracking, '');
console.log('detached HTML detail/tracking parser tests passed');

const listUrl = 'https://www.amazon.com/your-orders/orders?timeFilter=year-2026&page=0';
const wrongRange = parse('list', '<html><body><select id="time-filter"><option value="months-3" selected>past 3 months</option></select><div class="order-card">Order # 112-8839569-9788250 Cancelled</div></body></html>', listUrl);
assert.match(wrongRange.result.issue, /date filter/i, 'A response displaying the wrong range must trigger fallback');
const list = parse('list', `<html><body><div class="order-card">Order # 112-8839569-9788250 Cancelled</div><a href="/your-orders/orders?timeFilter=year-2026&page=15">16</a></body></html>`, listUrl);
assert.ok(!list.error, list.error);
assert.strictEqual(list.result.cancelledOrders[0].orderId, '112-8839569-9788250');
assert.strictEqual(list.result.maxPage, 16);
assert.ok(parse('list', '<html><body>Loading...</body></html>', listUrl).result.issue);
assert.ok(parse('list', '<html><body>Enter the characters you see below</body></html>', listUrl).result.issue);
assert.strictEqual(parse('list', '<html><body>You have not placed any orders in this time period.</body></html>', listUrl).result.issue, '');
const activeList = parse('list', `<html><body><div class="order-card">Order # 114-8512719-3097055 Order placed September 1, 2026 <div class="shipment"><h2>Delivered</h2><div class="item-box"><a href="/dp/B0F1B8Q5GT">Laptop</a><span>$759.99</span></div></div></div></body></html>`, listUrl);
assert.ok(!activeList.error, activeList.error);
assert.strictEqual(activeList.result.orders[0].orderId, '114-8512719-3097055');
assert.strictEqual(activeList.result.orders[0].shipments[0].asin, 'B0F1B8Q5GT');
const partialList = parse('list', '<html><body>160 orders placed in 2026<div class="order-card">Order # 112-8839569-9788250 Cancelled</div><div class="a-pagination">Loading...</div></body></html>', listUrl);
assert.ok(partialList.result.issue, 'Missing pager must trigger fallback rather than truncate a large history');
const addressTemplateList = parse('list', `<html><body>1 order placed<div class="order-card">Order # 114-8512719-3097055 Order placed September 1, 2026 <div class="shipment"><h2>Delivered</h2><div class="item-box"><a href="/dp/B0F1B8Q5GT">Laptop</a><span>$759.99</span></div></div><script type="text/template" id="shipToData-shippingAddress-test"><div class="a-popover-preload"><div class="a-row">Test Recipient</div><div class="a-row">10 Test Street</div><div class="a-row">Nashua, NH 03063</div></div></script></div></body></html>`, listUrl);
assert.strictEqual(addressTemplateList.result.orders[0].zipCode, '03063', 'Retain inert address templates for ZIP filtering');
const scriptCommentDoc = new DOMParser().parseFromString(`<html><body><div class="order-card">Order # 114-3149382-3240200 Order placed August 5, 2026 Approval needed <a href="/dp/B0F1B8Q5GT">Product</a><span>$2.91</span><script>// Cancelled order: check the shipment status text</script></div></body></html>`, 'text/html');
const scriptCommentResult = ctx.ieidExtractOrderList(scriptCommentDoc, new URL(listUrl));
assert.strictEqual(scriptCommentResult.cancelledOrders.length, 0, 'Amazon script comments are not cancellation status');
assert.strictEqual(scriptCommentResult.orders.length, 1, 'Active order remains present despite cancellation words in script comments');
