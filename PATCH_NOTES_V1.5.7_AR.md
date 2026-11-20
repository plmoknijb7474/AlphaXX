# AlphaX v1.5.7 — OpenRouter Gemma Routing

- Added built-in OpenRouter provider (`https://openrouter.ai/api/v1`, OpenAI-compatible).
- Routed only Y5Z Coder Pro to `google/gemma-4-26b-a4b-it:free` and AlphaX Max to `google/gemma-4-31b-it:free`.
- Kept AlphaX Pro on Google AI Studio / Gemini 3.6 Flash.
- Added one-time database migration V9. Previous per-customer Google keys attached to the two Gemma models are disabled but retained (not deleted); admins must add OpenRouter keys for those model/user assignments.
- Mapped Gemma minimal to OpenRouter `reasoning.effort=none` and high to `reasoning.effort=high` for regular and streaming requests.
- Added provider admin UI, provider-aware model creation/update validation, and OpenRouter-specific key entry guidance.
- No global OPENROUTER_API_KEY environment variable is required; credentials remain encrypted per customer and model.
