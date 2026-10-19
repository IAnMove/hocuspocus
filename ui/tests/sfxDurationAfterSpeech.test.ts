// Speech (VoxCPM2 default 60 s) -> SFX with an untouched form: the SFX slider shows at most 20 s but the
// request used to carry the leftover 60 s, which the closed generation.sfx builder refuses.
import assert from 'node:assert/strict'
import test from 'node:test'
import { JSDOM } from 'jsdom'

const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
Object.assign(globalThis, { window: dom.window, document: dom.window.document,
  localStorage: dom.window.localStorage, Event: dom.window.Event, CustomEvent: dom.window.CustomEvent })
window.matchMedia = (() => ({ matches: false })) as typeof window.matchMedia
const { useStore } = await import('../src/stores/useStore')
const { applyStudioAudioSubmitParams } = await import('../src/stores/studioAudioSubmit')
const { projectStudioSfxFormParams, createStudioSfxGenerationCommand } = await import('../src/features/studio/sfxGenerationSpec')

for (const [label, leftover] of [['a 60 s Speech duration', 60], ['an "auto" (0) duration', 0]] as const) {
  test(`SFX tab after ${label} submits what its slider shows`, async () => {
    const before = useStore.getState(), beforeFetch = globalThis.fetch
    try {
      globalThis.fetch = (async () => new Response('{}', { headers: { 'content-type': 'application/json' } })) as typeof fetch
      useStore.setState({ generationMode: 'audio', audioSubMode: 'speech', activeWorkspace: 'sfx-duration',
        audioReferenceStash: {}, selectedModelPerAudioSubMode: {},
        models: [
          { model_type: 'voxcpm2_voicedesign', name: 'VoxCPM2', family: 'tts', is_downloaded: true },
          { model_type: 'mmaudio_v2', name: 'MMAudio', family: 'tts', is_downloaded: true },
        ] as typeof before.models,
        durationSeconds: leftover,       // what loadModelOptions leaves for a speech model
        params: { ...before.params, model_type: 'voxcpm2_voicedesign', prompt: 'Hello there' },
        loadLoras: async () => {} })
      useStore.getState().setAudioSubMode('sfx')
      useStore.getState().setParams({ MMAudio_prompt: 'a door slams' } as never)
      const state = useStore.getState()
      assert.equal(state.params.model_type, 'mmaudio_v2')
      const shown = Math.max(1, Math.min(state.durationSeconds, 20))     // SfxControls: range 1..20
      const full = applyStudioAudioSubmitParams({ ...state.params, generation_mode: 'audio', workspace: 'sfx-duration' }, state)
      assert.equal(full.duration_seconds, shown, 'the request duration differs from the slider')
      assert.doesNotThrow(() => createStudioSfxGenerationCommand(projectStudioSfxFormParams(JSON.parse(JSON.stringify(full))), 'sfx-duration'))
    } finally {
      await new Promise(resolve => setTimeout(resolve, 20))
      useStore.setState(before); globalThis.fetch = beforeFetch
    }
  })
}
