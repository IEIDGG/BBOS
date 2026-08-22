const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');

const extPath = path.join(__dirname, '..', 'chrome_extension');
assert.ok(fs.existsSync(path.join(extPath, 'manifest.json')));

let playwright;
try {
  playwright = require('playwright');
} catch (err) {
  console.error('playwright is required for the unpacked extension smoke test');
  process.exit(1);
}

(async () => {
  const userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'ieid-ext-'));
  const context = await playwright.chromium.launchPersistentContext(userDataDir, {
    headless: false,
    args: [
      `--disable-extensions-except=${extPath}`,
      `--load-extension=${extPath}`,
      '--no-sandbox',
      '--disable-dev-shm-usage',
    ],
  });
  try {
    let worker = context.serviceWorkers()[0];
    if (!worker) {
      worker = await context.waitForEvent('serviceworker', { timeout: 20000 });
    }
    assert.ok(worker.url().startsWith('chrome-extension://'), `unexpected worker url: ${worker.url()}`);
    const version = await worker.evaluate(async () => chrome.runtime.getManifest().version);
    const installed = JSON.parse(fs.readFileSync(path.join(extPath, 'manifest.json'), 'utf8')).version;
    assert.strictEqual(version, installed);
    console.log(`extension smoke passed (service worker v${version})`);
  } finally {
    await context.close();
    fs.rmSync(userDataDir, { recursive: true, force: true });
  }
})().catch((err) => {
  console.error(err);
  process.exit(1);
});
