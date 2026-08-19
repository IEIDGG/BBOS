(() => {
  function cleanText(value) {
    return (value || '').replace(/\s+/g, ' ').trim();
  }

  function textFromSelectors(selectors, root = document) {
    for (const selector of selectors) {
      const value = cleanText(root.querySelector(selector)?.textContent);
      if (value) return value;
    }
    return '';
  }

  function stripTrackingLabel(value) {
    return cleanText(value).replace(/^Tracking(?:\s+ID|\s+number)\s*:?\s*/i, '');
  }

  function isValidTrackingId(value) {
    const id = cleanText(value);
    if (!id || id.length < 10) return false;
    if (!/\d/.test(id)) return false;
    if (/^(workouts|packages|events|details|updates)$/i.test(id)) return false;
    return /^(1Z[A-Z0-9]{16}|TBA[A-Z0-9]{9,}|9\d{15,34}|7\d{19,34}|JD[A-Z0-9]{12,}|[A-Z]{2}\d{9}US|\d{12,})$/i.test(id);
  }

  function normalizeTrackingCandidate(value) {
    const stripped = stripTrackingLabel(value);
    return isValidTrackingId(stripped) ? stripped : '';
  }

  function extractTrackingIdFromDom() {
    const selectors = [
      '.pt-delivery-card-trackingId',
      '.tracking-event-trackingId-text h4',
      '.tracking-event-trackingId-text',
      '#tracking-events-container .tracking-event-trackingId-text',
      '#a-popover-tracking-events-modal .tracking-event-trackingId-text',
    ];

    for (const selector of selectors) {
      const candidate = normalizeTrackingCandidate(document.querySelector(selector)?.textContent || '');
      if (candidate) return candidate;
    }

    for (const el of document.querySelectorAll('[class*="trackingId"]')) {
      const candidate = normalizeTrackingCandidate(el.textContent || '');
      if (candidate) return candidate;
    }

    return '';
  }

  function extractTrackingIdFromHtml(html) {
    if (!html) return '';

    const patterns = [
      /Tracking ID:\s*(TBA[A-Z0-9]{9,})/gi,
      /Tracking ID:\s*(1Z[A-Z0-9]{16})/gi,
      /pt-delivery-card-trackingId[^>]*>\s*Tracking ID:\s*([^<]+)/gi,
      /\b(1Z[A-Z0-9]{16})\b/g,
      /\b(TBA[A-Z0-9]{9,})\b/g,
    ];

    for (const pattern of patterns) {
      for (const match of html.matchAll(pattern)) {
        const candidate = normalizeTrackingCandidate(match[1] || match[0] || '');
        if (candidate) return candidate;
      }
    }

    return '';
  }

  function extractTrackingIdFromText(text) {
    const compact = cleanText(text);
    const labeledPattern = /Tracking(?:\s+ID|\s+number)\s*:?\s*([A-Z0-9-]+)/gi;
    let match = labeledPattern.exec(compact);
    while (match) {
      const candidate = normalizeTrackingCandidate(`Tracking ID: ${match[1]}`);
      if (candidate) return candidate;
      match = labeledPattern.exec(compact);
    }

    const knownPattern = compact.match(/\b(1Z[A-Z0-9]{16}|TBA[A-Z0-9]{9,}|9\d{15,34}|7\d{19,34}|JD[A-Z0-9]{12,}|[A-Z]{2}\d{9}US)\b/i)?.[1];
    return isValidTrackingId(knownPattern || '') ? knownPattern : '';
  }

  function extractCarrierFromText(text) {
    const compact = cleanText(text);
    const shippedWith = compact.match(/Shipped with\s+(Amazon Logistics|Amazon|UPS|USPS|FedEx|OnTrac|DHL|LaserShip|Veho)\b/i)?.[1];
    if (shippedWith) return shippedWith;

    const labeled = compact.match(/(?:Carrier|Ship carrier)\s*:?\s*(Amazon Logistics|Amazon|UPS|USPS|FedEx|OnTrac|DHL|LaserShip|Veho)\b/i)?.[1];
    if (labeled) return labeled;

    const anyCarrier = compact.match(/\b(Amazon Logistics|Amazon|UPS|USPS|FedEx|OnTrac|DHL|LaserShip|Veho)\b/i)?.[1];
    return anyCarrier || '';
  }

  function extractCarrierFromDom() {
    const selectors = [
      '.tracking-event-carrier-header h2',
      '.tracking-event-carrier-header',
      '.delivery-card h3',
      '.pt-delivery-card-wrapper h3',
    ];

    for (const selector of selectors) {
      const text = cleanText(document.querySelector(selector)?.textContent);
      const carrier = extractCarrierFromText(text);
      if (carrier) return carrier;
    }

    return '';
  }

  function extractEvents() {
    const events = [];
    const eventRoot = document.querySelector('#tracking-events-container')
      || document.querySelector('.tracking-events-modal-inner')
      || document.body;

    const dateGroups = Array.from(eventRoot.querySelectorAll('.tracking-event-date-header, .a-row.tracking-event-date-header'))
      .map(el => el.closest('.a-row') || el.parentElement)
      .filter(Boolean);

    for (const group of dateGroups) {
      const date = textFromSelectors(['.tracking-event-date-header', '.tracking-event-date'], group);
      const blocks = group.parentElement
        ? Array.from(group.parentElement.querySelectorAll('.a-spacing-large.a-spacing-top-medium'))
        : [];

      for (const block of blocks) {
        const time = textFromSelectors(['.tracking-event-time'], block);
        const message = textFromSelectors(['.tracking-event-message'], block);
        const location = textFromSelectors(['.tracking-event-location'], block);

        if (time || message || location) {
          const event = { date, time, message, location };
          const key = JSON.stringify(event);
          if (!events.some(existing => JSON.stringify(existing) === key)) events.push(event);
        }
      }
    }

    return events;
  }

  function detectPageIssue() {
    const text = cleanText(document.body?.innerText || '');
    if (/enter the characters you see below|sorry, we just need to make sure you're not a robot/i.test(text)) {
      return 'Amazon verification page';
    }
    if (/sign in|email or mobile phone number|enter your password|session has expired/i.test(text)
      && !/Tracking ID:/i.test(text)) {
      return 'Amazon sign-in required';
    }
    return '';
  }

  function detectCancelled() {
    const text = cleanText(document.body?.innerText || '');
    if (/cancel(?:led|ed)/i.test(text) && !/tracking id:/i.test(text)) {
      return 'order cancelled';
    }
    return '';
  }

  function detectNotShippedFromDom() {
    if (extractTrackingIdFromDom()) return '';

    const mainStatus = cleanText(document.querySelector('.pt-status-main-status')?.textContent);
    if (/^ordered$/i.test(mainStatus)) {
      return 'no tracking available yet';
    }

    const promiseSlot = cleanText(document.querySelector('.pt-promise-main-slot')?.textContent);
    if (/^arriving\b/i.test(promiseSlot)) {
      return 'no tracking available yet';
    }

    const milestones = document.querySelector('.pt-status-milestones');
    if (milestones) {
      const deliveryStatus = milestones.getAttribute('aria-label') || '';
      if (/delivery status:\s*ordered\b/i.test(deliveryStatus)) {
        return 'no tracking available yet';
      }

      for (const milestone of milestones.querySelectorAll('.pt-status-milestone')) {
        const label = cleanText(milestone.querySelector('.pt-status-milestone-label')?.textContent);
        const reached = milestone.getAttribute('data-reached');
        if (/^shipped$/i.test(label) && reached === 'false') {
          return 'no tracking available yet';
        }
      }
    }

    if (document.querySelector('.status-card.pt-card, section.status-card')) {
      if (mainStatus && !/shipped|delivered|out for delivery|on the way/i.test(mainStatus)) {
        return 'no tracking available yet';
      }
    }

    return '';
  }

  function detectNoTrackingAvailable() {
    if (/tracking id:/i.test(cleanText(document.body?.innerText || ''))) return '';

    const fromDom = detectNotShippedFromDom();
    if (fromDom) return fromDom;

    const text = cleanText(document.body?.innerText || '');
    if (/cancel(?:led|ed)/i.test(text)) return 'order cancelled';
    if (/not yet shipped|preparing for shipment|shipping info (?:will be )?available|has(?:n't| not) shipped yet|we'?re getting your (?:order|package) ready|no tracking information|tracking will be updated|package has not left|tracking info is not available|available once the package ships|order received|processing your order|pending shipment|awaiting shipment|shipment delayed|delivery estimate unavailable|delivery status:\s*ordered\b|\barriving\s+(?:today|tomorrow|\w+\s+\d{1,2}|\d)/i.test(text)) {
      return 'no tracking available yet';
    }
    return '';
  }

  function extractTrackingSnapshot() {
    const bodyText = cleanText(document.body?.innerText || '');
    const html = document.documentElement?.innerHTML || '';
    const trackingId = extractTrackingIdFromDom()
      || extractTrackingIdFromText(bodyText)
      || extractTrackingIdFromHtml(html);
    const carrier = extractCarrierFromDom() || extractCarrierFromText(bodyText) || extractCarrierFromText(html);
    const issue = detectPageIssue();
    const cancelled = issue ? '' : detectCancelled();
    const noTracking = issue || cancelled ? '' : detectNoTrackingAvailable();

    return {
      carrier: cleanText(carrier),
      trackingId: cleanText(trackingId),
      events: extractEvents(),
      issue,
      cancelled,
      noTracking,
    };
  }

  function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  async function waitForTrackingData(maxMs = 8000, intervalMs = 250) {
    const started = Date.now();
    let latest = extractTrackingSnapshot();

    while (Date.now() - started < maxMs) {
      latest = extractTrackingSnapshot();
      if (latest.trackingId) return latest;
      if (latest.issue) return latest;
      if (latest.cancelled) return latest;
      if (latest.noTracking) return latest;
      await sleep(intervalMs);
    }

    if (!latest.trackingId && !latest.issue && !latest.cancelled && !latest.noTracking) {
      latest.timedOut = true;
    }
    return latest;
  }

  return waitForTrackingData();
})();
