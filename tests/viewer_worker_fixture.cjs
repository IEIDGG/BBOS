const {ViewerOrders} = require('../chrome_extension/viewer_state.js');

// Supply real display-state behavior to tests that execute selected worker functions.
module.exports = function viewerWorkerFixture() {
  const viewerOrders = new ViewerOrders();
  return {
    viewerOrders,
    viewerReady: Promise.resolve(),
    viewerChanged() {},
    updateViewerOrders(orders, stage) { viewerOrders.upsert(orders, stage); },
    setViewerStatus(id, status, message) { viewerOrders.setStatus(id, status, message); },
  };
};
