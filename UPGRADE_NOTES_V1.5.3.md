# AlphaX v1.5.3 — Legacy users table schema repair

- Adds the missing `users.active` column during startup when upgrading older/custom PostgreSQL or SQLite databases.
- Existing rows receive `active = TRUE` so valid customer accounts are not locked out by a missing flag.
- If an older schema has `is_active`, its values are copied into the new `active` column before normal use.
- Null values in an existing `active` column are normalized to `TRUE`.
- Existing usernames, emails (internal legacy compatibility), password hashes, subscriptions, payment records, usage records, and API keys are preserved.
- Keeps username-and-password-only customer registration and the shared admin/customer login page from v1.5.2.

No database reset is required. Keep the existing Render environment variables and encryption keys unchanged.
