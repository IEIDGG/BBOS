const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
(async () => {
const extensionId = 'a'.repeat(32);
const extensionUrl = 'chrome-extension://'+extensionId+'/';
const state = 's'.repeat(43);
const pageUrl = 'https://ieidgg.com/extension-connect?extension_id='+extensionId+'&state='+state;
const message = {type:'ieid-extension-handoff',extension_id:extensionId,state,code:'c'.repeat(43),action:'start_scrape',config:{year:'2026'}};
let pageListener;
const forwarded = [];
const window = {addEventListener:(_type,callback)=>{pageListener=callback;}};
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../chrome_extension/auth_bridge.js'),'utf8'),{
  window,location:new URL(pageUrl),URLSearchParams,chrome:{runtime:{id:extensionId,sendMessage:async value=>{forwarded.push(value);}}},
});
pageListener({source:window,origin:'https://ieidgg.com',data:message});
assert.deepEqual(JSON.parse(JSON.stringify(forwarded)), [{type:'ieid-extension-handoff',extension_id:extensionId,state,code:'c'.repeat(43)}], 'bridge must discard every non-handoff field');

let workerListener;
let scrapes = 0;
let popups = 0;
const stateData = {running:false,stopped:false};
const saved = {};
const writes = [];
const workerSource = fs.readFileSync(path.join(__dirname,'../chrome_extension/background.js'),'utf8');
vm.runInNewContext(workerSource.slice(workerSource.indexOf('// Message handler')),{
  URL,console,scrapeState:stateData,runScrape:async (_config,_checkpoint,started)=>{scrapes++;started();},runSingleOrderScrape:async (_config,started)=>{scrapes++;started();},log:()=>{},scrapeLogsReady:Promise.resolve(),scrapeLogs:[],
  chrome:{runtime:{id:extensionId,getURL:value=>extensionUrl+value,onMessage:{addListener:callback=>{workerListener=callback;}}},
    action:{openPopup:async()=>{popups++;}},storage:{local:{set:value=>new Promise((resolve,reject)=>writes.push({commit:()=>{Object.assign(saved,value);resolve();},reject}))}}},
});
const respond = ()=>{};
workerListener(message,{id:extensionId,url:pageUrl},respond);
workerListener({action:'start_scrape'},{id:extensionId,url:pageUrl},respond);
workerListener({action:'stop_scrape'},{id:extensionId,url:pageUrl},respond);
assert.equal(scrapes, 0, 'web content cannot start extraction');
assert.equal(stateData.stopped, false, 'web content cannot stop extraction');
workerListener({action:'start_scrape'},{id:extensionId,url:extensionUrl+'popup.html'},respond);
assert.equal(scrapes, 1, 'trusted extension controls still work');
const amazonSender = {id:extensionId,url:'https://www.amazon.com/your-orders/order-details?orderID=114-1234567-1234567',frameId:0};
const prepared = new Promise(resolve=>workerListener({action:'prepare_single_order_scan',orderId:'114-1234567-1234567'},amazonSender,resolve));
assert.equal(popups, 0, 'popup must wait until selected order is durably saved');
writes.shift().commit();
assert.equal((await prepared).ok, true);
assert.equal(saved.pendingSingleOrderId, '114-1234567-1234567');
assert.equal(popups, 1, 'Amazon order-page button still opens the extension');
workerListener({action:'prepare_single_order_scan',orderId:'other'},{id:extensionId,url:pageUrl},respond);
assert.equal(saved.pendingSingleOrderId, '114-1234567-1234567', 'other web pages cannot change the pending order');
const failed = new Promise(resolve=>workerListener({action:'prepare_single_order_scan',orderId:'114-7654321-7654321'},amazonSender,resolve));
writes.shift().reject(new Error('quota failure'));
assert.ok((await failed).error, 'failed storage must report an error');
assert.equal(popups, 1, 'failed storage must not open a popup with the previous order');
console.log('Extension message boundary tests passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
