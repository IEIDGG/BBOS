function isVersionNewer(latest, current) {
  const parse = (version) => String(version || '0').replace(/^v/, '').split('.').map((part) => parseInt(part, 10) || 0);
  const latestParts = parse(latest);
  const currentParts = parse(current);
  const length = Math.max(latestParts.length, currentParts.length);
  for (let index = 0; index < length; index += 1) {
    const latestValue = latestParts[index] || 0;
    const currentValue = currentParts[index] || 0;
    if (latestValue > currentValue) return true;
    if (latestValue < currentValue) return false;
  }
  return false;
}

function isSafeRelativePath(relative) {
  if (!relative || relative.startsWith('/') || relative.includes('\\')) return false;
  const parts = relative.split('/');
  return parts.every((part) => part && part !== '.' && part !== '..');
}

function isIeidExtensionManifest(manifest) {
  return Boolean(manifest && manifest.name === 'IEID Order Scraper');
}
