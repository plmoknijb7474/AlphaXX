# AlphaX v1.5.8 — APInex DeepSeek + Regolo Gemma

## Provider route changes

- Y5Z Coder Pro → APInex `free/deepseek-v4-pro-0813` at `https://api.apinex.bond/v1`.
- AlphaX Pro → Regolo `gemma4-31b` at `https://api.regolo.ai/v1`.
- AlphaX Max remains on OpenRouter `google/gemma-4-31b-it:free`.
- Google AI Studio connector remains available for custom Gemini model configurations.

## Thinking and reasoning

- APInex and Regolo requests use the documented `reasoning_effort` field.
- Y5Z and AlphaX Pro expose low / medium / high reasoning effort in customer metadata and variants.
- AlphaX normalizes client `thinking_level` and `reasoning_effort` inputs to the provider field.
- When reasoning is disabled through the AlphaX boolean control, the new routes use their lowest supported effort (`low`) because these documented routes do not expose a `none` level.
- Provider reasoning text is preserved in compatible responses and streams when supplied upstream.

## Key safety and rotation

- Credentials stay encrypted per customer and per model.
- V10 disables (but does not delete) Y5Z OpenRouter keys and AlphaX Pro Google keys because they cannot authenticate to the new providers.
- AlphaX Max OpenRouter credentials remain active.
- Per-customer key rotation remains; keys are not shared between customers.
- No upstream model fallback is configured for Y5Z or AlphaX Pro, preventing hidden paid-model fallback.

## Free-tier notes

- APInex lists DeepSeek V4 Pro free route at $0 per 1M input/output tokens, with account rate limits (currently 15 RPM on free tier).
- Regolo's Gemma 4 31B is included in a 30-day trial allowance with daily usage limits; not a permanent zero-cost route.

## Preserved features

Customer aliases, unified login, subscriptions, admin provisioning, system prompts, grant checks, quota accounting, usage tracking, payments, AlphaX API keys, Render PostgreSQL support, streaming, tool calls, and per-customer API-key rotation remain in the project. The migration does not delete customer data.
