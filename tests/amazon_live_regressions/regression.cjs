const fs = require('node:fs');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const {chromium} = require('playwright');
const path = require('node:path');
const dir = process.env.SCRAPER_DIR || path.resolve(__dirname, '../../chrome_extension');
const orderId = '111-1111111-1111111';
const title = 'Meta Quest 3S 128GB | Virtual Reality — VR Headset — Gorilla Tag Bundle';
function row(qty, asin = 'B0F2GYMC8H', name = title) {
  return `<div class="a-fixed-left-grid"><div class="a-row"><a href="https://www.amazon.com/dp/${asin}" ><img alt="${name}" src="https://m.media-amazon.com/images/I/test.jpg"></a><span class="item-view-qty">${qty}</span></div><div class="a-row"><a href="https://www.amazon.com/dp/${asin}">${name}</a><span>Quantity: ${qty}</span><div data-component="unitPrice"><span class="a-offscreen">$297.00</span></div></div></div>`;
}
function shipment(items, id = '') {
 return `<div class="shipment-item"><h2>Arriving Wednesday</h2>${id ? `<a href="https://www.amazon.com/progress-tracker/package?orderId=${orderId}&shipmentId=${id}&itemId=item">Track package</a>` : ''}<div data-component="purchasedItems"><div class="a-row">${items}</div></div></div>`;
}
function html(content) { return `<html><body><div id="orderDetails">Order # ${orderId}${content}</div></body></html>`; }
const failures = [];
async function check(name, fn) { try { await fn(); console.log(`PASS ${name}`); } catch(e) { failures.push(name); console.log(`FAIL ${name}: ${e.message}`); } }
(async () => {
const browser = await chromium.launch({headless:true, ...(process.env.CHROMIUM_EXECUTABLE ? {executablePath:process.env.CHROMIUM_EXECUTABLE} : {})});
try {
const page = await browser.newPage();
await page.route('**/*', route => route.abort());
await page.addScriptTag({content:'globalThis.IEID_PARSE_ONLY = true;'});
await page.addScriptTag({content:fs.readFileSync(`${dir}/scrape_core.js`,'utf8')});
await page.addScriptTag({content:fs.readFileSync(`${dir}/order_detail_scraper.js`,'utf8')});
async function parse(markup) { return page.evaluate(({markup, orderId}) => globalThis.ieidExtractOrderDetail(new DOMParser().parseFromString(markup,'text/html'), new URL(`https://www.amazon.com/your-orders/order-details?orderID=${orderId}`)), {markup, orderId}); }
await check('captured Amazon Quest order has one item, quantity 2 and tracking link', async () => {
 const result = await parse(fs.readFileSync(path.join(__dirname,'quest-order.html'),'utf8'));
 const items = result.orders[0].shipments;
 console.log('Captured item summary:', JSON.stringify(items.map(s=>({asin:s.asin,quantity:s.quantity,status:s.status,price:s.unitPrice,hasTracking:!!s.trackingUrl}))));
 assert.equal(items.length,1); assert.equal(items[0].quantity,2);
 assert.equal(items[0].unitPrice,'$297.00');
 assert.ok(items[0].trackingUrl.includes('/progress-tracker/package'));
 assert.equal(items[0].status,'Now arriving October 14 - October 16');
});
await check('image and title links produce one item with quantity 2', async () => {
 const result = await parse(html(shipment(row(2))));
 assert.equal(result.orders[0].shipments.length,1);
 assert.equal(result.orders[0].shipments[0].quantity,2);
 assert.equal(result.orders[0].shipments[0].productTitle,title);
 assert.equal(result.orders[0].shipments[0].unitPrice,'$297.00');
});
await check('delivery-level tracking and status survive item row extraction', async () => {
 const result = await parse(html(shipment(row(2),'ship1')));
 assert.equal(result.orders[0].shipments.length,1);
 assert.equal(result.orders[0].shipments[0].shipmentId,'ship1');
 assert.equal(result.orders[0].shipments[0].status,'Arriving Wednesday');
 assert.ok(result.orders[0].shipments[0].trackingUrl.includes('shipmentId=ship1'));
});
await check('same ASIN in two physical deliveries remains two quantities', async () => {
 const result = await parse(html(shipment(row(1),'ship1') + shipment(row(1),'ship2')));
 assert.equal(result.orders[0].shipments.length,2);
 assert.deepEqual(result.orders[0].shipments.map(s=>s.quantity),[1,1]);
 assert.deepEqual(result.orders[0].shipments.map(s=>s.shipmentId),['ship1','ship2']);
});
await check('sibling generic deliveries retain their own status and tracking', async () => {
 const generic = (id,status) => `<div><div data-component="shipmentStatus"><h4>${status}</h4></div><div data-component="purchasedItems">${row(1)}</div><a href="https://www.amazon.com/progress-tracker/package?orderId=${orderId}&shipmentId=${id}">Track package</a></div>`;
 const result = await parse(html(`<div class="a-box-inner">${generic('first','Delivered today')}${generic('second','Arriving Wednesday')}</div>`));
 assert.deepEqual(result.orders[0].shipments.map(s=>[s.quantity,s.shipmentId,s.status]),[[1,'first','Delivered today'],[1,'second','Arriving Wednesday']]);
});
await check('two products in one purchased block retain separate prices and quantities', async () => {
 const result = await parse(html(shipment(row(2)+row(3,'B0DZ77D5HL','Apple iPad'),'ship1')));
 assert.equal(result.orders[0].shipments.length,2);
 assert.deepEqual(result.orders[0].shipments.map(s=>s.quantity),[2,3]);
});
await check('nested fallback shipment wrappers do not duplicate an item', async () => {
 const result = await parse(html(`<div class="shipment"><div class="shipment-item">${row(3)}</div></div>`));
 assert.equal(result.orders[0].shipments.length,1);
 assert.equal(result.orders[0].shipments[0].quantity,3);
});
await check('detail validation rejects doubled quantities before upload', async () => {
 const code = fs.readFileSync(`${dir}/background.js`,'utf8');
 const start=code.indexOf('function validateDetailedOrder('), end=code.indexOf('\nasync function readOrderDetail',start);
 const ctx=vm.createContext({}); vm.runInContext(code.slice(start,end),ctx);
 assert.throws(()=>ctx.validateDetailedOrder({orders:[{orderId,shipments:[{asin:'B0F2GYMC8H',quantity:4}]}]}, {orderId,shipments:[{asin:'B0F2GYMC8H',quantity:2}]}));
});
await check('complete unshipped HTML with known prices avoids tab fallback', async () => {
 const core = fs.readFileSync(`${dir}/scrape_core.js`,'utf8');
 const code = fs.readFileSync(`${dir}/background.js`,'utf8');
 const start=code.indexOf('function validateDetailedOrder('), end=code.indexOf('\nasync function discoverMissingTracking',start);
 const ctx=vm.createContext({scrapeState:{}, log:()=>{}, buildTrackingUrl:()=>'', buildOrderDetailUrl:()=>'https://www.amazon.com/your-orders/order-details', readAmazonPage:async (url,kind,accept)=>{
 const result={orders:[{orderId,shipments:[{asin:'B0F2GYMC8H',quantity:2,unitPrice:'$297.00',status:'Arriving Wednesday'}]}]};
 assert.equal(accept(result),true); return result;
 }});
 vm.runInContext(core,ctx);
 const moneyStart=code.indexOf('function parseMoneyAmount('), moneyEnd=code.indexOf('\nfunction formatMoneyAmount',moneyStart);
 const mergeStart=code.indexOf('function mergeShipment('), mergeEnd=code.indexOf('\nfunction ',mergeStart+1);
 vm.runInContext(code.slice(moneyStart,moneyEnd),ctx); vm.runInContext(code.slice(mergeStart,mergeEnd),ctx);
 vm.runInContext(code.slice(start,end),ctx);
 await ctx.readOrderDetail({orderId,shipments:[{asin:'B0F2GYMC8H',quantity:2}]});
});
await page.addScriptTag({content:fs.readFileSync(`${dir}/tracking_scraper.js`,'utf8')});
async function track(markup) { return page.evaluate(markup => ieidExtractTracking(new DOMParser().parseFromString(markup,'text/html'),false), markup); }
await check('unshipped HTML ignores navigation sign-in and script text', async () => {
 const result=await track(fs.readFileSync(path.join(__dirname,'tracking-ordered.html'),'utf8'));
 assert.equal(result.issue,''); assert.equal(result.noTracking,'no tracking available yet');
});
await check('actual sign-in form is still detected', async () => {
 const result=await track('<h1>Sign in</h1><form action="/ap/signin"><input id="ap_email" name="email"></form>');
 assert.equal(result.issue,'Amazon sign-in required');
});
await check('real enhanced list card retains all three product quantities', async () => {
 await page.addScriptTag({content:fs.readFileSync(`${dir}/scraper.js`,'utf8')});
 const result=await page.evaluate(markup=>ieidExtractOrderList(new DOMParser().parseFromString(markup,'text/html'),new URL('https://www.amazon.com/your-orders/orders')),fs.readFileSync(path.join(__dirname,'ipad-list.html'),'utf8'));
 assert.deepEqual(result.orders[0].shipments.map(s=>s.quantity),[3,3,3]);
 assert.ok(result.orders[0].shipments.every(s=>s.quantityExplicit));
});
await check('captured multi-product details retain quantities and pass validation', async () => {
 const result=await page.evaluate(markup=>ieidExtractOrderDetail(new DOMParser().parseFromString(markup,'text/html'),new URL('https://www.amazon.com/your-orders/order-details?orderID=222-2222222-2222222')),fs.readFileSync(path.join(__dirname,'ipad-details.html'),'utf8'));
 assert.deepEqual(result.orders[0].shipments.map(s=>s.quantity),[3,3,3]);
});
await check('unshipped background result avoids unnecessary tab fallback', async () => {
 const code=fs.readFileSync(`${dir}/background.js`,'utf8');
 const start=code.indexOf('async function fetchTrackingBatch('),end=code.indexOf('\nfunction validateDetailedOrder',start);
 const ctx=vm.createContext({readAmazonPage:async (url,kind,accept)=>{const result={noTracking:'no tracking available yet'};assert.equal(accept(result),true);return result;},applyTrackingResult:(order,shipment,index,result,error)=>{assert.equal(error,null);return {timedOut:false};}});
 vm.runInContext(code.slice(start,end),ctx);await ctx.fetchTrackingBatch([{trackUrl:'test',targets:[{}]}]);
});
await check('mixed tracked and untracked splits update the aggregate status', async () => {
 const code=fs.readFileSync(`${dir}/background.js`,'utf8');
 const ctx=vm.createContext({scrapeState:{},log:()=>{},normalizeTrackingList:value=>value?[value]:[],compactScrapeRow:row=>row});
 vm.runInContext(code.slice(code.indexOf('function parseMoneyAmount('),code.indexOf('async function uploadOrdersToApi(')),ctx);
 const base={order_id:orderId,asin:'B0F2GYMC8H',quantity:'1',total_owed:'297.00',unit_price:'297.00'};
 const merged=ctx.aggregateProductPayload([{...base,shipment_status:'Shipped',tracking_number:'TBA123456789012'},{...base,shipment_status:'Not yet shipped',tracking_number:''}])[0];
 assert.equal(merged.shipment_status,'Shipped');assert.equal(merged.tracking_number,undefined);assert.equal(merged.quantity,'2');
});
await check('shipment status requires a tracking number', async () => {
 const code=fs.readFileSync(`${dir}/background.js`,'utf8');
 const start=code.indexOf('function normalizeShipmentStatus('),end=code.indexOf('\nchrome.alarms',start);
 const ctx=vm.createContext({}); vm.runInContext(code.slice(start,end),ctx);
 for (const raw of ['Arriving Wednesday','Expected tomorrow','Shipped','Ordered','Not yet shipped']) {
  assert.equal(ctx.normalizeShipmentStatus(raw,''),'Not yet shipped');
  assert.equal(ctx.normalizeShipmentStatus(raw,'TBA335220329763'),'Shipped');
 }
 assert.equal(ctx.normalizeShipmentStatus('Shipped','   '),'Not yet shipped');
 assert.equal(ctx.normalizeShipmentStatus('Delivered September 29','TBA335220329763'),'Delivered');
 assert.equal(ctx.normalizeShipmentStatus('Cancelled','TBA335220329763'),'Cancelled');
});
} finally { await browser.close(); }
if(failures.length) process.exitCode=1;
})();
