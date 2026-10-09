# Amazon purchased-item quantity recovery

On Amazon's unshipped order-details layout, a purchased row contains an empty
image anchor and a separate product-title anchor. The detail parser previously
assigned different fallback identities to those anchors and emitted both as
shipment items. Product aggregation then doubled the quantity.

The parser now counts each DOM product root and ASIN once and reads the first
nonempty product title. Separate rows without Amazon shipment IDs retain a DOM
row identity through background deduplication. Product aggregation sums each
row's quantity and cost together.

Detail enrichment requires the same ASIN quantities as explicitly observed
order-list quantities. Missing quantity badges are inferred lower bounds, so
valid split details can supply their complete quantities. A mismatch marks the
order disputed and excludes it from upload. Failed enrichment of an inferred
quantity also excludes that order. Shipment-link caches and resumable jobs use
new keys so data extracted by the old parser cannot bypass the fix.

Regression coverage includes the actual left/right purchased-grid structure,
empty image anchors, quantities greater than one, separate product prices,
rendered-tab extraction, unexpected/doubled detail quantities, valid split
quantities, and repeat API payloads in native Chromium. Fixtures use synthetic
orders and products.

Updating the extension prevents future corruption; it does not repair saved
orders. Repair existing rows against Amazon order evidence, scoped by account,
row ID, order ID and ASIN. Check the old quantities and all other fields before
updating, retain a rollback artifact, change only verified fields, and read the
rows back after commit. Do not blanket-divide an account's quantities or prices.

The original 1.1.16 candidate backported this fix to cookie-session 1.1.12.
IEIDLLC subsequently merged the modern authentication release into main.
Release numbers remain semantic MAJOR.MINOR.PATCH; 1.1.19 is the consolidated
candidate above the already-used legacy 1.1.16 and modern 1.1.17 versions. The intermediate
1.1.18 cookie-session candidate remains in history; modern 1.1.19 has a distinct
version to prevent an updater from treating different authentication clients as
identical.
Automatic BBOS promotion stays held. Verify the generated final version commit
and the backend/client compatibility pair before publication.

## Consolidated 1.1.19 update

BBOS PRs #20 and #21 contain identical quantity-fix changes in all five
extension source files. #20 now consolidates that fix with the October 8 live
scrape corrections; #21 is superseded. IEIDLLC main now includes account
authentication (#119), so the consolidated
PR preserves the modern authentication base from #21 and targets BBOS main.
IEIDLLC #139 pins this modern client together with the current modern backend.
The earlier cookie-session candidate remains in history for legacy deployments;
it must not replace the client after the account authentication cutover.

Additional fixes recover delivery-level metadata without crossing sibling
purchased-items blocks, read enhanced order-card badges, accept complete
unshipped HTML, and avoid false tracking-page sign-in errors from navigation.
Active shipments require tracking to be Shipped; untracked shipments are Not
yet shipped. Delivered and Cancelled remain terminal states. A product with a
tracked split remains Shipped while another split is pending, without replacing
saved tracking arrays with a partial list.

Validation adds 16 isolated Chromium regressions using sanitized captures and
synthetic split deliveries, plus the existing JavaScript suites and native
extension repeat-upload smoke test. The live three-page scan of the earlier
local fix updated 16 product rows without false sign-in errors; a subsequent
status-fix scan encountered a real Amazon sign-in page. Release validation is
isolated and does not itself repair production data.
