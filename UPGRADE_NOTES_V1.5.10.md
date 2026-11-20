# Upgrade notes — v1.5.10

- Adds `capabilities.reasoning.toggle: true` to Y5Z Coder Pro's exported OpenCode configuration.
- Maps the generated OFF/`none` choice to DeepSeek's explicit `thinking: {"type":"disabled"}` request field.
- Maps enabled Low/Medium/High choices to `thinking: {"type":"enabled"}` plus `reasoning_effort`.
- Adds an idempotent V12 database migration.
- Does not change APInex/Regolo/Google routes, user keys, quotas, subscriptions, grants, or model prompts.
