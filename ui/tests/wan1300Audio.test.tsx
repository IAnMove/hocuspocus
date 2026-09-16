import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'
import { applyInstructionSpeechParams } from '../src/lib/instructionSpeech'
import { detectCapability, catalogVramGb } from '../src/lib/modelCatalog'
import { catalogEntry } from '../src/lib/musicGenerationSpec'

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' })
Object.assign(globalThis, {
  window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement,
  localStorage: dom.window.localStorage, MutationObserver: dom.window.MutationObserver,
})
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
const { render, cleanup, fireEvent, waitFor } = await import('@testing-library/react')
const { useStore } = await import('../src/stores/useStore')
const { InstructionAudioControls } = await import('../src/components/Sidebar/InstructionAudioControls')
const { Yue2Controls } = await import('../src/components/Sidebar/Yue2Controls')
const { createStudioSpeechGenerationCommand } = await import('../src/features/studio/speechGenerationSpec')
const { createStudioMusicGenerationCommand } = await import('../src/features/studio/musicGenerationSpec')

test('new models appear in the correct audio catalog categories', () => {
  assert.equal(detectCapability({ model_type: 'yue2', architecture: 'yue2', family: 'tts' }), 'music')
  assert.equal(detectCapability({ model_type: 'auk_flash', architecture: 'auk', family: 'tts' }), 'speech')
  assert.equal(catalogEntry('yue2')?.durationMax, 600)
  assert.equal(catalogVramGb({ model_type: 'yue2', architecture: 'yue2' }), undefined)
})

test('AuK native snapshot keeps instructions and source, clearing inactive dialogue fields', () => {
  const prompt = 'Replace "Mara: hello" with "Mara: goodbye", keeping the same speaker.\nKeep the background.'
  const params: Record<string, unknown> = {
    workspace: 'test', model_type: 'auk_flash', resolution: '1280x720', prompt,
    audio_prompt_type: 'A', audio_guide: '/api/v1/uploads/source.wav',
    audio_guide2: '/api/v1/uploads/stale.wav', _tts_speaker_name1: 'Mara',
    _tts_voice_count: 3, num_inference_steps: 32, temperature: 0.7, custom_settings: { pace: 1 },
  }
  applyInstructionSpeechParams(params)
  const command = createStudioSpeechGenerationCommand(params, 'auk-snapshot')
  assert.equal(command.input.params.prompt, prompt)
  assert.equal(command.input.params.audio_guide, '/api/v1/uploads/source.wav')
  assert.equal(command.input.params.audio_guide2, undefined)
  assert.equal(command.input.params.num_inference_steps, 4)
  assert.equal(command.input.params.guidance_scale, 0)
  assert.equal(command.input.params.guidance_phases, 0)
})

test('YuE2 music command preserves multiline lyrics, style and planning mode', () => {
  const params = { workspace: 'test', model_type: 'yue2', resolution: '1280x720',
    prompt: '[Verse]\nLínea literal\n[Chorus]\nAquí sigo', alt_prompt: 'Spanish acoustic pop', model_mode: 1 }
  const command = createStudioMusicGenerationCommand(params, 'yue2-snapshot')
  assert.equal(command.input.params.prompt, params.prompt)
  assert.equal(command.input.params.alt_prompt, params.alt_prompt)
  assert.equal(command.input.params.model_mode, 1)
  assert.throws(() => createStudioMusicGenerationCommand({ ...params, alt_prompt: '' }, 'empty-style'))
})

test('AuK mode controls clear an inactive source and Flash has no editable sampling', () => {
  const previous = useStore.getState()
  const fetchBefore = globalThis.fetch
  globalThis.fetch = async () => new Response(JSON.stringify({ files: [], outputs: [], items: [] }), {
    status: 200, headers: { 'content-type': 'application/json' },
  })
  useStore.setState({ params: { ...previous.params, model_type: 'auk_flash', audio_prompt_type: 'A',
    audio_guide: '/api/v1/uploads/source.wav' }, activeWorkspace: 'test' })
  try {
    const view = render(<InstructionAudioControls />)
    assert.equal(view.queryAllByRole('spinbutton').length, 0)
    fireEvent.change(view.getByRole('combobox'), { target: { value: '' } })
    assert.equal(useStore.getState().params.audio_prompt_type, '')
    assert.equal(useStore.getState().params.audio_guide, undefined)
  } finally { cleanup(); useStore.setState(previous); globalThis.fetch = fetchBefore }
})

test('YuE2 planning selection stores a numeric native mode', () => {
  const previous = useStore.getState()
  useStore.setState({ params: { ...previous.params, model_type: 'yue2', model_mode: 0 } })
  try {
    const view = render(<Yue2Controls />)
    fireEvent.change(view.getByRole('combobox'), { target: { value: '2' } })
    assert.equal(useStore.getState().params.model_mode, 2)
  } finally { cleanup(); useStore.setState(previous) }
})

for (const mode of [0, 1, 2]) {
  test(`loading a YuE2 output restores planning mode ${mode} and its sampling recipe`, async () => {
    await assertAudioRecipeRestore('yue2', { model_mode: mode, top_k: 17, top_p: 0.72, temperature: 0.8 },
      { model_mode: mode, top_k: 17, top_p: 0.72, temperature: 0.8 })
  })
}

test('older YuE2 output settings use native defaults when sampling fields are absent', async () => {
  await assertAudioRecipeRestore('yue2', {}, { model_mode: 0, top_k: 100, top_p: 0.95, temperature: 1,
    guidance_scale: 1, num_inference_steps: 32 })
})

test('loading AuK output settings keeps zero guidance and the fixed Flash recipe', async () => {
  await assertAudioRecipeRestore('auk', { guidance_scale: 0 }, { guidance_scale: 0, num_inference_steps: 32 })
  await assertAudioRecipeRestore('auk_flash', {}, { guidance_scale: 0, num_inference_steps: 4, guidance_phases: 0 })
})

async function assertAudioRecipeRestore(model: string, saved: Record<string, unknown>, expected: Record<string, unknown>) {
  const previous = useStore.getState(), fetchBefore = globalThis.fetch
  const params = { model_type: model, prompt: '[Verse]\nKeep these exact words', alt_prompt: 'English acoustic pop',
    duration_seconds: 8, ...saved }
  globalThis.fetch = async input => {
    const url = String(input)
    const data = url.includes('/metadata') ? { source: 'sidecar', params }
      : url.includes('/model-options/') ? { audio_only: true,
        default_num_inference_steps: 32, default_guidance_scale: 1, guidance_max_phases: 1,
        duration_slider: { min: 1, max: 600, default: 120 } }
        : { loras: [], items: [], outputs: [], choices: [] }
    return new Response(JSON.stringify(data), { status: 200, headers: { 'content-type': 'application/json' } })
  }
  useStore.setState({ activeWorkspace: 'test', browsingUploads: false,
    models: [{ model_type: model, family: 'tts', architecture: model === 'yue2' ? 'yue2' : 'auk' }],
    loadLoras: async () => {} })
  try {
    assert.equal(await useStore.getState().loadSettingsFromOutput({ workspace: 'test', name: 'song.wav' }), true)
    const restored = useStore.getState().params as unknown as Record<string, unknown>
    for (const [key, value] of Object.entries(expected)) assert.equal(restored[key], value, key)
    assert.equal(restored.prompt, params.prompt)
    assert.equal(restored.alt_prompt, params.alt_prompt)
  } finally { useStore.setState(previous); globalThis.fetch = fetchBefore }
}


test('AuK keeps its reference across audio tabs but clears foreign references on model selection', async () => {
  const previous = useStore.getState(), fetchBefore = globalThis.fetch
  globalThis.fetch = async input => new Response(JSON.stringify(String(input).includes('/model-options/') ? {
    audio_only: true, max_voice_count: 1, default_num_inference_steps: 32, default_guidance_scale: 2,
    guidance_max_phases: 1, duration_slider: { min: 0.1, max: 300, default: 5 },
    audio_prompt_type_sources: { selection: ['', 'A'], default: '' },
  } : {}), { status: 200, headers: { 'content-type': 'application/json' } })
  useStore.setState({ activeWorkspace: 'test', generationMode: 'audio', audioSubMode: 'speech',
    models: [{ model_type: 'auk', family: 'tts' }, { model_type: 'yue2', family: 'tts' }],
    selectedModelPerAudioSubMode: { speech: 'auk', music: 'yue2' }, audioReferenceStash: {},
    loadLoras: async () => {}, ttsVoiceCount: 0,
    params: { ...previous.params, model_type: 'auk', audio_prompt_type: 'A', audio_guide: '/api/v1/uploads/reference.wav' },
    audioGuideFilename: 'reference.wav' })
  const settled = () => waitFor(() => assert.equal(useStore.getState().modelOptionsLoading, false))
  try {
    useStore.getState().setAudioSubMode('music')
    await settled()
    assert.equal(useStore.getState().params.audio_guide, undefined)
    useStore.getState().setAudioSubMode('speech')
    await settled()
    assert.equal(useStore.getState().params.audio_prompt_type, 'A')
    assert.equal(useStore.getState().params.audio_guide, '/api/v1/uploads/reference.wav')
    assert.equal(useStore.getState().audioGuideFilename, 'reference.wav')
    useStore.setState({ ttsVoiceCount: 3, params: { ...useStore.getState().params, model_type: 'chatterbox', audio_prompt_type: 'AB',
      audio_guide: '/api/v1/uploads/other.wav', audio_guide2: '/api/v1/uploads/second.wav' } })
    useStore.getState().selectModel('auk')
    await settled()
    assert.equal(useStore.getState().params.audio_prompt_type, '')
    assert.equal(useStore.getState().params.audio_guide, undefined)
    assert.equal(useStore.getState().params.audio_guide2, undefined)
    assert.equal(useStore.getState().audioGuideFilename, null)
  } finally { useStore.setState(previous); globalThis.fetch = fetchBefore }
})

function mockNativeAudioFetches() {
  return async (input: RequestInfo | URL) => {
    const url = String(input)
    const body = url.includes('/model-options/')
      ? {
        audio_only: true, max_voice_count: 1, default_num_inference_steps: 32, default_guidance_scale: 1,
        guidance_max_phases: 1, duration_slider: { min: 1, max: 600, default: 120 },
        audio_prompt_type_sources: { selection: ['', 'A'], default: '' },
      }
      : url.includes('/defaults/')
        ? { num_inference_steps: 32, guidance_scale: 1, temperature: 1, top_k: 100, top_p: 0.95, model_mode: 0 }
        : {}
    return new Response(JSON.stringify(body), { status: 200, headers: { 'content-type': 'application/json' } })
  }
}

async function settleNativeAudioLoad(modelType: string) {
  await waitFor(() => {
    assert.equal(useStore.getState().params.model_type, modelType)
    assert.equal(useStore.getState().modelOptionsLoading, false)
  })
  await new Promise(resolve => setTimeout(resolve, 20))
}

test('YuE2 planning and sampling survive a Speech tab return', async () => {
  const previous = useStore.getState(), fetchBefore = globalThis.fetch
  globalThis.fetch = mockNativeAudioFetches()
  useStore.setState({
    activeWorkspace: 'test', generationMode: 'audio', audioSubMode: 'music',
    models: [{ model_type: 'auk', family: 'tts' }, { model_type: 'yue2', family: 'tts' }],
    selectedModelPerAudioSubMode: { speech: 'auk', music: 'yue2' }, selectedModelPerMode: { audio: 'yue2' },
    audioReferenceStash: {}, loadLoras: async () => {},
    params: { ...previous.params, model_type: 'yue2', model_mode: 2, top_k: 17, top_p: 0.72,
      temperature: 0.8, num_inference_steps: 40, guidance_scale: 3 },
  })
  try {
    useStore.getState().setAudioSubMode('speech')
    await settleNativeAudioLoad('auk')
    useStore.getState().setAudioSubMode('music')
    await settleNativeAudioLoad('yue2')
    const params = useStore.getState().params as unknown as Record<string, unknown>
    assert.equal(params.model_mode, 2)
    assert.equal(params.top_k, 17)
    assert.equal(params.top_p, 0.72)
    assert.equal(params.temperature, 0.8)
    assert.equal(params.num_inference_steps, 40)
    assert.equal(params.guidance_scale, 3)
  } finally { useStore.setState(previous); globalThis.fetch = fetchBefore }
})

test('YuE2 planning survives leaving Audio for Video and coming back', async () => {
  const previous = useStore.getState(), fetchBefore = globalThis.fetch
  globalThis.fetch = mockNativeAudioFetches()
  useStore.setState({
    activeWorkspace: 'test', generationMode: 'audio', audioSubMode: 'music',
    models: [{ model_type: 'yue2', family: 'tts' }, { model_type: 'wan_2_2', family: 'wan' }],
    selectedModelPerAudioSubMode: { music: 'yue2' }, selectedModelPerMode: { audio: 'yue2', video: 'wan_2_2' },
    savedParamsPerMode: {}, audioReferenceStash: {}, loadLoras: async () => {},
    params: { ...previous.params, model_type: 'yue2', model_mode: 2, top_k: 17, num_inference_steps: 40 },
  })
  try {
    useStore.getState().setGenerationMode('video')
    await settleNativeAudioLoad('wan_2_2')
    useStore.getState().setGenerationMode('audio')
    await settleNativeAudioLoad('yue2')
    const params = useStore.getState().params as unknown as Record<string, unknown>
    assert.equal(params.model_mode, 2)
    assert.equal(params.top_k, 17)
    assert.equal(params.num_inference_steps, 40)
  } finally { useStore.setState(previous); globalThis.fetch = fetchBefore }
})

test('AuK custom sampling survives a Music tab return', async () => {
  const previous = useStore.getState(), fetchBefore = globalThis.fetch
  globalThis.fetch = mockNativeAudioFetches()
  useStore.setState({
    activeWorkspace: 'test', generationMode: 'audio', audioSubMode: 'speech',
    models: [{ model_type: 'auk', family: 'tts' }, { model_type: 'yue2', family: 'tts' }],
    selectedModelPerAudioSubMode: { speech: 'auk', music: 'yue2' }, selectedModelPerMode: { audio: 'auk' },
    audioReferenceStash: {}, loadLoras: async () => {},
    params: { ...previous.params, model_type: 'auk', guidance_scale: 2.5, num_inference_steps: 40,
      audio_prompt_type: 'A', audio_guide: '/api/v1/uploads/reference.wav' },
    audioGuideFilename: 'reference.wav',
  })
  try {
    useStore.getState().setAudioSubMode('music')
    await settleNativeAudioLoad('yue2')
    useStore.getState().setAudioSubMode('speech')
    await settleNativeAudioLoad('auk')
    const params = useStore.getState().params as unknown as Record<string, unknown>
    assert.equal(params.guidance_scale, 2.5)
    assert.equal(params.num_inference_steps, 40)
    assert.equal(params.audio_guide, '/api/v1/uploads/reference.wav')
  } finally { useStore.setState(previous); globalThis.fetch = fetchBefore }
})

test('explicit YuE2 selection still loads the native leftover recipe', async () => {
  const previous = useStore.getState(), fetchBefore = globalThis.fetch
  globalThis.fetch = mockNativeAudioFetches()
  useStore.setState({
    activeWorkspace: 'test', generationMode: 'audio', audioSubMode: 'music',
    models: [{ model_type: 'yue2', family: 'tts' }], selectedModelPerMode: { audio: 'ace_step_v1_5_xl_sft_lm_4b' },
    audioReferenceStash: {}, loadLoras: async () => {},
    params: { ...previous.params, model_type: 'ace_step_v1_5_xl_sft_lm_4b', model_mode: 2, top_k: 17,
      num_inference_steps: 8, guidance_scale: 5 },
  })
  try {
    useStore.getState().selectModel('yue2')
    await waitFor(() => {
      const params = useStore.getState().params as unknown as Record<string, unknown>
      assert.equal(params.model_type, 'yue2')
      assert.equal(params.model_mode, 0)
      assert.equal(params.top_k, 100)
      assert.equal(params.num_inference_steps, 32)
      assert.equal(params.guidance_scale, 1)
    })
  } finally { useStore.setState(previous); globalThis.fetch = fetchBefore }
})
