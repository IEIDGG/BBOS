// This script is injected into Amazon order list pages to extract data.
// It intentionally uses several selector and text fallbacks because Amazon
// serves different order markup across accounts, years, and experiments.

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
    const nodes = Array.from(root.querySelectorAll('span, div, a, b, strong'));

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

  function parseHeaderFromText(text) {
    const compact = cleanText(text);
    return {
      orderDate: (
        compact.match(/Order placed\s+(.+?)\s+(?:Total|Ship to|Order #)/i)?.[1]
        || compact.match(/Placed on\s+(.+?)\s+(?:Total|Ship to|Order #)/i)?.[1]
        || ''
      ),
      total: cleanMoney(
        compact.match(/Total\s+(\$[\d,]+(?:\.\d{2})?)/i)?.[1]
        || compact.match(/Order total\s+(\$[\d,]+(?:\.\d{2})?)/i)?.[1]
        || ''
      ),
      shipTo: (
        compact.match(/Ship to\s+(.+?)\s+(?:Order #|View order details|Invoice|Buy again)/i)?.[1]
        || ''
      ),
      orderId: compact.match(ORDER_ID_RE)?.[0] || '',
    };
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
    const fromBreaks = html.replace(/<br\s*\/?>/gi, ', ').replace(/<[^>]+>/g, ' ');
    return cleanText(fromBreaks);
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

  function addressFromHtmlRoot(root) {
    if (!root) return '';

    const popover = root.querySelector('.a-popover-preload, [id^="a-popover-shippingAddress"]');
    if (popover) {
      const rows = Array.from(popover.querySelectorAll('.a-row'));
      const rowParts = rows.map(row => textFromElement(row)).filter(Boolean);
      if (rowParts.length) return rowParts.join(', ');
    }

    const listItems = Array.from(root.querySelectorAll('[data-component="shippingAddress"] li .a-list-item, li .a-list-item'));
    if (listItems.length) {
      const parts = listItems.map(item => textFromElement(item)).filter(Boolean);
      if (parts.length) return parts.join(', ');
    }

    return cleanText(root.textContent);
  }

  function extractAddressFromScriptTemplates(card) {
    const scripts = card.querySelectorAll('script[id^="shipToData-shippingAddress"], script[type="text/template"][id*="shippingAddress"]');
    for (const script of scripts) {
      const template = document.createElement('div');
      template.innerHTML = script.textContent || '';
      const address = addressFromHtmlRoot(template);
      if (isValidShippingAddress(address)) return address;
    }
    return '';
  }

  function extractShipToName(card) {
    const trigger = card.querySelector('.yohtmlc-recipient .insert-encrypted-trigger-text, .yohtmlc-recipient .a-popover-trigger');
    if (trigger) return cleanText(trigger.textContent);

    const component = card.querySelector('[data-component="shippingAddress"]');
    const firstLine = component?.querySelector('li .a-list-item');
    if (firstLine) return cleanText(firstLine.textContent);

    const preloadName = card.querySelector('.a-popover-preload h5, [id^="a-popover-shippingAddress"] h5');
    if (preloadName) return cleanText(preloadName.textContent);

    return findValueAfterLabel(card, ['Ship to', 'Recipient']) || '';
  }

  function extractShippingAddressFromCard(card) {
    const preloadSelectors = [
      '.yohtmlc-recipient .a-popover-preload',
      '[id^="shipToInsertionNode"] .a-popover-preload',
      '[id^="a-popover-shippingAddress"]',
    ];

    for (const selector of preloadSelectors) {
      const preload = card.querySelector(selector);
      if (!preload) continue;
      const address = addressFromHtmlRoot(preload);
      if (isValidShippingAddress(address)) return address;
    }

    const componentAddress = addressFromHtmlRoot(card.querySelector('[data-component="shippingAddress"]'));
    if (isValidShippingAddress(componentAddress)) return componentAddress;

    const templateAddress = extractAddressFromScriptTemplates(card);
    if (templateAddress) return templateAddress;

    return '';
  }

  function extractOrderHeader(card) {
    const textValues = parseHeaderFromText(card.textContent);
    const shippingAddress = extractShippingAddressFromCard(card);
    const shipTo = extractShipToName(card);
    const order = {
      orderDate: findValueAfterLabel(card, ['Order placed', 'Placed on']) || textValues.orderDate,
      total: cleanMoney(findValueAfterLabel(card, ['Total', 'Order total'])) || textValues.total,
      shipTo,
      shippingAddress,
      zipCode: extractZip(shippingAddress),
      orderId: findValueAfterLabel(card, ['Order #', 'Order number']) || textValues.orderId,
      shipments: [],
    };

    const idMatch = cleanText(order.orderId).match(ORDER_ID_RE);
    order.orderId = idMatch?.[0] || textValues.orderId;
    return order;
  }

  function findOrderCards() {
    const selectors = [
      '.order-card.js-order-card',
      '.order-card',
      '.js-order-card',
      '[data-order-id]',
      '[id^="orderCard"]',
      '.your-orders-content .a-box-group',
      '.yohtmlc-order-card',
      '.a-box-group.a-spacing-base',
    ];

    const cards = [];
    const seen = new Set();

    for (const selector of selectors) {
      for (const node of document.querySelectorAll(selector)) {
        const text = cleanText(node.textContent);
        if (!ORDER_ID_RE.test(text)) continue;

        const orderRoot = node.closest('.order-card, .js-order-card, .yohtmlc-order-card, [data-order-id]')
          || (ORDER_ID_RE.test(cleanText(node.textContent)) ? node : null);
        if (!orderRoot || seen.has(orderRoot)) continue;
        seen.add(orderRoot);
        cards.push(orderRoot);
      }
    }

    if (cards.length) return cards;

    const fallback = [];
    for (const node of document.querySelectorAll('div, section')) {
      const text = cleanText(node.textContent);
      if (!ORDER_ID_RE.test(text) || !/Order placed|Order #|View order details/i.test(text)) continue;
      const containsExisting = fallback.some(existing => existing.contains(node));
      if (!containsExisting) fallback.push(node);
    }
    return fallback;
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

    const text = cleanText(container.textContent);
    const statusIndex = status ? text.indexOf(status) : -1;
    if (statusIndex >= 0) {
      return cleanText(text.slice(statusIndex + status.length).split(/(?:Buy again|View item|Return|Track package|Leave seller feedback)/i)[0]);
    }
    return '';
  }

  function isShipTrackHref(href) {
    try {
      const absolute = new URL(href, location.href).href;
      if (typeof isShipTrackUrl === 'function') return isShipTrackUrl(absolute);
      const url = new URL(absolute);
      if (url.protocol !== 'https:') return false;
      const host = url.hostname.replace(/\.$/, '').toLowerCase();
      if (!/(?:^|\.)amazon\.com$/i.test(host)) return false;
      if (url.pathname.includes('/your-orders/pop')) return false;
      return url.pathname.includes('/gp/your-account/ship-track') || url.pathname.includes('ship-track');
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
        const absolute = url.href;
        if (typeof isApprovedAmazonUrl === 'function' && !isApprovedAmazonUrl(absolute)) continue;
        if (typeof isApprovedAmazonUrl !== 'function') {
          if (url.protocol !== 'https:' || !/(?:^|\.)amazon\.com$/i.test(url.hostname.replace(/\.$/, ''))) continue;
        }
        ids.shipmentId = ids.shipmentId || url.searchParams.get('shipmentId') || '';
        ids.itemId = ids.itemId || url.searchParams.get('itemId') || '';
        ids.lineItemId = ids.lineItemId || url.searchParams.get('lineItemId') || ids.itemId || '';
        ids.packageId = ids.packageId || url.searchParams.get('packageId') || '';
      } catch {
      }
    }
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

        const imageRoot = getProductRoot(asinLink, container);
        const nearbyImage = imageUrlFromElement(imageRoot.querySelector('.product-image img, img[data-a-hires], img[src*="m.media-amazon.com/images/I/"]'));
        if (nearbyImage) return nearbyImage;
      }
    }

    return '';
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

  function normalizeComparable(value) {
    return cleanText(value).toLowerCase();
  }

  function normalizeTrackingUrlForKey(value) {
    if (!value) return '';
    try {
      const url = new URL(value, location.href);
      if (url.hostname.includes('amazon.com') && url.pathname.includes('/gp/your-account/ship-track')) {
        const params = new URLSearchParams();
        for (const key of ['orderId', 'shipmentId', 'lineItemId', 'itemId', 'packageId', 'packageIndex']) {
          const paramValue = url.searchParams.get(key);
          if (paramValue) params.set(key, paramValue);
        }
        return `${url.origin}${url.pathname}?${params.toString()}`;
      }
      url.hash = '';
      return url.toString();
    } catch {
      return cleanText(value);
    }
  }

  function getShipmentIdentity(shipment) {
    if (shipment.asin) {
      const itemId = shipment.itemId || shipment.lineItemId || '';
      const shipmentPart = shipment.shipmentId || shipment.packageId || '';
      if (shipmentPart || itemId) {
        return ['line', shipment.asin, shipmentPart, itemId].join('|');
      }
      return ['line', shipment.asin].join('|');
    }

    const trackingUrl = normalizeTrackingUrlForKey(shipment.trackingUrl || '');
    if (trackingUrl) {
      return ['tracking-url', trackingUrl].join('|');
    }

    return [
      'product',
      normalizeComparable(shipment.productTitle || ''),
    ].join('|');
  }

  function mergeShipment(existing, incoming) {
    if (incoming.quantity > (existing.quantity || 1)) existing.quantity = incoming.quantity;
    if (!existing.status && incoming.status) existing.status = incoming.status;
    if (!existing.statusDetail && incoming.statusDetail) existing.statusDetail = incoming.statusDetail;
    if (!existing.productTitle && incoming.productTitle) existing.productTitle = incoming.productTitle;
    if (!existing.itemImage && incoming.itemImage) existing.itemImage = incoming.itemImage;
    if (!existing.unitPrice && incoming.unitPrice) existing.unitPrice = incoming.unitPrice;
    if (!existing.trackingUrl && incoming.trackingUrl) existing.trackingUrl = incoming.trackingUrl;
    if (!existing.shipmentId && incoming.shipmentId) existing.shipmentId = incoming.shipmentId;
    if (!existing.itemId && incoming.itemId) existing.itemId = incoming.itemId;
    if (!existing.lineItemId && incoming.lineItemId) existing.lineItemId = incoming.lineItemId;
    if (!existing.packageId && incoming.packageId) existing.packageId = incoming.packageId;
  }

  function mergeShipmentIds(...sources) {
    const ids = {};
    for (const source of sources) {
      if (!source) continue;
      ids.shipmentId = ids.shipmentId || source.shipmentId || '';
      ids.itemId = ids.itemId || source.itemId || '';
      ids.lineItemId = ids.lineItemId || source.lineItemId || '';
      ids.packageId = ids.packageId || source.packageId || '';
    }
    if (!ids.lineItemId && ids.itemId) ids.lineItemId = ids.itemId;
    return ids;
  }

  function shipmentIdentityKey(shipment) {
    if (typeof getShipmentIdentity === 'function') {
      return getShipmentIdentity({ orderId: '' }, shipment);
    }
    return [
      shipment.shipmentId || '',
      shipment.packageId || '',
      shipment.itemId || '',
      shipment.lineItemId || '',
      shipment.asin || '',
      shipment.productTitle || '',
    ].join('|');
  }

  function extractSingleItemShipment(itemRoot, container, inheritedStatus) {
    const link = itemRoot.querySelector('a[href*="/dp/"][aria-hidden="false"], a[href*="/gp/product/"][aria-hidden="false"], a[href*="/gp/aw/d/"][aria-hidden="false"]')
      || itemRoot.querySelector('a[href*="/dp/"], a[href*="/gp/product/"], a[href*="/gp/aw/d/"]');
    if (!link) return null;

    const href = link.href || '';
    const asin = href.match(ASIN_RE)?.[1]?.toUpperCase() || '';
    if (!asin) return null;

    const title = extractProductTitle(itemRoot, link);
    const quantity = extractQuantity(itemRoot);
    const unitPrice = extractUnitPrice(itemRoot);
    const imageUrl = extractProductImage(itemRoot, link, container, asin);
    const status = inheritedStatus || getStatusFromContainer(container);

    return {
      status,
      statusDetail: getStatusDetail(container, status),
      asin,
      productTitle: title,
      quantity,
      unitPrice,
      itemImage: imageUrl,
      trackingUrl: extractTrackingLink(container) || extractTrackingLink(itemRoot),
      ...mergeShipmentIds(extractShipmentIds(container), extractShipmentIds(itemRoot)),
    };
  }

  function extractProductShipments(container, inheritedStatus) {
    const itemBoxes = Array.from(container.querySelectorAll('.item-box'));
    const fallbackItemBoxes = itemBoxes.length
      ? itemBoxes
      : Array.from(container.querySelectorAll('li .a-list-item > .a-fixed-left-grid'));
    if (fallbackItemBoxes.length) {
      const shipments = [];
      const seen = new Set();

      for (const itemRoot of fallbackItemBoxes) {
        const shipment = extractSingleItemShipment(itemRoot, container, inheritedStatus);
        if (!shipment) continue;
        const key = shipmentIdentityKey(shipment);
        if (seen.has(key)) continue;
        seen.add(key);
        shipments.push(shipment);
      }

      if (shipments.length) return shipments;
    }

    const productLinks = Array.from(container.querySelectorAll('a[href*="/dp/"], a[href*="/gp/product/"], a[href*="/gp/aw/d/"]'))
      .sort((a, b) => cleanText(b.textContent).length - cleanText(a.textContent).length);
    const shipments = [];
    const seen = new Set();
    const byIdentity = new Map();

    for (const link of productLinks) {
      const href = link.href || '';
      const asin = href.match(ASIN_RE)?.[1]?.toUpperCase() || '';
      if (!asin) continue;

      const productRoot = getProductRoot(link, container);
      const title = extractProductTitle(productRoot, link);
      const quantity = extractQuantity(productRoot);
      const unitPrice = extractUnitPrice(productRoot);
      const imageUrl = extractProductImage(productRoot, link, container, asin);
      const ids = mergeShipmentIds(extractShipmentIds(container), extractShipmentIds(productRoot));
      const shipment = {
        status: inheritedStatus || getStatusFromContainer(productRoot),
        statusDetail: getStatusDetail(productRoot, inheritedStatus),
        asin,
        productTitle: title,
        quantity,
        unitPrice,
        itemImage: imageUrl,
        trackingUrl: extractTrackingLink(productRoot) || extractTrackingLink(container),
        ...ids,
      };
      const key = shipmentIdentityKey(shipment);
      if (seen.has(`${asin}|${title}|${key}`)) continue;
      seen.add(`${asin}|${title}|${key}`);
      if (byIdentity.has(key)) {
        mergeShipment(byIdentity.get(key), shipment);
        continue;
      }
      shipments.push(shipment);
      byIdentity.set(key, shipment);
    }

    return shipments;
  }

  function findShipmentContainers(card) {
    const deliveryBoxes = Array.from(card.querySelectorAll('.delivery-box'));
    if (deliveryBoxes.length) return deliveryBoxes;

    const itemBoxes = Array.from(card.querySelectorAll('.item-box'));
    if (itemBoxes.length) return itemBoxes;

    const selectors = [
      '[class*="shipment"]',
      '[data-shipment-id]',
      '[id*="shipment"]',
    ];

    const containers = [];
    const seen = new Set();

    for (const selector of selectors) {
      for (const node of card.querySelectorAll(selector)) {
        const text = cleanText(node.textContent);
        if (!text || !node.querySelector('a[href*="/dp/"], a[href*="/gp/product/"], a[href*="/gp/aw/d/"], a[href*="track"], a[href*="ship-track"]')) continue;
        if (seen.has(node)) continue;
        seen.add(node);
        containers.push(node);
      }
    }

    return containers.length ? containers : [card];
  }

  function extractShipments(card) {
    const shipments = [];
    const seen = new Set();
    const containers = findShipmentContainers(card);

    for (const container of containers) {
      const status = getStatusFromContainer(container);
      if (/cancel(?:led|ed)/i.test(status)) continue;

      const productShipments = extractProductShipments(container, status);
      for (const shipment of productShipments) {
        const key = getShipmentIdentity(shipment);
        if (seen.has(key)) {
          const existing = shipments.find(item => getShipmentIdentity(item) === key);
          if (existing) mergeShipment(existing, shipment);
          continue;
        }
        seen.add(key);
        shipments.push(shipment);
      }
    }

    if (shipments.length) return shipments;

    const status = getStatusFromContainer(card);
    if (/cancel(?:led|ed)/i.test(status)) return [];

    const ids = extractShipmentIds(card);
    return [{
      status,
      statusDetail: getStatusDetail(card, status),
      asin: '',
      productTitle: '',
      quantity: 1,
      trackingUrl: extractTrackingLink(card),
      ...ids,
    }];
  }

  function extractMaxPage() {
    let maxPage = 1;
    const paginationText = cleanText(document.querySelector('.a-pagination')?.textContent || '');
    const pageLinks = document.querySelectorAll('.a-pagination li, .a-pagination a, [aria-label*="page" i]');

    for (const el of pageLinks) {
      const num = parseInt(cleanText(el.textContent || el.getAttribute('aria-label')), 10);
      if (!Number.isNaN(num) && num > maxPage) maxPage = num;
    }

    const textMatch = paginationText.match(/Page\s+\d+\s+of\s+(\d+)/i);
    if (textMatch) maxPage = Math.max(maxPage, parseInt(textMatch[1], 10));
    return maxPage;
  }

  function detectPageIssue() {
    const text = cleanText(document.body?.innerText || '');
    if (/enter the characters you see below|sorry, we just need to make sure you're not a robot/i.test(text)) {
      return 'Amazon is showing a verification page. Open Amazon in the browser tab and complete the check, then try again.';
    }
    if (/sign in|authentication required/i.test(text) && !ORDER_ID_RE.test(text)) {
      return 'Amazon is asking you to sign in. Sign in to Amazon, then run the scraper again.';
    }
    return '';
  }

  function extractOrdersFromPage() {
    const issue = detectPageIssue();
    if (issue) return { orders: [], maxPage: 1, issue };

    const orders = [];
    const cancelledOrders = [];
    const seenOrders = new Set();
    const seenCancelled = new Set();

    for (const card of findOrderCards()) {
      const order = extractOrderHeader(card);
      if (!order.orderId || seenOrders.has(order.orderId) || seenCancelled.has(order.orderId)) continue;

      const cardText = cleanText(card.textContent);
      const hasOnlyCancelledStatuses = /cancel(?:led|ed)/i.test(cardText)
        && !/(delivered|arriving|shipped|on the way|out for delivery)/i.test(cardText);
      if (hasOnlyCancelledStatuses) {
        seenCancelled.add(order.orderId);
        cancelledOrders.push({
          orderId: order.orderId,
          orderDate: order.orderDate || '',
          shippingAddress: order.shippingAddress || '',
          zipCode: order.zipCode || extractZip(order.shippingAddress || ''),
          cancelled: true,
        });
        continue;
      }

      order.shipments = extractShipments(card);
      if (!order.shipments.length) continue;

      seenOrders.add(order.orderId);
      orders.push(order);
    }

    return { orders, cancelledOrders, maxPage: extractMaxPage(), issue: orders.length || cancelledOrders.length ? '' : detectPageIssue() };
  }

  return extractOrdersFromPage();
})();
