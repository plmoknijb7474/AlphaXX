# AlphaX v1.2.1 — Gemma 4 update

- AlphaX Max uses Google AI Studio Gemini API model ID `gemma-4-26b-a4b-it`.
- Added one-time `alphax_max_gemma4_26b_a4b_v6` migration. It updates only the known built-in Google AI Studio Gemma route and preserves Admin-custom providers/model IDs and the existing model System Prompt.
- Gemma 4 thinking controls are `thinking-off` (`minimal`) and `thinking-on` (`high`); no low/medium levels are offered.
- OpenCode model capabilities now expose reasoning effort values `minimal` and `high`, plus image and tool support.
- No customer-facing public alias changed: it remains `alphax-max` / `AlphaX Max`.
