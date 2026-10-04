const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const { execFileSync } = require('child_process');

const root = path.join(__dirname, '..', 'chrome_extension');
const core = require(path.join(root, 'scrape_core.js'));
const manifestPath = path.join(root, 'manifest.json');
const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));

assert.strictEqual(manifest.name, 'IEID Order Scraper');
assert.strictEqual(typeof manifest.version, 'string');
assert.ok(Number(manifest.minimum_chrome_version?.split('.')[0]) >= 140, 'Durable credentials require trusted local-storage access, introduced in Chrome 140');
assert.ok(!manifest.permissions.includes('activeTab'));

function collectFiles(dir, prefix, files) {
  for (const name of fs.readdirSync(dir)) {
    if (name === '.DS_Store') continue;
    const full = path.join(dir, name);
    const rel = prefix ? `${prefix}/${name}` : name;
    if (fs.statSync(full).isDirectory()) {
      collectFiles(full, rel, files);
      continue;
    }
    files[rel] = { encoding: 'utf-8', content: fs.readFileSync(full, 'utf8') };
  }
}

const files = {};
collectFiles(root, '', files);
const validated = core.validatePackagePayload({ version: manifest.version, files });
assert.strictEqual(validated.version, manifest.version);
const restrictedFiles = {...files, 'manifest.json': {encoding:'utf-8', content:JSON.stringify({...manifest, minimum_chrome_version:'140'})}};
const restrictedPackage = {version:manifest.version, files:restrictedFiles};
assert.throws(() => core.validatePackagePayload(restrictedPackage, '139.0.7258.66'), /Update Chrome to 140 or newer/, 'Reject an incompatible update before its files can be written');
assert.strictEqual(core.validatePackagePayload(restrictedPackage, '140.0.7339.16').version, manifest.version);
assert.strictEqual(core.validatePackagePayload(restrictedPackage, '145.0.7632.6').version, manifest.version);
const futureFiles = {...restrictedFiles, 'manifest.json': {encoding:'utf-8', content:JSON.stringify({...manifest, minimum_chrome_version:'140.0.7339.20'})}};
assert.throws(() => core.validatePackagePayload({version:manifest.version, files:futureFiles}, '140.0.7339.16'), /Update Chrome to 140\.0\.7339\.20 or newer/);
const missingHistory = { ...files };
delete missingHistory['order_history.js'];
assert.throws(() => core.validatePackagePayload({ version: manifest.version, files: missingHistory }), /missing required files: order_history\.js/, 'Reject packages that would break the background history import');
const missingListParser = { ...files };
delete missingListParser['scraper.js'];
assert.throws(() => core.validatePackagePayload({ version: manifest.version, files: missingListParser }), /missing required files: scraper\.js/, 'Reject packages that would break the offscreen list parser');

const jsFiles = Object.keys(files).filter((rel) => rel.endsWith('.js'));
for (const rel of jsFiles) {
  execFileSync('node', ['--check', path.join(root, rel)], { stdio: 'pipe' });
}

async function verifyIncompatibleRecovery() {
  let sideEffects = 0;
  const payload = {version:manifest.version, files:{...files, 'manifest.json':{encoding:'utf-8', content:JSON.stringify({...manifest, minimum_chrome_version:'146'})}}};
  const context = {
    navigator:{userAgent:'Mozilla/5.0 Chrome/145.0.0.0 Safari/537.36'},
    document:{addEventListener:()=>{}},
    chrome:{runtime:{getManifest:()=>{sideEffects++;return manifest;}}},
  };
  const apply = vm.runInNewContext(fs.readFileSync(path.join(root,'scrape_core.js'),'utf8')+'\n'+fs.readFileSync(path.join(root,'update.js'),'utf8')+'\napplyPackage;', context);
  await assert.rejects(apply({}, payload), /Update Chrome to 146 or newer/, 'Recovered updates must also reject an incompatible package before touching the installed extension');
  assert.strictEqual(sideEffects, 0);
}
verifyIncompatibleRecovery().then(() => console.log(`package integrity passed (${jsFiles.length} js files, v${manifest.version})`)).catch(error => {console.error(error);process.exitCode=1;});
