# AlphaXX v1.5.11 Upgrade Notes

- Y5Z Coder Pro / DeepSeek V4 Pro on APInex retains Reasoning ON/OFF and Low / Medium / High effort levels.
- AlphaX Pro / Gemma 4 31B on Regolo now exposes ON/OFF only; no user-facing effort scale remains. The migration is guarded by provider name and upstream model ID.
- AlphaX Max / Gemini 3.6 Flash settings remain unchanged.
- Database migration V13 is idempotent and does not overwrite the private System Prompt, user credentials, grants, quotas, or subscriptions.
- Legacy/custom models that still use `reasoning_mode=levels` retain their previous `alpha_reasoning=false` mapping.
- The release adds/updates migration, payload, UI-cache, and health-version tests.

Regolo `reasoning_effort: none` behavior remains provider/model-specific and needs a live API verification for `gemma4-31b`.
