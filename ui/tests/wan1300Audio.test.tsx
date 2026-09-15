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
const { render, cleanup, fireEvent } = await import('@testing-library/react')
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
