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
const productPrices = parse('detail', `<html><body><main id="orderDetails">
  Order # 112-9246572-5333850
  <div data-component="purchasedItems"><div class="a-row">
  ${[['B000000001', '399.99'], ['B000000002', '49.95']].map(([asin, price]) => `
    <div class="a-fixed-left-grid"><div class="a-fixed-left-grid-inner">
      <div class="a-fixed-left-grid-col a-col-left"><div class="product-image"><a href="/dp/${asin}">Image</a><span class="product-image__qty">3</span></div></div>
      <div data-component="purchasedItemsRightGrid"><div class="a-fixed-left-grid-col a-col-right">
        <div data-component="itemTitle"><div class="a-row"><a class="a-link-normal" href="/dp/${asin}">Product ${asin}</a></div></div>
        <div data-component="unitPrice"><span class="a-price a-text-price"><span class="a-offscreen">$${price}</span><span aria-hidden="true">$${price}</span></span></div>
      </div></div>
    </div></div>`).join('')}
  </div></div></main></body></html>`, detailUrl);
assert.deepStrictEqual(Array.from(productPrices.result.orders[0].shipments, s => [s.asin, s.quantity, s.unitPrice]), [
  ['B000000001', 3, '$399.99'], ['B000000002', 3, '$49.95'],
], 'Read each product’s own unit price and quantity from the current purchased-items grid');
assert.ok(parse('detail', '<html><body>Sign in</body></html>', detailUrl).error);
assert.ok(parse('detail', html.replaceAll('112-9246572-5333850', '111-1111111-1111111'), detailUrl).error);
// Current unshipped orders have an empty image link before the title link.
// Both links describe the same grid row, including its quantity and unit cost.
const unshippedHtml = fs.readFileSync(path.join(__dirname, 'fixtures/amazon/unshipped-grid-detail.html'), 'utf8');
const unshippedDetail = parse('detail', unshippedHtml, detailUrl);
assert.deepStrictEqual(Array.from(unshippedDetail.result.orders[0].shipments, s => [s.asin, s.productTitle, s.quantity, s.unitPrice]), [
  ['B000000001', 'Laptop', 3, '$1,099.00'],
], 'An empty image link and its title link must produce one purchased item, not double its quantity');
const renderedDoc = new DOMParser().parseFromString(unshippedHtml, 'text/html');
assert.deepStrictEqual(Array.from(ctx.ieidExtractOrderDetail(renderedDoc, new URL(detailUrl)).orders[0].shipments, s => [s.asin, s.quantity]), [
  ['B000000001', 3],
], 'The rendered-tab parser must also preserve the purchased quantity');
const splitDoc = new DOMParser().parseFromString(unshippedHtml.replace('<span>3</span>', '<span>1</span>'), 'text/html');
const purchasedBlock = splitDoc.querySelector('[data-component="purchasedItems"]');
purchasedBlock.after(purchasedBlock.cloneNode(true));
const unidentifiedSplits = ctx.ieidExtractOrderDetail(splitDoc, new URL(detailUrl)).orders[0];
assert.deepStrictEqual(Array.from(unidentifiedSplits.shipments, s => s.quantity), [1, 1], 'Separate purchased rows without shipment IDs must both survive');
assert.strictEqual(new Set(Array.from(unidentifiedSplits.shipments, s => ctx.getShipmentIdentity(unidentifiedSplits, s))).size, 2, 'Background deduplication must preserve separate DOM rows too');
const nestedFallback = parse('detail', `<html><body><main id="orderDetails">Order # 112-9246572-5333850
  <div class="delivery-box"><div class="a-fixed-left-grid"><div class="shipment-item">
    <a class="a-link-normal" href="/dp/B000000001">Laptop</a><span class="item-view-qty">3</span>
    <div data-component="unitPrice"><span class="a-offscreen">$1,099.00</span></div>
  </div></div></div></main></body></html>`, detailUrl);
assert.deepStrictEqual(Array.from(nestedFallback.result.orders[0].shipments, s => s.quantity), [3], 'Overlapping fallback containers must retain one identity for the same purchased row');
const wrapperFallback = parse('detail', `<html><body><main id="orderDetails">Order # 112-9246572-5333850
  <div class="delivery-box"><div class="shipment-wrapper">
    <a class="a-link-normal" href="/dp/B000000001">Laptop</a><span class="item-view-qty">3</span>
    <div data-component="unitPrice"><span class="a-offscreen">$1,099.00</span></div>
  </div></div></main></body></html>`, detailUrl);
assert.deepStrictEqual(Array.from(wrapperFallback.result.orders[0].shipments, s => s.quantity), [3], 'Fallback wrappers without product grids must not reclaim the same anchors');
const siblingHtml = `<html><body><main id="orderDetails">Order # 112-9246572-5333850
  <div class="delivery-box"><div class="a-row">${['first','second'].map(id => `<div class="shipment-wrapper">
    <a class="a-link-normal" href="/dp/B000000001">Laptop</a><span class="item-view-qty">1</span>
    <div data-component="unitPrice"><span class="a-offscreen">$1,099.00</span></div>
    <a href="/your-orders/pop?orderId=112-9246572-5333850&shipmentId=${id}&lineItemId=shared">Track</a>
  </div>`).join('')}</div></div></main></body></html>`;
const siblingWrappers = parse('detail', siblingHtml, detailUrl);
assert.deepStrictEqual(Array.from(siblingWrappers.result.orders[0].shipments, s => [s.quantity,s.shipmentId]), [[1,'first'],[1,'second']], 'A shared outer row must not merge separate shipment wrappers');
const partialSiblingHtml = siblingHtml.replace('<a href="/your-orders/pop?orderId=112-9246572-5333850&shipmentId=second&lineItemId=shared">Track</a>', '');
const partialSiblings = parse('detail', partialSiblingHtml, detailUrl).result.orders[0].shipments;
assert.deepStrictEqual(Array.from(partialSiblings, s => [s.quantity,s.shipmentId]), [[1,'first'],[1,'']], 'A row with missing IDs must not inherit its sibling shipment identity');
assert.strictEqual(partialSiblings[1].trackingUrl, '', 'A row with missing tracking must not inherit a sibling link');
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
assert.strictEqual(activeList.result.orders[0].shipments[0].quantityExplicit, false, 'A missing list quantity badge is an inferred one');
// Older orders use enhanced cards with separate image/title wrappers. Both
// links belong to one item, even when several cards share an outer a-row.
const enhancedList = parse('list', `<html><body><div class="order-card">Order # 114-8512719-3097055 Order placed October 1, 2025
  <div class="shipment"><h2>Delivered</h2><div class="a-row"><div class="yo-enhanced-flex">
    <div class="yo-enhanced-flex-card"><div class="yo-enhanced-flex-image"><a class="a-link-normal" href="/dp/B0F1B8Q5GT"><img src="https://m.media-amazon.com/images/I/test.jpg"></a></div><div class="yo-enhanced-title"><a class="a-link-normal" href="/dp/B0F1B8Q5GT">Laptop</a></div><span class="item-view-qty">3</span></div>
    <div class="yo-enhanced-flex-card"><div class="yo-enhanced-flex-image"><a class="a-link-normal" href="/dp/B0F1B8Q5GU"><img src="https://m.media-amazon.com/images/I/other.jpg"></a></div><div class="yo-enhanced-title"><a class="a-link-normal" href="/dp/B0F1B8Q5GU">Tablet</a></div></div>
  </div></div></div></div></body></html>`, listUrl);
assert.deepStrictEqual(Array.from(enhancedList.result.orders[0].shipments, s => [s.asin, s.productTitle, s.quantity]), [['B0F1B8Q5GT', 'Laptop', 3], ['B0F1B8Q5GU', 'Tablet', 1]], 'Image and title links must not double older-order quantities');
assert.deepStrictEqual(Array.from(enhancedList.result.orders[0].shipments, s => s.quantityExplicit), [true, false]);
const partialList = parse('list', '<html><body>160 orders placed in 2026<div class="order-card">Order # 112-8839569-9788250 Cancelled</div><div class="a-pagination">Loading...</div></body></html>', listUrl);
assert.ok(partialList.result.issue, 'Missing pager must trigger fallback rather than truncate a large history');
const addressTemplateList = parse('list', `<html><body>1 order placed<div class="order-card">Order # 114-8512719-3097055 Order placed September 1, 2026 <div class="shipment"><h2>Delivered</h2><div class="item-box"><a href="/dp/B0F1B8Q5GT">Laptop</a><span>$759.99</span></div></div><script type="text/template" id="shipToData-shippingAddress-test"><div class="a-popover-preload"><div class="a-row">Test Recipient</div><div class="a-row">10 Test Street</div><div class="a-row">Nashua, NH 03063</div></div></script></div></body></html>`, listUrl);
assert.strictEqual(addressTemplateList.result.orders[0].zipCode, '03063', 'Retain inert address templates for ZIP filtering');
const scriptCommentDoc = new DOMParser().parseFromString(`<html><body><div class="order-card">Order # 114-3149382-3240200 Order placed August 5, 2026 Approval needed <a href="/dp/B0F1B8Q5GT">Product</a><span>$2.91</span><script>// Cancelled order: check the shipment status text</script></div></body></html>`, 'text/html');
const scriptCommentResult = ctx.ieidExtractOrderList(scriptCommentDoc, new URL(listUrl));
assert.strictEqual(scriptCommentResult.cancelledOrders.length, 0, 'Amazon script comments are not cancellation status');
assert.strictEqual(scriptCommentResult.orders.length, 1, 'Active order remains present despite cancellation words in script comments');
