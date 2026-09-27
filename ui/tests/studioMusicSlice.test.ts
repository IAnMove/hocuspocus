import assert from 'node:assert/strict'
import test from 'node:test'
import { JSDOM } from 'jsdom'

const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
Object.assign(globalThis, {
  window: dom.window,
  document: dom.window.document,
  localStorage: dom.window.localStorage,
})

const {
  applyStudioMusicSubmitParams,
  createStudioMusicSlice,
  restoredStudioMusicForm,
} = await import('../src/stores/studioMusicSlice.ts')
const { projectStudioMusicFormParams } = await import('../src/features/studio/musicGenerationSpec.ts')

const ACE = 'ace_step_v1_5_xl_sft_lm_4b'

function musicState(overrides: Record<string, unknown> = {}) {
  return {
    generationMode: 'audio' as const,
    audioSubMode: 'music' as const,
    musicDescription: 'A nocturnal harbor at blue hour.',
    musicInstrumental: false,
    durationSeconds: 12,
    ...overrides,
  }
}

function baseParams(overrides: Record<string, unknown> = {}) {
  return {
    prompt: '[Verse]\nA literal line.\n',
    alt_prompt: 'acoustic pop, brushed drums',
    model_type: ACE,
    generation_mode: 'audio',
    _audio_sub_mode: 'music',
    seed: 7,
    num_inference_steps: 24,
    guidance_scale: 1.7,
    repeat_generation: 1,
    activated_loras: [],
    loras_multipliers: '',
    workspace: 'studio-g03',
    ...overrides,
  }
}

test('Studio music slice owns form state without owning generation execution', () => {
  let state: Record<string, unknown> = {}
  const set = (update: object | ((current: typeof state) => object)) => {
    const partial = typeof update === 'function' ? update(state) : update
    state = { ...state, ...partial }
  }
  const slice = createStudioMusicSlice(set as never, () => state as never)
  state = { ...state, ...slice }
  assert.equal(state.musicDescription, '')
  assert.equal(state.musicInstrumental, false)
  slice.setMusicDescription('harbor')
  slice.setMusicInstrumental(true)
  assert.equal(state.musicDescription, 'harbor')
  assert.equal(state.musicInstrumental, true)
  assert.equal('startGeneration' in slice, false)
  assert.equal('jobs' in slice, false)
  assert.equal('setAudioSubMode' in slice, false)
})

test('create, cover and rehydrate submit payloads stay equivalent', () => {
  const created = applyStudioMusicSubmitParams(baseParams(), musicState())
  assert.equal(created._music_description, 'A nocturnal harbor at blue hour.')
  assert.equal(created._music_instrumental, false)
  assert.equal(created.video_length, 0)
  assert.equal(created.image_mode, 0)
  assert.equal(created.multi_prompts_gen_type, 2)
  assert.equal(created.duration_seconds, 12)
  assert.equal(created.audio_guide, undefined)

  const cover = applyStudioMusicSubmitParams(
    baseParams({ audio_prompt_type: 'A', audio_guide: '/outputs/studio-g03/ref.wav' }),
    musicState(),
  )
  assert.equal(cover.audio_prompt_type, 'A')
  assert.equal(cover.audio_guide, '/outputs/studio-g03/ref.wav')
  assert.equal(cover._music_description, created._music_description)
  assert.equal(cover.duration_seconds, created.duration_seconds)

  const createdProjection = projectStudioMusicFormParams(created)
  const coverProjection = projectStudioMusicFormParams(cover)
  assert.equal(createdProjection.params._music_description, coverProjection.params._music_description)
  assert.equal(coverProjection.params.audio_guide, '/outputs/studio-g03/ref.wav')
  assert.ok(!('flow_shift' in createdProjection.params))

  const restored = restoredStudioMusicForm(created, created.prompt as string)
  const rehydrated = applyStudioMusicSubmitParams(
    baseParams({
      audio_prompt_type: cover.audio_prompt_type,
      audio_guide: cover.audio_guide,
    }),
    musicState({
      musicDescription: restored.musicDescription,
      musicInstrumental: restored.musicInstrumental,
    }),
  )
  assert.equal(rehydrated._music_description, created._music_description)
  assert.equal(rehydrated._music_instrumental, created._music_instrumental)
  assert.equal(rehydrated.audio_guide, cover.audio_guide)
  assert.equal(rehydrated.duration_seconds, created.duration_seconds)
})

test('rehydrate infers instrumental from the lyrics sentinel and clears a missing description', () => {
  const inferred = restoredStudioMusicForm(
    { _music_instrumental: false, prompt: '[Instrumental]' },
    '[Instrumental]',
  )
  assert.equal(inferred.musicDescription, '')
  assert.equal(inferred.musicInstrumental, true)

  const missing = restoredStudioMusicForm({})
  assert.equal(missing.musicDescription, '')
  assert.equal(missing.musicInstrumental, false)

  const speech = applyStudioMusicSubmitParams(
    baseParams({ _audio_sub_mode: 'speech' }),
    musicState({ audioSubMode: 'speech' }),
  )
  assert.equal(speech._music_description, undefined)
  assert.equal(speech.video_length, undefined)
})
