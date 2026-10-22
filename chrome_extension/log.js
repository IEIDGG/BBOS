const $ = id => document.getElementById(id);
let autoScroll = true;
let renderedLogs = '';
let renderedRows = '';
const ORDERS_PER_PAGE = 50;
let currentOrderRows = [];
let currentOrdersPage = 1;
let viewerRevision;
let pollTimer = null;
let pollInFlight = false;
const rowNodes = new Map();
const logEl = $('log');
const importLabels = {pending:'Pending import',paused:'Resume pending',interrupted:'Interrupted',uploading:'Saving…',inserted:'Inserted',updated:'Updated',saved:'Saved to IEID',error:'Import error',partial:'Partially saved',unconfirmed:'Needs verification',skipped:'Skipped',stopped:'Stopped'};
const stageLabels = {interrupted:'Scan interrupted',upload:'Importing into IEID',complete:'Import processed',discovered:'Discovered',details:'Reading details',tracking:'Fetching tracking',ready:'Ready to import',cancelled:'Cancelled on Amazon'};

function selectView(view, updateUrl = true) {
  const selected = view === 'logs' ? 'logs' : 'orders';
  for (const name of ['orders','logs']) {
    $(name + 'Tab').setAttribute('aria-selected',String(name === selected));
    $(name + 'Tab').tabIndex = name === selected ? 0 : -1;
    $(name + 'Panel').hidden = name !== selected;
  }
  if (updateUrl) history.replaceState(null,'',`#${selected}`);
  if (selected === 'logs' && autoScroll) logEl.scrollTop = logEl.scrollHeight;
}
for (const name of ['orders','logs']) $(name+'Tab').addEventListener('click',() => selectView(name));
document.querySelector('.viewer-tabs').addEventListener('keydown',event => {
  if (!['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return;
  event.preventDefault();
  const name = event.key === 'Home' ? 'orders' : event.key === 'End' ? 'logs' : $('ordersTab').getAttribute('aria-selected') === 'true' ? 'logs' : 'orders';
  selectView(name); $(name+'Tab').focus();
});
window.addEventListener('hashchange',() => selectView(location.hash.slice(1),false));
selectView(location.hash.slice(1));
$('extensionVersion').textContent = `v${chrome.runtime.getManifest().version}`;

logEl.addEventListener('scroll',() => {
  if ($('logsPanel').hidden) return;
  autoScroll = logEl.scrollHeight - logEl.scrollTop - logEl.clientHeight < 40;
  $('scrollHint').textContent = autoScroll ? 'Auto-scroll on' : 'Auto-scroll paused';
});

function renderLogs(logs) {
  const snapshot = JSON.stringify(logs);
  if (snapshot === renderedLogs) return;
  renderedLogs = snapshot;
  const fragment = document.createDocumentFragment();
  for (const entry of logs) {
    const node = document.createElement('div');
    const level = ['success','error','info'].includes(entry.level) ? entry.level : '';
    node.className = `log-entry ${level}`;
    node.textContent = `${new Date(entry.time || Date.now()).toLocaleTimeString()} ${entry.text}`;
    fragment.append(node);
  }
  logEl.replaceChildren(fragment);
  $('logCount').textContent = `${logs.length} entries`;
  if (autoScroll) logEl.scrollTop = logEl.scrollHeight;
}

function textNode(tag, text, className = '') {
  const node = document.createElement(tag); node.textContent = text; node.className = className; return node;
}

function productThumbnail(imageUrl) {
  const frame = textNode('div', '', 'product-thumbnail');
  const placeholder = textNode('span', '▧', 'product-image-placeholder');
  placeholder.setAttribute('aria-hidden', 'true');
  frame.append(placeholder);
  let url;
  try {
    url = new URL(imageUrl);
    if (url.protocol !== 'https:' || url.username || url.password) return frame;
  } catch { return frame; }
  const img = document.createElement('img');
  img.alt = ''; // The adjacent product name already describes the item.
  img.width = 44; img.height = 44;
  img.loading = 'lazy'; img.decoding = 'async'; img.referrerPolicy = 'no-referrer';
  img.addEventListener('error', () => img.remove(), {once:true});
  img.src = url.href;
  frame.append(img);
  return frame;
}

function renderOrder(row) {
  const tr = document.createElement('tr');
  tr.dataset.orderId = row.orderId;
  const cells = Array.from({length:7},() => {const td=document.createElement('td');tr.append(td);return td;});
  const parsed = new Date(/^\d{4}-\d{2}-\d{2}$/.test(row.orderDate) ? `${row.orderDate}T12:00:00` : row.orderDate);
  cells[0].textContent = Number.isNaN(parsed.getTime()) ? 'Unknown date' : parsed.toLocaleDateString(undefined,{month:'short',day:'numeric',year:'numeric'});
  const link = textNode('a',row.orderId,'order-link');
  link.href = `https://www.amazon.com/your-orders/order-details?orderID=${encodeURIComponent(row.orderId)}`;
  link.target = '_blank'; link.rel = 'noopener noreferrer'; cells[1].append(link);
  cells[1].append(textNode('div',stageLabels[row.stage] || 'Discovered','row-detail'));
  for (const shipment of row.shipments || []) {
    const item = textNode('div','','item-line product-line');
    const copy = textNode('div','','product-copy');
    copy.append(textNode('div',shipment.productTitle || shipment.asin || 'Product details pending','product-title'));
    copy.append(textNode('div',`Qty ${shipment.quantity || 1}${shipment.status ? ' · '+shipment.status : ''}`,'row-detail'));
    item.append(productThumbnail(shipment.itemImage), copy);
    cells[2].append(item);
    const tracking = textNode('div','','item-line');
    const numbers = Array.isArray(shipment.trackingNumber) ? shipment.trackingNumber.join(', ') : shipment.trackingNumber;
    tracking.append(textNode('div',numbers || 'No tracking yet',numbers ? 'tracking-number' : 'row-detail'));
    const note = shipment.trackingNote || (shipment.cached ? 'Reused from IEID' : !numbers ? 'Waiting for details or unavailable from Amazon' : '');
    tracking.append(textNode('div',[shipment.carrier,note].filter(Boolean).join(' · '),'row-detail'));
    cells[5].append(tracking);
  }
  if (!row.shipments?.length) {cells[2].textContent = row.stage === 'cancelled' ? 'Cancelled order' : 'Waiting for product details';cells[5].textContent='—';}
  cells[3].textContent = row.total || '—'; cells[4].textContent = row.zipCode || '—';
  const status = Object.hasOwn(importLabels,row.importStatus) ? row.importStatus : 'pending';
  cells[6].append(textNode('span',importLabels[status],`import-badge ${status}`));
  cells[6].append(textNode('div',row.importMessage || 'Waiting to send to IEID','row-detail'));
  return tr;
}

function renderOrders(rows) {
  const snapshot = JSON.stringify(rows);
  if (snapshot === renderedRows) return;
  renderedRows = snapshot;
  const date = row => Number.isFinite(Date.parse(row.orderDate)) ? Date.parse(row.orderDate) : -Infinity;
  currentOrderRows = [...rows].sort((a,b)=>date(b)-date(a) || a.orderId.localeCompare(b.orderId));
  drawOrdersPage();
}

function drawOrdersPage() {
  const total = currentOrderRows.length;
  const pageCount = Math.max(1, Math.ceil(total / ORDERS_PER_PAGE));
  currentOrdersPage = Math.max(1, Math.min(currentOrdersPage, pageCount));
  const start = (currentOrdersPage - 1) * ORDERS_PER_PAGE;
  const visibleRows = currentOrderRows.slice(start, start + ORDERS_PER_PAGE);
  const ids = new Set(); const fragment = document.createDocumentFragment();
  for (const row of visibleRows) {
    ids.add(row.orderId);
    const signature = JSON.stringify(row);
    let cached = rowNodes.get(row.orderId);
    if (!cached || cached.signature !== signature) {cached={signature,node:renderOrder(row)};rowNodes.set(row.orderId,cached);}
    fragment.append(cached.node);
  }
  // Keep DOM nodes only for the visible page, even during very large scans.
  for (const id of rowNodes.keys()) if (!ids.has(id)) rowNodes.delete(id);
  $('orderRows').replaceChildren(fragment);
  $('ordersEmpty').hidden = total > 0;
  $('orderCount').textContent = total ? `${start + 1}–${start + visibleRows.length} of ${total} order${total === 1 ? '' : 's'}` : '0 orders';
  $('orderCountBadge').textContent = total;
  document.querySelectorAll('.orders-pagination').forEach(pager => {
    pager.hidden = total === 0;
    pager.querySelector('[data-page-label]').textContent = `Page ${currentOrdersPage} of ${pageCount}`;
    pager.querySelector('[data-page-action="previous"]').disabled = currentOrdersPage === 1;
    pager.querySelector('[data-page-action="next"]').disabled = currentOrdersPage === pageCount;
  });
}

document.querySelectorAll('[data-page-action]').forEach(button => {
  button.addEventListener('click', () => {
    currentOrdersPage += button.dataset.pageAction === 'next' ? 1 : -1;
    drawOrdersPage();
    const table = document.querySelector('.table-container');
    table.focus({preventScroll:true});
    table.scrollIntoView({block:'start'});
  });
});

function applyStatus(data) {
  if (!data) return;
  $('runningBadge').textContent = data.running ? 'Scanning' : data.stopped ? 'Stopped' : data.interrupted ? (data.resumePending ? 'Resume pending' : 'Interrupted') : data.statusText ? 'Finished' : 'Idle';
  $('runningBadge').classList.toggle('active',Boolean(data.running));
  const pct = Math.max(0,Math.min(100,Number(data.pct) || 0));
  $('progressFill').style.width = `${pct}%`;
  $('progressPercent').textContent = `${Math.round(pct)}%`;
  $('progressBar').setAttribute('aria-valuenow',String(pct));
  $('statusText').textContent = data.statusText || 'Waiting for a scan. Start scraping from the extension.';
  for (const [id,key] of Object.entries({statOrders:'orders',statShipments:'shipments',statTracking:'tracked',statSent:'sent',statCancelled:'cancelled',statSkipped:'skippedCached'})) $(id).textContent=data[key] || 0;
  if (Array.isArray(data.logs)) renderLogs(data.logs);
  if (Array.isArray(data.orderRows)) renderOrders(data.orderRows);
  viewerRevision = data.viewerRevision;
}

function pollStatus() {
  if (pollInFlight) return;
  pollInFlight = true;
  chrome.runtime.sendMessage({action:'scrape_status',viewerRevision},response => {
    pollInFlight = false;
    if (chrome.runtime.lastError) {
      $('connectionStatus').textContent = 'Connection to the extension was interrupted. Reload this viewer to reconnect.';
      return;
    }
    $('connectionStatus').textContent = '';
    applyStatus(response);
  });
}
chrome.runtime.onMessage.addListener(message => {
  if (['scrape_orders','scrape_log','scrape_progress','scrape_stats','scrape_done'].includes(message.type)) pollStatus();
});
window.addEventListener('pagehide',() => clearInterval(pollTimer));
window.addEventListener('pageshow',() => {clearInterval(pollTimer);pollStatus();pollTimer=setInterval(pollStatus,1000);});
pollStatus();
