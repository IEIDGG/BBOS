const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const path = require('path');
const file = path.join(__dirname, '../chrome_extension/amazon_requests.js');
assert.ok(fs.existsSync(file), 'Request-first transport must exist');
const source = fs.readFileSync(file, 'utf8');
const url = 'https://www.amazon.com/your-orders/order-details?orderID=111-1111111-1111111';
function fixture(mode) {
  const calls = { fetch: 0, created: 0, tabs: 0, closed: 0 };
  const ctx = vm.createContext({ URL, AbortController, setTimeout, clearTimeout,
    scrapeState: { stopped: false }, activeTrackingTabIds: [], log() {},
    chrome: { runtime: { getURL: p => 'chrome-extension://test/' + p,
      async getContexts() { return []; },
      async sendMessage(message) { assert.strictEqual(message.target, 'ieid-html-parser'); return { result: ['incomplete', 'tab-error'].includes(mode) ? { incomplete: true } : mode === 'verification' ? { issue: 'Amazon verification page' } : { valid: true } }; },
    }, offscreen: { async createDocument() { calls.created++; } } },
    async fetch(request, options) { calls.fetch++; assert.strictEqual(options.credentials, 'include');
      if (mode === 'network') throw new Error('network');
      return { ok: true, url: mode === 'signin' ? 'https://www.amazon.com/ap/signin' : mode === 'wrong-order' ? 'https://www.amazon.com/progress-tracker/package?orderId=other' : mode === 'missing-shipment' ? request.replace('&shipmentId=first', '') : request, headers: { get: () => 'text/html' }, async text() { return '<html>order</html>'; } };
    },
    async openTab() { calls.tabs++; return 10; }, async closeTab() { calls.closed++; }, async waitForTabReady() {},
    async injectAndRun() { if (mode === 'tab-error') throw new Error('tab extraction failed'); return { valid: true, tab: true }; },
  });
  vm.runInContext(source, ctx);
  return { ctx, calls };
}
(async () => {
  for (const mode of ['success', 'network', 'incomplete', 'verification', 'signin']) {
    const { ctx, calls } = fixture(mode);
    const result = await ctx.readAmazonPage(url, 'detail', value => value?.valid);
    assert.strictEqual(result.valid, true);
    assert.strictEqual(calls.tabs, mode === 'success' ? 0 : 1);
    assert.strictEqual(calls.closed, calls.tabs);
  }
  const referral = fixture('success');
  await referral.ctx.readAmazonPage('https://www.amazon.com/gp/your-account/ship-track/ref=ppx_yo_dt_b_track_package?orderId=111&shipmentId=first', 'tracking', value => value?.valid);
  assert.strictEqual(referral.calls.tabs, 0, 'Legitimate referral paths use the request transport');
  for (const mode of ['wrong-order', 'missing-shipment']) {
    const redirected = fixture(mode);
    await assert.rejects(() => redirected.ctx.requestAmazonPage('https://www.amazon.com/gp/your-account/ship-track?orderID=111&shipmentId=first', 'tracking'));
  }
  const broken = fixture('tab-error');
  await assert.rejects(() => broken.ctx.readAmazonPage(url, 'detail', value => value?.valid));
  assert.strictEqual(broken.calls.closed, 1, 'Close fallback tabs even when extraction fails');
  const { ctx, calls } = fixture('success');
  await Promise.all([1, 2, 3, 4].map(() => ctx.readAmazonPage(url, 'detail', value => value?.valid)));
  assert.strictEqual(calls.created, 1, 'Concurrent requests share one parser');
  await assert.rejects(() => ctx.readAmazonPage('https://evilamazon.com/your-orders/order-details', 'detail', () => true));
  assert.strictEqual(calls.fetch, 4, 'Reject unapproved URL before any request');
  ctx.scrapeState.stopped = true;
  await assert.rejects(() => ctx.readAmazonPage(url, 'detail', () => true));
  assert.strictEqual(calls.tabs, 0);
  console.log('request-first transport tests passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
