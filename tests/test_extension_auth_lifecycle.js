const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {webcrypto} = require('node:crypto');

const source = fs.readFileSync(path.join(__dirname, '../chrome_extension/auth_client.js'), 'utf8');
const grant = () => ({access_token:'access-one', refresh_token:'refresh-one', expires_at:new Date(Date.now()+86400000).toISOString()});
const clone = value => JSON.parse(JSON.stringify(value));

function client(options = {}) {
  const local = clone(options.local || {});
  const session = clone(options.session || {});
  const calls = [];
  const tabs = [];
  let listener;
  let accessLevel;
  const storage = data => ({
    async get(key) {return {[key]:clone(data[key] ?? null)};},
    async set(values) {Object.assign(data, clone(values));},
    async remove(keys) {for (const key of Array.isArray(keys)?keys:[keys]) delete data[key];},
  });
  const localStorage = storage(local);
  localStorage.setAccessLevel = async value => {accessLevel = value.accessLevel;};
  const chrome = {
    storage:{local:localStorage, session:storage(session)},
    runtime:{id:'a'.repeat(32),getURL:value=>'chrome-extension://'+'a'.repeat(32)+'/'+value,onMessage:{addListener:value=>{listener=value;}}},
    tabs:{create:async value=>{tabs.push(value);}},
  };
  const scope = {chrome, crypto:webcrypto, TextEncoder, Uint8Array, URL, URLSearchParams, Date, Promise, Headers, Response, AbortController, btoa, console,
    setTimeout:(fn, delay)=>setTimeout(fn, Math.min(delay, 20)), clearTimeout,
    fetch:async (url, settings)=>{
      calls.push({url,settings});
      assert.equal(settings.credentials, 'omit');
      if (options.fetch) return options.fetch(url, settings);
      if (url.endsWith('/logout')) return Response.json({success:true});
      if (url.endsWith('/exchange')) return Response.json({...grant(),access_token:'access-two',refresh_token:'refresh-two'});
      return Response.json({success:true});
    },
  };
  scope.globalThis = scope;
  vm.runInNewContext(source, scope);
  const handoff = async () => {
    const opened = new URL(tabs.at(-1).url);
    const message = {type:'ieid-extension-handoff',extension_id:chrome.runtime.id,state:opened.searchParams.get('state'),code:'c'.repeat(43)};
    return new Promise(resolve=>listener(message,{id:chrome.runtime.id,url:opened.href},resolve));
  };
  return {scope,local,session,calls,tabs,handoff,accessLevel:()=>accessLevel};
}

async function durableGrant() {
  const fixture = client({session:{accountGrant:grant()}});
  assert.equal(await fixture.scope.IEIDAuth.getToken(), 'access-one');
  for (const key of Object.keys(fixture.session)) delete fixture.session[key];
  assert.equal(await fixture.scope.IEIDAuth.getToken(), 'access-one', 'reload must not lose the only credential copy');
  assert.equal(fixture.accessLevel(), 'TRUSTED_CONTEXTS', 'content scripts must not read durable credentials');
  await fixture.scope.IEIDAuth.disconnect();
  assert.equal(fixture.local.accountGrant, undefined);
  assert.equal(fixture.session.accountGrant, undefined);
}

async function reconnectRevokesPreviousGrant() {
  const fixture = client({session:{accountGrant:grant()},local:{accountGrant:grant()}});
  await fixture.scope.IEIDAuth.connect();
  assert.equal((await fixture.handoff()).value, true);
  await fixture.scope.IEIDAuth.disconnect();
  const revoked = fixture.calls.filter(call=>call.url.endsWith('/logout')).map(call=>JSON.parse(call.settings.body).refresh_token);
  assert.deepEqual(revoked, ['refresh-one','refresh-two'], 'disconnect must cover the prior and replacement grants');
  const failed = client({local:{accountGrant:grant()},session:{accountGrant:grant()},fetch:async url=>url.endsWith('/logout')?Response.json({success:false},{status:503}):Response.json({success:true})});
  await assert.rejects(failed.scope.IEIDAuth.connect());
  assert.equal(failed.tabs.length, 0, 'failed revocation must not start another grant');
  assert.equal(failed.local.accountGrant.refresh_token, 'refresh-one');
}

async function connectionImportsAccountZipFiltersWithoutPopup() {
  const fixture = client({local:{zipFilters:'99999',fetchTracking:false},fetch:async (url, settings)=>{
    if (url.endsWith('/exchange')) return Response.json({...grant(),access_token:'new-account-token'});
    if (url.endsWith('/api/settings/monitor')) {
      assert.equal(new Headers(settings.headers).get('X-Auth-Token'), 'new-account-token');
      assert.equal(new Headers(settings.headers).get('X-Extension-Origin'), 'chrome-extension://'+'a'.repeat(32));
      return Response.json({settings:{zip_mappings:{'11201':'Warehouse B',' 00501 ':'Warehouse A','11201 ':'duplicate','10001-1234':'Warehouse C','bad':'invalid'}}});
    }
    return Response.json({success:true});
  }});
  await fixture.scope.IEIDAuth.connect();
  assert.equal((await fixture.handoff()).value, true);
  assert.equal(fixture.local.zipFilters, '00501, 10001-1234, 11201', 'connection must persist normalized account ZIPs without a popup');
  assert.equal(fixture.local.fetchTracking, false, 'ZIP import must preserve other settings');
  assert.equal(fixture.local.zipFilterImportStatus.type, 'success');
  fixture.local.zipFilters = '90210';
  await fixture.scope.IEIDAuth.getToken();
  assert.equal(fixture.local.zipFilters, '90210', 'ordinary token validation must preserve manual edits');
  assert.equal(fixture.calls.filter(call=>call.url.endsWith('/api/settings/monitor')).length, 1);
}

async function emptyAccountMappingsClearPreviousFilters() {
  const fixture = client({local:{zipFilters:'99999'},fetch:async url=>url.endsWith('/exchange')
    ? Response.json(grant()) : Response.json({settings:{zip_mappings:{}}})});
  await fixture.scope.IEIDAuth.connect();
  assert.equal((await fixture.handoff()).value, true);
  assert.equal(fixture.local.zipFilters, '', 'a new account with no mappings must not inherit the previous ZIP filter');
  assert.equal(fixture.local.zipFilterImportStatus.type, 'success');
}

async function zipImportFailuresDoNotBreakAuthentication() {
  for (const mode of ['unavailable','malformed','timeout']) {
    const fixture = client({local:{zipFilters:'00501'},fetch:async url=>{
      if (url.endsWith('/exchange')) return Response.json(grant());
      if (url.endsWith('/api/settings/monitor')) {
        if (mode === 'timeout') return new Promise(()=>{});
        return mode === 'unavailable' ? Response.json({}, {status:503}) : Response.json({settings:{zip_mappings:[]}});
      }
      return Response.json({success:true});
    }});
    await fixture.scope.IEIDAuth.connect();
    assert.equal((await fixture.handoff()).value, true, mode+' must not fail a completed connection');
    assert.equal(fixture.local.zipFilters, '00501', mode+' must not erase saved filters');
    assert.equal(fixture.local.zipFilterImportStatus.type, 'error');
    assert.match(fixture.local.zipFilterImportStatus.message, /import.*ZIP|ZIP.*import/i);
    assert.equal(await fixture.scope.IEIDAuth.getToken(), 'access-one', 'auth queue must still work');
  }
}

async function boundedValidationReleasesQueue() {
  let stalled = true;
  const fixture = client({local:{accountGrant:grant()},session:{accountGrant:grant()},fetch:async url=>{
    if (url.endsWith('/api/user') && stalled) return new Promise(()=>{});
    return Response.json({success:true});
  }});
  const request = fixture.scope.IEIDAuth.getToken();
  const queuedDisconnect = fixture.scope.IEIDAuth.disconnect();
  const result = await Promise.race([request.then(()=> 'resolved',()=> 'rejected'),new Promise(resolve=>setTimeout(()=>resolve('hung'),150))]);
  assert.equal(result, 'rejected', 'stalled validation must report a bounded error');
  assert.equal(fixture.calls[0].settings.signal.aborted, true);
  stalled = false;
  await queuedDisconnect;
  assert.equal(fixture.local.accountGrant, undefined, 'later disconnect must leave the shared queue');
}

async function refreshUncertaintyCannotReplay() {
  let refreshes = 0;
  const fixture = client({local:{accountGrant:grant()},session:{accountGrant:grant()},fetch:async url=>{
    if (url.endsWith('/api/user')) return Response.json({}, {status:401});
    if (url.endsWith('/refresh')) {refreshes++; return {ok:true,json:()=>new Promise(()=>{})};}
    return Response.json({success:true});
  }});
  const result = await Promise.race([fixture.scope.IEIDAuth.getToken().then(()=> 'resolved',()=> 'rejected'),new Promise(resolve=>setTimeout(()=>resolve('hung'),150))]);
  assert.equal(result, 'rejected', 'a stalled refresh body must time out');
  await assert.rejects(fixture.scope.IEIDAuth.getToken(true));
  assert.equal(refreshes, 1, 'uncertain rotating refresh must never be automatically replayed');
  await fixture.scope.IEIDAuth.disconnect();
  assert.equal(fixture.local.accountGrant, undefined, 'retain the old refresh credential for confirmed revocation');
}

async function publicVersionBypassesAuthentication() {
  const fixture = client({local:{accountGrant:grant()},session:{accountGrant:grant()},fetch:async url=>{
    if (url.endsWith('/api/user')) return Response.json({}, {status:503});
    return Response.json({version:'1.1.14'});
  }});
  const response = await fixture.scope.fetch('https://ieidgg.com/api/order-scraper/version');
  assert.equal((await response.json()).version, '1.1.14');
  assert.equal(fixture.calls.length, 1, 'public version check must not enter the auth queue');
  assert.equal(new Headers(fixture.calls[0].settings.headers).has('X-Auth-Token'), false);
}

(async()=>{
  const failures = [];
  for (const test of [durableGrant,reconnectRevokesPreviousGrant,connectionImportsAccountZipFiltersWithoutPopup,emptyAccountMappingsClearPreviousFilters,zipImportFailuresDoNotBreakAuthentication,boundedValidationReleasesQueue,refreshUncertaintyCannotReplay,publicVersionBypassesAuthentication]) {
    try {await test(); console.log(test.name+' passed');}
    catch (error) {console.error(test.name+': '+error.message); failures.push(error);}
  }
  assert.equal(failures.length, 0, 'authentication lifecycle regressions');
})().catch(error=>{console.error(error);process.exitCode=1;});
