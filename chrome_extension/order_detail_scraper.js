(() => {
  const ORDER_ID_RE = /\b\d{3}-\d{7}-\d{7}\b/;
  const ASIN_RE = /\/(?:dp|gp\/product|gp\/aw\/d)\/([A-Z0-9]{10})(?:[/?#]|$)/i;

  function cleanText(value) {
    return (value || '').replace(/\s+/g, ' ').trim();
  }

  function cleanMoney(value) {
    const match = cleanText(value).match(/\$[\d,]+(?:\.\d{2})?/);
    return match ? match[0] : cleanText(value);
  }

  function normalizeLabel(value) {
    return cleanText(value).replace(/:$/, '').toLowerCase();
  }

  function getDirectText(element) {
    if (!element) return '';
    return cleanText(Array.from(element.childNodes)
      .filter(node => node.nodeType === Node.TEXT_NODE)
      .map(node => node.textContent)
      .join(' '));
  }

  function findValueAfterLabel(root, labels) {
    const wanted = labels.map(normalizeLabel);
    const nodes = Array.from(root.querySelectorAll('span, div, a, b, strong, td, th'));

    for (let i = 0; i < nodes.length; i++) {
      const label = normalizeLabel(getDirectText(nodes[i]) || nodes[i].textContent);
      if (!wanted.includes(label)) continue;

      const sameContainer = nodes[i].parentElement;
      const siblings = sameContainer ? Array.from(sameContainer.children) : [];
      const siblingIndex = siblings.indexOf(nodes[i]);
      const nextSibling = siblings.slice(siblingIndex + 1)
        .map(el => cleanText(el.textContent))
        .find(Boolean);
      if (nextSibling && !wanted.includes(normalizeLabel(nextSibling))) return nextSibling;

      for (let j = i + 1; j < Math.min(nodes.length, i + 8); j++) {
        const next = cleanText(nodes[j].textContent);
        if (!next || wanted.includes(normalizeLabel(next))) continue;
        return next;
      }
    }

    return '';
  }

  function extractZip(text) {
    const compact = cleanText(text);
    return (
      compact.match(/\b[A-Z]{2}\s+(\d{5}(?:-\d{4})?)\b/i)?.[1]
      || compact.match(/\b(\d{5}(?:-\d{4})?)\b/)?.[1]
      || ''
    );
  }

  function textFromElement(element) {
    if (!element) return '';
    const html = element.innerHTML || '';
    return cleanText(html.replace(/<br\s*\/?>/gi, ', ').replace(/<[^>]+>/g, ' '));
  }

  function isValidShippingAddress(text) {
    const compact = cleanText(text);
    if (!compact || compact.length < 10) return false;
    if (/payment method|prime visa|ending in \d{4}|view related transaction|earns \d+% back|no-rush delivery|billing address/i.test(compact)) {
      return false;
    }
    if (extractZip(compact)) return true;
    return /\b(united states|usa)\b/i.test(compact) && /,\s*[A-Z]{2}\b/.test(compact);
  }

  function textFromAddressSelectors() {
    const selectors = [
      '[data-component="shippingAddress"]',
      '#od-shipping-address',
      '.od-shipping-address',
      '[data-testid*="shipping-address" i]',
      '[data-test-id*="shipping-address" i]',
      '[class*="shipping-address" i]',
      '[class*="ship-address" i]',
      '[id*="shipping-address" i]',
    ];

    for (const selector of selectors) {
      const root = document.querySelector(selector);
      if (!root) continue;
      const listItems = Array.from(root.querySelectorAll('li .a-list-item'));
      if (listItems.length) {
        const parts = listItems.map((item) => textFromElement(item)).filter(Boolean);
        const text = parts.join(', ');
        if (text && extractZip(text)) return text;
      }
      const text = cleanText(root.textContent);
      if (text && extractZip(text)) return text;
    }

    return '';
  }

  function textAfterShippingLabel() {
    const bodyText = cleanText(document.body?.innerText || '');
    const match = bodyText.match(/Shipping Address\s+(.+?)(?:Payment Method|Order Summary|Billing address|Items Ordered|Transactions|Shipment|Need to return|Archive order|$)/i);
    return cleanText(match?.[1] || '');
  }

  function extractShippingAddress() {
    return textFromAddressSelectors() || textAfterShippingLabel();
  }

  function extractShipToName(shippingAddress) {
    const firstPart = cleanText(shippingAddress.split(',')[0] || '');
    if (firstPart && !/\d/.test(firstPart)) return firstPart;
    return findValueAfterLabel(document, ['Ship to', 'Recipient']) || '';
  }

  function getOrderId() {
    const params = new URLSearchParams(location.search);
    const fromParam = params.get('orderID') || params.get('orderId') || '';
    if (ORDER_ID_RE.test(fromParam)) return fromParam.match(ORDER_ID_RE)[0];
    const fromLabel = findValueAfterLabel(document, ['Order #', 'Order number']);
    const labelMatch = cleanText(fromLabel).match(ORDER_ID_RE);
    if (labelMatch) return labelMatch[0];
    const bodyMatch = cleanText(document.body?.innerText || '').match(ORDER_ID_RE);
    return bodyMatch?.[0] || '';
  }

  function extractOrderDate() {
    const fromLabel = findValueAfterLabel(document, ['Order placed', 'Placed on']);
    if (fromLabel) return fromLabel;
    const bodyText = cleanText(document.body?.innerText || '');
    return (
      bodyText.match(/Order placed\s+(.+?)\s+(?:Order #|Total|Ship to|Payment)/i)?.[1]
      || bodyText.match(/Placed on\s+(.+?)\s+(?:Order #|Total|Ship to|Payment)/i)?.[1]
      || ''
    );
  }

  function extractTotal() {
    const summarySelectors = [
      '#od-suborder-totals',
      '[data-testid="order-summary"]',
      '.order-summary',
      '#orderSummary',
    ];

    for (const selector of summarySelectors) {
      const root = document.querySelector(selector);
      if (!root) continue;
      const total = cleanMoney(findValueAfterLabel(root, ['Grand Total', 'Order total', 'Total']));
      if (total) return total;
    }

    const fromLabel = cleanMoney(findValueAfterLabel(document, ['Grand Total', 'Order total', 'Total']));
    if (fromLabel) return fromLabel;

    const bodyText = cleanText(document.body?.innerText || '');
    return cleanMoney(
      bodyText.match(/Grand Total\s+(\$[\d,]+(?:\.\d{2})?)/i)?.[1]
      || bodyText.match(/Order total\s+(\$[\d,]+(?:\.\d{2})?)/i)?.[1]
      || ''
    );
  }

  function getStatusFromContainer(container) {
    const selectors = [
      '.delivery-box__primary-text',
      '[data-test-id*="delivery"]',
      '[class*="delivery"] .a-size-medium',
      '[class*="shipment"] .a-size-medium',
      '.shipment-top-row .a-size-medium',
      '.a-size-medium.a-text-bold',
      'h2',
      'h3',
    ];

    for (const selector of selectors) {
      const text = cleanText(container.querySelector(selector)?.textContent);
      if (text && !ORDER_ID_RE.test(text)) return text;
    }

    const text = cleanText(container.textContent);
    const match = text.match(/\b(Delivered|Arriving|Shipped|Out for delivery|On the way|Running late|Cancelled|Canceled|Return started|Refund issued)[^.$|]*/i);
    return cleanText(match?.[0] || '');
  }

  function getStatusDetail(container, status) {
    const detail = cleanText(
      container.querySelector('.delivery-box__secondary-text')?.textContent
      || container.querySelector('[class*="secondary"]')?.textContent
      || ''
    );
    if (detail && detail !== status) return detail;
    return '';
  }

  function isShipTrackHref(href) {
    try {
      const url = new URL(href, location.href);
      if (url.pathname.includes('/your-orders/pop')) return false;
      return url.pathname.includes('ship-track');
    } catch {
      return false;
    }
  }

  function parseShipTrackLink(href) {
    if (!isShipTrackHref(href)) return null;
    try {
      const url = new URL(href, location.href);
      const itemId = url.searchParams.get('itemId') || '';
      return {
        trackingUrl: url.href,
        shipmentId: url.searchParams.get('shipmentId') || '',
        itemId,
        lineItemId: url.searchParams.get('lineItemId') || itemId || '',
        packageId: url.searchParams.get('packageId') || '',
      };
    } catch {
      return null;
    }
  }

  function collectShipTrackLinks(root = document) {
    const links = [];
    const seen = new Set();

    for (const link of root.querySelectorAll('a[href*="ship-track"]')) {
      const parsed = parseShipTrackLink(link.href);
      if (!parsed) continue;
      const key = `${parsed.shipmentId}|${parsed.itemId}|${parsed.trackingUrl}`;
      if (seen.has(key)) continue;
      seen.add(key);
      links.push(parsed);
    }

    return links;
  }

  function extractTrackingLink(container) {
    for (const link of container.querySelectorAll('a[href*="ship-track"]')) {
      const parsed = parseShipTrackLink(link.href);
      if (parsed?.trackingUrl) return parsed.trackingUrl;
    }
    return '';
  }

  function extractShipmentIds(container) {
    const ids = {};
    const candidates = Array.from(container.querySelectorAll('a[href*="ship-track"], a[href*="shipmentId"], a[href*="lineItemId"], a[href*="itemId"]'));

    for (const link of candidates) {
      const parsed = parseShipTrackLink(link.href);
      if (parsed) {
        ids.shipmentId = ids.shipmentId || parsed.shipmentId || '';
        ids.itemId = ids.itemId || parsed.itemId || '';
        ids.lineItemId = ids.lineItemId || parsed.lineItemId || '';
        ids.packageId = ids.packageId || parsed.packageId || '';
        continue;
      }

      try {
        const url = new URL(link.href, location.href);
        ids.shipmentId = ids.shipmentId || url.searchParams.get('shipmentId') || '';
        ids.itemId = ids.itemId || url.searchParams.get('itemId') || '';
        ids.lineItemId = ids.lineItemId || url.searchParams.get('lineItemId') || ids.itemId || '';
        ids.packageId = ids.packageId || url.searchParams.get('packageId') || '';
      } catch {
      }
    }

    if (!ids.lineItemId && ids.itemId) ids.lineItemId = ids.itemId;
    return ids;
  }

  function extractQuantity(itemRoot) {
    const badge = itemRoot.querySelector('.product-image .product-image__qty, .item-view-qty, .od-item-view-qty');
    if (badge) {
      const qty = parseInt(cleanText(badge.textContent), 10);
      if (!Number.isNaN(qty) && qty > 0) return qty;
    }

    const text = cleanText(itemRoot.textContent);
    const qtyMatch = text.match(/\b(?:Qty|Quantity)\s*:?\s*(\d+)\b/i);
    return qtyMatch ? parseInt(qtyMatch[1], 10) : 1;
  }

  function extractUnitPrice(itemRoot) {
    const unitPriceRoot = itemRoot.querySelector('[data-component="unitPrice"]');
    if (unitPriceRoot) {
      const fromOffscreen = cleanMoney(unitPriceRoot.querySelector('.a-offscreen')?.textContent);
      if (fromOffscreen) return fromOffscreen;
      const fromPrice = cleanMoney(unitPriceRoot.textContent);
      if (fromPrice) return fromPrice;
    }

    for (const priceEl of itemRoot.querySelectorAll('.a-price .a-offscreen, .a-text-price .a-offscreen')) {
      const price = cleanMoney(priceEl.textContent);
      if (price) return price;
    }

    return '';
  }

  function normalizeImageUrl(value) {
    if (!value) return '';
    try {
      return new URL(value, location.href).href;
    } catch {
      return value;
    }
  }

  function imageUrlFromElement(img) {
    if (!img) return '';
    return normalizeImageUrl(
      img.getAttribute('data-a-hires')
      || img.getAttribute('data-old-hires')
      || img.currentSrc
      || img.getAttribute('src')
      || ''
    );
  }

  function extractProductTitle(container, link) {
    const selectors = [
      'a[href*="/dp/"][aria-hidden="false"]',
      'a[href*="/gp/product/"][aria-hidden="false"]',
      'a[href*="/gp/aw/d/"][aria-hidden="false"]',
      '.yohtmlc-product-title',
      '.a-link-normal[href*="/dp/"]',
      '.a-link-normal[href*="/gp/product/"]',
    ];

    for (const selector of selectors) {
      const text = cleanText(container.querySelector(selector)?.textContent);
      if (text && !/^\d+$/.test(text)) return text;
    }

    return cleanText(link?.getAttribute('aria-label') || link?.textContent || '');
  }

  function getProductRoot(link, container) {
    const selectors = [
      '.item-box',
      '.a-fixed-left-grid',
      '[data-itemid]',
      '[data-asin]',
      'li',
      '.a-row',
      '[class*="product"]',
      '[class*="item"]',
    ];

    for (const selector of selectors) {
      const root = link.closest(selector);
      if (root && container.contains(root)) return root;
    }

    return container;
  }

  function extractProductImage(productRoot, link, container, asin) {
    const linkedImage = imageUrlFromElement(link.querySelector('img'));
    if (linkedImage) return linkedImage;

    const rootImage = imageUrlFromElement(productRoot.querySelector('.product-image img, img[data-a-hires], img[src*="m.media-amazon.com/images/I/"]'));
    if (rootImage) return rootImage;

    if (asin) {
      const asinLinks = Array.from(container.querySelectorAll(`a[href*="${asin}"]`));
      for (const asinLink of asinLinks) {
        const image = imageUrlFromElement(asinLink.querySelector('img'));
        if (image) return image;
      }
    }

    return '';
  }

  function findShipmentContainers() {
    const purchasedItems = document.querySelector('[data-component="purchasedItems"]');
    if (purchasedItems) {
      const itemRows = Array.from(purchasedItems.querySelectorAll(':scope > .a-row > .a-fixed-left-grid, :scope > .a-fixed-left-grid'));
      if (itemRows.length) return itemRows;
    }

    const selectors = [
      '.delivery-box',
      '[data-test-id="shipment-item"]',
      '.shipment-item',
      '[class*="shipment"]',
      '#orderDetails .item-box',
      '#orderDetails .a-fixed-left-grid',
    ];

    const containers = [];
    const seen = new Set();

    for (const selector of selectors) {
      for (const node of document.querySelectorAll(selector)) {
        const hasProduct = node.querySelector('a[href*="/dp/"], a[href*="/gp/product/"], a[href*="/gp/aw/d/"]');
        if (!hasProduct || seen.has(node)) continue;
        seen.add(node);
        containers.push(node);
      }
    }

    if (containers.length) return containers;

    const orderRoot = document.querySelector('#orderDetails, .order-details, main, #ppx-yo-main');
    return orderRoot ? [orderRoot] : [document.body];
  }

  function extractShipments() {
    const shipments = [];
    const seen = new Set();
    const containers = findShipmentContainers();
    const pageTrackLinks = collectShipTrackLinks();

    for (const container of containers) {
      const status = getStatusFromContainer(container);
      if (/cancel(?:led|ed)/i.test(status)) continue;

      const productLinks = Array.from(container.querySelectorAll('a[href*="/dp/"], a[href*="/gp/product/"], a[href*="/gp/aw/d/"]'))
        .sort((a, b) => cleanText(b.textContent).length - cleanText(a.textContent).length);

      for (const link of productLinks) {
        const href = link.href || '';
        const asin = href.match(ASIN_RE)?.[1]?.toUpperCase() || '';
        if (!asin || seen.has(asin)) continue;
        seen.add(asin);

        const productRoot = getProductRoot(link, container);
        const title = extractProductTitle(productRoot, link);
        const quantity = extractQuantity(productRoot);
        const unitPrice = extractUnitPrice(productRoot);
        const imageUrl = extractProductImage(productRoot, link, container, asin);
        const ids = extractShipmentIds(container);
        const pageTrack = pageTrackLinks.find((entry) => entry.shipmentId && entry.itemId) || pageTrackLinks[0] || null;

        if (pageTrack) {
          ids.shipmentId = ids.shipmentId || pageTrack.shipmentId || '';
          ids.itemId = ids.itemId || pageTrack.itemId || '';
          ids.lineItemId = ids.lineItemId || pageTrack.lineItemId || '';
          ids.packageId = ids.packageId || pageTrack.packageId || '';
        }

        shipments.push({
          status,
          statusDetail: getStatusDetail(container, status),
          asin,
          productTitle: title,
          quantity,
          unitPrice,
          itemImage: imageUrl,
          trackingUrl: extractTrackingLink(container) || pageTrack?.trackingUrl || '',
          ...ids,
        });
      }
    }

    if (!shipments.length && pageTrackLinks.length) {
      const pageTrack = pageTrackLinks[0];
      shipments.push({
        status: getStatusFromContainer(document.body),
        statusDetail: '',
        asin: '',
        productTitle: '',
        quantity: 1,
        itemImage: '',
        trackingUrl: pageTrack.trackingUrl,
        shipmentId: pageTrack.shipmentId,
        itemId: pageTrack.itemId,
        lineItemId: pageTrack.lineItemId,
        packageId: pageTrack.packageId,
      });
    }

    return shipments;
  }

  function detectPageIssue() {
    const bodyText = cleanText(document.body?.innerText || '');
    if (/enter the characters you see below|sorry, we just need to make sure you're not a robot/i.test(bodyText)) {
      return 'Amazon is showing a verification page. Open Amazon in the browser tab and complete the check, then try again.';
    }
    if (/sign in|email or mobile phone number|enter your password/i.test(bodyText) && !ORDER_ID_RE.test(bodyText)) {
      return 'Amazon is asking for sign-in before order details can be read.';
    }
    return '';
  }

  function extractOrderFromDetailPage() {
    const issue = detectPageIssue();
    if (issue) return { orders: [], issue };

    const shippingAddress = extractShippingAddress();
    const orderId = getOrderId();
    const order = {
      orderId,
      orderDate: extractOrderDate(),
      total: extractTotal(),
      shipTo: extractShipToName(shippingAddress),
      shippingAddress,
      zipCode: extractZip(shippingAddress),
      shipments: extractShipments(),
    };

    if (!order.orderId) {
      return { orders: [], issue: 'Could not find an order ID on this page.' };
    }

    if (!order.shipments.length) {
      const bodyText = cleanText(document.body?.innerText || '');
      const isCancelled = /cancel(?:led|ed)/i.test(bodyText)
        && !/(delivered|arriving|shipped|on the way|out for delivery)/i.test(bodyText);
      if (isCancelled) {
        return {
          orders: [],
          cancelledOrders: [{
            orderId: order.orderId,
            orderDate: order.orderDate || '',
            shippingAddress: order.shippingAddress || '',
            zipCode: order.zipCode || '',
            cancelled: true,
          }],
          issue: '',
        };
      }
      return { orders: [], issue: 'Could not find any items on this order page.' };
    }

    return { orders: [order], cancelledOrders: [], issue: '' };
  }

  return extractOrderFromDetailPage();
})();
