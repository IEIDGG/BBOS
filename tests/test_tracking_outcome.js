const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync(require.resolve('../chrome_extension/background.js'), 'utf8');
const code = source.slice(source.indexOf('function applyTrackingResult('), source.indexOf('async function fetchTrackingBatch('));
for (const [response, error] of [
  [{ unavailable: 'Amazon tracking information unavailable', carrier: 'Amazon' }, null],
  [{ timedOut: true }, null],
  [{ issue: 'Amazon verification page' }, null],
  [null, 'network'], [null, 'no ship-track URL'], [null, null],
]) {
  const ctx = vm.createContext({ scrapeState: { tracked: 0, extractionIncomplete: false }, log() {} });
  vm.runInContext(code, ctx);
  const shipment = { trackingNumber: '1Z999AA10123456784', carrier: 'UPS' };
  ctx.applyTrackingResult({ orderId: 'old' }, shipment, 0, response, error);
  assert.strictEqual(shipment.trackingNumber, '1Z999AA10123456784', 'Failed refresh must preserve existing tracking');
  assert.strictEqual(shipment.carrier, 'UPS');
  assert.strictEqual(ctx.scrapeState.extractionIncomplete, true, 'Missing tracking must not count as a complete scan');
  assert.strictEqual(shipment.trackingLookupIncomplete, true,
    'An unsuccessful refresh must mark its manifest incomplete even with saved tracking');
}
for (const response of [{ cancelled: 'order cancelled' }, { noTracking: 'no tracking available yet' }, { trackingId: 'TBA123456789012', carrier: 'Amazon' }]) {
  const ctx = vm.createContext({ scrapeState: { tracked: 0 }, log() {} });
  vm.runInContext(code, ctx);
  const shipment = { trackingLookupIncomplete: true };
  ctx.applyTrackingResult({ orderId: 'recent' }, shipment, 0, response, null);
  assert.ok(!ctx.scrapeState.extractionIncomplete);
  assert.strictEqual(shipment.trackingLookupIncomplete, false, 'A definitive retry clears the previous lookup failure');
  if (response.trackingId) assert.strictEqual(shipment.trackingNumber, response.trackingId);
}
console.log('tracking failure completeness and saved tracking preservation tests passed');

// A batch-level timeout may finish before readAmazonPage settles. The upload
// checkpoint must already know that the old tracking has not been refreshed.
(async () => {
  let finish;
  const ctx = vm.createContext({ scrapeState: { tracked: 0 }, log() {},
    readAmazonPage: () => new Promise(resolve => { finish = resolve; }),
  });
  vm.runInContext(source.slice(source.indexOf('function applyTrackingResult('), source.indexOf('function validateDetailedOrder(')), ctx);
  const shipment = { trackingNumber: 'KNOWN' };
  const pending = ctx.fetchTrackingBatch([{ trackUrl: 'https://www.amazon.com/progress-tracker/package',
    targets: [{ order: { orderId: 'pending' }, shipment, shipmentIndex: 0 }] }]);
  assert.strictEqual(shipment.trackingLookupIncomplete, true, 'An in-flight lookup cannot claim a complete refreshed manifest');
  finish({ trackingId: 'KNOWN' });
  await pending;
  assert.strictEqual(shipment.trackingLookupIncomplete, false);
  console.log('in-flight tracking manifest completeness tests passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
