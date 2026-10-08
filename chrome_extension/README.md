# IEID Amazon Order Scraper v1.1.19

Chrome extension for importing Amazon order and tracking details into IEID.

## 1.1.19 fixes

Retains the 1.1.16 purchased-row quantity fix and cache safeguards. Enhanced
order cards now read their quantity badges, and purchased items retain their
delivery-level status and tracking link. Complete unshipped HTML and valid
no-tracking outcomes avoid unnecessary tab retries. Tracking pages require an
actual credential form before reporting that Amazon sign-in is required.

An active shipment is Shipped only when it has a tracking number; otherwise it
is Not yet shipped. Delivered and Cancelled states remain available.

## Install

Requires Chrome 140 or newer to protect account credentials from content scripts. Update Chrome before installing or updating the extension.

1. Unzip the downloaded extension folder.
2. Open Chrome and go to `chrome://extensions`.
3. Turn on Developer mode.
4. Click Load unpacked.
5. Select the unzipped extension folder.
6. Pin IEID Order Scraper from the Chrome toolbar.

## Use

1. Sign in to IEID in Chrome.
2. Sign in to Amazon in the same Chrome profile.
3. Open the extension, click **Sign in with IEID**, and approve the connection.
4. Choose the order year and optional page limit.
5. Optionally enter ZIP codes to keep. Leave ZIP codes blank to import all scraped orders.
6. Leave tracking enabled when you want carrier and tracking numbers.
7. Click Start Scraping.

If Amazon asks for sign-in or verification, complete that page first and run the scraper again.
