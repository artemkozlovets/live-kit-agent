# Database + Migrations

> **Last Updated**: 2026-01-30  
> **Audience**: Codex (repo context)  
> **Status**: Draft

## TL;DR
- API server code depends on a small `DatabaseClient` protocol.
- DB implementation is chosen by env vars in `api_server/server/dependencies.py`.
- Migrations live in `migrations/` and are Postgres SQL.

## What this repo stores in Postgres (high-signal)
Big picture: the DB is used for **business objects** (customers/units/service orders) plus **observability** (session reports).
There is no separate “STT/TTS/LLM database” in this codebase.

Tables used by this repo:
- `customers` (customer lookup + create + update)
- `units` (fleet unit lookup + create)
- `service_orders` (create + update service orders)
- `session_reports` (store per-room session report JSON)

Where this is implemented:
- Business tables: `api_server/server/postgres_client.py`
- Session reports: `api_server/observability/session_report_store.py`

## DatabaseClient interface
- Protocol definition: `api_server/server/dependencies.py`
- Design intent:
  - Keep handlers dependency-injected (easy to test / swap DBs).
  - Return `None`/empty results instead of raising for “not found”.

## Implementations

### Postgres
- Enabled when `DATABASE_URL` is set.
- Implementation: `api_server/server/postgres_client.py`
- Field mapping notes (API → DB) are documented in the file header:
  - `service_complaint` → `customer_complaint`
  - `service_location` → `location_address`
  - `email_address` → `email`
  - `vin_number` → `vin`
- Gotcha: `get_database_client()` currently calls `psycopg2.connect(DATABASE_URL)` when invoked (no pooling).

### In-memory (non-durable)
- Enabled when `USE_IN_MEMORY_DB=1`.
- Implementation: `api_server/server/in_memory_database_client.py`
- Intended for local debugging only (state is lost on restart).

### Not implemented (explicit failures)
- When neither `DATABASE_URL` nor `USE_IN_MEMORY_DB=1` is set, `get_database_client()` returns `NotImplementedDatabaseClient` which raises `NotImplementedError` for all operations.

## Migrations
SQL migrations live in `migrations/`.

Currently:
- `migrations/001_add_nickname_and_location_address.sql`
  - Adds `units.unit_nickname` and `service_orders.location_address`
  - Adds an index on `(customer_id, unit_nickname)`
  - Uses `CREATE INDEX CONCURRENTLY` (must run outside a transaction)
- `migrations/002_add_session_reports.sql`
  - Adds `session_reports` table for programmatic agent session report exports
  - Stores one JSONB report per LiveKit room (`room_name` primary key)
  - Adds an index on `received_at DESC` for “most recent” lookups

## Related docs
- `docs/documentations/api-server.md`
