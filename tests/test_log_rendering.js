const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const { parseHTML } = require('linkedom');
const { document } = parseHTML(fs.readFileSync(require.resolve('../chrome_extension/log.html'), 'utf8'));
let listener;
const ctx = vm.createContext({ document, Date, console, setInterval: () => 1, clearInterval() {}, window: { addEventListener() {} },
  chrome: { runtime: { onMessage: { addListener(fn) { listener = fn; } }, sendMessage() {} } } });
vm.runInContext(fs.readFileSync(require.resolve('../chrome_extension/log.js'), 'utf8'), ctx);
const entry = { text: 'Scraping page 1', time: 1000, level: 'info' };
listener({ type: 'scrape_log', ...entry });
ctx.applyStatus({ logs: [entry] });
assert.strictEqual(document.getElementById('log').children.length, 1, 'Live event and status snapshot render once');
ctx.applyStatus({ logs: [{ ...entry, text: 'Next page' }] });
assert.ok(document.getElementById('log').textContent.includes('Next page'), 'Same-size rolling log updates');
ctx.applyStatus({ logs: [] });
assert.strictEqual(document.getElementById('log').children.length, 0, 'New scan clears old entries');
console.log('log snapshot rendering tests passed');
