# AlphaX v1.3.0 — Admin UI and Supabase readiness

## Changes
- Refreshed the authenticated admin workspace with a simpler four-item primary navigation and grouped advanced settings.
- Rebuilt the dashboard around the main workflow: orders, payment review, customers, and models/prompts.
- Unified admin styling with the cyan/blue AlphaX customer theme and improved narrow-screen navigation/forms/tables.
- Bumped all CSS/JavaScript asset URLs to `v=1.3.0` to invalidate stale browser caches.
- Kept the existing customer portal's four-page structure and ghost/atmosphere design; only its asset version was bumped.
- Normalized PostgreSQL/Supabase URLs to SQLAlchemy's `postgresql+psycopg` driver, enforce SSL, and disabled psycopg prepared statements for pooler compatibility.
- Fixed legacy schema upgrade DDL to use PostgreSQL `TIMESTAMP WITH TIME ZONE` instead of SQLite-only `DATETIME` for newly added timestamp fields.
- Added a genuinely read-only preview and batched SQLite-to-Supabase migration utility; it refuses to write into any non-empty public target schema, performs column preflight before schema creation, and preserves the SQLite source.

## Retained backend behavior
- Multiple encrypted provider keys per customer/model, priority-based automatic retry/failover, and coder upstream-model fallback.
- Independent required System Prompt for every public model, injected by the gateway.
- Multiple independent AlphaX API keys per subscriber.
- Manual payment review and activation gates.
- OpenCode config uses public AlphaX model aliases and exports no upstream credentials.

## Deployment notes
- Do not overwrite `.env`, SQLite database files, uploads, or `SECRET_KEY` / `FERNET_KEY`.
- Supabase is supported but is not configured until the owner adds the project's connection string to the private `.env` and runs the migration script.
- Run the migration script without `--apply` first; only add `--apply` after reviewing the planned table/row counts and confirming Supabase is empty.
- Provider connectivity requires real provider credentials and should be tested after deployment; unit tests use mocked upstream providers.
