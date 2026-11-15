# AlphaX v1.4.0 — Google AI Studio only

- Removes xKiro, OdiRouter, and OpenRouter as active provider choices.
- All three public aliases use the Google AI Studio native Gemini API adapter.
- AlphaX Pro now routes to `gemini-3.6-flash`; reasoning effort: minimal, low, medium, high.
- Y5Z Coder Pro now routes to `gemma-4-31b-it`; thinking: minimal/high.
- AlphaX Max remains on `gemma-4-26b-a4b-it`; thinking: minimal/high.
- Y5Z Coder Pro's earlier Qwen model fallback is removed. Customer-specific Google API keys rotate for retryable key/service failures; no shared key pool exists.
- Existing per-user credentials attached to Y5Z Coder Pro and AlphaX Pro are disabled during the one-time V7 migration because they were entered for different providers and cannot safely be sent to Google. The encrypted records are retained for recovery/audit. Admins must add Google AI Studio keys for those user/model assignments. AlphaX Max Google keys remain active.
- Existing per-model System Prompts, user grants, subscriptions, customer API keys, payment history and usage records are preserved.
- Legacy provider rows are removed from the database after model reassignment. Other admin-created models that depended on removed providers are disabled and reassigned to the Google provider pending admin review.
- The provider admin page now exposes Google AI Studio only; adding other provider endpoints is disabled.
- Cache-busting updated to v1.4.0.

The model IDs `gemini-3.6-flash`, `gemma-4-31b-it`, and `gemma-4-26b-a4b-it` are documented Google Gemini API model identifiers. Live availability still depends on the AI Studio project, API key, region, quota, and access policy.
