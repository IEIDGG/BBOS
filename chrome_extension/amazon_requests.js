// Request transport shared by detail discovery and tracking lookups.
let amazonParserCreation = null;

function validateAmazonReadUrl(value, kind) {
  const url = new URL(value);
  if (url.protocol !== 'https:' || !['www.amazon.com', 'amazon.com'].includes(url.hostname)) {
    throw new Error('Unapproved Amazon request URL');
  }
  const validPath = kind === 'list'
    ? /^\/(?:your-orders\/orders|gp\/your-account\/order-history)(?:\/ref=[^/]+)?\/?$/i.test(url.pathname)
    : kind === 'detail'
    ? /^\/(?:your-orders|gp\/your-account)\/order-details(?:\/ref=[^/]+)?\/?$/i.test(url.pathname)
    : /^(?:\/gp\/your-account\/ship-track|\/progress-tracker\/package)(?:\/ref=[^/]+)?\/?$/i.test(url.pathname);
  if (!validPath) throw new Error('Unexpected Amazon page type');
  return url;
}

async function ensureAmazonHtmlParser() {
  if (amazonParserCreation) return amazonParserCreation;
  amazonParserCreation = (async () => {
    const documentUrl = chrome.runtime.getURL('amazon_parser.html');
    const contexts = await chrome.runtime.getContexts({ contextTypes: ['OFFSCREEN_DOCUMENT'], documentUrls: [documentUrl] });
    if (!contexts.length) {
      await chrome.offscreen.createDocument({ url: 'amazon_parser.html', reasons: ['DOM_PARSER'],
        justification: 'Extract shipment and tracking data from fetched Amazon HTML without opening tabs.' });
    }
  })();
  try {
    await amazonParserCreation;
  } finally {
    amazonParserCreation = null;
  }
}

async function requestAmazonPage(url, kind) {
  const requestUrl = validateAmazonReadUrl(url, kind);
  // Amazon supplies this URL in its noscript fallback for encrypted order cards.
  if (kind === 'list') requestUrl.searchParams.set('disableCsd', 'no-js');
  url = requestUrl.href;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 12000);
  let html;
  let responseUrl;
  try {
    const response = await fetch(url, { credentials: 'include', signal: controller.signal, cache: 'no-store' });
    if (!response.ok) throw new Error(`Amazon HTTP ${response.status}`);
    responseUrl = response.url;
    validateAmazonReadUrl(responseUrl, kind); // Sign-in redirects need the browser fallback.
    const requested = new URL(url);
    const returned = new URL(responseUrl);
    for (const aliases of [['orderID', 'orderId'], ['shipmentId'], ['packageId'], ['packageIndex'], ['timeFilter', 'orderFilter'], ['page'], ['startIndex']]) {
      const expected = aliases.map(key => requested.searchParams.get(key)).filter(value => value !== null);
      const actual = aliases.map(key => returned.searchParams.get(key)).filter(value => value !== null);
      if (expected.length && (!actual.length || expected.some(value => value !== expected[0])
          || actual.some(value => value !== expected[0]))) {
        throw new Error('Amazon redirected to another order or shipment');
      }
    }
    if (!/text\/html/i.test(response.headers.get('content-type') || '')) throw new Error('Expected Amazon HTML');
    html = await response.text();
    if (!html || html.length > 8 * 1024 * 1024) throw new Error('Unexpected Amazon HTML size');
  } finally {
    clearTimeout(timer);
  }
  await ensureAmazonHtmlParser();
  let parseTimer;
  try {
    const reply = await Promise.race([
      chrome.runtime.sendMessage({ target: 'ieid-html-parser', kind, html, url: responseUrl }),
      new Promise((_, reject) => { parseTimer = setTimeout(() => reject(new Error('HTML parser timed out')), 5000); }),
    ]);
    if (reply?.error || !reply?.result) throw new Error(reply?.error || 'No HTML parser response');
    return reply.result;
  } finally {
    clearTimeout(parseTimer);
  }
}

async function readAmazonPage(url, kind, accept) {
  validateAmazonReadUrl(url, kind);
  if (scrapeState.stopped) throw new Error('Scan stopped');
  try {
    const result = await requestAmazonPage(url, kind);
    if (scrapeState.stopped) throw new Error('Scan stopped');
    if (!accept(result)) throw new Error(result?.issue || 'HTML has incomplete shipment data');
    log(`${kind === 'list' ? 'Order list' : kind === 'detail' ? 'Order details' : 'Tracking'} read by background request`, 'info');
    return result;
  } catch (err) {
    if (scrapeState.stopped) throw err;
    log(`${kind === 'list' ? 'Order list' : kind === 'detail' ? 'Order details' : 'Tracking'} request needs tab fallback (${err.message})`, 'info');
  }
  let tabId = null;
  try {
    tabId = await openTab(url);
    if (kind === 'tracking') activeTrackingTabIds.push(tabId);
    if (scrapeState.stopped) throw new Error('Scan stopped');
    await waitForTabReady();
    return await injectAndRun(tabId, kind === 'list' ? 'scraper.js' : kind === 'detail' ? 'order_detail_scraper.js' : 'tracking_scraper.js');
  } finally {
    if (tabId) await closeTab(tabId);
    if (kind === 'tracking') activeTrackingTabIds = activeTrackingTabIds.filter(id => id !== tabId);
  }
}
