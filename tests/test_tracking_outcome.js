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
}
for (const response of [{ cancelled: 'order cancelled' }, { noTracking: 'no tracking available yet' }, { trackingId: 'TBA123456789012', carrier: 'Amazon' }]) {
  const ctx = vm.createContext({ scrapeState: { tracked: 0 }, log() {} });
  vm.runInContext(code, ctx);
  const shipment = {};
  ctx.applyTrackingResult({ orderId: 'recent' }, shipment, 0, response, null);
  assert.ok(!ctx.scrapeState.extractionIncomplete);
  if (response.trackingId) assert.strictEqual(shipment.trackingNumber, response.trackingId);
}
console.log('tracking failure completeness and saved tracking preservation tests passed');
