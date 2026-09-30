// This document only parses HTML. Never attach fetched nodes to its live DOM.
globalThis.IEID_PARSE_ONLY = true;
chrome.runtime.onMessage.addListener((message, sender, respond) => {
  if (message.target !== 'ieid-html-parser' || sender.id !== chrome.runtime.id) return;
  try {
    if (!['detail', 'tracking', 'list'].includes(message.kind) || typeof message.html !== 'string') {
      throw new Error('Invalid HTML parsing request');
    }
    const url = new URL(message.url);
    if (url.protocol !== 'https:' || !['www.amazon.com', 'amazon.com'].includes(url.hostname)) {
      throw new Error('Invalid Amazon origin');
    }
    const doc = new DOMParser().parseFromString(message.html, 'text/html');
    // Resolve relative links against Amazon rather than the extension origin.
    doc.querySelectorAll('base').forEach(node => node.remove());
    const base = doc.createElement('base');
    base.href = url.href;
    doc.head.prepend(base);
    // Keep script text out of body-text extraction. HTML regex extraction can
    // still read data in the head, but nothing in this detached document runs.
    doc.body?.querySelectorAll('script, style, noscript').forEach(node => node.remove());
    if (message.kind === 'detail') {
      const orderId = url.searchParams.get('orderID') || url.searchParams.get('orderId');
      if (!orderId || !doc.body?.textContent.includes(orderId)) {
        throw new Error('Requested order is not present in the response');
      }
    }
    const result = message.kind === 'list'
      ? globalThis.ieidExtractOrderList(doc, url)
      : message.kind === 'detail'
      ? globalThis.ieidExtractOrderDetail(doc, url)
      : globalThis.ieidExtractTracking(doc, false);
    if (message.kind === 'list' && !result.issue) {
      const count = (result.orders?.length || 0) + (result.cancelledOrders?.length || 0);
      const totalMatch = (doc.body?.textContent || '').match(/([\d,]+)\s+orders?\s+placed/i);
      const total = totalMatch ? Number(totalMatch[1].replace(/,/g, '')) : null;
      const hasPager = Array.from(doc.querySelectorAll('a[href]')).some(link => {
        try {
          const target = new URL(link.getAttribute('href'), url);
          return target.origin === url.origin
            && /^\/(?:your-orders\/orders|gp\/your-account\/order-history)(?:\/|$)/i.test(target.pathname)
            && ['page', 'startIndex'].some(key => /^\d+$/.test(target.searchParams.get(key) || ''))
            && (target.searchParams.get('timeFilter') || target.searchParams.get('orderFilter'))
              === (url.searchParams.get('timeFilter') || url.searchParams.get('orderFilter'));
        } catch { return false; }
      });
      if (count && !hasPager && !(total !== null && total === count && !(Number(url.searchParams.get('page')) || Number(url.searchParams.get('startIndex'))))) {
        result.issue = 'Order-list pagination is incomplete or unrecognized';
      }
    }
    respond({ result });
  } catch (err) {
    respond({ error: err.message });
  }
});
