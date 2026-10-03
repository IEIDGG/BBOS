const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { parseHTML } = require('linkedom');
const root = path.join(__dirname, '..', 'chrome_extension');
const payload = { version: '1.1.12', files: {} };
function collect(dir, prefix = '') {
  for (const item of fs.readdirSync(dir, { withFileTypes: true })) {
    const rel = prefix + item.name;
    if (item.isDirectory()) collect(path.join(dir, item.name), rel + '/');
    else
      payload.files[rel] = {
        encoding: 'base64',
        content: fs.readFileSync(path.join(dir, item.name)).toString('base64')
      };
  }
}
collect(root);
const packagedManifest = JSON.parse(fs.readFileSync(path.join(root, 'manifest.json'), 'utf8'));
packagedManifest.version = '1.1.12';
payload.files['manifest.json'] = { encoding: 'utf-8', content: JSON.stringify(packagedManifest) };
function storage(obj) {
  return {
    async get(keys) {
      if (typeof keys === 'string') return { [keys]: obj[keys] };
      return Object.fromEntries(keys.map((k) => [k, obj[k]]));
    },
    async set(values) {
      Object.assign(obj, values);
    },
    async remove(keys) {
      for (const k of [].concat(keys)) delete obj[k];
    }
  };
}
async function scenario({
  writeFailure = false,
  wrongFolder = false,
  silentStatus = false,
  stalledDownload = false,
  permanentStall = false,
  activeScan = false,
  serverFailure = false,
  stalledBody = false,
  rejectedAuth = false,
  buttonFlow = false,
  scanStartsDuringDownload = false,
  liveWriteFailure = false
} = {}) {
  const local = { zipFilters: '03063', yearFilter: 'year-2026' };
  const session = {};
  const db = new Map();
  const files = new Map([
    ['manifest.json', Buffer.from(JSON.stringify({ name: 'IEID Order Scraper', version: '1.1.11' }))]
  ]);
  let installed = '1.1.11',
    reloads = 0,
    authCalls = 0,
    picks = 0,
    statusCalls = 0;
  let failWrites = writeFailure || liveWriteFailure;
  let liveWrites = 0;
  let accessToken = 'synthetic-test-token';
  const timers = new Map();
  let nextTimer = 0;
  const timeout = (fn, ms) => {
    const id = ++nextTimer;
    timers.set(id, { fn, ms });
    return id;
  };
  const clear = (id) => timers.delete(id);
  async function flush() {
    for (let i = 0; i < 100; i++) await Promise.resolve();
  }
  async function expire() {
    await flush();
    const item = timers.entries().next().value;
    assert.ok(item, 'stalled operation must have a bounded timeout');
    timers.delete(item[0]);
    item[1].fn();
    await flush();
  }
  function dir(prefix = '') {
    return {
      async queryPermission() {
        return 'granted';
      },
      async getDirectoryHandle(name, opts) {
        return dir(prefix + name + '/');
      },
      async removeEntry(name) {
        for (const key of files.keys())
          if (key === prefix + name || key.startsWith(prefix + name + '/')) files.delete(key);
      },
      async getFileHandle(name, opts) {
        const key = prefix + name;
        if (!opts?.create && !files.has(key)) throw Error('NotFound');
        return {
          async getFile() {
            const b = files.get(key);
            return {
              async text() {
                return b.toString();
              },
              async arrayBuffer() {
                return b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength);
              }
            };
          },
          async createWritable() {
            if (
              failWrites &&
              (!liveWriteFailure || (!key.startsWith('.ieid-update-staging/') && liveWrites >= 2))
            ) {
              throw Error('Permission denied during file replacement');
            }
            return {
              async write(data) {
                files.set(key, Buffer.from(typeof data === 'string' ? data : new Uint8Array(data)));
                if (!key.startsWith('.ieid-update-staging/')) liveWrites++;
              },
              async close() {}
            };
          }
        };
      }
    };
  }
  const handle = dir();
  const { window, document } = parseHTML(fs.readFileSync(path.join(root, 'update.html'), 'utf8'));
  const logs = [];
  const context = vm.createContext({
    document,
    window,
    URLSearchParams,
    location: { search: '' },
    console: {
      info(...args) {
        logs.push(args);
      },
      error(...args) {
        logs.push(args);
      }
    },
    Uint8Array,
    Date,
    AbortController,
    setTimeout: timeout,
    clearTimeout: clear,
    atob: (s) => Buffer.from(s, 'base64').toString('binary'),
    fetch: async (url, options) => {
      authCalls++;
      if (url.endsWith('/api/refresh-token')) {
        accessToken = 'synthetic-refreshed-token';
        return { ok: true, status: 200, json: async () => ({ success: true }) };
      }
      assert.ok(url.endsWith('/api/order-scraper/package'));
      if (rejectedAuth) return { ok: false, status: 401 };
      if (serverFailure && authCalls === 1) return { ok: false, status: 503 };
      if (stalledDownload && (permanentStall || authCalls === 1)) {
        return new Promise((resolve, reject) => {
          options?.signal?.addEventListener(
            'abort',
            () => {
              const e = new Error('aborted');
              e.name = 'AbortError';
              reject(e);
            },
            { once: true }
          );
        });
      }
      if (stalledBody && authCalls === 1) {
        return { ok: true, status: 200, json: async () => new Promise(() => {}) };
      }
      return { ok: true, status: 200, json: async () => payload };
    },
    chrome: {
      storage: { local: storage(local), session: storage(session) },
      cookies: {
        get: async ({ name }) => ({
          value: name === 'access_token' ? accessToken : 'synthetic-refresh-token'
        })
      },
      runtime: {
        getManifest: () => ({ version: installed }),
        sendMessage: (msg, cb) => {
          statusCalls++;
          if (silentStatus && (permanentStall || statusCalls === 1)) return;
          cb({ running: activeScan || (scanStartsDuringDownload && authCalls > 0) });
        },
        reload() {
          reloads++;
          if (!wrongFolder) installed = JSON.parse(files.get('manifest.json').toString()).version;
          for (const k of Object.keys(session)) delete session[k];
        }
      },
      tabs: {
        getCurrent: async () => ({ id: 123 }),
        get: async () => {
          throw Error('closed');
        }
      }
    }
  });
  window.showDirectoryPicker = async () => {
    picks++;
    return handle;
  };
  for (const name of ['scrape_core.js', 'update_helpers.js', 'update.js'])
    vm.runInContext(fs.readFileSync(path.join(root, name), 'utf8'), context, { filename: name });
  context.idbGet = async (s, k) => db.get(s + ':' + k);
  context.idbSet = async (s, k, v) => db.set(s + ':' + k, v);
  context.idbDelete = async (s, k) => db.delete(s + ':' + k);
  await context.start();
  assert.equal(document.getElementById('pickFolderBtn').hidden, false);
  let running;
  if (buttonFlow) {
    const apply = context.runApply;
    context.runApply = (...args) => {
      running = apply(...args);
      return running;
    };
    document.getElementById('pickFolderBtn').click();
    await flush();
    assert.ok(running, 'the folder-selection button must start the updater');
  } else {
    const selected = await context.pickFolder();
    running = context.runApply(selected);
  }
  if (silentStatus || stalledDownload || stalledBody) {
    await flush();
    assert.match(
      document.getElementById('status').textContent,
      /checking|downloading|retry|sign/i,
      'progress must show while the updater waits after folder selection'
    );
    await expire();
    if (permanentStall) await expire();
  }
  await running;
  await flush();
  if (activeScan || permanentStall || rejectedAuth || scanStartsDuringDownload) {
    assert.equal(reloads, 0);
    assert.equal(
      JSON.parse(files.get('manifest.json').toString()).version,
      '1.1.11',
      'failed status/download must not replace installed files'
    );
    assert.ok(document.getElementById('status').classList.contains('error'));
    if (rejectedAuth) assert.equal(authCalls, 3, 'refresh authentication only once, then stop');
    if (buttonFlow) {
      assert.equal(document.getElementById('pickFolderBtn').hidden, false);
      assert.equal(document.getElementById('pickFolderBtn').disabled, false, 'failure must allow a retry');
    }
    return {
      case: scanStartsDuringDownload
        ? 'scan started during package download'
        : rejectedAuth
          ? 'rejected refreshed authentication'
          : activeScan
            ? 'active scan'
            : silentStatus
              ? 'unresponsive worker'
              : 'unresponsive package',
      result: 'bounded failure; no writes or reload'
    };
  }
  if (writeFailure || liveWriteFailure) {
    assert.equal(reloads, 0);
    assert.match(document.getElementById('status').textContent, /Permission denied/);
    assert.ok(db.has('state:pendingPackage'));
    if (liveWriteFailure) {
      assert.equal(liveWrites, 2, 'failure occurs after replacing some live files');
      assert.equal(
        JSON.parse(files.get('manifest.json').toString()).version,
        '1.1.11',
        'manifest commits last'
      );
    }
    failWrites = false;
    await context.runApply(handle);
    assert.equal(authCalls, 1, 'resume the retained package without downloading it again');
  }
  const result = await context.settleUpdateAfterReload();
  if (wrongFolder) {
    assert.equal(result.status, 'mismatch');
    assert.equal(installed, '1.1.11');
    assert.equal(db.has('handles:extensionDir'), false);
    return {
      case: 'different extension copy selected',
      result: 'version mismatch detected after write/reload; folder grant cleared'
    };
  }
  assert.equal(result.status, 'verified');
  assert.equal(installed, '1.1.12');
  assert.equal(reloads, 1);
  assert.equal(authCalls, stalledDownload || stalledBody || serverFailure ? 2 : 1);
  assert.equal(picks, 1);
  assert.equal(local.zipFilters, '03063');
  assert.equal(local.yearFilter, 'year-2026');
  assert.equal(db.has('state:pendingPackage'), false);
  for (const [name, entry] of Object.entries(payload.files))
    assert.deepEqual(
      files.get(name),
      Buffer.from(entry.content, entry.encoding === 'utf-8' ? 'utf8' : 'base64')
    );
  return {
    case:
      writeFailure || liveWriteFailure
        ? 'interrupted write recovery'
        : silentStatus
          ? 'worker reconnect'
          : stalledDownload
            ? 'download retry'
            : stalledBody
              ? 'stalled JSON body retry'
              : serverFailure
                ? 'temporary HTTP failure retry'
                : buttonFlow
                  ? 'folder button flow'
                  : 'correct folder and writable grant',
    result: 'package copied byte-for-byte; v1.1.12 verified; settings retained'
  };
}
(async () => {
  for (const opts of [
    { silentStatus: true },
    { stalledDownload: true },
    { stalledBody: true },
    { serverFailure: true },
    { scanStartsDuringDownload: true, buttonFlow: true },
    { silentStatus: true, permanentStall: true },
    { stalledDownload: true, permanentStall: true },
    { activeScan: true, buttonFlow: true },
    { rejectedAuth: true, buttonFlow: true },
    { buttonFlow: true },
    {},
    { wrongFolder: true },
    { writeFailure: true },
    { liveWriteFailure: true }
  ])
    console.log(JSON.stringify(await scenario(opts)));
  console.log(
    'update flow regression tests passed (browser APIs simulated; native picker and reload are not covered)'
  );
})().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
