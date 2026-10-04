# BBOS

BBOS extracts retailer orders, products, cancellations, and shipment tracking.
It contains a Python email importer and the **IEID Order Scraper** Chrome extension
for Amazon. This README is the starting map for contributors and coding agents:
use the relevant paths below to keep repository exploration and context small.

## Data flow and boundaries

- **Email:** IMAP → `EmailConnector` → retailer handlers → `EmailProcessor` and
  parsers → `OutputHandler` → local SQLite; CSV output is optional. The console
  supports Best Buy, Costco, and Xbox promotional codes. Its Amazon processing
  action is a placeholder, although Amazon email parsing modules exist. Apple
  handlers also exist for integration use; they are not a console menu option.
- **Monitoring:** `ContinuousMonitor` runs the Best Buy email pipeline every
  30 seconds. Tracking submission to a separately configured backend is optional
  and disabled by default; BBOS does not include that backend server.
- **Amazon:** popup or order-page button → Manifest V3 background worker →
  authenticated Amazon requests → detached HTML parsing, with browser-tab
  fallback → product/shipment payloads → IEID API. Scan checkpoints and shipment
  discovery caches live in Chrome storage. The extension requires IEID and Amazon
  sessions; it sends extracted data to `https://ieidgg.com`.

Keep orders, products, shipments, and tracking distinct. One order can contain
multiple shipments of the same ASIN. Preserve shipment and line-item identifiers
when merging or deduplicating, and keep partial extraction/upload outcomes visible.

## Find the code for your task

| Task | Start with |
| --- | --- |
| Console routing or monitoring | [main.py](main.py), [continuous_monitor.py](continuous_monitor.py) |
| IMAP connections, searches, batching, or processed-UID cache | [email_processing/connector.py](email_processing/connector.py) |
| MIME decoding or retailer HTML extraction | [email_processing/processor.py](email_processing/processor.py), [email_processing/parsers/](email_processing/parsers/), [html_selectors.json](email_processing/parsers/html_selectors.json) |
| Reconcile confirmation, cancellation, and shipment emails | [email_processing/handlers.py](email_processing/handlers.py) |
| SQLite schema, persistence, or CSV output | [config/settings.py](config/settings.py), [core/database.py](core/database.py), [output/file_handlers.py](output/file_handlers.py) |
| Email profiles or filenames | [core/profile_manager.py](core/profile_manager.py), [core/utils.py](core/utils.py) |
| Optional tracking API configuration and submission | [api/submitter.py](api/submitter.py) |
| Amazon scan state, authentication, upload, or UI | [background.js](chrome_extension/background.js), [popup.js](chrome_extension/popup.js), [order_page.js](chrome_extension/order_page.js), [log.js](chrome_extension/log.js) |
| Amazon request transport or HTML parsing | [amazon_requests.js](chrome_extension/amazon_requests.js), [amazon_parser.js](chrome_extension/amazon_parser.js), [scraper.js](chrome_extension/scraper.js), [order_detail_scraper.js](chrome_extension/order_detail_scraper.js), [tracking_scraper.js](chrome_extension/tracking_scraper.js), [account_scraper.js](chrome_extension/account_scraper.js) |
| Shipment identity, scan range, or caches | [scrape_core.js](chrome_extension/scrape_core.js), [order_history.js](chrome_extension/order_history.js), [shipment_cache.js](chrome_extension/shipment_cache.js) |
| Updates or versioning | [core/updater.py](core/updater.py), [update.js](chrome_extension/update.js), [update_helpers.js](chrome_extension/update_helpers.js), [manifest.json](chrome_extension/manifest.json), [bump_scraper_version.py](scripts/bump_scraper_version.py) |
| Dependencies or verification | [pyproject.toml](pyproject.toml), [uv.lock](uv.lock), [tests/](tests/), [CI workflow](.github/workflows/ci.yml) |

Search within the relevant paths first, then follow their imports/callers and
matching tests. Prefer targeted searches such as `rg -n 'shipmentId' chrome_extension`
over loading the whole repository. Treat source and tests as authoritative;
older guides under `docs/` and `api/` include historical setup and behavior.

## Run locally

### Python email importer

With Git, `uv`, and Python 3.11+ available:

```sh
git clone https://github.com/IEIDGG/BBOS.git
cd BBOS
uv sync --locked
uv run --locked python main.py
```

Run from the repository root so relative profile, cache, and output paths resolve
correctly. Use the interactive menu to select a service, add/select an email
profile, choose a mailbox folder, and set the date range. Profiles support Gmail,
Proton Mail Bridge, and iCloud; use the credentials required by your mail provider.
Proton Bridge must be running; its host/port defaults are `127.0.0.1:1143`,
overridable with `PROTON_BRIDGE_HOST` and `PROTON_BRIDGE_PORT`.

Windows users can run [install.bat](install.bat), then [run.bat](run.bat).
There is no `requirements.txt` or profile-management CLI flag interface.

### Amazon extension

1. Open `chrome://extensions`, enable **Developer mode**, and **Load unpacked**
   using this repository's `chrome_extension/` folder.
2. Sign in to IEID and Amazon.com in the same Chrome profile.
3. Open **IEID Order Scraper**, select the date range/page limit and optional ZIP
   filters, then click **Start Scraping**. An Amazon order-details page also offers
   **Scan with IEID** for a single order.

Complete any Amazon sign-in/verification prompt before retrying. Check the
extension log for failed uploads, incomplete tracking, or page-limit results.
IEID authentication, storage, and package endpoints are provided by the external
IEID service; cloning BBOS does not create an IEID account or run that service.

## Configuration and public contributions

- **Email:** [config/profiles.json.example](config/profiles.json.example) describes
  the local `config/profiles.json` format. Profiles store credentials in plain
  JSON. Server settings, search criteria, database schemas, and output toggles are
  in `config/settings.py`; CSV output is disabled by default.
- **Tracking API:** local `api/api_config.json` controls `api_url`, `api_key`,
  `enabled`, and ZIP/state buying-group mappings. [APIConfig](api/submitter.py)
  supplies disabled defaults when the file is absent. Submission uses `X-API-Key`
  with `/bestbuy/submit-order` or `/bestbuy/submit-orders` on your backend.
- **Extension:** hosts/permissions are in `chrome_extension/manifest.json`;
  `API_BASE` is set in `background.js`, `popup.js`, and `update.js`. Updating through
  the extension requests write access to its loaded folder. Its version comes
  from the manifest; a [workflow](.github/workflows/bump-scraper-version.yml) bumps
  the patch after extension changes reach `main`. Python's updater separately
  targets the `FastAPI-Config` branch and reads `CURRENT_VERSION`.

Use accounts and mailboxes you are authorized to access. Keep passwords, API keys,
session cookies, order exports, databases, and private logs out of commits and
public issues. The profile/API files and some generated files are ignored by Git;
check `git status` before committing other output. Add sanitized fixtures and
include the relevant version, reproduction steps, and redacted errors in
[issues](https://github.com/IEIDGG/BBOS/issues) and pull requests.

## Verify changes

Run from the repository root; these checks do not require live account credentials:

```sh
uv run --locked --with pytest==9.1.1 python -m pytest -o pythonpath=. tests -q
node tests/test_scrape_core.js
node tests/test_package_integrity.js
uvx --from ruff==0.16.2 ruff check .
uvx --from ruff==0.16.2 ruff format --check .
uvx --from ty==0.0.70 ty check --output-format github .
```

Use Node.js 20 for the extension checks. `test_scrape_core.js` also loads the
transport, pagination, cancellation, single-order, shipment, and cache suites.
The [CI workflow](.github/workflows/ci.yml) defines the full checks, including
detached-HTML/UI tests with `linkedom`, an unpacked Chromium smoke test with
Playwright, and Windows installation. Check that workflow for current tool pins.

## License

[Apache License 2.0](LICENSE).
