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

The deployed backend still uses cookie-session authentication. Its compatible
hotfix is a backport from the published 1.1.12 source, versioned 1.1.16. Keep
modern account-grant releases and automatic BBOS promotion behind the existing
coordinated-release hold. This parser fix on main does not authorize publishing
the modern extension to the legacy backend.

Release numbers use three numeric components. Versions 1.1.13 through 1.1.15
were already used, so the compatible hotfix takes 1.1.16. Modern main starts
above that number; its generated post-merge version must be verified before any
future parent pin. A higher version does not authorize lifting the release hold.
