const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const { parseHTML } = require('linkedom');
const popup = fs.readFileSync(require.resolve('../chrome_extension/popup.html'), 'utf8');
const source = fs.readFileSync(require.resolve('../chrome_extension/popup.js'), 'utf8');
const settings = source.slice(source.indexOf('const SETTINGS_KEYS'), source.indexOf('function saveSettings()'));
(async () => {
  for (const stored of [{}, { yearFilter: 'year-2025', maxPages: 2 }]) {
    const { document } = parseHTML(popup);
    // linkedom exposes a getter-only select.value; model the browser's setter.
    const select = document.getElementById('yearFilter');
    Object.defineProperty(select, 'value', {
      get() { return this.querySelector('option[selected]')?.value || ''; },
      set(value) { this.querySelectorAll('option').forEach(o => { if (o.value === value) o.setAttribute('selected', ''); else o.removeAttribute('selected'); }); },
    });
    const ctx = vm.createContext({ document, $: id => document.getElementById(id),
      Date: class extends Date { constructor() { super(2029, 0, 1); } },
      chrome: { storage: { local: { async get() { return stored; } } } } });
    vm.runInContext(settings, ctx);
    await ctx.loadSettings();
    const years = Array.from(document.querySelectorAll('#yearFilter option'), o => o.value);
    assert.ok(years.includes('year-2029'), 'Calendar years must remain current');
    assert.strictEqual(document.getElementById('yearFilter').value, stored.yearFilter || 'months-12');
    assert.strictEqual(document.getElementById('maxPages').value, String(stored.maxPages || 0));
    if (stored.maxPages) assert.match(document.getElementById('historyRangeHint').textContent, /Limited to 2 pages/);
  }
  console.log('popup full-year defaults, dynamic years and saved limit warning tests passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
