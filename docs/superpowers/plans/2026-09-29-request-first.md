# Request-first Amazon extraction

Goal: retrieve order details and tracking via authenticated HTML requests before opening tabs, retaining the existing extraction and fallback behavior.

Approved design: the preceding conversation's request-first flow. Existing Amazon host permissions permit fetch; one offscreen extension document supplies DOM parsing. No remote HTML is inserted into a live page. Tabs remain the fallback for unavailable or incomplete HTML. Account-scoped shipment identities are cached for seven days only after all shipments return tracking; changed list quantities/statuses invalidate the cache and manual scans always refresh details.

Implementation:
- [x] Add a request transport with bounded fetch, URL validation, one concurrent offscreen creation, and fallback tests (network failure, sign-in, incomplete details, unknown tracking, cancellation/stop).
- [x] Expose existing detail/tracking extractors for detached documents; add an offscreen parser with scripts/assets blocked and include all runtime files in package checks.
- [x] Integrate request-first detail discovery, single-order scans, and tracking batches; preserve quantity coverage and existing tracking on failures.
- [x] Run regressions and live read-only probes on older/split orders where authentication permits; update Downloads and existing PR with precise verification limits.

Review focus: no cross-order results; no partial quantity replacement; no script/image execution; no orphan fallback tabs on stop; no duplicate offscreen creation under four concurrent requests.

Verification: request transport, detached HTML parser, cache, existing extraction regressions, package integrity, and diff checks passed. Live Brave verification remains pending user availability; no live success claimed.
