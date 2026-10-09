# Amazon live-layout regressions

Sanitized Amazon captures from October 8, 2026 cover purchased rows, enhanced
multi-product order cards and an ordered tracking page. Recipient/account data,
embedded scripts and session attributes are removed; order IDs are synthetic.
The hidden Sign in text represents the navigation that caused a false auth error.

Run `node tests/amazon_live_regressions/regression.cjs` with Playwright available
on `NODE_PATH` and its Chromium installed. Optionally set `CHROMIUM_EXECUTABLE`
or `SCRAPER_DIR`. The browser aborts every network request and parses local HTML.
CI runs this suite alongside the unpacked-extension smoke test.
