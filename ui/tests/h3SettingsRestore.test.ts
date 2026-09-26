import assert from 'node:assert/strict'
import test from 'node:test'
import { JSDOM } from 'jsdom'

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' })
Object.assign(globalThis, {
  window: dom.window,
  document: dom.window.document,
  localStorage: dom.window.localStorage,
})

const { useStore, alignFrameCount } = await import('../src/stores/useStore.ts')
const { H3_EXPERIMENTAL_MAX_FRAMES, requestedVideoFrames } = await import('../src/lib/h3ExtendedDuration.ts')

const initial = useStore.getState()
const originalFetch = globalThis.fetch
const json = (body: unknown) => new Response(JSON.stringify(body), { headers: { 'Content-Type': 'application/json' } })
const h3Options = {
  architecture: 'minimax_h3',
  model_type: 'minimax_h3',
  fps: 24,
  frames_minimum: 124,
  frames_maximum: 345,
  sliding_window: true,
  sliding_window_defaults: { window_min: 124, window_max: 345, window_step: 17, overlap_default: 5 },
  frame_alignment_modulus: 17,
  frame_alignment_remainder: 5,
  frame_alignment_mode: 'ceil',
}

function setup(params: Record<string, unknown>) {
  useStore.setState({
    ...initial,
    generationMode: 'video',
    activeWorkspace: 'h3-restore',
    models: [{ model_type: 'minimax_h3', family: 'minimax_h3', name: 'H3', fps: 24 }] as never,
    modelOptions: h3Options as never,
    selectedOutputMeta: { params } as never,
    loadLoras: async () => {},
    params: { ...initial.params, model_type: 'minimax_h3', minimax_h3_extended_duration: false },
  }, true)
  globalThis.fetch = async input => String(input).includes('/model-options/') ? json(h3Options) : json({})
}

test.afterEach(() => {
  useStore.setState(initial, true)
  globalThis.fetch = originalFetch
})

function submitFrames() {
  const state = useStore.getState()
  return requestedVideoFrames(
    state.durationSeconds,
    state.modelOptions,
    state.params.minimax_h3_extended_duration,
    alignFrameCount,
  )
}

test('Load Settings of a 30s H3 clip keeps the extended pass on reroll', async () => {
  setup({
    model_type: 'minimax_h3',
    prompt: 'Keep the spoken line',
    resolution: '1280x720',
    video_length: H3_EXPERIMENTAL_MAX_FRAMES,
    num_inference_steps: 20,
    guidance_scale: 5,
    image_mode: 0,
    minimax_h3_extended_duration: true,
  })
  assert.equal(await useStore.getState().loadSettingsFromOutput(), true)
  assert.equal(useStore.getState().params.minimax_h3_extended_duration, true)
  assert.equal(useStore.getState().durationSeconds, 30)
  assert.equal(submitFrames(), H3_EXPERIMENTAL_MAX_FRAMES)
})

test('a 719-frame H3 sidecar without the flag still rerolls at 30s', async () => {
  setup({
    model_type: 'minimax_h3',
    prompt: 'Older sidecar',
    resolution: '1280x720',
    video_length: H3_EXPERIMENTAL_MAX_FRAMES,
    num_inference_steps: 20,
    guidance_scale: 5,
    image_mode: 0,
  })
  assert.equal(await useStore.getState().loadSettingsFromOutput(), true)
  assert.equal(useStore.getState().params.minimax_h3_extended_duration, true)
  assert.equal(submitFrames(), H3_EXPERIMENTAL_MAX_FRAMES)
})

test('a catalog 15s H3 clip does not turn the 30s experiment on', async () => {
  setup({
    model_type: 'minimax_h3',
    prompt: 'Fifteen seconds',
    resolution: '1280x720',
    video_length: 345,
    num_inference_steps: 20,
    guidance_scale: 5,
    image_mode: 0,
  })
  assert.equal(await useStore.getState().loadSettingsFromOutput(), true)
  assert.equal(useStore.getState().params.minimax_h3_extended_duration, false)
  assert.equal(submitFrames(), 345)
})
