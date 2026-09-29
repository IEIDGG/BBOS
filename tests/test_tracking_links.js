const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const core = require('../chrome_extension/scrape_core.js');
const root = path.join(__dirname, '..', 'chrome_extension');
const orderId = '111-1111111-1111111';
const progressUrl = `https://www.amazon.com/progress-tracker/package?orderId=${orderId}&shipmentId=shipmentA&packageIndex=0`;
const legacyUrl = `https://www.amazon.com/gp/your-account/ship-track?orderId=${orderId}&shipmentId=shipmentB&itemId=itemB`;

// A minimal anchor-only DOM boundary: apply the selectors to actual hrefs,
// rather than returning the tracking link regardless of the selector used.
function anchors(hrefs) {
  return {
    querySelectorAll(selector) {
      const needles = selector.split(',').map(part => {
        const match = part.trim().match(/^a\[href\*="([^"]+)"\]$/);
        assert.ok(match, `Unsupported anchor fixture selector: ${part}`);
        return match[1];
      });
      return hrefs.filter(href => needles.some(needle => href.includes(needle)))
        .map(href => ({ href }));
    },
  };
}

for (const [file, entry] of [
  ['scraper.js', 'extractOrdersFromPage'],
  ['order_detail_scraper.js', 'extractOrderFromDetailPage'],
]) {
  const source = fs.readFileSync(path.join(root, file), 'utf8');
  // Expose the closure's real extraction helpers without invoking the page scan.
  const helpersSource = source.replace(`return ${entry}();`,
    'return { extractTrackingLink, extractShipmentIds, collect: typeof collectShipTrackLinks === "function" ? collectShipTrackLinks : null };');
  for (const sharedCore of [core, {}]) {
    const helpers = vm.runInNewContext(helpersSource, {
      ...sharedCore, URL, location: { href: 'https://www.amazon.com/your-orders/orders' },
    });
    const container = anchors([progressUrl]);
    assert.strictEqual(helpers.extractTrackingLink(container), progressUrl, file);
    assert.strictEqual(helpers.extractShipmentIds(container).shipmentId, 'shipmentA', file);
    assert.strictEqual(helpers.extractTrackingLink(anchors([legacyUrl])), legacyUrl, file);
    assert.strictEqual(helpers.extractTrackingLink(anchors([
      progressUrl.replace('www.amazon.com', 'evilamazon.com'),
    ])), '', file);
    if (helpers.collect) {
      const links = helpers.collect(anchors([progressUrl, legacyUrl]));
      assert.strictEqual(links.length, 2);
      assert.strictEqual(links[0].trackingUrl, progressUrl);
    }
  }
}

// Exercise the background's actual queue builder without starting Chrome APIs.
const background = fs.readFileSync(path.join(root, 'background.js'), 'utf8');
const queueCode = background.slice(background.indexOf('function buildTrackingUrl('),
  background.indexOf('function normalizeComparable('));
const context = vm.createContext({ ...core, URL, URLSearchParams,
  normalizeTrackingUrlForKey: value => value });
vm.runInContext(queueCode, context);
const queued = context.buildTrackingFetchGroups([{ orderId, shipments: [
  { trackingUrl: progressUrl, shipmentId: 'shipmentA' },
  { trackingUrl: legacyUrl, shipmentId: 'shipmentB', itemId: 'itemB' },
] }]);
assert.strictEqual(queued.shipmentCount, 2);
assert.strictEqual(queued.groups.length, 2);
assert.strictEqual(queued.noUrlTargets.length, 0);
assert.strictEqual(new URL(queued.groups[0].trackUrl).pathname, '/progress-tracker/package');
console.log('tracking link extraction and queue tests passed');
