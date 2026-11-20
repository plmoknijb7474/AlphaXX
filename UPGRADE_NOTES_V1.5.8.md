# Upgrade Notes — AlphaX v1.5.8

1. The first startup creates/activates fixed provider connectors for APInex and Regolo.
2. Migration marker `apinex_regolo_model_routes_v10` routes Y5Z Coder Pro to APInex `free/deepseek-v4-pro-0813` and AlphaX Pro to Regolo `gemma4-31b`.
3. AlphaX Max remains on OpenRouter `google/gemma-4-31b-it:free`.
4. The migration preserves model IDs, public names, prompts, grants, subscriptions, customer gateway API keys, usage, and payment data.
5. Existing Y5Z OpenRouter and AlphaX Pro Google credentials are retained but deactivated with `PROVIDER_CHANGED`; administrators add new APInex and Regolo credentials. AlphaX Max keys remain active.
6. The two migrated models have no upstream model fallbacks. Provider-key rotation remains per customer/model.
7. APInex and Regolo requests use provider-specific `reasoning_effort` low/medium/high mapping.

Do not change `FERNET_KEY`, `SECRET_KEY`, or `DATABASE_URL` as part of this model routing update. See `RENDER_APINEX_REGOLO_SETUP_AR.md`.
