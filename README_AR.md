# AlphaX v1.5.10

AlphaX is a multi-customer, OpenAI-compatible gateway. Public aliases stay stable while upstream provider IDs and customer-specific API credentials remain server-side and encrypted.

## Built-in public models

| Public alias | Provider | Upstream model ID | Thinking levels | Free-access status |
|---|---|---|---|---|
| Y5Z Coder Pro | APInex | `free/deepseek-v4-pro-0813` | ON/OFF + low / medium / high | APInex free tier route; account limits apply |
| AlphaX Pro | Regolo | `gemma4-31b` | low / medium / high | Regolo limited trial; not permanently free |
| AlphaX Max | Google AI Studio | `gemini-3.6-flash` | minimal / low / medium / high | Google AI Studio quotas and account limits apply |

Endpoints: APInex `https://api.apinex.bond/v1`; Regolo `https://api.regolo.ai/v1`; Google AI Studio native Gemini API `https://generativelanguage.googleapis.com/v1beta`.

## Reasoning and request mapping

- Y5Z Coder Pro exposes a separate ON/OFF switch. OFF sends DeepSeek's `thinking: {"type":"disabled"}`; ON sends `thinking: {"type":"enabled"}` and the selected `reasoning_effort` (`low`, `medium`, `high`).
- AlphaX Pro accepts `low`, `medium`, `high`, mapped to Regolo's `reasoning_effort` field.
- AlphaX Max accepts `minimal`, `low`, `medium`, `high`, mapped to Gemini 3.6 Flash `generationConfig.thinkingConfig.thinkingLevel`.
- Thinking levels are model-specific; the server validates each value against the model's configured list.
- Gemini 3.6 Flash uses the native Google AI Studio API adapter. System instructions, supported tool calls, streaming and vision conversion remain in the Google adapter.

## Customer-specific provider credentials

Provider credentials are stored per customer and per public model, encrypted with `FERNET_KEY`.

- Y5Z Coder Pro: APInex key.
- AlphaX Pro: Regolo key from `https://dashboard.regolo.ai/api-keys`.
- AlphaX Max: Google AI Studio key from `https://aistudio.google.com/apikey`.

Do not add shared provider keys to Render Environment. Admin adds each key under Customers → customer → matching model.

## v1.5.10 — DeepSeek reasoning toggle

The V12 migration enables the OpenCode `capabilities.reasoning.toggle` flag for Y5Z Coder Pro only. OpenCode exposes a separate `none`/OFF option in addition to low/medium/high. The gateway maps OFF to the explicit DeepSeek `thinking.type=disabled` field; it never substitutes Low. AlphaX Pro and AlphaX Max remain unchanged.

## v1.5.9 migration

The V11 startup migration moves only `alphax-max` from OpenRouter to Google AI Studio / `gemini-3.6-flash`, clears upstream fallback routes, and configures the four documented thinking levels. Existing active OpenRouter keys are disabled but retained. Previously disabled Google keys carrying the V9 `PROVIDER_CHANGED` marker are re-enabled for reuse. No model aliases, grants, system prompts, subscriptions, payment data, usage data, or AlphaX gateway keys are deleted or changed. Y5Z remains on APInex and AlphaX Pro remains on Regolo.

## API key rotation and routing

The existing per-customer key rotation remains active and scoped to one customer and one model. The V10/V11 routes do not configure alternate upstream model fallbacks; provider failures are not silently redirected to a paid model. Provider-side quotas and pricing still apply.

## Render and database

- Runtime: Docker. Build and Start Command fields remain blank.
- Health Check: `/health/ready` (version `1.5.10`).
- Preserve `DATABASE_URL`, `SECRET_KEY`, and `FERNET_KEY`; changing `FERNET_KEY` can make stored provider credentials unreadable.

## Tests

```bash
python -m compileall -q app tests scripts
python -m pytest -q
```
