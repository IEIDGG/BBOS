# IEIDLLC integration

BBOS and IEIDLLC run on the same Docker host. BBOS therefore persists shipped
orders directly into IEIDLLC's `public.scanned_orders` table rather than
introducing another network service boundary.

See [`api/README.md`](../api/README.md) for the required environment variables
and persistence contract.
