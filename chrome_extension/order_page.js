(() => {
  const ORDER_DETAILS_RE = /^\/(?:your-orders|gp\/your-account)\/order-details(?:\/|$)/i;
  const ORDER_ID_PARAM = 'orderID';

  function getOrderId() {
    const params = new URLSearchParams(location.search);
    const fromParam = params.get(ORDER_ID_PARAM) || params.get('orderId') || '';
    if (fromParam) return fromParam;
    const match = document.body?.innerText?.match(/\b\d{3}-\d{7}-\d{7}\b/);
    return match?.[0] || '';
  }

  function createButton(orderId) {
    if (document.getElementById('ieid-scan-order-btn')) return;

    const btn = document.createElement('button');
    btn.id = 'ieid-scan-order-btn';
    btn.type = 'button';
    btn.textContent = 'Scan with IEID';
    btn.title = `Scan order ${orderId} with IEID`;
    Object.assign(btn.style, {
      position: 'fixed',
      bottom: '24px',
      right: '24px',
      zIndex: '2147483646',
      padding: '12px 18px',
      border: 'none',
      borderRadius: '8px',
      background: 'linear-gradient(135deg, #667eea, #764ba2)',
      color: '#fff',
      fontSize: '14px',
      fontWeight: '600',
      fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
      cursor: 'pointer',
      boxShadow: '0 4px 14px rgba(102, 126, 234, 0.45)',
      transition: 'opacity 0.2s, transform 0.2s',
    });

    btn.addEventListener('mouseenter', () => {
      btn.style.opacity = '0.92';
      btn.style.transform = 'translateY(-1px)';
    });
    btn.addEventListener('mouseleave', () => {
      btn.style.opacity = '1';
      btn.style.transform = 'translateY(0)';
    });

    let needsRefresh = false;
    function offerRefresh() {
      needsRefresh = true;
      btn.disabled = false;
      btn.textContent = 'Refresh page to scan';
      btn.title = 'Refresh this Amazon page to reconnect to IEID, then scan again.';
    }

    btn.addEventListener('click', () => {
      if (needsRefresh) {
        location.reload();
        return;
      }
      btn.disabled = true;
      btn.textContent = 'Opening IEID...';

      // Open Amazon tabs can retain an old content script after an extension
      // reload. Catch both immediate API failures and later callback failures.
      try {
        if (!chrome.runtime?.id) {
          offerRefresh();
          return;
        }
        // The worker persists this selection; content scripts cannot access credentials.
        chrome.runtime.sendMessage({ action: 'prepare_single_order_scan', orderId }, response => {
          try {
            if (chrome.runtime.lastError || !chrome.runtime.id) {offerRefresh(); return;}
            btn.disabled = false;
            if (response?.error) {
              btn.textContent = 'Try opening IEID again';
              btn.title = 'Unable to save this order selection. Try again.';
              return;
            }
            btn.textContent = 'Scan with IEID';
          } catch { offerRefresh(); }
        });
      } catch {
        offerRefresh();
      }
    });

    document.body.appendChild(btn);
  }

  function init() {
    if (!ORDER_DETAILS_RE.test(location.pathname)) return;
    const orderId = getOrderId();
    if (!orderId) {
      console.log('[IEID] Order details page detected but no order ID found');
      return;
    }
    createButton(orderId);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
