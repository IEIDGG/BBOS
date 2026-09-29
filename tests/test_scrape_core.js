const assert = require('assert');
const path = require('path');
const core = require(path.join(__dirname, '..', 'chrome_extension', 'scrape_core.js'));

assert.strictEqual(core.isApprovedAmazonHost('www.amazon.com'), true);
assert.strictEqual(core.isApprovedAmazonHost('amazon.com'), true);
assert.strictEqual(core.isApprovedAmazonHost('smile.amazon.com'), true);
assert.strictEqual(core.isApprovedAmazonHost('evilamazon.com'), false);
assert.strictEqual(core.isApprovedAmazonHost('amazon.com.example'), false);
assert.strictEqual(core.isShipTrackUrl('https://www.amazon.com/gp/your-account/ship-track?orderId=1'), true);
assert.strictEqual(core.isShipTrackUrl('http://www.amazon.com/gp/your-account/ship-track?orderId=1'), false);
assert.strictEqual(core.isShipTrackUrl('https://evilamazon.com/gp/your-account/ship-track?orderId=1'), false);

// Delivered orders can link directly to the new tracker without an itemId.
const progressUrl = 'https://www.amazon.com/progress-tracker/package?orderId=111-1111111-1111111&shipmentId=shipmentA&packageIndex=0&vt=NOTIFICATIONS';
assert.strictEqual(core.isShipTrackUrl(progressUrl), true);
const normalizedProgress = new URL(core.normalizeTrackingUrl(progressUrl));
assert.strictEqual(normalizedProgress.pathname, '/progress-tracker/package');
assert.strictEqual(normalizedProgress.searchParams.get('shipmentId'), 'shipmentA');
assert.strictEqual(normalizedProgress.searchParams.get('packageIndex'), '0');
for (const invalid of [
  progressUrl.replace('https:', 'http:'),
  progressUrl.replace('www.amazon.com', 'amazon.com.example'),
  progressUrl.replace('/progress-tracker/package', '/progress-tracker/package-other'),
  'https://www.amazon.com/your-orders/pop?shipmentId=shipmentA',
]) {
  assert.strictEqual(core.isShipTrackUrl(invalid), false);
  assert.strictEqual(core.normalizeTrackingUrl(invalid), '');
}

require('./test_tracking_links.js');
require('./test_cancelled_orders.js');

const sameAsinDifferentShipments = [
  { order_id: '111', asin: 'B00A', shipment_id: 's1', line_item_id: 'l1', quantity: '1', tracking_number: '1ZAAA' },
  { order_id: '111', asin: 'B00A', shipment_id: 's2', line_item_id: 'l2', quantity: '1', tracking_number: '1ZBBB' },
];
assert.strictEqual(core.dedupePayloadLineItems(sameAsinDifferentShipments).length, 2);

const trueDupes = [
  { order_id: '111', asin: 'B00A', shipment_id: 's1', line_item_id: 'l1', quantity: '1', tracking_number: '1ZAAA' },
  { order_id: '111', asin: 'B00A', shipment_id: 's1', line_item_id: 'l1', quantity: '2', tracking_number: '1ZAAA' },
];
const merged = core.dedupePayloadLineItems(trueDupes);
assert.strictEqual(merged.length, 1);
assert.strictEqual(merged[0].quantity, '3');

assert.deepStrictEqual(
  core.getShipmentIdentity({ orderId: '111' }, { asin: 'B00A', shipmentId: 's1', itemId: 'i1' }),
  'ids|111|s1||i1||B00A'
);
assert.notStrictEqual(
  core.getShipmentIdentity({ orderId: '111' }, { asin: 'B00A', shipmentId: 's1' }),
  core.getShipmentIdentity({ orderId: '111' }, { asin: 'B00A', shipmentId: 's2' })
);

const pageTracks = [
  { shipmentId: 's1', itemId: 'i1', lineItemId: 'l1', trackingUrl: 'https://www.amazon.com/gp/your-account/ship-track?shipmentId=s1' },
  { shipmentId: 's2', itemId: 'i2', lineItemId: 'l2', trackingUrl: 'https://www.amazon.com/gp/your-account/ship-track?shipmentId=s2' },
];
assert.strictEqual(core.matchingShipTrack({ shipmentId: 's2', itemId: 'i2' }, pageTracks).shipmentId, 's2');
assert.strictEqual(core.matchingShipTrack({ shipmentId: 's9' }, pageTracks), null);

const cancelled = core.buildCancelledPayload({ orderId: '111', orderDate: '' }, 'a@amazon.com');
assert.strictEqual(cancelled.order_id, '111');
assert.strictEqual(cancelled.order_status, 'Cancelled');
assert.strictEqual('order_date' in cancelled, false);
assert.strictEqual(cancelled.email_address, 'a@amazon.com');

assert.deepStrictEqual(
  core.compactScrapeRow({ order_id: '111', tracking_number: '', product_name: 'Widget' }),
  { order_id: '111', product_name: 'Widget' }
);

assert.strictEqual(core.nextPatchVersion('1.1.7'), '1.1.8');
assert.throws(() => core.nextPatchVersion('1.1.65535'));

assert.strictEqual(core.scrapeOutcomeSuccess({ failed: 0, stopped: false, extractionIncomplete: false }), true);
assert.strictEqual(core.scrapeOutcomeSuccess({ failed: 1, stopped: false, extractionIncomplete: false }), false);
assert.strictEqual(core.scrapeOutcomeSuccess({ failed: 0, stopped: false, extractionIncomplete: true }), false);

const validPackage = {
  version: '1.1.7',
  files: {
    'manifest.json': {
      encoding: 'utf-8',
      content: JSON.stringify({
        name: 'IEID Order Scraper',
        version: '1.1.7',
        background: { service_worker: 'background.js' },
        action: { default_popup: 'popup.html' },
      }),
    },
    'background.js': { encoding: 'utf-8', content: '' },
    'popup.html': { encoding: 'utf-8', content: '' },
    'update.js': { encoding: 'utf-8', content: '' },
    'update.html': { encoding: 'utf-8', content: '' },
    'update_helpers.js': { encoding: 'utf-8', content: '' },
  },
};
assert.strictEqual(core.validatePackagePayload(validPackage).version, '1.1.7');
assert.throws(() => {
  const bad = JSON.parse(JSON.stringify(validPackage));
  delete bad.files['background.js'];
  core.validatePackagePayload(bad);
});

console.log('scrape_core tests passed');
