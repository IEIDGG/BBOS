# Enable scanned-order persistence

1. Configure the PostgreSQL and IEIDLLC owner variables listed in
   [`api/README.md`](../api/README.md).
2. Start BBOS on the shared Docker network.
3. Enable automatic persistence from the BBOS menu.
4. Run the health check; it must report PostgreSQL as connected.

Writes are idempotent by IEIDLLC owner and BBOS order number.
