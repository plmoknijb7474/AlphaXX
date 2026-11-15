# AlphaX v1.2.0 — Multi-key routing and OpenCode

## Main changes

- Multiple encrypted upstream credentials per user/model. Admin can append a batch of keys and independently disable each one.
- Automatic key failover among active keys belonging to the same user and model. Recently failing keys receive a temporary cooldown.
- Model-level fallback for Y5Z Coder Pro: xKiro Qwen 3.7 Max first, then Qwen 3.6 Max Preview on capacity/availability failure, using the same user's assigned keyset and keeping the same public alias.
- Multiple independent AlphaX customer API keys. Creating a new AlphaX key does not revoke older keys; each key can be revoked individually.
- OpenCode v2 config exposes AlphaX only, public aliases only, and per-model variants where supported.
- Correct default routes: AlphaX Pro -> OdiRouter (`gemini-2.5-pro`, provisional until confirmed in the account catalog); AlphaX Max -> Google AI Studio (`gemma-3-27b-it`).
- Per-model Admin-owned System Prompt remains mandatory and is injected server-side for every request.

## Upgrade precautions

1. Back up the active SQLite/PostgreSQL database and `.env` before deployment.
2. Preserve the existing `SECRET_KEY` and `FERNET_KEY`. Do not rotate `FERNET_KEY` during upgrade.
3. The schema migration removes the old uniqueness constraint on `(user_id, model_id)` in `user_model_credentials`; existing direct customer credentials are retained. The retired global Pool tables are not reintroduced.
4. The one-time V5 catalog migration remaps only known bundled provider/model combinations to the intended provider defaults. Admin-customized unknown provider/model IDs are preserved.
5. The ZIP contains `.env.example` only and does not include real credentials or database data.
6. PostgreSQL/Supabase is supported but requires the operator's own `DATABASE_URL`; no external Supabase project was connected during this build.

## Provider availability caveats

- xKiro IDs are configured exactly as `qwen/qwen3.7-max:free` and `qwen/qwen3.6-max-preview:free`.
- OdiRouter base URL is `https://api.odirouter.ai/v1`. Confirm the exact Gemini 2.5 Pro model ID for your OdiRouter account with `GET https://api.odirouter.ai/v1/models/catalog?keyword=gemini-2.5-pro` and `Authorization: Bearer YOUR_ODIROUTER_KEY`. The seed value `gemini-2.5-pro` is provisional; use the returned exact ID in Admin → Models & System Prompts if different.
- The requested Google AI Studio model is configured as `gemma-3-27b-it`. Google's current Gemini API hosted-Gemma guide currently documents Gemma 4 31B and 26B A4B as supported hosted models, not Gemma 3 27B. The requested Gemma 3 model therefore needs an account-level/API availability test; it was not silently replaced.

## Validation

Local project tests are run against mocked provider responses and local SQLite. They do not constitute a successful live request to xKiro, OdiRouter or Google AI Studio. See the release guide for commands and the complete flow.


## Version 1.2.1 — AlphaX Max Gemma 4 update

- AlphaX Max now routes to Google AI Studio / Gemini API model ID `gemma-4-26b-a4b-it`.
- Added a one-time V6 data migration that upgrades only the known built-in Gemma 3/Gemma 4 Google AI Studio route. Administrator-custom upstream IDs/providers remain untouched. Existing System Prompt and user-specific provider keys are preserved.
- Enabled model-specific thinking variants: `thinking-off` sends `thinkingLevel: minimal`; `thinking-on` sends `thinkingLevel: high`.
- Enabled image input and function calling in the customer/OpenCode capability description.
- Updated OpenCode configuration generation, tests, and Arabic/PythonAnywhere documentation.
