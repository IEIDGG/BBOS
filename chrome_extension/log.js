const $ = (id) => document.getElementById(id);

let autoScroll = true;
let renderedCount = 0;
let pollTimer = null;

const logEl = $('log');

logEl.addEventListener('scroll', () => {
  const atBottom = logEl.scrollHeight - logEl.scrollTop - logEl.clientHeight < 40;
  autoScroll = atBottom;
  $('scrollHint').textContent = autoScroll ? 'Auto-scroll on' : 'Auto-scroll off';
});

function renderLogEntry(entry) {
  const node = document.createElement('div');
  node.className = `log-entry ${entry.level || ''}`;
  const timeStr = new Date(entry.time || Date.now()).toLocaleTimeString();
  node.textContent = `${timeStr} ${entry.text}`;
  logEl.appendChild(node);
}

function appendLog(text, level, time) {
  renderLogEntry({ text, level, time });
  $('logCount').textContent = `${logEl.children.length} entries`;
  if (autoScroll) logEl.scrollTop = logEl.scrollHeight;
}

function renderLogs(logs, fromIndex = 0) {
  if (!logs?.length) return;
  for (let i = fromIndex; i < logs.length; i++) {
    renderLogEntry(logs[i]);
  }
  renderedCount = logs.length;
  $('logCount').textContent = `${logEl.children.length} entries`;
  if (autoScroll) logEl.scrollTop = logEl.scrollHeight;
}

function updateProgress(pct, text) {
  $('progressFill').style.width = `${pct || 0}%`;
  $('statusText').textContent = text || '';
}

function updateStats(data) {
  $('statOrders').textContent = data.orders || 0;
  $('statShipments').textContent = data.shipments || 0;
  $('statTracking').textContent = data.tracked || 0;
  $('statSent').textContent = data.sent || 0;
  $('statCancelled').textContent = data.cancelled || 0;
  $('statSkipped').textContent = data.skippedCached || 0;
}

function updateRunning(running) {
  const badge = $('runningBadge');
  if (running) {
    badge.textContent = 'Running';
    badge.classList.add('active');
  } else {
    badge.textContent = 'Idle';
    badge.classList.remove('active');
  }
}

function applyStatus(resp) {
  if (!resp) return;
  updateRunning(resp.running);
  updateProgress(resp.pct, resp.statusText);
  updateStats(resp);
  if (resp.logs?.length > renderedCount) {
    renderLogs(resp.logs, renderedCount);
  }
}

function stopPoll() {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

function startPoll() {
  if (pollTimer) return;
  pollTimer = setInterval(pollStatus, 500);
}

chrome.runtime.onMessage.addListener((msg) => {
  if (msg.type === 'scrape_log') {
    appendLog(msg.text, msg.level || '');
    startPoll();
  }
  if (msg.type === 'scrape_progress') {
    updateProgress(msg.pct, msg.text);
    startPoll();
  }
  if (msg.type === 'scrape_stats') updateStats(msg);
  if (msg.type === 'scrape_done') {
    updateRunning(false);
    stopPoll();
  }
});

function pollStatus() {
  chrome.runtime.sendMessage({ action: 'scrape_status' }, (resp) => {
    if (chrome.runtime.lastError) {
      console.info('[IEID log] worker unavailable', chrome.runtime.lastError.message);
      stopPoll();
      return;
    }
    applyStatus(resp);
    if (resp?.running) startPoll();
    else stopPoll();
  });
}

window.addEventListener('pagehide', stopPoll);
pollStatus();
