# IEIDLLC scanned-order persistence

BBOS writes shipped Best Buy orders directly to IEIDLLC's shared PostgreSQL
`public.scanned_orders` table. It does not call an HTTP ingestion endpoint.

Set these variables in the BBOS container:

- `POSTGRES_HOST`
- `POSTGRES_PORT`
- `POSTGRES_DB`
- `POSTGRES_USER`
- `POSTGRES_PASSWORD`
- `IEIDLLC_USER_ID`
- `IEIDLLC_MONEY_CUTOVER_GATE_FILE` (the exact shared sentinel path used to
  pause local SQLite writers during the coordinated money cutover)

The local `api_config.json` file retains only the `enabled` toggle. Legacy URL,
API-key, and buying-group fields are ignored and removed on the next save.

Each tracking number is idempotently upserted using
`(user_id, provider='bbos', source_key=<order_number>_<tracking_number>)`.
Dollar text is parsed exactly and persisted as integer `amount_minor` plus
`currency_code='USD'`. Invalid or sub-cent values fail closed. When the gate
file exists, all local SQLite writes fail closed until the cutover removes it.
