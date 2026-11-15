# AlphaX v1.5.0

- Corrected the built-in alias assignment: Y5Z Coder Pro → `gemma-4-26b-a4b-it`; AlphaX Pro → `gemini-3.6-flash`; AlphaX Max → `gemma-4-31b-it`.
- Added one-time V8 DB migration; preserves per-model System Prompts, customer Google credentials, grants, subscriptions, payment records, AlphaX keys and usage history.
- Kept all built-in and custom models on Google AI Studio / native Gemini API.
- Expanded Admin → Models & Prompts so Admin can add arbitrary Google AI Studio model IDs with a unique public alias and a mandatory separate System Prompt, reasoning options, variants, defaults, fallbacks and public profile.
- Added server-side validation for public aliases, duplicate IDs, provider choice, Google model IDs and required System Prompts.
- Added `scripts/backup_sqlite_before_supabase.py` to create a verified SQLite snapshot plus `.env` backup before switching DBs.
- Added automatic latest-backup selection for the migration preview/apply tool.
- Added `scripts/configure_supabase.py`: hidden interactive input, Supabase URI validation, SSL enforcement, live connectivity check, empty-public-schema check, automatic `.env` backup, and safe replacement of `DATABASE_URL`.
- Added Supabase and PythonAnywhere instructions.
- Updated OpenCode variants to use Google `thinking_level` fields.
- Updated cache-busting version to 1.5.0 and health endpoints.
- Local tests use mocked provider calls; no live Google AI Studio key or Supabase database was available for integration tests.
