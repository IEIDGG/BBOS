// Freeze the date boundary in checkpoints so a resumed scan uses the same range.
function createOrderHistoryPlan(filter = 'months-12', now = new Date()) {
  if (/^year-\d{4}$/.test(filter)) return { filters: [filter], cutoffDate: '' };
  if (filter !== 'months-12') throw new Error('Unsupported Amazon date range');
  const year = now.getFullYear();
  const month = now.getMonth();
  const day = Math.min(now.getDate(), new Date(year - 1, month + 1, 0).getDate());
  const cutoffDate = `${year - 1}-${String(month + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
  return { filters: [`year-${year}`, `year-${year - 1}`], cutoffDate };
}

function filterOrderHistory(orders, plan) {
  if (!plan.cutoffDate) return orders;
  return orders.filter(order => {
    const text = String(order.orderDate || '').trim();
    const parsed = new Date(text);
    if (!text || Number.isNaN(parsed.getTime())) throw new Error(`Unrecognized order date for ${order.orderId || 'Amazon order'}`);
    const date = /^\d{4}-\d{2}-\d{2}$/.test(text) ? text
      : `${parsed.getFullYear()}-${String(parsed.getMonth() + 1).padStart(2, '0')}-${String(parsed.getDate()).padStart(2, '0')}`;
    return date >= plan.cutoffDate;
  });
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { createOrderHistoryPlan, filterOrderHistory };
}
