# AlphaAPI v0.8.2 — English Ambient UI

## Visual updates
- Converted the site UI to English and left-to-right layout.
- Added a minimal cyan jelly companion with two eyes only, dimensional gradients, inner highlights, soft contact shadow, pointer awareness, and a tap-to-bounce reaction.
- Added a slow aurora layer, 24 drifting fireflies, 32 subtle magic-dust particles, and occasional shooting stars.
- Kept the ambient layers non-interactive so they never block forms, links, or navigation.
- Respects `prefers-reduced-motion`.

## Functional scope
- Preserved the FastAPI routes, database models, payment workflow, quota handling, provider routing, and admin actions.
- Translated customer-facing validation messages and default seeded model descriptions/skills/benchmark notes.
- Existing form buttons remain connected to their backend routes. Model-profile dialog controls remain connected to the site JavaScript. No business actions were replaced with decorative controls.
- Admin-entered dynamic descriptions and payment instructions are displayed as stored; this update does not silently rewrite user-managed database content.

## Validation
- Python compile check: passed.
- Jinja template parse check: 17 templates passed.
- Test suite: 25 passed.
