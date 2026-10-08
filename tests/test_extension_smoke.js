const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');

const extPath = path.join(__dirname, '..', 'chrome_extension');
assert.ok(fs.existsSync(path.join(extPath, 'manifest.json')));

let playwright;
try {
  // Playwright 1.55 requires this flag to route service-worker API requests.
  process.env.PW_EXPERIMENTAL_SERVICE_WORKER_NETWORK_EVENTS = '1';
  playwright = require('playwright');
} catch (err) {
  console.error('playwright is required for the unpacked extension smoke test');
  process.exit(1);
}

(async () => {
  const userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'ieid-ext-'));
  const options = {
    headless: false,
    ...(process.env.CHROMIUM_PATH ? {executablePath: process.env.CHROMIUM_PATH} : {}),
    args: [
      `--disable-extensions-except=${extPath}`,
      `--load-extension=${extPath}`,
      '--no-sandbox',
      '--disable-dev-shm-usage',
      '--host-resolver-rules=MAP ieidgg.com ~NOTFOUND, MAP *.amazon.com ~NOTFOUND',
    ],
  };
  let context;
  let extensionHome;
  const quantityUploads = [];
  const installed = JSON.parse(fs.readFileSync(path.join(extPath, 'manifest.json'), 'utf8')).version;
  async function launch() {
    const browser = await playwright.chromium.launchPersistentContext(userDataDir, options);
    // This is an isolated browser with synthetic responses, never a live account.
    await browser.route('https://ieidgg.com/**', async route => {
      const pathname = new URL(route.request().url()).pathname;
      if (pathname === '/api/orders/amazon/scrape') quantityUploads.push(route.request().postDataJSON().orders);
      const json = pathname === '/api/order-scraper/version' ? {version:installed}
        : pathname === '/api/user' ? {uid:'test-user',email:'synthetic@example.com'}
        : pathname === '/api/orders/amazon/scrape' ? {inserted:1,updated:0,failed:0}
        : {success:true};
      await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(json)});
    });
    return browser;
  }
  async function getWorker() {
    let worker = context.serviceWorkers()[0];
    if (!worker) {
      const ready = context.waitForEvent('serviceworker', {timeout:20000});
      ready.catch(() => {});
      if (extensionHome) {
        const wake = await context.newPage();
        await wake.goto(extensionHome+'popup.html');
      }
      worker = await ready;
    }
    // The CDP worker target can appear before its importScripts finishes.
    const deadline = Date.now()+10000;
    while (!await worker.evaluate(() => typeof globalThis.IEIDAuth !== 'undefined')) {
      if (Date.now() >= deadline) throw new Error('Extension auth client did not initialize');
      await new Promise(resolve=>setTimeout(resolve,25));
    }
    return worker;
  }
  try {
    context = await launch();
    let worker = await getWorker();
    assert.ok(worker.url().startsWith('chrome-extension://'), `unexpected worker url: ${worker.url()}`);
    extensionHome = new URL('.', worker.url()).href;
    const version = await worker.evaluate(async () => chrome.runtime.getManifest().version);
    assert.strictEqual(version, installed);
    await worker.evaluate(async () => {
      await chrome.storage.session.set({accountGrant:{access_token:'synthetic-access',refresh_token:'synthetic-refresh',expires_at:new Date(Date.now()+86400000).toISOString()}});
    });
    assert.strictEqual(await worker.evaluate(() => IEIDAuth.getToken()), 'synthetic-access');
    const page = await context.newPage();
    await context.route('https://www.amazon.com/**', route => route.fulfill({status:200,contentType:'text/html',body:'<html><body>Order 114-1234567-1234567</body></html>'}));
    await page.goto('https://www.amazon.com/your-orders/order-details?orderID=114-1234567-1234567');
    await page.waitForSelector('#ieid-scan-order-btn');
    const tabId = await worker.evaluate(async () => (await chrome.tabs.query({url:'https://www.amazon.com/*'}))[0].id);
    const contentAccess = await worker.evaluate(async id => (await chrome.scripting.executeScript({target:{tabId:id},func:async () => {
      try {await chrome.storage.local.get('accountGrant'); return 'allowed';} catch {return 'denied';}
    }}))[0].result, tabId);
    assert.strictEqual(contentAccess, 'denied', 'content scripts must not read durable grants');
    await page.click('#ieid-scan-order-btn');
    await page.waitForFunction(() => document.querySelector('#ieid-scan-order-btn').textContent === 'Scan with IEID');
    assert.strictEqual(await worker.evaluate(async () => (await chrome.storage.local.get('pendingSingleOrderId')).pendingSingleOrderId), '114-1234567-1234567');
    console.log('Chromium content-script isolation and order button passed');
    const quantityHtml = fs.readFileSync(path.join(__dirname, 'fixtures/amazon/unshipped-grid-detail.html'), 'utf8');
    await page.route('https://www.amazon.com/your-orders/order-details?orderID=112-9246572-5333850', route => route.fulfill({status:200,contentType:'text/html',body:quantityHtml}));
    await page.goto('https://www.amazon.com/your-orders/order-details?orderID=112-9246572-5333850');
    const quantityTabId = await worker.evaluate(async () => (await chrome.tabs.query({url:'https://www.amazon.com/*'}))[0].id);
    const parsedQuantity = await worker.evaluate(async id => (await chrome.scripting.executeScript({target:{tabId:id},files:['scrape_core.js','order_detail_scraper.js']})).at(-1).result, quantityTabId);
    assert.deepStrictEqual(parsedQuantity.orders[0].shipments.map(s => [s.asin,s.quantity,s.unitPrice]), [['B000000001',3,'$1,099.00']], 'Native Chromium must read image and title links as one purchased row');
    await worker.evaluate(async orders => {
      scrapeState.stopped = false;
      await uploadOrdersToApi(orders, 'synthetic@example.test');
      await uploadOrdersToApi(orders, 'synthetic@example.test');
    }, parsedQuantity.orders);
    assert.strictEqual(quantityUploads.length, 2);
    assert.ok(quantityUploads.every(upload => upload.every(row => row.shipment_status === 'Not yet shipped')), 'Untracked arrival estimates must not upload as Shipped');
    for (const upload of quantityUploads) assert.deepStrictEqual(upload.map(r => [r.asin,r.quantity,r.unit_price,r.total_owed]), [['B000000001','3','1099.00','3297.00']], 'First import and retry must upload the original quantity and cost');
    const splitQuantity = await page.evaluate(() => {
      document.querySelector('.od-item-view-qty span').textContent = '1';
      const purchased = document.querySelector('[data-component="purchasedItems"]');
      purchased.after(purchased.cloneNode(true));
      return window.location.href;
    });
    assert.ok(splitQuantity.includes('orderID=112-9246572-5333850'));
    const splitOrders = await worker.evaluate(async id => (await chrome.scripting.executeScript({target:{tabId:id},files:['scrape_core.js','order_detail_scraper.js']})).at(-1).result.orders, quantityTabId);
    await worker.evaluate(async orders => {
      orders.forEach(order => dedupeOrderShipments(order));
      await uploadOrdersToApi(orders, 'synthetic@example.test');
    }, splitOrders);
    assert.deepStrictEqual(quantityUploads.at(-1).map(r => [r.quantity,r.total_owed]), [['2','2198.00']], 'Separate rows without line IDs must preserve both quantity and cost through background deduplication');
    console.log('Chromium purchased-item extraction and repeat upload preserve quantity and cost');
    // Chrome clears session storage on reload/update. Command-line-loaded
    // extensions cannot reliably reload themselves in the Chromium harness.
    await worker.evaluate(() => chrome.storage.session.clear());
    assert.strictEqual(await worker.evaluate(() => IEIDAuth.getToken()), 'synthetic-access', 'session-storage reset must retain the grant');
    console.log('Chromium session-storage reset retained authentication');
    // Close extension popup windows before shutting down the persistent profile.
    await Promise.all(context.pages().map(open => open.close()));
    console.log('Restarting isolated Chromium profile');
    await context.close();
    console.log('Isolated Chromium profile closed');
    context = await launch();
    console.log('Isolated Chromium profile restarted');
    worker = await getWorker();
    assert.strictEqual(await worker.evaluate(() => IEIDAuth.getToken()), 'synthetic-access', 'browser restart must retain the grant');
    await worker.evaluate(() => IEIDAuth.disconnect());
    assert.strictEqual(await worker.evaluate(async () => (await chrome.storage.local.get('accountGrant')).accountGrant), undefined);
    console.log(`extension smoke passed (service worker v${version})`);
    console.log('Chromium auth persistence, content-script isolation, order button and disconnect passed');
  } finally {
    if (context) {
      await Promise.all(context.pages().map(open => open.close()));
      await context.close();
    }
    fs.rmSync(userDataDir, { recursive: true, force: true });
  }
})().catch((err) => {
  console.error(err);
  process.exit(1);
});
