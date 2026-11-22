import { createEffect, createMemo, Show } from "solid-js"
import { Plugin, Slot } from "@opencode/plugin/gui"

const MODEL_SPECS: Record<string, {
  label: string
  toggle: boolean
  efforts: string[]
  outputs: number[]
  defaultEffort: string
  defaultOn: boolean
  defaultOutput: number
}> = {
  "y5z-coder-pro": {
    label: "Y5Z Coder Pro",
    toggle: true,
    efforts: ["minimal", "low", "medium", "high", "xhigh", "max"],
    outputs: [8192, 16384, 32768, 65536, 131072],
    defaultEffort: "high",
    defaultOn: true,
    defaultOutput: 32768,
  },
  "alphax-pro": {
    label: "AlphaX Pro",
    toggle: true,
    efforts: ["low", "high", "max"],
    outputs: [8192, 16384, 32768, 65536, 131072, 262144, 393216],
    defaultEffort: "high",
    defaultOn: true,
    defaultOutput: 32768,
  },
  "alphax-max": {
    label: "AlphaX Max",
    toggle: false,
    efforts: ["minimal", "low", "medium", "high"],
    outputs: [8192, 16384, 32768, 65536],
    defaultEffort: "medium",
    defaultOn: true,
    defaultOutput: 32768,
  },
}

function makeVariant(modelID: string, effort: string, output: number, enabled: boolean) {
  const spec = MODEL_SPECS[modelID]
  return spec.toggle
    ? `${enabled ? "on" : "off"}-${effort}-${output}`
    : `${effort}-${output}`
}

function readVariant(modelID: string, variant?: string) {
  const spec = MODEL_SPECS[modelID]
  const fallback = {
    enabled: spec.defaultOn,
    effort: spec.defaultEffort,
    output: spec.defaultOutput,
  }
  if (!variant) return fallback
  const parts = variant.split("-")
  let enabled = true
  let effort = ""
  let output = 0
  if (spec.toggle) {
    if (parts.length !== 3) return fallback
    enabled = parts[0] === "on"
    effort = parts[1]
    output = Number(parts[2])
  } else {
    if (parts.length !== 2) return fallback
    effort = parts[0]
    output = Number(parts[1])
  }
  if (!spec.efforts.includes(effort) || !spec.outputs.includes(output)) return fallback
  return { enabled, effort, output }
}

function labelTokens(value: number) {
  return value >= 1024 ? `${Math.round(value / 1024)}K` : String(value)
}

function Controls(props: { ctx: any }) {
  const ctx = props.ctx
  const currentModel = () => ctx.screen.current()?.composer?.model()
  const spec = createMemo(() => {
    const current = currentModel()
    if (!current || current.providerID !== "alphaxx") return undefined
    const config = MODEL_SPECS[current.modelID]
    return config ? { current, config } : undefined
  })
  const state = createMemo(() => {
    const selected = spec()
    if (!selected) return undefined
    return readVariant(selected.current.modelID, selected.current.variant)
  })

  // Select a complete starting variant once the model is actually in the picker.
  // This makes the visible 32K default the real request cap, not just a UI label.
  createEffect(() => {
    const selected = spec()
    if (!selected || selected.current.variant) return
    const initial = selected.config
    const composer = ctx.screen.current()?.composer
    composer?.setVariant(makeVariant(
      selected.current.modelID,
      initial.defaultEffort,
      initial.defaultOutput,
      initial.defaultOn,
    ))
  })

  const update = (patch: Partial<{ enabled: boolean; effort: string; output: number }>) => {
    const selected = spec()
    const current = state()
    if (!selected || !current) return
    const next = { ...current, ...patch }
    const ok = ctx.screen.current()?.composer?.setVariant(
      makeVariant(selected.current.modelID, next.effort, next.output, next.enabled),
    )
    if (ok === false) {
      ctx.toast.show({
        variant: "error",
        title: "AlphaXX control unavailable",
      })
    }
  }

  const ui = ctx.ui
  return (
    <Show when={spec() && state()}>
      <div style={{
        display: "flex",
        "align-items": "center",
        gap: "12px",
        padding: "8px 14px",
        "border-top": "1px solid var(--border-base)",
        "background-color": "var(--surface-base)",
        "flex-wrap": "wrap",
        "font-size": "12px",
      }}>
        <strong style={{ "white-space": "nowrap" }}>AlphaXX Controls</strong>
        <Show when={spec()!.config.toggle}>
          <ui.Switch
            label="Thinking ON/OFF"
            checked={state()!.enabled}
            onChange={(checked: boolean) => update({ enabled: checked })}
          />
        </Show>
        <div style={{ display: "flex", "align-items": "center", gap: "6px" }}>
          <span style={{ color: "var(--text-muted)" }}>Reasoning Effort</span>
          <ui.Select
            label="Reasoning Effort"
            value={state()!.effort}
            disabled={!!spec()!.config.toggle && !state()!.enabled}
            options={spec()!.config.efforts.map((effort: string) => ({ value: effort, label: effort.toUpperCase() }))}
            onChange={(effort: string) => update({ effort })}
          />
        </div>
        <div style={{ display: "flex", "align-items": "center", gap: "6px" }}>
          <span style={{ color: "var(--text-muted)" }}>Max Output</span>
          <ui.Select
            label="Maximum output tokens"
            value={String(state()!.output)}
            options={spec()!.config.outputs.map((output: number) => ({ value: String(output), label: labelTokens(output) }))}
            onChange={(output: string) => update({ output: Number(output) })}
          />
        </div>
        <span style={{ color: "var(--text-muted)", "white-space": "nowrap" }}>
          {spec()!.config.label} · Cap {labelTokens(state()!.output)}
        </span>
      </div>
    </Show>
  )
}

export default Plugin.define({
  setup(ctx) {
    ctx.add(Slot, {
      at: "window.bottom",
      order: 70,
      render: () => <Controls ctx={ctx} />,
    })
  },
})
