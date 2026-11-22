# AlphaXX controls for OpenCode

This package adds one hidden-upstream provider entry called **AlphaXX** and the
three customer-facing model aliases:

- `alphaxx/y5z-coder-pro`
- `alphaxx/alphax-pro`
- `alphaxx/alphax-max`

No upstream provider names or upstream model IDs are registered in OpenCode.
All requests go to `https://alphaxx.onrender.com/v1` using the customer's own
AlphaXX gateway key.

## What appears in OpenCode Desktop

The GUI plugin adds a control strip to the bottom of the OpenCode window. It
updates the selected model variant, and the server plugin applies that variant
on every model request, tool continuation, compaction, and generate request.

### Y5Z Coder Pro

- Separate **Thinking ON/OFF** switch.
- Reasoning Effort: Minimal, Low, Medium, High, XHigh, Max.
- Max Output: 8K, 16K, 32K, 64K, 128K.
- Tools and image input enabled.
- OFF sends `reasoning_effort: none` to the AlphaXX gateway.

### AlphaX Pro

- Separate **Thinking ON/OFF** switch.
- Reasoning Effort: Low, High, Max.
- Max Output: 8K, 16K, 32K, 64K, 128K, 256K, 384K.
- Tools enabled; image input disabled for this route.
- OFF is translated by AlphaXX into the APInex DeepSeek `thinking.type=disabled`
  request form.

### AlphaX Max

- Reasoning Effort: Minimal, Low, Medium, High.
- Max Output: 8K, 16K, 32K, 64K.
- Tools and image input enabled.
- No separate OFF switch is shown because Gemini 3.5 Flash-Lite exposes a
  MINIMAL thinking level, not a documented true OFF option.

## Install in OpenCode Desktop

1. Run `npm install` and `npm run build` in this directory. The build creates
   `dist/gui-experimental.cjs`, which OpenCode Desktop loads.
2. Make the package available to OpenCode. Easiest: keep it at
   `opencode-plugin/alphaxx-opencode-controls` in the AlphaXX checkout.
3. Add this path to the `plugins` array in the global `opencode.jsonc` file,
   using an absolute path on your computer. Example:

   ```jsonc
   {
     "plugins": [
       "C:/Projects/AlphaXX/opencode-plugin/alphaxx-opencode-controls"
     ]
   }
   ```

   Merge the entry into the existing array; do not overwrite other settings.
4. Restart OpenCode Desktop, run `/connect`, choose **AlphaXX**, and enter the
   customer AlphaXX key (`alpha_...`). Then run `/models` and choose an alias.

The GUI SDK is currently marked experimental by OpenCode and is Desktop-only.
The server part also registers combined variants for TUI/CLI. The OpenCode
Desktop app loads the GUI part from its global `opencode.jsonc` plugin list. The
TUI reads its plugin list from `cli.json`; add the same local plugin directory
there as well when using the terminal interface. TUI users can select a combined
variant such as `off-high-32768`, but they do not get the separate graphical
switch strip.

## Output-token behavior

The GUI choices are always bounded by each model's configured ceiling. The
AlphaXX server independently enforces the same hard ceiling:

| Model | Context | Maximum output |
|---|---:|---:|
| Y5Z Coder Pro | 262,144 | 131,072 |
| AlphaX Pro | 1,048,576 | 393,216 |
| AlphaX Max | 1,048,576 | 65,536 |

A selected output value is an upper bound, not a promise that every response
will consume that many tokens. A provider can still impose a lower account or
route limit. The APInex route's live acceptance of the full 393,216 output cap
must be verified with the customer's active APInex credential after deployment.

## Important

- The customer-facing AlphaXX key is different from upstream Inferway, APInex,
  and Google AI Studio keys. Only AlphaXX keys are entered into OpenCode.
- Changing a model's provider disables old provider-specific customer keys but
  does not delete them. Admins must add new Inferway keys for Y5Z Coder Pro and
  APInex keys for AlphaX Pro. AlphaX Max can retain its existing Google key.
- All three models are marked tool-capable. The gateway adapts the OpenAI tool
  format to Gemini function declarations for AlphaX Max.
