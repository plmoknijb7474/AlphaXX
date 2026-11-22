import { Model, Plugin, Provider } from "@opencode/plugin"

const PROVIDER_ID = Provider.ID.make("alphaxx")
const BASE_URL = "https://alphaxx.onrender.com/v1"

type ModelSpec = {
  name: string
  context: number
  output: number
  outputs: number[]
  efforts: string[]
  toggle: boolean
  parameter: "reasoning_effort" | "thinking_level"
  defaultEffort: string
  defaultOn: boolean
  vision: boolean
}

const SPECS: Record<string, ModelSpec> = {
  "y5z-coder-pro": {
    name: "Y5Z Coder Pro",
    context: 262144,
    output: 131072,
    outputs: [8192, 16384, 32768, 65536, 131072],
    efforts: ["minimal", "low", "medium", "high", "xhigh", "max"],
    toggle: true,
    parameter: "reasoning_effort",
    defaultEffort: "high",
    defaultOn: true,
    vision: true,
  },
  "alphax-pro": {
    name: "AlphaX Pro",
    context: 1048576,
    output: 393216,
    outputs: [8192, 16384, 32768, 65536, 131072, 262144, 393216],
    efforts: ["low", "high", "max"],
    toggle: true,
    parameter: "reasoning_effort",
    defaultEffort: "high",
    defaultOn: true,
    vision: false,
  },
  "alphax-max": {
    name: "AlphaX Max",
    context: 1048576,
    output: 65536,
    outputs: [8192, 16384, 32768, 65536],
    efforts: ["minimal", "low", "medium", "high"],
    toggle: false,
    parameter: "thinking_level",
    defaultEffort: "medium",
    defaultOn: true,
    vision: true,
  },
}

function variantID(modelID: string, effort: string, output: number, enabled = true) {
  const spec = SPECS[modelID]
  return spec.toggle
    ? `${enabled ? "on" : "off"}-${effort}-${output}`
    : `${effort}-${output}`
}

function variantBody(spec: ModelSpec, effort: string, output: number, enabled: boolean) {
  return {
    max_tokens: output,
    [spec.parameter]: enabled ? effort : "none",
  }
}

function variantsFor(modelID: string, spec: ModelSpec) {
  const result: Array<{ id: string; body: Record<string, unknown> }> = []
  for (const effort of spec.efforts) {
    for (const output of spec.outputs) {
      if (spec.toggle) {
        result.push({
          id: variantID(modelID, effort, output, true),
          body: variantBody(spec, effort, output, true),
        })
        result.push({
          id: variantID(modelID, effort, output, false),
          body: variantBody(spec, effort, output, false),
        })
      } else {
        result.push({
          id: variantID(modelID, effort, output, true),
          body: variantBody(spec, effort, output, true),
        })
      }
    }
  }
  return result
}

function parseVariant(modelID: string, variant: string | undefined) {
  const spec = SPECS[modelID]
  const fallback = {
    enabled: spec.defaultOn,
    effort: spec.defaultEffort,
    output: Math.min(32768, spec.output),
  }
  if (!variant) return fallback
  const pieces = variant.split("-")
  let enabled = true
  let effort = ""
  let output = 0
  if (spec.toggle) {
    if (pieces.length !== 3) return fallback
    enabled = pieces[0] === "on"
    effort = pieces[1]
    output = Number(pieces[2])
  } else {
    if (pieces.length !== 2) return fallback
    effort = pieces[0]
    output = Number(pieces[1])
  }
  if (!spec.efforts.includes(effort) || !spec.outputs.includes(output)) return fallback
  return { enabled, effort, output: Math.min(output, spec.output) }
}

function applyModelControls(event: any) {
  if (event.model?.providerID !== "alphaxx") return
  const modelID = String(event.model.id || "")
  const spec = SPECS[modelID]
  if (!spec) return
  const state = parseVariant(modelID, event.model.variant)
  // OpenCode's semantic generation option is maxTokens. The provider adapter
  // lowers it to max_tokens, which AlphaXX then clamps to the model's ceiling.
  event.options.maxTokens = state.output
  if (spec.parameter === "thinking_level") {
    event.options.thinking_level = state.effort
    delete event.options.reasoning_effort
  } else {
    event.options.reasoning_effort = state.enabled ? state.effort : "none"
    delete event.options.thinking_level
  }
}

function buildModel(modelID: string, spec: ModelSpec) {
  const id = Model.ID.make(modelID)
  const model: any = Model.Info.default(PROVIDER_ID, id)
  model.name = spec.name
  model.modelID = modelID
  model.enabled = true
  model.limit = { context: spec.context, output: spec.output }
  model.capabilities = {
    tools: true,
    input: spec.vision ? ["text", "image"] : ["text"],
    output: ["text"],
    temperature: true,
  }
  model.compatibility = {
    maxTokensField: "max_tokens",
    streamUsage: true,
  }
  model.body = variantBody(
    spec,
    spec.defaultEffort,
    Math.min(32768, spec.output),
    spec.defaultOn,
  )
  model.variants = variantsFor(modelID, spec)
  return model
}

export default Plugin.define({
  id: "alphaxx-opencode-controls",
  async setup(ctx) {
    const models = Object.entries(SPECS).map(([id, spec]) => buildModel(id, spec))
    await ctx.provider.transform((editor) => {
      editor.remove("alphaxx")
      editor.add({
        info: {
          ...Provider.Info.empty(PROVIDER_ID),
          name: "AlphaXX",
          activation: "enabled",
          package: "@opencode/ai/providers/openai-compatible",
          env: ["ALPHAXX_API_KEY"],
          settings: { baseURL: BASE_URL },
        } as any,
        models,
      })
    })

    await ctx.session.hook("context", applyModelControls, { providerID: "alphaxx" })
    await ctx.session.hook("compaction", applyModelControls, { providerID: "alphaxx" })
    await ctx.session.hook("generate", applyModelControls, { providerID: "alphaxx" })
  },
})
