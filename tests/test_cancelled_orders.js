const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const core = require('../chrome_extension/scrape_core.js');
const source = fs.readFileSync(path.join(__dirname, '..', 'chrome_extension', 'background.js'), 'utf8');
const missingZip = { orderId: '111-1111111-1111111', cancelled: true };
const otherZip = { orderId: '111-2222222-2222222', cancelled: true, zipCode: '11779' };
const absent = { orderId: '111-3333333-3333333', cancelled: true };

function harness({ lookupFails = false, updateFails = false } = {}) {
  const writes = [];
  const logs = [];
  const context = vm.createContext({
    ...core, encodeURIComponent,
    scrapeState: { stopped: false, sent: 0, failed: 0, cancelled: 0 },
    log(message) { logs.push(message); }, stats() {},
    async apiGet(endpoint) {
      assert.strictEqual(endpoint, '/api/orders/amazon?refresh=true');
      if (lookupFails) throw new Error('lookup unavailable');
      return { orders: [
        { id: 'row-a', order_id: missingZip.orderId, order_status: 'Open' },
        { id: 'row-b', order_id: missingZip.orderId, order_status: 'Open' },
        { id: 'row-c', order_id: otherZip.orderId, order_status: 'Open' },
        { id: 'unrelated', order_id: '111-4444444-4444444', order_status: 'Open' },
      ] };
    },
    async authorizedFetch(endpoint, options) {
      writes.push({ endpoint, method: options.method, body: JSON.parse(options.body) });
      if (updateFails && endpoint.endsWith('row-a')) throw new Error('update unavailable');
      return { success: true };
    },
    async apiPost() { throw new Error('Cancellation sync must never call the insert-capable endpoint'); },
  });
  vm.runInContext(source.slice(source.indexOf('function normalizeZipCode('),
    source.indexOf('async function detectAmazonAccountEmail(')), context);
  vm.runInContext(source.slice(source.indexOf('function filterOrdersByZip('),
    source.indexOf('function buildOrderDetailUrl(')), context);
  return { context, writes, logs };
}

(async () => {
  const { context, writes } = harness();
  const accumulated = [];
  context.mergeCancelledOrders(accumulated, [missingZip, otherZip, absent]);
  context.mergeCancelledOrders(accumulated, [missingZip]);
  const reported = context.reportCancelledOrders(accumulated, ['03063']);
  assert.deepStrictEqual(Array.from(reported, order => order.orderId),
    [missingZip.orderId, otherZip.orderId, absent.orderId], 'Cancellations must ignore ZIP filters');
  assert.strictEqual(context.scrapeState.cancelled, 3);
  assert.strictEqual(context.filterOrdersByZip([missingZip, otherZip], ['03063']).keptOrders.length, 0);
  await context.uploadCancelledOrdersToApi(reported, 'test@example.com');
  assert.deepStrictEqual(writes, ['row-a', 'row-b', 'row-c'].map(id => ({
    endpoint: `/api/orders/amazon/${id}`, method: 'PUT',
    body: { order_status: 'Cancelled', shipment_status: 'Cancelled' },
  })));
  assert.strictEqual(context.scrapeState.sent, 3);
  assert.strictEqual(context.scrapeState.failed, 0);

  const failedLookup = harness({ lookupFails: true });
  await failedLookup.context.uploadCancelledOrdersToApi([missingZip]);
  assert.strictEqual(failedLookup.writes.length, 0);
  assert.strictEqual(failedLookup.context.scrapeState.failed, 1);

  const failedUpdate = harness({ updateFails: true });
  await failedUpdate.context.uploadCancelledOrdersToApi([missingZip]);
  assert.strictEqual(failedUpdate.writes.length, 2, 'Continue with remaining matching rows after one failure');
  assert.strictEqual(failedUpdate.context.scrapeState.failed, 1);
  assert.strictEqual(failedUpdate.context.scrapeState.sent, 1);

  const stopped = harness();
  stopped.context.scrapeState.stopped = true;
  await stopped.context.uploadCancelledOrdersToApi([missingZip]);
  assert.strictEqual(stopped.writes.length, 0);
  console.log('cancelled order selection and update-only sync tests passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
