# AlphaX v1.5.6 — Render PostgreSQL Deployment

- Updated Render deployment documentation to use Render-managed PostgreSQL.
- Added a full Arabic guide for creating a Render PostgreSQL database and connecting the existing web service through its Internal Database URL.
- Clarified that changing `DATABASE_URL` does not migrate existing Supabase data.
- Documented same-workspace/same-region requirements and free PostgreSQL expiration limits.
- Application database layer already supports PostgreSQL through SQLAlchemy + psycopg; no database-driver replacement is required.

No database contents are copied or deleted by this release. Keep the existing `FERNET_KEY` and all other production secrets unchanged.
