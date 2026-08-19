const assert = require('assert');
const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');

const root = path.join(__dirname, '..', 'chrome_extension');
const core = require(path.join(root, 'scrape_core.js'));
const manifestPath = path.join(root, 'manifest.json');
const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));

assert.strictEqual(manifest.name, 'IEID Order Scraper');
assert.strictEqual(typeof manifest.version, 'string');
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

const jsFiles = Object.keys(files).filter((rel) => rel.endsWith('.js'));
for (const rel of jsFiles) {
  execFileSync('node', ['--check', path.join(root, rel)], { stdio: 'pipe' });
}

console.log(`package integrity passed (${jsFiles.length} js files, v${manifest.version})`);
