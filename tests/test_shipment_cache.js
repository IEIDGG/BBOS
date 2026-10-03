const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync(require.resolve('../chrome_extension/shipment_cache.js'), 'utf8');
const storage = {};
const ctx = vm.createContext({ Date, Map, log() {}, scrapeState: { stopped: false },
  buildTrackingUrl: (order, shipment) => shipment.shipmentId ? 'https://www.amazon.com/track' : '',
  parseMoneyAmount: value => value ? parseFloat(String(value).replace('$', '')) : null,
  validateDetailedOrder: result => result.orders[0],
  chrome: { storage: { local: { async get(key) { return { [key]: storage[key] }; }, async set(value) { Object.assign(storage, value); } } } },
});
vm.runInContext(source, ctx);
(async () => {
  const list = () => ({ orderId: 'old', shipments: [{ asin: 'A', quantity: 2, status: 'Delivered' }] });
  const order = list();
  await ctx.restoreShipmentDiscovery([order], 'account-a@example.com');
  order.detailsScanned = true;
  order.shipments = [1, 2].map(i => ({ asin: 'A', quantity: 1, status: 'Delivered', shipmentId: 'shipment' + i, trackingNumber: 'tracking' + i }));
  await ctx.saveShipmentDiscovery([order], 'account-a@example.com');
  const restored = list();
  await ctx.restoreShipmentDiscovery([restored], 'account-a@example.com');
  assert.strictEqual(restored.shipments.length, 2);
  assert.ok(restored.shipments.every(s => !s.trackingNumber && !s.skipTrackingFetch));
  const disabled = list();
  await ctx.restoreShipmentDiscovery([disabled], 'account-a@example.com', false);
  assert.strictEqual(disabled.detailsScanned, undefined, 'Disabled reuse must fetch fresh shipment links');
  assert.ok(disabled.discoverySignature, 'Fresh discoveries retain the original list signature');
  const other = list();
  await ctx.restoreShipmentDiscovery([other], 'account-b@example.com');
  assert.strictEqual(other.detailsScanned, undefined, 'Never reuse another account’s links');
  const changed = list(); changed.shipments[0].quantity = 3;
  await ctx.restoreShipmentDiscovery([changed], 'account-a@example.com');
  assert.strictEqual(changed.detailsScanned, undefined);
  const manual = list(); manual.detailsScanned = true;
  await ctx.restoreShipmentDiscovery([manual], 'account-a@example.com');
  assert.strictEqual(manual.shipments.length, 1, 'Fresh single-order details take priority');
  storage[ctx.shipmentDiscoveryCacheKey('account-a@example.com')].old.expiresAt = 0;
  const expired = list(); await ctx.restoreShipmentDiscovery([expired], 'account-a@example.com');
  assert.strictEqual(expired.detailsScanned, undefined);
  console.log('account-scoped shipment discovery cache tests passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
