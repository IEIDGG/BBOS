const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const root = path.resolve(__dirname, '../chrome_extension');

function model() {
  const file = path.join(root, 'viewer_state.js');
  assert.ok(fs.existsSync(file), 'live order state is available');
  return new (require(file).ViewerOrders)();
}
const order = (orderId, orderDate = '2026-10-20') => ({orderId, orderDate, total: '$12.00', zipCode: '10001', shipments: [{productTitle: 'Cable', asin: 'B000000001', quantity: 2}]});

test('rows sort newest first, put unknown dates last, and enrich in place', () => {
  const m = model();
  m.upsert([order('old', 'October 3, 2025'), order('unknown', ''), order('new')]);
  const fresh = order('old', 'October 3, 2025');
  fresh.shipments[0].trackingNumber = 'TBA123';
  fresh.shipments[0].carrier = 'Amazon';
  m.upsert([fresh], 'tracking');
  const rows = m.snapshot();
  assert.deepEqual(rows.map(r => r.orderId), ['new', 'old', 'unknown']);
  assert.equal(rows[1].shipments[0].trackingNumber, 'TBA123');
  assert.equal(rows[1].stage, 'tracking');
});

test('an order spanning upload batches becomes saved only after all its products succeed', () => {
  const m = model(); m.upsert([order('a')]);
  const payload = [{order_id:'a', asin:'ONE'}, {order_id:'a', asin:'TWO'}];
  m.beginUpload(payload);
  m.applyUploadResult(payload.slice(0,1), {success:true, inserted:1, updated:0, failed:0, errors:[]});
  assert.equal(m.snapshot()[0].importStatus, 'uploading');
  m.applyUploadResult(payload.slice(1), {success:true, inserted:0, updated:1, failed:0, errors:[]});
  assert.equal(m.snapshot()[0].importStatus, 'saved');
  m.upsert([order('a')], 'tracking');
  assert.equal(m.snapshot()[0].importStatus, 'saved');
});

test('identified API errors stay on the correct order while other orders are saved', () => {
  const m = model(); m.upsert([order('a'),order('b')]);
  const payload = [{order_id:'a'}, {order_id:'b'}]; m.beginUpload(payload);
  m.applyUploadResult(payload, {success:true, inserted:1, updated:0, failed:1, errors:[{order_id:'b',message:'Invalid item'}]});
  const rows = Object.fromEntries(m.snapshot().map(r=>[r.orderId,r]));
  assert.equal(rows.a.importStatus,'saved');
  assert.equal(rows.b.importStatus,'error');
  assert.match(rows.b.importMessage,/Invalid item/);
});

test('truncated errors and malformed receipts never falsely claim an order was saved', () => {
  for (const result of [{success:true,inserted:0,updated:0,failed:2,errors:[{order_id:'a',message:'Bad row'}]}, {success:true}]) {
    const m = model(); m.upsert([order('a'),order('b')]);
    const payload=[{order_id:'a'},{order_id:'b'}]; m.beginUpload(payload); m.applyUploadResult(payload,result);
    assert.equal(m.snapshot().find(r=>r.orderId==='b').importStatus,'unconfirmed');
  }
});

test('network failure, stop, and session restore retain honest per-order outcomes', () => {
  const m=model(); m.upsert([order('a'),order('b')]); m.beginUpload([{order_id:'a'}]);
  m.applyUploadResult([{order_id:'a'}],null,'Network unavailable');
  m.finish('stopped','Stopped by user');
  assert.equal(m.snapshot().find(r=>r.orderId==='a').importStatus,'error');
  assert.equal(m.snapshot().find(r=>r.orderId==='b').importStatus,'stopped');
  const restored=model(); restored.restore(JSON.parse(JSON.stringify(m.snapshot())));
  assert.deepEqual(restored.snapshot(),m.snapshot());
});

test('View Log focuses an existing viewer window and selects Logs', async () => {
  const source=fs.readFileSync(path.join(root,'background.js'),'utf8');
  const fn=source.slice(source.indexOf('async function openLogTab('),source.indexOf('async function getAuthCookie('));
  let update, focus;
  const context={viewerOpenChain:Promise.resolve(),LOG_PAGE:'log.html',logTabId:12,console,chrome:{runtime:{getURL:p=>'chrome-extension://ieid/'+p},tabs:{get:async()=>({id:12,windowId:4,url:'chrome-extension://ieid/log.html#orders'}),query:async()=>[],update:async(id,opts)=>{update={id,...opts}; return {id,windowId:4};},create:async()=>{throw Error('duplicate viewer');}},windows:{update:async(id,opts)=>{focus={id,...opts};}}}};
  vm.createContext(context); vm.runInContext(fn,context);
  await context.openLogTab({active:true,view:'logs'});
  assert.equal(update.active,true);
  assert.equal(update.url,'chrome-extension://ieid/log.html#logs');
  assert.deepEqual(focus,{id:4,focused:true});
});


test('product images survive live enrichment and session restoration', () => {
  const m = model();
  const initial = order('image-order');
  initial.shipments[0].itemImage = 'https://m.media-amazon.com/images/I/cable.jpg';
  m.upsert([initial]);
  assert.equal(m.snapshot()[0].shipments[0].itemImage, 'https://m.media-amazon.com/images/I/cable.jpg');
  const detail = order('image-order');
  detail.shipments[0].trackingNumber = 'TBA123';
  m.upsert([detail], 'tracking');
  assert.equal(m.snapshot()[0].shipments[0].itemImage, 'https://m.media-amazon.com/images/I/cable.jpg');
  const restored = model(); restored.restore(JSON.parse(JSON.stringify(m.snapshot())));
  assert.equal(restored.snapshot()[0].shipments[0].itemImage, 'https://m.media-amazon.com/images/I/cable.jpg');
});
