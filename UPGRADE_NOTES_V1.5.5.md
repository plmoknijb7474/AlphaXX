# AlphaX v1.5.5 — PostgreSQL sequence and registration error fix

- Synchronizes PostgreSQL serial/identity integer primary-key sequences to existing MAX(id) at startup, without moving a sequence backwards.
- Classifies only an actual users.username unique-constraint violation as a taken username.
- Other database integrity failures now receive a generic database error and safe diagnostic logging without SQL parameters.
- No existing customer data, subscriptions, credentials, or environment settings are intentionally changed.
