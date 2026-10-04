/* Disposable Chromium: real extension locks, IndexedDB and OPFS handles.
 * The directory picker and runtime.reload UI are deliberately outside this test.
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
process.env.PW_EXPERIMENTAL_SERVICE_WORKER_NETWORK_EVENTS = '1';
const {chromium} = require('playwright');
const extension = path.join(__dirname, '../chrome_extension');
const manifest = JSON.parse(fs.readFileSync(path.join(extension, 'manifest.json'), 'utf8'));
const parts = manifest.version.split('.').map(Number); parts[2]++;
const target = parts.join('.');
const payload = {version: target, files: {}};
function collect(directory, prefix = '') {
  for (const entry of fs.readdirSync(directory, {withFileTypes: true})) {
    const name = prefix + entry.name;
    if (entry.isDirectory()) collect(path.join(directory, entry.name), name + '/');
    else payload.files[name] = {encoding: 'base64', content: fs.readFileSync(path.join(directory, entry.name)).toString('base64')};
  }
}
collect(extension);
payload.files['manifest.json'] = {encoding: 'utf-8', content: JSON.stringify({...manifest, version: target})};
const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'ieid-update-native-'));
let context, home;
let packageRequests = 0;
async function launch() {
  context = await chromium.launchPersistentContext(profile, {
    headless: false,
    ...(process.env.CHROMIUM_PATH ? {executablePath: process.env.CHROMIUM_PATH} : {}),
    args: [`--disable-extensions-except=${extension}`, `--load-extension=${extension}`,
      '--no-sandbox', '--disable-dev-shm-usage', '--host-resolver-rules=MAP ieidgg.com ~NOTFOUND, MAP *.amazon.com ~NOTFOUND'],
  });
  await context.route('https://ieidgg.com/**', async route => {
    const pathname = new URL(route.request().url()).pathname;
    if (pathname === '/api/order-scraper/package') {
      packageRequests++;
      const headers = route.request().headers();
      assert.equal(headers['x-auth-token'], 'synthetic-update-token');
      assert.ok(headers['x-extension-origin']?.startsWith('chrome-extension://'));
      assert.equal(headers.cookie, undefined);
    }
    const json = pathname === '/api/order-scraper/package' ? payload
      : pathname === '/api/order-scraper/version' ? {version: manifest.version}
      : pathname === '/api/user' ? {uid: 'synthetic', email: 'synthetic@example.test'} : {success: true};
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(json)});
  });
  await context.route('https://www.amazon.com/**', route => route.abort());
  let worker = context.serviceWorkers()[0] || await context.waitForEvent('serviceworker', {timeout: 15000});
  await worker.evaluate(() => typeof IEIDAuth);
  home = new URL('.', worker.url()).href;
  await worker.evaluate(async () => {
    await chrome.storage.local.set({accountGrant: {access_token: 'synthetic-update-token', refresh_token: 'synthetic-refresh', expires_at: new Date(Date.now() + 86400000).toISOString()}});
  });
  return worker;
}
async function updater() {
  const page = await context.newPage();
  await page.goto(home + 'update.html');
  await page.waitForFunction(() => typeof runApply === 'function');
  await page.evaluate(async () => {
    window.fixtureRoot = await (await navigator.storage.getDirectory()).getDirectoryHandle('update-fixture', {create: true});
    chrome.runtime.reload = () => {window.reloads = (window.reloads || 0) + 1;};
  });
  return page;
}
async function seed(page) {
  await page.evaluate(async current => {
    const file = await fixtureRoot.getFileHandle('manifest.json', {create: true});
    const stream = await file.createWritable(); await stream.write(JSON.stringify(current)); await stream.close();
  }, manifest);
}
async function waitForNoOperation(page) {
  await page.waitForFunction(async () => !(await navigator.locks.query()).held.some(lock => lock.name === 'ieid-scan-update'));
}
async function rejectedScan(worker, action = 'runScrape') {
  return worker.evaluate(async method => {
    try {
      await globalThis[method]({orderId: '114-1234567-1234567', yearFilter: 'year-2026', maxPages: 0});
      return 'unsafe-entry';
    } catch (error) {return error.message;}
  }, action);
}
// Playwright retains the first execution context for a worker target. Use CDP
// after stop/start so verification runs in the actual fresh worker context.
async function attachRestartedWorker() {
  const cdp = await context.browser().newBrowserCDPSession();
  const {targetInfos} = await cdp.send('Target.getTargets');
  const target = targetInfos.find(item => item.type === 'service_worker' && item.url === home + 'background.js');
  assert.ok(target, 'the restarted extension must have a worker target');
  const {sessionId} = await cdp.send('Target.attachToTarget', {targetId: target.targetId, flatten: false});
  let sequence = 0;
  const pending = new Map();
  cdp.on('Target.receivedMessageFromTarget', event => {
    if (event.sessionId !== sessionId) return;
    const message = JSON.parse(event.message);
    const request = pending.get(message.id);
    if (!request) return;
    pending.delete(message.id);
    if (message.error || message.result?.exceptionDetails) request.reject(Error(JSON.stringify(message)));
    else request.resolve(message.result.result.value);
  });
  return {evaluate(fn, argument) {
    const id = ++sequence;
    const response = new Promise((resolve, reject) => pending.set(id, {resolve, reject}));
    const expression = `(${fn.toString()})(${JSON.stringify(argument) ?? ''})`;
    cdp.send('Target.sendMessageToTarget', {sessionId, message: JSON.stringify({id, method: 'Runtime.evaluate', params: {expression, awaitPromise: true, returnByValue: true}})}).catch(error => {
      pending.get(id)?.reject(error); pending.delete(id);
    });
    return response;
  }};
}
async function run() {
  let worker = await launch();
  console.log('Native updater browser: ' + await context.browser().version());
  let owner = await updater();
  const contender = await updater();
  await seed(owner);
  await owner.evaluate(() => {
    window.held = withExtensionOperation('update', () => new Promise(resolve => {window.release = resolve; window.entered = true;}));
  });
  await owner.waitForFunction(() => window.entered);
  for (const method of ['runScrape', 'runSingleOrderScrape']) assert.match(await rejectedScan(worker, method), /scan|update/i);
  await contender.evaluate(() => runApply(fixtureRoot));
  assert.equal(packageRequests, 0, 'a competing updater must not start its package request');
  assert.match(await contender.locator('#status').textContent(), /scan|update/i);

  // A stale completed target must never let another startup clear new write intent.
  await owner.evaluate(async ({installed, pending}) => {
    await chrome.storage.local.set({updateTargetVersion: installed});
    await idbSet('state', 'pendingPackage', pending);
  }, {installed: manifest.version, pending: payload});
  const settler = await updater();
  await settler.evaluate(() => verifyAfterReload().catch(() => {}));
  await worker.evaluate(() => maybeAutoApplyUpdate());
  assert.equal(await owner.evaluate(async () => (await idbGet('state', 'pendingPackage'))?.version), target,
    'startup settlement must not erase pending write intent owned by another updater');
  await owner.evaluate(async () => {
    await idbDelete('state', 'pendingPackage');
    await chrome.storage.local.remove(['updateTargetVersion', 'updateInProgress', 'updateReloadPending']);
  });
  await settler.close();

  // Terminate only this disposable extension's worker while its page owns a lock.
  const cdp = await context.newCDPSession(contender);
  const versions = new Map();
  cdp.on('ServiceWorker.workerVersionUpdated', event => {
    for (const version of event.versions) versions.set(version.versionId, version);
  });
  await cdp.send('ServiceWorker.enable');
  for (let attempt = 0; attempt < 100 && ![...versions.values()].some(item => item.scriptURL === worker.url()); attempt++) {
    await contender.waitForTimeout(50);
  }
  const workerVersion = [...versions.values()].find(item => item.scriptURL === worker.url());
  assert.ok(workerVersion, 'locate the owned native worker version');
  await worker.evaluate(() => {globalThis.restartMarker = 'old-worker';});
  await cdp.send('ServiceWorker.stopWorker', {versionId: workerVersion.versionId});
  for (let attempt = 0; attempt < 100 && versions.get(workerVersion.versionId)?.runningStatus !== 'stopped'; attempt++) {
    await contender.waitForTimeout(50);
  }
  assert.equal(versions.get(workerVersion.versionId)?.runningStatus, 'stopped', 'the disposable worker must stop before waking it');
  await contender.evaluate(() => chrome.runtime.sendMessage({action: 'scrape_status'}));
  worker = await attachRestartedWorker();
  assert.equal(await worker.evaluate(() => globalThis.restartMarker), undefined, 'worker wakeup must create a fresh execution context');
  assert.match(await rejectedScan(worker), /scan|update/i, 'a restarted worker must honor the still-open updater lock');
  await cdp.detach();
  await owner.close();
  await waitForNoOperation(contender);
  assert.equal(await worker.evaluate(() => withExtensionOperation('scan', () => true)), true, 'closing the owner releases the native lock');
  console.log('Native cross-context exclusion, competing updater, worker restart and owner-close release passed');

  // A scan owns the lock through cleanup, even after stop is requested.
  await worker.evaluate(() => {
    globalThis.heldScan = withExtensionOperation('scan', () => new Promise(resolve => {globalThis.releaseScan = resolve; scrapeState.running = true;}));
  });
  await contender.evaluate(() => chrome.runtime.sendMessage({action: 'stop_scrape'}));
  await contender.evaluate(() => runApply(fixtureRoot));
  assert.equal(packageRequests, 0);
  await worker.evaluate(async () => {releaseScan(); await heldScan; scrapeState.running = false;});
  await waitForNoOperation(contender);

  // Interrupt actual OPFS staging with the durable pending package already stored.
  owner = await updater();
  await owner.evaluate(() => {
    const original = writeStaging;
    writeStaging = async (...args) => {window.stagingEntered = true; await new Promise(resolve => {window.releaseStaging = resolve;}); return original(...args);};
    window.applyTask = runApply(fixtureRoot);
  });
  await owner.waitForFunction(() => window.stagingEntered);
  await contender.evaluate(() => runApply(fixtureRoot));
  assert.equal(packageRequests, 1, 'two native updater tabs must have only one downloader/writer');
  await owner.close();
  assert.match(await rejectedScan(worker), /recover|update/i, 'closing the writer must not expose interrupted files to a scan');
  await context.close();
  worker = await launch();
  assert.match(await rejectedScan(worker, 'runSingleOrderScrape'), /recover|update/i, 'durable barrier survives browser and worker restart');
  const recovery = await updater();
  await recovery.evaluate(() => runApply(fixtureRoot));
  assert.equal(packageRequests, 1, 'recovery uses the committed pending package without another download');
  assert.equal(await recovery.evaluate(() => window.reloads), 1);
  const copied = await recovery.evaluate(async entries => {
    for (const [name, entry] of Object.entries(entries)) {
      let dir = fixtureRoot; const parts = name.split('/'); const file = parts.pop();
      for (const part of parts) dir = await dir.getDirectoryHandle(part);
      const bytes = new Uint8Array(await (await (await dir.getFileHandle(file)).getFile()).arrayBuffer());
      const expected = entry.encoding === 'utf-8' ? new TextEncoder().encode(entry.content) : Uint8Array.from(atob(entry.content), ch => ch.charCodeAt(0));
      if (bytes.length !== expected.length || bytes.some((value, index) => value !== expected[index])) return name;
    }
    return null;
  }, payload.files);
  assert.equal(copied, null, 'all actual OPFS package files must match byte-for-byte');
  assert.match(await rejectedScan(worker), /recover|update/i, 'reload intent remains a scan barrier until the new version is verified');
  console.log('Native IndexedDB/OPFS interruption, browser restart, authenticated package recovery and byte-for-byte replacement passed');
  console.log('Native directory picker and activation of the command-line-loaded extension remain outside this harness');
}
(async () => {
  let deadline;
  try {
    await Promise.race([run(), new Promise((_, reject) => {deadline = setTimeout(() => reject(Error('Native updater test exceeded 90 seconds')), 90000);})]);
  } finally {
    clearTimeout(deadline);
    if (context) await context.close().catch(() => {});
    fs.rmSync(profile, {recursive: true, force: true});
  }
})().catch(error => {console.error(error);process.exitCode=1;});
