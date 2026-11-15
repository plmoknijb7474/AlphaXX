# AlphaX v1.5.0 — PythonAnywhere

- Project: `/home/AlphaX/alpha_deploy/AlphaAPI`
- Virtualenv: `/home/AlphaX/.virtualenvs/alphax-venv`
- Domain: `AlphaX.pythonanywhere.com`

## Built-in Google AI Studio models

| Public alias | Google model ID | Thinking |
|---|---|---|
| Y5Z Coder Pro | `gemma-4-26b-a4b-it` | minimal / high |
| AlphaX Pro | `gemini-3.6-flash` | minimal / low / medium / high |
| AlphaX Max | `gemma-4-31b-it` | minimal / high |

The one-time V8 catalog migration applies the above model assignments. It preserves model-specific System Prompts, existing Google credentials, user grants, subscriptions, payment orders, customer AlphaX keys and usage history.

## Add your own model

Admin → Models & Prompts → Add a Model. Enter the customer-facing name and ID, exact Google model ID, a required independent System Prompt, supported reasoning levels and defaults. Then add customer-specific Google AI Studio keys and grants under each customer account. New model IDs remain public aliases; upstream IDs are never added to OpenCode config.

## Configure Supabase

First, while `.env` still points to SQLite, create a final DB and `.env` backup:

```bash
cd /home/AlphaX/alpha_deploy/AlphaAPI
source /home/AlphaX/.virtualenvs/alphax-venv/bin/activate
python scripts/backup_sqlite_before_supabase.py
python scripts/configure_supabase.py
```

Paste the Supabase PostgreSQL URI when prompted (input hidden). The script tests the connection, requires an empty `public` schema, backs up `.env`, and writes `DATABASE_URL` only after validation. Then run `python scripts/migrate_sqlite_to_supabase.py` for a read-only preview, followed by `python scripts/migrate_sqlite_to_supabase.py --apply` only after reviewing the source path and row counts. See `SUPABASE_SETUP_AR.md`.

**PythonAnywhere requires a paid plan for external PostgreSQL connections.** On a free account the outbound network restrictions can block Supabase even when its URI is valid.

Never replace the current `SECRET_KEY` or `FERNET_KEY`, and do not delete SQLite until Supabase login, user keys, payment history, and API requests are verified.
