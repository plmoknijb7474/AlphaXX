# AlphaX 1.0.0 — Upgrade notes

## Main changes

- Replaced shared provider credential pools and route fallback chains with one encrypted provider credential per user and public model.
- Removed automatic key rotation and alternate-key/alternate-route retries. A failed provider credential returns an error; it never silently switches to another key.
- Added a model-owned `system_prompt`; the server injects it into every chat completion request for that model. Models without a configured prompt are not exposed to customers.
- Added customer-generated AlphaX gateway API keys after subscription activation and model provisioning. The full AlphaX key is shown once.
- Added an OpenCode configuration download using the OpenAI-compatible AlphaX `/v1` endpoint and the customer's AlphaX key.
- Preserved the manual payment review and subscription setup flow, and prevented duplicate open payment orders.
- Added PostgreSQL/psycopg support and a Supabase Transaction Pooler example using placeholders.
- Added xKiro as an OpenAI-compatible provider endpoint (`https://api.xkiro.com/v1`) and updated the default Y5Z upstream model ID to `qwen/qwen3.8-max`.

## Database migration

On startup, the application upgrades the existing schema, adds each model's `system_prompt`, migrates only the active primary legacy credential assignment for each user/model into the new direct credential table, and drops the obsolete pool/route/global-prompt tables. Existing unrelated account, subscription, payment, usage, and plan data are not intentionally removed.

**Back up the database before the first 1.0.0 startup.** Extra legacy pool keys, alternate/fallback routes, and shared provider-wide secrets are not retained in the new architecture. The previous active global prompt is copied into models that do not already have a model-specific prompt, as a starting point. Each model then stores its own independent prompt; review and customize them in Admin → Models & System Prompts.

Changing `DATABASE_URL` from SQLite to Supabase PostgreSQL does not transfer data. Export/import the existing data before switching production to a new Supabase database. Keep the existing production `.env`, `SECRET_KEY`, and `FERNET_KEY`; do not replace them with `.env.example`.

## xKiro key safety

No real xKiro key is included in this release. Configure a fresh key only in the individual user's model credential form after revoking any key that was exposed in chat or logs.
