# AlphaX v1.5.4 — Database and action hardening

- Adds an additive ORM-schema reconciliation pass for every existing mapped table, not just the previously known short list of columns.
- Uses safe defaults for legacy rows; columns without a reliable backfill remain nullable rather than inventing foreign-key relationships or user data.
- Handles SQLite date/time backfills without non-constant `ALTER TABLE` defaults.
- Restores mapped indexes after legacy username normalization and legacy data migrations.
- Normalizes legacy usernames case-insensitively and resolves case collisions while preserving account IDs and password hashes.
- Fixes missing `secrets` import in the Admin create-user action.
- Handles duplicate plan creation as a user-facing redirect rather than an unhandled integrity error.
- Bumps app/health/UI cache version to 1.5.4.

Validation: 62 tests pass, including schema reconciliation, legacy account preservation, unified customer/admin authentication, Admin page smoke checks, and Admin create-user action.

The actual Supabase production database was not accessible from this build environment; the additive migration runs on application startup after deployment.
