import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' })
Object.assign(globalThis, { window: dom.window, document: dom.window.document,
  HTMLElement: dom.window.HTMLElement, localStorage: dom.window.localStorage,
  MutationObserver: dom.window.MutationObserver })
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })

const { render, fireEvent, cleanup } = await import('@testing-library/react')
const { useStore } = await import('../src/stores/useStore.ts')
const { MiniMaxH3TurboToggle } = await import('../src/components/Sidebar/MiniMaxH3TurboToggle.tsx')
const { H3PromptControls } = await import('../src/components/Sidebar/H3PromptControls.tsx')

test('disabling a selected non-default H3 preset removes it once', () => {
  const before = useStore.getState()
  try {
    useStore.setState({ modelOptions: {
      ...before.modelOptions,
      minimax_h3_turbo: { filename:'pdd.safetensors', label:'Turbo mode', preset_id:'pdd', experimental:true, steps:8, weight:1, guide:'Preset',
        presets:[{ id:'v4', filename:'v4.safetensors', label:'v4', steps:6, weight:1, description:'v4', runtime:'standard_lora', workflow:'all' }] },
    } as typeof before.modelOptions,
    params: { ...before.params, model_type:'minimax_h3', minimax_h3_turbo_mode:true, minimax_h3_turbo_preset:'v4',
      activated_loras:['v4.safetensors'], loras_multipliers:'1', num_inference_steps:6 } })
    const view = render(<MiniMaxH3TurboToggle />)
    fireEvent.click(view.getByRole('checkbox'))
    assert.deepEqual(useStore.getState().params.activated_loras, [])
    assert.equal(useStore.getState().params.minimax_h3_turbo_mode, false)
  } finally { cleanup(); useStore.setState(before) }
})

test('H3 writing and audio modes persist in the generation snapshot', () => {
  const before = useStore.getState()
  try {
    useStore.setState({ params:{...before.params, model_type:'minimax_h3'}, isEnhancing:false })
    const view = render(<H3PromptControls />)
    const selects = view.getAllByRole('combobox')
    fireEvent.change(selects[0], { target:{value:'creative'} })
    fireEvent.change(selects[1], { target:{value:'legacy'} })
    assert.equal(useStore.getState().params.minimax_h3_planning_style,'creative')
    assert.equal(useStore.getState().params.minimax_h3_audio_policy,'legacy')
    assert.equal(useStore.getState().h3WindowPlan,null)
  } finally { cleanup(); useStore.setState(before) }
})


test('Fused is presented as fast mode with qualified memory observations', async () => {
  const { H3ModelInfo, H3ModelName } = await import('../src/components/Sidebar/H3ModelInfo.tsx')
  try {
    const view = render(<><H3ModelName modelType="minimax_h3_fused_turbo" fallback="old" />
      <H3ModelInfo modelType="minimax_h3_fused_turbo" /></>)
    assert.match(view.container.textContent ?? '', /Fast mode|Modo rápido/)
    assert.match(view.container.textContent ?? '', /4 steps|4 pasos/)
    assert.match(view.container.textContent ?? '', /40.6 GiB/)
    assert.match(view.container.textContent ?? '', /not minimum|no requisitos mínimos/)
    assert.match(view.container.textContent ?? '', /anomalous|anómala/)
  } finally { cleanup() }
})

test('catalog labels preserve unrelated models and do not infer measurements for Legacy', async () => {
  const { H3ModelInfo, H3ModelName } = await import('../src/components/Sidebar/H3ModelInfo.tsx')
  try {
    const view = render(<><H3ModelName modelType="wan" fallback="Wan" />
      <H3ModelInfo modelType="wan" /><H3ModelInfo modelType="minimax_h3_legacy" /></>)
    assert.match(view.container.textContent ?? '', /^Wan/)
    assert.match(view.container.textContent ?? '', /not measured|No se midió/)
    assert.doesNotMatch(view.container.textContent ?? '', /GiB/)
  } finally { cleanup() }
})

test('FastH3 is a fixed 8-step distilled model, not the fused fast mode', async () => {
  const { H3ModelInfo, H3ModelName } = await import('../src/components/Sidebar/H3ModelInfo.tsx')
  const { h3FramesModelId, h3FusedStepRange } = await import('../src/lib/h3Catalog.ts')
  try {
    const name = render(<H3ModelName modelType="minimax_h3_fasth3_v2" fallback="FastH3 V2" />)
    assert.equal(name.container.textContent, 'FastH3 V2')
    cleanup()
    const view = render(<H3ModelInfo modelType="minimax_h3_fasth3_v2" />)
    const text = view.container.textContent ?? ''
    assert.match(text, /8 steps|8 pasos/)
    assert.match(text, /not measured|No se midió/)
    assert.doesNotMatch(text, /GiB/)
  } finally { cleanup() }
  assert.deepEqual(h3FusedStepRange('minimax_h3_fasth3_trim'), { min: 8, max: 8, fallback: 8 })
  assert.deepEqual(h3FusedStepRange('minimax_h3_fused_turbo'), { min: 4, max: 8, fallback: 4 })
  assert.equal(h3FramesModelId('minimax_h3_fasth3_trim'), 'minimax_h3_fasth3_trim')
  assert.equal(h3FramesModelId('minimax_h3_ref2va_fused_turbo'), 'minimax_h3_fused_turbo')
})

test('FastH3 offers dense attention by default while fused keeps SLA', () => {
  const before = useStore.getState()
  const select = (view: ReturnType<typeof render>) =>
    view.getByLabelText(/Attention|Atención/) as HTMLSelectElement
  try {
    useStore.setState({ modelOptions: { ...before.modelOptions, minimax_h3_fused_turbo: true, minimax_h3_fasth3: true } as typeof before.modelOptions,
      params: { ...before.params, model_type: 'minimax_h3_fasth3_v2', override_attention: '' } })
    let view = render(<H3PromptControls />)
    assert.equal(select(view).value, '')
    assert.deepEqual([...select(view).options].map(option => option.value), ['', 'sdpa', 'sla'])
    cleanup()
    useStore.setState({ modelOptions: { ...before.modelOptions, minimax_h3_fused_turbo: true, minimax_h3_fasth3: false } as typeof before.modelOptions,
      params: { ...before.params, model_type: 'minimax_h3_fused_turbo', override_attention: '' } })
    view = render(<H3PromptControls />)
    assert.equal(select(view).value, 'sla')
    assert.deepEqual([...select(view).options].map(option => option.value), ['sdpa', 'sla'])
  } finally { cleanup(); useStore.setState(before) }
})

test('FastH3 entries are added to existing installs once', async () => {
  const { DEFAULT_ENABLED_MODELS, DEFAULTS_ADDED_IN, DEFAULTS_VERSION } = await import('../src/stores/modelVisibility.ts')
  for (const modelType of ['minimax_h3_fasth3_v2', 'minimax_h3_fasth3_trim']) {
    assert.ok(DEFAULT_ENABLED_MODELS.has(modelType), modelType)
    assert.ok(DEFAULTS_ADDED_IN[DEFAULTS_VERSION].includes(modelType), modelType)
  }
})

test('switching to FastH3 clears SLA and Sol, keeps SDPA, and fused still forces SLA', async () => {
  const { h3ModelSwitchSettings } = await import('../src/lib/h3OptionalSettings.ts')
  const base = { ...useStore.getState().params, model_type: 'minimax_h3' }
  const attention = (override: string, target: string) =>
    h3ModelSwitchSettings({ ...base, override_attention: override } as typeof base, target).override_attention
  assert.equal(attention('sla', 'minimax_h3_fasth3_v2'), undefined)
  assert.equal(attention('sol', 'minimax_h3_fasth3_trim'), undefined)
  assert.equal(attention('sdpa', 'minimax_h3_fasth3_v2'), 'sdpa')
  assert.equal(attention('', 'minimax_h3_fused_turbo'), 'sla')
  assert.equal(attention('sol', 'minimax_h3'), 'sol')
})
