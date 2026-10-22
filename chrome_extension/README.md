# IEID Amazon Order Scraper v1.1.20

Chrome extension for importing Amazon orders and shipment tracking into IEID.
Requires Chrome 140 or newer. Retains the v1.1.19 parsing, quantity, cache,
authentication, checkpoint and sparse-update safeguards.

## Testing and versioning

The current test version is **1.1.20**. Keep development and test changes at
this version. The existing main-branch workflow handles production version bumps.

## Parser warning fix

The offscreen HTML parser explicitly permits inline CSS in detached Amazon HTML,
preventing repeated inline-style CSP errors during parsing. This permission applies
only to `amazon_parser.html`; inline scripts and remote resource loading remain
blocked, and fetched nodes are never attached to the extension's live document.

## Orders layout and pagination

- Orders now grow naturally down the page, without a short inner scroll area.
- Each page shows up to 50 orders, with Previous/Next controls above and below
  the table and a visible range and total count.
- Newest-first sorting, thumbnails and live updates continue across all pages.
  Live updates preserve your selected page; page numbers adjust if results shrink.
- The Logs tab keeps its existing scrollable layout. This viewer pagination does
  not change the Amazon scan page limit or how many orders are imported.

## Product images and popup spacing

- Product thumbnails now appear beside item names in the Orders viewer and update
  as images are discovered. Missing or failed images use a compact placeholder.
  Reopening the viewer preserves discovered images during the browser session.
- Removed the empty settings-notification space below the popup header. The
  settings confirmation still appears after saving.
- Viewer snapshots from before thumbnail support lack image URLs; scan again to populate them.

## Live Viewer and settings

- IEIDLLC website logo and dark, indigo and cyan styling in the popup, Live Viewer,
  icons, update screen and scan-order button.
- **Orders** and **Logs** tabs in the Live Viewer. One row per order, sorted by
  order date from newest to oldest. Multiple items and tracking numbers stay
  within their order row. Unknown dates sort last.
- Rows appear during discovery, then update with details, tracking and actual
  IEID import results. The last column distinguishes pending, saving, inserted,
  updated, saved, partial failure, error, skipped and stopped orders.
- **View Log** focuses the viewer's Logs tab, including when it is in another
  browser window. **View Orders** opens its Orders tab. Automatic scan startup
  opens the viewer in the background without taking focus from Amazon.
- A gear beside the popup version opens saved settings for **Fetch tracking
  details**, **Skip tracked shipments already in IEID**, **Reuse cached shipment
  links**, and **Keep orders for ZIP codes**. Save changes with **Save settings**.
  Close or Escape discards unsaved edits. Existing preferences are retained.
- The date-range explanation is behind the info button beside **Date range**.
- Viewer rows and final results survive viewer reloads and worker restarts in
  the current browser session. Interrupted imports are marked for verification,
  and resumable bulk jobs are labeled accordingly. A new scan clears the previous viewer session.

## Install or update

1. Open `chrome://extensions` and enable **Developer mode**.
2. Choose **Load unpacked** and select this repository's `chrome_extension/` folder.
3. For an existing unpacked installation, update the checkout and click **Reload**.
4. Pin IEID Order Scraper to the toolbar.

## Use

1. Sign in to IEID and Amazon in the same Chrome profile, then connect the
   extension using **Sign in with IEID**.
2. Open the gear, choose your preferences and optional ZIP filters, then save.
   **Import from IEID** fills the ZIP field; save to apply it.
3. Choose the date range and page limit. Use **0** for all pages.
4. Click **Start Scraping**, then **View Orders** or **View Log**.
5. A single-order scan always refreshes tracking and bypasses bulk ZIP/cache
   preferences, as in previous versions.

## Reading results

- **Inserted / Updated** is shown when the API response identifies that outcome.
- **Saved to IEID** means all the order's items were confirmed saved, but the
  server's mixed batch totals do not identify insert versus update per order.
- **Needs verification** means the server receipt was incomplete or its capped
  error details did not identify every result. Check IEID before retrying.
- Tracking availability is separate from import status. Amazon may no longer
  expose older tracking; those orders still import and saved tracking is preserved.
- Cancelled orders update existing website rows only. Unknown cancellations and
  ZIP-filtered orders are marked skipped. Quantity disputes are skipped for safety.

## Branding

Logo source: `IEIDGG/IEIDLLC/static/images/ieidllc-logo.png`.
Colors follow `static/css/style.css`. UI fonts use the website's Outfit family
when available and native system fallbacks; this package makes no font-network requests.
