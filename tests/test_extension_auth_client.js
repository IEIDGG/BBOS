const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {webcrypto} = require('node:crypto');

async function main() {
  let listener;
  let refreshes = 0;
  let live = false;
  let logoutStatus = 200;
  let logoutSuccess = true;
  const calls = [];
  const data = {accountGrant:{access_token:'old-extension-access', refresh_token:'independent-extension-refresh', expires_at:new Date(Date.now()+86400000).toISOString()}};
  const storage = {
    async get(key) {return {[key]:data[key]};},
    async set(value) {Object.assign(data,value);},
    async remove(keys) {for (const key of Array.isArray(keys)?keys:[keys]) delete data[key];}
  };
  const chrome = {storage:{session:storage}, runtime:{id:'a'.repeat(32), getURL:p=>'chrome-extension://'+'a'.repeat(32)+'/'+p, onMessage:{addListener:l=>listener=l}},tabs:{create:async tab=>{calls.push(tab);}}};
  async function fetch(url, options) {
    calls.push({url,options});
    assert.equal(options.credentials,'omit');
    assert.equal(new Headers(options.headers).get('X-Extension-Origin'),'chrome-extension://'+'a'.repeat(32));
    if (url.endsWith('/api/user')) return new Response('{}',{status:live?200:401});
    if (url.endsWith('/logout')) {return Response.json({success:logoutSuccess},{status:logoutStatus});}
    if (url.endsWith('/refresh')) {refreshes++; live=true; return Response.json({...data.accountGrant, access_token:'new-extension-access'});}
    if (url.endsWith('/exchange')) {live=true; return Response.json({access_token:'handoff-access', refresh_token:'handoff-refresh',expires_at:new Date(Date.now()+86400000).toISOString()});}
    return Response.json({success:true});
  }
  const scope = {chrome,fetch,crypto:webcrypto,TextEncoder,Uint8Array,URL,URLSearchParams,Date,Promise,Headers,Response,btoa,console};
  scope.globalThis=scope;
  vm.runInNewContext(fs.readFileSync(require('node:path').join(__dirname,'../chrome_extension/auth_client.js'),'utf8'),scope);
  const results = await Promise.all([scope.IEIDAuth.getToken(true),scope.IEIDAuth.getToken(true)]);
  assert.deepEqual(results,['new-extension-access','new-extension-access']);
  assert.equal(refreshes,1,'all contexts share a single refresh lineage');
  await scope.IEIDAuth.connect();
  const opened = new URL(calls.find(c=>c.url?.startsWith('https://ieidgg.com/extension-connect?')).url);
  assert.equal(opened.searchParams.get('extension_id'),chrome.runtime.id);
  assert.equal(opened.searchParams.has('token'),false);
  assert.equal(opened.searchParams.has('verifier'),false);
  const send = (value,sender) => new Promise(resolve => listener(value,sender,resolve));
  const message = {type:'ieid-extension-handoff',extension_id:chrome.runtime.id,state:data.accountHandoff.state,code:'c'.repeat(43)};
  const wrong = await send(message,{id:chrome.runtime.id,url:'https://evil.example/extension-connect'});
  assert.ok(wrong.error);
  assert.ok(data.accountHandoff,'wrong origin must not claim handoff');
  const good = await send(message,{id:chrome.runtime.id,url:opened.href});
  assert.equal(good.value,true);
  assert.equal(data.accountGrant.access_token,'handoff-access');
  assert.equal(data.accountHandoff,undefined);
  const duplicate = await send(message,{id:chrome.runtime.id,url:opened.href});
  assert.ok(duplicate.error);
  for (const name of ['background','popup','update']) {
    const source = fs.readFileSync(require('node:path').join(__dirname,`../chrome_extension/${name}.js`),'utf8');
    assert.equal(source.includes('chrome.cookies'),false,name+' cannot copy browser credentials');
    assert.ok(source.includes('IEIDAuth.getToken'),name+' uses maintained shared session client');
  }
  live = false; // Stored access expired: logout must use independent refresh credential.
  logoutStatus = 503;
  await assert.rejects(scope.IEIDAuth.disconnect(), /disconnect|unavailable|sign out/i);
  assert.ok(data.accountGrant, 'failed server revocation retains the credential for retry');
  logoutStatus = 200; logoutSuccess = false;
  await assert.rejects(scope.IEIDAuth.disconnect());
  assert.ok(data.accountGrant);
  logoutSuccess = true;
  await Promise.all([scope.IEIDAuth.disconnect(), scope.IEIDAuth.disconnect()]);
  assert.equal(data.accountGrant, undefined);
  const logoutCall = calls.filter(c=>c.url?.endsWith('/logout')).at(-1);
  assert.equal(new Headers(logoutCall.options.headers).has('X-Auth-Token'), false);
  assert.equal(JSON.parse(logoutCall.options.body).refresh_token, 'handoff-refresh');
  assert.equal(calls.filter(c=>c.url?.endsWith('/logout')).length, 3, 'serialized disconnect sends one successful revocation');
  const popupSource = fs.readFileSync(require('node:path').join(__dirname,'../chrome_extension/popup.js'),'utf8');
  const elements = new Map();
  const element = id => {
    if (!elements.has(id)) elements.set(id, {textContent:'',disabled:false,style:{},listeners:{},classList:{add(){},remove(){}},addEventListener(type, fn){this.listeners[type]=fn;}});
    return elements.get(id);
  };
  const popupScope = {$:element, API_BASE:'https://ieidgg.com', IEIDAuth:{disconnect:async()=>{throw new Error('outage');}}, fetch, setInterval, clearInterval, setTimeout};
  vm.runInNewContext(popupSource.slice(popupSource.indexOf('// --- Auth ---'),popupSource.indexOf('// --- Settings ---')),popupScope);
  await element('signOutBtn').listeners.click();
  assert.match(element('authStatus').textContent,/sign out.*try again/i);
  assert.equal(element('signOutBtn').disabled,false);
  popupScope.IEIDAuth.disconnect=async()=>{};
  await element('signOutBtn').listeners.click();
  assert.equal(element('authStatus').textContent,'');
  assert.equal(element('scrapeSection').style.display,'none');
  console.log('Extension auth client: serialized refresh, exact sender/state/PKCE handoff, all three clients passed');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
