const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const root=path.resolve(__dirname,'../chrome_extension');

function worker(initialSession={}, initialLocal={}) {
  const local=structuredClone(initialLocal), session=structuredClone(initialSession), listeners=[], sent=[], requests=[];
  const storage=data=>({get:async keys=>typeof keys==='string'?{[keys]:data[keys]}:{...data},set:async values=>Object.assign(data,structuredClone(values)),remove:async keys=>{for(const key of Array.isArray(keys)?keys:[keys]) delete data[key];}});
  const noop=()=>{};
  const context={console:{...console,info:()=>{}}, URL,URLSearchParams,setTimeout,clearTimeout,Map,Set,Date,Promise,IEIDAuth:{getToken:async()=> 'fixture'},
    fetch:async(url,opts)=>{requests.push({url,opts});return {ok:true,status:200,json:async()=>({version:'1.1.20'})};},
    chrome:{storage:{local:storage(local),session:storage(session)},runtime:{id:'fixture',getURL:p=>'chrome-extension://fixture/'+p,getManifest:()=>({version:'1.1.20'}),sendMessage:async msg=>{sent.push(structuredClone(msg));},onMessage:{addListener:fn=>listeners.push(fn)},onInstalled:{addListener:noop},onStartup:{addListener:noop}},
      alarms:{get:async()=>({}),create:noop,clear:noop,onAlarm:{addListener:noop}},action:{setBadgeText:async()=>{}},tabs:{query:async()=>[],create:async()=>({id:10,windowId:1}),onRemoved:{addListener:noop}},windows:{update:async()=>{}}}};
  vm.createContext(context);
  context.importScripts=(...files)=>files.filter(f=>f!=='auth_client.js').forEach(f=>vm.runInContext(fs.readFileSync(path.join(root,f),'utf8'),context,{filename:f}));
  vm.runInContext(fs.readFileSync(path.join(root,'background.js'),'utf8'),context,{filename:'background.js'});
  // IndexedDB locks are unrelated to the worker/viewer contract being exercised.
  vm.runInContext('withExtensionOperation = async (_kind, work) => work(); maybeAutoApplyUpdate = async () => {};',context);
  const run=code=>vm.runInContext(code,context);
  const message=msg=>new Promise(resolve=>listeners.at(-1)(msg,{id:'fixture',url:'chrome-extension://fixture/popup.html'},resolve));
  return {context,local,session,sent,requests,run,message};
}
const data={orderId:'111-0000000-0000001',orderDate:'2026-10-20',total:'$10.00',zipCode:'10001',shippingAddress:'New York, NY 10001',shipments:[{asin:'B000000001',quantity:1,unitPrice:'10.00',productTitle:'Cable',trackingNumber:'',status:'Shipped'}]};

test('scan admission reports running while session state is being restored',async()=>{
  const w=worker();
  w.context.detectAmazonAccountEmail=async()=> 'fixture@example.com';
  let finishDetails;
  w.context.readOrderDetail=()=>new Promise(r=>finishDetails=r);
  const admitted=await w.message({action:'start_single_order_scrape',config:{orderId:data.orderId}});
  assert.equal(admitted.ok,true);assert.equal(admitted.running,true);
  await new Promise(r=>setImmediate(r));
  finishDetails({orders:[],cancelledOrders:[],issue:'Fixture completion'});
  await new Promise(r=>setTimeout(r,10));
});

test('tracking, real upload payload, receipt status and session restoration flow through scrape_status',async()=>{
  const w=worker(); await w.run('viewerReady');
  w.context.fixture=structuredClone(data);
  w.run('updateViewerOrders([fixture]); applyTrackingResult(fixture,fixture.shipments[0],0,{trackingId:"TBA123",carrier:"Amazon"});');
  w.context.apiPost=async(url,body)=>{
    assert.equal(url,'/api/orders/amazon/scrape');
    assert.equal(body.orders[0].tracking_number,'TBA123');
    assert.equal(body.orders[0].order_id,data.orderId);
    return {success:true,inserted:1,updated:0,failed:0,errors:[]};
  };
  await w.run('uploadOrdersToApi([fixture],"fixture@example.com")');
  const status=await w.message({action:'scrape_status'});
  assert.equal(status.orderRows[0].importStatus,'inserted');
  assert.equal(status.orderRows[0].shipments[0].trackingNumber,'TBA123');
  const unchanged=await w.message({action:'scrape_status',viewerRevision:status.viewerRevision});
  assert.equal(unchanged.orderRows,undefined);
  await w.run('saveViewerSnapshot()');
  const restored=worker(w.session);
  const state=await restored.message({action:'scrape_status'});
  assert.equal(state.orderRows[0].importStatus,'inserted');
  assert.equal(state.sent,1);
});

test('unconfirmed receipts do not report a successful scrape',async()=>{
  const w=worker();await w.run('viewerReady');w.context.fixture=structuredClone(data);
  w.context.apiPost=async()=>({success:true});
  await w.run('uploadOrdersToApi([fixture],"fixture@example.com")');
  assert.equal((await w.message({action:'scrape_status'})).orderRows[0].importStatus,'unconfirmed');
  assert.equal(w.run('scrapeOutcomeSuccess(scrapeState)'),false);
});

test('cancelled orders show update, skip, and server failure results accurately',async()=>{
  const w=worker();await w.run('viewerReady');
  w.context.cancelled=[{orderId:'a'},{orderId:'b'},{orderId:'c'}];w.run('updateViewerOrders(cancelled,"cancelled")');
  w.context.apiGet=async()=>({orders:[{order_id:'a',id:1},{order_id:'c',id:2}]});
  w.context.authorizedFetch=async url=>{if(url.endsWith('/2'))throw Error('Server unavailable');return {success:true};};
  await w.run('uploadCancelledOrdersToApi(cancelled)');
  const rows=Object.fromEntries((await w.message({action:'scrape_status'})).orderRows.map(r=>[r.orderId,r.importStatus]));
  assert.deepEqual(rows,{a:'updated',b:'skipped',c:'error'});
});

test('worker restoration marks in-flight uploads unconfirmed and unsent orders interrupted',async()=>{
  const w=worker({liveViewerSnapshot:{revision:5,state:{running:true,statusText:'Sending to API...',orders:3},rows:[
    {orderId:'a',importStatus:'uploading',shipments:[]},
    {orderId:'b',importStatus:'pending',shipments:[]},
    {orderId:'c',importStatus:'inserted',shipments:[]}
  ]}});
  const state=await w.message({action:'scrape_status'});
  assert.equal(state.running,false);assert.equal(state.interrupted,true);
  assert.match(state.statusText,/interrupted/i);
  assert.equal(state.orderRows.find(r=>r.orderId==='a').importStatus,'unconfirmed');
  assert.equal(state.orderRows.find(r=>r.orderId==='b').importStatus,'interrupted');
  assert.equal(state.orderRows.find(r=>r.orderId==='c').importStatus,'inserted');
});

test('bulk checkpoint restoration distinguishes resume-pending orders from lost uploads',async()=>{
  const w=worker({liveViewerSnapshot:{revision:1,state:{running:true},rows:[{orderId:'a',importStatus:'pending',shipments:[]}]}}, {'scrapeJobCheckpoint:v2':{incomplete:true,kind:'bulk',config:{}}});
  const state=await w.message({action:'scrape_status'});
  assert.equal(state.resumePending,true);
  assert.equal(state.orderRows[0].importStatus,'paused');
  w.context.fixture=structuredClone(data);w.run('updateViewerOrders([fixture])');
  assert.equal((await w.message({action:'scrape_status'})).orderRows.find(r=>r.orderId===data.orderId).importStatus,'pending');
});
