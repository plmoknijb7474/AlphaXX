# AlphaX / AlphaAPI v0.9.0

## Customer portal merge

- Merged the standalone AlphaX customer design into the original FastAPI application.
- Customer registration/login now lead to the actual authenticated `/account` portal.
- Customer portal has four sections: API Access, Usage, Plans, and About Models.
- About Models contains capability explanations and the project's local model artwork; it does not display per-model prices. Subscription plan prices remain controlled by Admin.
- Added Syria-time ambient day/evening/night theme, aurora, stars/fireflies, dust, meteors, and the interactive 3D ghost companion.
- Kept the separate admin interface under `/admin`; no admin navigation is exposed in the customer portal.
- Prepared absolute paths and ASGI startup instructions for PythonAnywhere.

## Important

This release contains source code and `.env.example`, but no production `.env`, database, provider credentials, or real admin password. Configure production secrets before starting the site.
