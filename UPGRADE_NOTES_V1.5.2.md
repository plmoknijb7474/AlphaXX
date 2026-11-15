# AlphaX v1.5.2 — Username-only customer accounts

- Customer registration and sign-in now use only a username and password. No email address is requested.
- Usernames are 3–30 characters, lowercase-normalized, and may contain letters, numbers, dots, hyphens, and underscores. Passwords must contain at least 10 characters.
- A missing account is reported separately from a wrong password; duplicate usernames are rejected with a clear message.
- The unified sign-in form still routes the configured administrator username to the admin dashboard.
- Existing customers are preserved. On upgrade, their username is derived from the portion of their old email address before `@`; if that is invalid or already taken, a unique fallback is generated. They continue using their existing password.
- The legacy database email column is retained internally to avoid destructive schema changes and maintain compatibility. New users receive an internal placeholder value; it is never requested or used for customer sign-in.
- No customer, subscription, payment, usage, or API-key records are deleted by this upgrade.
