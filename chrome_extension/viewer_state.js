// Small, display-only projections. Credentials and Amazon page HTML never enter the viewer.
class ViewerOrders {
  constructor() { this.rows = new Map(); }

  reset() { this.rows.clear(); }

  restore(rows) {
    this.rows = new Map((Array.isArray(rows) ? rows : []).filter(row => row?.orderId).map(row => [row.orderId, row]));
  }

  upsert(orders, stage = 'discovered') {
    for (const order of orders) {
      if (!order.orderId) continue;
      const previous = this.rows.get(order.orderId) || {importStatus:'pending', importMessage:'Waiting to send to IEID'};
      if (['paused','interrupted'].includes(previous.importStatus)) Object.assign(previous, {importStatus:'pending', importMessage:'Waiting to send to IEID'});
      this.rows.set(order.orderId, {
        ...previous,
        orderId: order.orderId,
        orderDate: order.orderDate || previous.orderDate || '',
        total: order.total || previous.total || '',
        zipCode: order.zipCode || previous.zipCode || '',
        stage,
        shipments: (order.shipments || []).map(s => ({
          productTitle: s.productTitle || '', asin:s.asin || '', quantity:s.quantity || 1,
          itemImage: s.itemImage || previous.shipments?.find(item =>
            s.asin ? item.asin === s.asin : s.productTitle && item.productTitle === s.productTitle)?.itemImage || '',
          unitPrice:s.unitPrice || '', status:s.status || '', carrier:s.carrier || '',
          trackingNumber:s.trackingNumber || '', trackingNote:s.viewerTrackingNote || '',
          cached:Boolean(s.skipTrackingFetch),
        })),
      });
    }
  }

  setStatus(orderId, importStatus, importMessage) {
    const row = this.rows.get(orderId);
    if (row) Object.assign(row, {importStatus, importMessage});
  }

  beginUpload(payload) {
    const counts = new Map();
    for (const row of payload) counts.set(row.order_id, (counts.get(row.order_id) || 0) + 1);
    for (const [id, total] of counts) {
      const row = this.rows.get(id);
      if (!row) continue;
      delete row.importError;
      row.stage = 'upload';
      row.receipt = {total, processed:0, saved:0, failed:0, unknown:0, inserted:0, updated:0};
      this.setStatus(id, 'uploading', `Sending ${total} item${total === 1 ? '' : 's'} to IEID`);
    }
  }

  applyUploadResult(batch, result, error = '') {
    const counts = new Map();
    for (const row of batch) counts.set(row.order_id, (counts.get(row.order_id) || 0) + 1);
    const valid = result?.success !== false && ['inserted','updated','failed'].every(key => Number.isInteger(result?.[key]) && result[key] >= 0)
      && result.inserted + result.updated + result.failed === batch.length;
    const errors = Array.isArray(result?.errors) ? result.errors : [];
    const errorCounts = new Map();
    for (const entry of errors) errorCounts.set(entry.order_id, (errorCounts.get(entry.order_id) || 0) + 1);
    // The API caps error details. Never infer success for unidentified failures.
    const completeErrors = valid && errors.length === result.failed
      && [...errorCounts].every(([id,n]) => counts.has(id) && n <= counts.get(id));
    const onlyOrder = counts.size === 1;
    for (const [id, count] of counts) {
      const row = this.rows.get(id);
      if (!row?.receipt) continue;
      const receipt = row.receipt;
      receipt.processed += count;
      const knownFailed = Math.min(count, errorCounts.get(id) || 0);
      const failed = error ? count : valid && onlyOrder ? result.failed : knownFailed;
      const saved = error ? 0 : valid && (completeErrors || onlyOrder) ? count - failed : 0;
      receipt.failed += failed;
      receipt.saved += saved;
      receipt.unknown += count - failed - saved;
      if (valid && (onlyOrder || result.inserted === batch.length)) receipt.inserted += onlyOrder ? result.inserted : count;
      if (valid && (onlyOrder || result.updated === batch.length)) receipt.updated += onlyOrder ? result.updated : count;
      if (receipt.processed >= receipt.total) row.stage = 'complete';
      const messages = errors.filter(e => e.order_id === id).map(e => e.message || 'Import failed');
      if (error || messages.length) row.importError = error || [...new Set(messages)].join('; ');
      if (receipt.failed) {
        this.setStatus(id, receipt.saved ? 'partial' : 'error', row.importError || `${receipt.failed} item(s) failed to save to IEID`);
      } else if (receipt.unknown) {
        this.setStatus(id, 'unconfirmed', 'IEID did not identify the result for every item. Check the website before retrying.');
      } else if (receipt.processed < receipt.total) {
        this.setStatus(id, 'uploading', `${receipt.saved}/${receipt.total} items saved to IEID`);
      } else {
        const status = receipt.inserted === receipt.total ? 'inserted' : receipt.updated === receipt.total ? 'updated' : 'saved';
        this.setStatus(id, status, `${receipt.saved}/${receipt.total} items saved to IEID`);
      }
    }
    return Boolean(valid && (completeErrors || onlyOrder));
  }

  interrupt(resumable) {
    for (const row of this.rows.values()) {
      if (row.importStatus === 'uploading') {
        this.setStatus(row.orderId, 'unconfirmed', 'The scan was interrupted during import. IEID may have received these items; check the website.');
        row.stage = 'interrupted';
      } else if (row.importStatus === 'pending') {
        this.setStatus(row.orderId, resumable ? 'paused' : 'interrupted', resumable ? 'Waiting for the saved scan to resume' : 'Scan interrupted before import; start a new scan to retry');
        row.stage = 'interrupted';
      }
    }
  }

  finish(status, message) {
    for (const row of this.rows.values()) {
      if (['pending','uploading'].includes(row.importStatus)) this.setStatus(row.orderId, status, message);
    }
  }

  snapshot() {
    const date = row => Number.isFinite(Date.parse(row.orderDate)) ? Date.parse(row.orderDate) : -Infinity;
    return [...this.rows.values()].sort((a,b) => date(b) - date(a) || a.orderId.localeCompare(b.orderId));
  }
}

if (typeof module !== 'undefined' && module.exports) module.exports = {ViewerOrders};
