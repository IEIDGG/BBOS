const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');

const extPath = path.join(__dirname, '..', 'chrome_extension');
assert.ok(fs.existsSync(path.join(extPath, 'manifest.json')));

let playwright;
try {
  process.env.PW_EXPERIMENTAL_SERVICE_WORKER_NETWORK_EVENTS = '1';
  playwright = require('playwright');
} catch (err) {
  console.error('playwright is required for the unpacked extension smoke test');
  process.exit(1);
}

(async () => {
  const userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'ieid-ext-'));
  const context = await playwright.chromium.launchPersistentContext(userDataDir, {
    headless: false,
    ...(process.env.CHROMIUM_PATH ? {executablePath: process.env.CHROMIUM_PATH} : {}),
    args: [
      `--disable-extensions-except=${extPath}`,
      `--load-extension=${extPath}`,
      '--no-sandbox',
      '--disable-dev-shm-usage',
      '--host-resolver-rules=MAP ieidgg.com ~NOTFOUND, MAP *.amazon.com ~NOTFOUND',
    ],
  });
  try {
    const uploads = [];
    await context.route('https://ieidgg.com/**', async route => {
      const pathname = new URL(route.request().url()).pathname;
      if (pathname === '/api/orders/amazon/scrape') uploads.push(route.request().postDataJSON().orders);
      await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({inserted:1,updated:0,failed:0})});
    });
    await context.addCookies([{name:'access_token',value:'synthetic-access',url:'https://ieidgg.com',secure:true}]);
    let worker = context.serviceWorkers()[0];
    if (!worker) {
      worker = await context.waitForEvent('serviceworker', { timeout: 20000 });
    }
    assert.ok(worker.url().startsWith('chrome-extension://'), `unexpected worker url: ${worker.url()}`);
    const version = await worker.evaluate(async () => chrome.runtime.getManifest().version);
    const installed = JSON.parse(fs.readFileSync(path.join(extPath, 'manifest.json'), 'utf8')).version;
    assert.strictEqual(version, installed);
    const quantityHtml = fs.readFileSync(path.join(__dirname, 'fixtures/amazon/unshipped-grid-detail.html'), 'utf8');
    await context.route('https://www.amazon.com/**', route => route.fulfill({status:200,contentType:'text/html',body:quantityHtml}));
    const page = await context.newPage();
    await page.goto('https://www.amazon.com/your-orders/order-details?orderID=112-9246572-5333850');
    const tabId = await worker.evaluate(async () => (await chrome.tabs.query({url:'https://www.amazon.com/*'}))[0].id);
    async function extractAndUpload() {
      const orders = await worker.evaluate(async id => (await chrome.scripting.executeScript({target:{tabId:id},files:['scrape_core.js','order_detail_scraper.js']})).at(-1).result.orders, tabId);
      await worker.evaluate(async parsed => {
        scrapeState.stopped = false;
        parsed.forEach(order => dedupeOrderShipments(order));
        await uploadOrdersToApi(parsed, 'synthetic@example.test');
      }, orders);
      return orders;
    }
    const parsed = await extractAndUpload();
    assert.deepStrictEqual(parsed[0].shipments.map(s => [s.asin,s.quantity,s.unitPrice]), [['B000000001',3,'$1,099.00']]);
    await extractAndUpload();
    assert.strictEqual(uploads.length, 2);
    assert.ok(uploads.every(upload => upload.every(row => row.shipment_status === 'Not yet shipped')), 'Untracked arrival estimates must not be uploaded as Shipped');
    for (const upload of uploads) assert.deepStrictEqual(upload.map(r => [r.asin,r.quantity,r.unit_price,r.total_owed]), [['B000000001','3','1099.00','3297.00']], 'First import and retry must preserve Amazon quantity and cost');
    await page.evaluate(() => {
      document.querySelector('.od-item-view-qty span').textContent = '1';
      const purchased = document.querySelector('[data-component="purchasedItems"]');
      purchased.after(purchased.cloneNode(true));
    });
    await extractAndUpload();
    assert.deepStrictEqual(uploads.at(-1).map(r => [r.quantity,r.total_owed]), [['2','2198.00']], 'Separate rows without line IDs must survive background deduplication and cost aggregation');
    console.log('Chromium legacy extraction and repeat upload preserve purchased quantity and cost');
    console.log(`extension smoke passed (service worker v${version})`);
  } finally {
    await context.close();
    fs.rmSync(userDataDir, { recursive: true, force: true });
  }
})().catch((err) => {
  console.error(err);
  process.exit(1);
});
