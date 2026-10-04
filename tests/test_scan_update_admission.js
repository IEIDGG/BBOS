const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const core = require('../chrome_extension/scrape_core.js');
const history = require('../chrome_extension/order_history.js');
const background = fs.readFileSync(require.resolve('../chrome_extension/background.js'), 'utf8');
const helpers = fs.readFileSync(require.resolve('../chrome_extension/update_helpers.js'), 'utf8');
let authCalls = 0;
let updateHeld = true;
let operationHeld = false;
let autoUpdates = 0;
const local = {};
let pending;
const context = vm.createContext({...core, ...history,
  console, scrapeState: {running: false}, normalizeZipFilters: () => [],
  clearScrapeLogs() {}, startScrapeKeepAlive() {}, stopScrapeKeepAlive() {}, openLogTab() {},
  scrapeDone() {}, getAuthCookie: async () => {authCalls++; return null;},
  maybeAutoApplyUpdate() {assert.equal(operationHeld, false, 'auto update must run after scan lock cleanup'); autoUpdates++;},
  chrome: {storage: {local: {get: async () => local}}, runtime: {getManifest: () => ({version: '1.1.14'})}},
  navigator: {locks: {request: async (_name, _options, work) => {
    if (updateHeld) return work(null);
    operationHeld = true;
    try {return await work({});} finally {operationHeld = false;}
  }}},
});
vm.runInContext(helpers, context);
context.idbGet = async () => pending;
vm.runInContext(background.slice(background.indexOf('async function runSingleOrderScrape('), background.indexOf('function normalizeCarrier(')), context);

(async () => {
  const config = {orderId: '114-1234567-1234567', yearFilter: 'year-2026', maxPages: 0};
  for (const kind of ['runScrape', 'runSingleOrderScrape']) {
    await assert.rejects(context[kind](config), /scan|update/i, 'a held updater lock must reject actual scan entry');
  }
  assert.equal(authCalls, 0, 'busy scans must not reach account or Amazon work');
  updateHeld = false;
  local.updateInProgress = true;
  await assert.rejects(context.runScrape(config, {config, incomplete: true, kind: 'bulk'}), /recover|update/i, 'checkpoint resume must obey interruption state after worker restart');
  delete local.updateInProgress;
  pending = {version: '1.1.15', files: {}};
  await assert.rejects(context.runSingleOrderScrape(config), /recover|update/i);
  assert.equal(autoUpdates, 0, 'denied scans must not schedule an update');
  pending = null;
  await context.runScrape(config);
  await context.runSingleOrderScrape(config);
  assert.equal(authCalls, 2, 'both normal scan paths resume after verified recovery');
  assert.equal(autoUpdates, 2, 'each completed admitted scan must check the pending update');
  console.log('Actual bulk, single and resumed scan admission tests passed');
})().catch(error => {console.error(error); process.exitCode = 1;});
