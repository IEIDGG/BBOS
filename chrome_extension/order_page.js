(() => {
  const ORDER_DETAILS_RE = /\/your-orders\/order-details/i;
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

    btn.addEventListener('click', () => {
      btn.disabled = true;
      btn.textContent = 'Opening IEID...';
      console.log('[IEID] Scan requested for order', orderId);

      chrome.storage.local.set({ pendingSingleOrderId: orderId }, () => {
        chrome.runtime.sendMessage(
          { action: 'prepare_single_order_scan', orderId },
          () => {
            btn.disabled = false;
            btn.textContent = 'Scan with IEID';
            if (chrome.runtime.lastError) {
              console.error('[IEID] Failed to open extension:', chrome.runtime.lastError.message);
            }
          }
        );
      });
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
