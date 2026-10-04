const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require.resolve('../chrome_extension/popup.js'), 'utf8');
const command = source.slice(source.indexOf('async function sendScanCommand('), source.indexOf("$('startBtn').addEventListener"));
(async () => {
  let response = {error: 'An update is active.', running: false};
  const states = [], logs = [];
  const context = vm.createContext({chrome: {runtime: {sendMessage: async () => response}},
    setScrapingUi: state => states.push(state), log: (message, level) => logs.push({message, level}),
  });
  vm.runInContext(command, context);
  await context.sendScanCommand({action: 'start_scrape'});
  assert.equal(states.at(-1), false);
  assert.match(logs.at(-1).message, /update/);
  response = {error: 'An order scan is active.', running: true};
  await context.sendScanCommand({action: 'start_single_order_scrape'});
  assert.equal(states.at(-1), true, 'busy rejection must still show the actual existing scan');
  response = {ok: true, running: true};
  await context.sendScanCommand({action: 'start_scrape'});
  assert.equal(states.at(-1), true);
  console.log('Popup rejects busy admissions without pretending an update is a scan or hiding an existing scan');
})().catch(error => {console.error(error);process.exitCode=1;});
