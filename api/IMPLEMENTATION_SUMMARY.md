# Direct persistence implementation

The former HTTP submission adapter now preserves the existing UI surface while
writing directly to IEIDLLC PostgreSQL through `ScannedOrderWriter`.

Canonical behavior, configuration, idempotency, and failure rules are documented
in [README.md](README.md). The old backend URL, API-key, and buying-group routing
are intentionally no longer part of the runtime design.
