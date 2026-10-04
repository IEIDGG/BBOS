const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../chrome_extension/update_helpers.js'), 'utf8');

function fixture() {
  let held = false;
  const local = {};
  let pending;
  const locks = {request: async (_name, options, callback) => {
    assert.equal(options.ifAvailable, true, 'busy work must be rejected, never queued for later');
    if (held) return callback(null);
    held = true;
    try { return await callback({name: 'ieid-scan-update'}); }
    finally { held = false; }
  }};
  const context = vm.createContext({navigator: {locks}, chrome: {
    storage: {local: {get: async () => local}}, runtime: {getManifest: () => ({version: '1.1.14'})},
  }});
  vm.runInContext(source, context);
  context.idbGet = async () => pending;
  return {context, local, setPending: value => {pending = value;}};
}

(async () => {
  const {context, local, setPending} = fixture();
  assert.equal(typeof context.withExtensionOperation, 'function', 'updater and scans need one shared admission lock');
  for (const first of ['scan', 'update']) {
    let release, entered;
    const ready = new Promise(resolve => {entered = resolve;});
    const owner = context.withExtensionOperation(first, async () => {
      entered();
      await new Promise(resolve => {release = resolve;});
    });
    await ready;
    let competingWork = 0;
    await assert.rejects(context.withExtensionOperation(first === 'scan' ? 'update' : 'scan', () => {competingWork++;}), /scan|update/i);
    await assert.rejects(context.withExtensionOperation('update', () => {competingWork++;}), /scan|update/i);
    assert.equal(competingWork, 0);
    release(); await owner;
    await context.withExtensionOperation('scan', () => {competingWork++;});
    assert.equal(competingWork, 1, 'the next operation may enter after complete owner cleanup');
  }
  await assert.rejects(context.withExtensionOperation('update', async () => {throw new Error('interrupted write');}), /interrupted/);
  await context.withExtensionOperation('update', () => {});
  for (const flag of ['updateInProgress', 'updateReloadPending']) {
    local[flag] = true;
    await assert.rejects(context.withExtensionOperation('scan', () => {throw Error('unsafe scan entered');}), /recover|update/i);
    await context.withExtensionOperation('update', () => {});
    delete local[flag];
  }
  setPending({version: '1.1.15', files: {}});
  await assert.rejects(context.withExtensionOperation('scan', () => {throw Error('unsafe scan entered');}), /recover|update/i);
  setPending({version: '1.1.14', files: {}});
  await context.withExtensionOperation('scan', () => {});
  context.idbGet = async () => {throw Error('database unavailable');};
  await assert.rejects(context.withExtensionOperation('scan', () => {}), /database unavailable/);
  delete context.navigator.locks;
  await assert.rejects(context.withExtensionOperation('update', () => {}), /coordination|Chrome/i);
  console.log('Operation admission tests passed: both race orders, competing updates, interruption, persistent recovery guards and fail-closed state reads');
})().catch(error => {console.error(error); process.exitCode = 1;});
