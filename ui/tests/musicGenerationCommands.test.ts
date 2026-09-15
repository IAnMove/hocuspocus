import assert from 'node:assert/strict'
import test from 'node:test'
import { JSDOM } from 'jsdom'

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' })
Object.assign(globalThis, {
  window: dom.window,
  document: dom.window.document,
  Event: dom.window.Event,
  localStorage: dom.window.localStorage,
})

const {
  createStudioMusicGenerationCommand,
  fetchMusicGenerationCommandReceipt,
  pendingMusicGenerationCommand,
  pendingMusicGenerationCommands,
  submitMusicGenerationCommand,
  MusicGenerationCommandError,
} = await import('../src/api/musicGenerationCommands.ts')
const {
  STUDIO_MUSIC_MODEL_TYPES,
  STUDIO_MUSIC_PARAM_KEYS,
  projectStudioMusicFormParams,
} = await import('../src/features/studio/musicGenerationSpec.ts')
const { neutralizeSfxOwnedFormFields } = await import('../src/features/studio/sfxFormResidue.ts')

const originalFetch = globalThis.fetch

function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function nativeParams(): Record<string, unknown> {
  return {
    workspace: 'music-workspace',
    prompt: '  [Verse]\nLa noche canta — mañana  ',
    alt_prompt: '  acoustic pop with brushed drums\nkeep this literal  ',
    model_type: 'ace_step_v1_5_xl_sft_lm_4b',
    resolution: '1280x720',
    lyrics_language: 'es-MX',
    video_length: 0,
    num_inference_steps: 8,
    guidance_scale: 1,
    seed: -1,
    image_mode: 0,
    generation_mode: 'audio',
    negative_prompt: '',
    repeat_generation: 1,
    batch_size: 1,
    activated_loras: [],
    loras_multipliers: '',
    multi_prompts_gen_type: 2,
    audio_prompt_type: '',
    audio_guide: null,
    audio_guide2: null,
    audio_guide3: null,
    audio_guide4: null,
    audio_guide5: null,
    audio_guide6: null,
    audio_source: null,
    duration_seconds: 20,
    temperature: null,
    top_p: null,
    top_k: null,
    audio_scale: null,
    alt_guidance_scale: null,
    guidance_phases: null,
    sample_solver: '',
    settings_version: 2,
    prompt_enhancer: '',
    model_mode: null,
    custom_settings: null,
    _music_description: '  a literal night scene  ',
    _music_instrumental: false,
    _audio_sub_mode: 'music',
    _tts_original_prompt: '  preserved TTS bookkeeping  ',
    _tts_speaker_name1: '',
    _tts_speaker_name2: null,
    _tts_speaker_name3: '',
    _tts_speaker_name4: '',
    _tts_speaker_name5: '',
    _tts_speaker_name6: '',
    _tts_voice_count: 0,
  }
}

function command(
  intentId = 'music-intent-1',
  overrides: Record<string, unknown> = {},
) {
  return createStudioMusicGenerationCommand({
    ...nativeParams(),
    ...overrides,
    provenance: { actor: 'wizard', workspace_id: 'music-collection' },
  }, intentId)
}

function queuedReceipt(value: { intent_id: string; operation: string; input: { workspace: string } }) {
  return {
    receipt: {
      version: 1,
      commandId: value.intent_id,
      operation: value.operation,
      status: 'queued',
      entities: [],
      artifacts: [],
      taskIds: [`task-${value.intent_id}`],
      pipelineIds: [],
      result: {
        job_id: `job-${value.intent_id}`,
        task_id: `task-${value.intent_id}`,
        root_task_id: `root-${value.intent_id}`,
        workspace: value.input.workspace,
        status: 'queued',
      },
      commandVersion: 2,
      fingerprintVersion: 2,
      contentFingerprint: 'a'.repeat(64),
    },
    replayed: false,
  }
}

function bodyOf(init: RequestInit | undefined): Record<string, unknown> {
  assert.ok(init?.body)
  return JSON.parse(String(init.body)) as Record<string, unknown>
}

test.afterEach(() => {
  dom.window.localStorage.clear()
  globalThis.fetch = originalFetch
})

test('music builder preserves literal fields, collection provenance and detached nested values', { concurrency: false }, () => {
  const source = nativeParams()
  const command = createStudioMusicGenerationCommand({
    ...source,
    provenance: { actor: 'wizard', workspace_id: 'music-collection' },
  }, ' music-literal-intent ')

  assert.equal(command.version, 2)
  assert.equal(command.operation, 'generation.music')
  assert.equal(command.intent_id, ' music-literal-intent ')
  assert.equal(command.input.workspace, 'music-workspace')
  assert.equal(command.input.workspace_collection_id, 'music-collection')
  assert.equal(command.input.params.prompt, source.prompt)
  assert.equal(command.input.params.alt_prompt, source.alt_prompt)
  assert.equal(command.input.params.lyrics_language, 'es-MX')
  assert.equal(command.input.params._music_description, source._music_description)
  assert.equal(command.input.params._tts_original_prompt, source._tts_original_prompt)
  assert.equal('workspace' in command.input.params, false)
  assert.equal('provenance' in command.input.params, false)
  assert.ok(STUDIO_MUSIC_PARAM_KEYS.includes('lyrics_language'))
  assert.deepEqual(STUDIO_MUSIC_MODEL_TYPES, [
    'ace_step_v1_5_xl_sft_lm_4b',
    'minimax_music3',
    'yue2',
  ])

  source.prompt = 'changed after freeze'
  ;(source as Record<string, unknown>).custom_settings = { bpm: 90 }
  assert.equal(command.input.params.prompt, '  [Verse]\nLa noche canta — mañana  ')
  assert.equal(command.input.params.custom_settings, null)
})

test('music builder retains inactive sentinels but rejects active modes, TTS and non-canonical refs', { concurrency: false }, () => {
  const value = command('music-sentinels')
  assert.equal(value.input.params.image_mode, 0)
  assert.equal(value.input.params.video_length, 0)
  assert.equal(value.input.params.repeat_generation, 1)
  assert.equal(value.input.params._tts_voice_count, 0)
  assert.equal(value.input.params.negative_prompt, '')
  assert.equal(value.input.params.prompt_enhancer, '')

  assert.throws(
    () => command('music-image-mode', { generation_mode: 'image' }),
    /generation_mode/,
  )
  assert.throws(
    () => command('music-voice-mode', { _tts_speaker_name1: 'Alice' }),
    /_tts_speaker_name1/,
  )
  assert.throws(
    () => command('music-orphan-selector', { audio_prompt_type: 'A', audio_guide: null }),
    /audio_guide requires/,
  )
  assert.throws(
    () => command('music-active-tts-count', { _tts_voice_count: 1 }),
    /_tts_voice_count/,
  )
  assert.throws(
    () => command('music-host-path', { audio_guide: '/tmp/guide.wav', audio_prompt_type: 'A' }),
    /canonical audio URL or asset ID/,
  )
  assert.throws(
    () => command('music-unsafe-seed', { seed: Number.MAX_SAFE_INTEGER + 1 }),
    /seed/,
  )
  assert.throws(
    () => command('music-remote', { model_type: 'music-3.0' }),
    /registered local music model/,
  )
})

test('music builder admits empty or omitted style captions', { concurrency: false }, () => {
  const blank = command('music-blank-caption', { alt_prompt: '' })
  assert.equal(blank.input.params.alt_prompt, '')
  assert.equal(blank.input.params.prompt, nativeParams().prompt)

  const withoutCaption = nativeParams()
  delete withoutCaption.alt_prompt
  const omitted = createStudioMusicGenerationCommand({
    ...withoutCaption,
    workspace: 'music-workspace',
  }, 'music-omitted-caption')
  assert.equal('alt_prompt' in omitted.input.params, false)
  assert.equal(omitted.input.params.prompt, withoutCaption.prompt)
})

test('form projection preserves music text, language, refs and sentinels while rejecting active stale controls', { concurrency: false }, () => {
  const source = {
    ...nativeParams(),
    // Normal shared Studio defaults restored beside the music form.
    skip_steps_cache_type: '',
    skip_steps_multiplier: 0.08,
    skip_steps_start_step_perc: 25,
    image_refs: [],
    image_start: [''],
    minimax_h3_turbo_mode: false,
    voice_clone_enabled: false,
    voice_clone_refs: [],
    MMAudio_setting: 0,
    provenance: { actor: 'wizard', workspace_id: 'music-collection' },
  } as Record<string, unknown>
  const projection = projectStudioMusicFormParams(source)

  assert.equal(projection.params.prompt, source.prompt)
  assert.equal(projection.params.alt_prompt, source.alt_prompt)
  assert.equal(projection.params.lyrics_language, source.lyrics_language)
  assert.equal(projection.params.image_mode, 0)
  assert.equal(projection.params._music_instrumental, false)
  assert.ok(projection.droppedFields.includes('skip_steps_multiplier'))
  assert.ok(projection.droppedFields.includes('image_refs'))
  assert.ok(projection.droppedFields.includes('voice_clone_refs'))
  assert.equal('skip_steps_multiplier' in projection.params, false)

  assert.throws(
    () => projectStudioMusicFormParams({ ...source, image_refs: ['asset_subject'] }),
    /image_refs is active and incompatible/,
  )
  assert.throws(
    () => projectStudioMusicFormParams({ ...source, voice_clone_enabled: true }),
    /voice_clone_enabled is active and incompatible/,
  )
  assert.throws(
    () => projectStudioMusicFormParams({ ...source, unknown_music_field: true }),
    /unknown_music_field is not supported/,
  )
  const emptyGuide = projectStudioMusicFormParams({ ...source, video_guide: '' })
  assert.ok(emptyGuide.droppedFields.includes('video_guide'))
  assert.equal('video_guide' in emptyGuide.params, false)
  assert.throws(
    () => projectStudioMusicFormParams({
      ...source, video_guide: '/api/v1/file/clip.mp4?workspace=sfx-source',
    }),
    /video_guide is active and incompatible/,
  )
  assert.throws(
    () => createStudioMusicGenerationCommand(source, 'music-direct-closed'),
    /skip_steps_cache_type|image_refs|voice_clone_enabled/,
  )
})

test('Music form adapter drops leftover SFX prompt and weight without opening the closed builder', { concurrency: false }, () => {
  const leftover = {
    ...nativeParams(),
    MMAudio_prompt: 'thunder crash on tin roof',
    MMAudio_neg_prompt: 'music',
    MMAudio_setting: 1,
    sfx_text_weight: 2.5,
    sfx_mode: true,
    _mmaudio_variant: 'v2',
    _sfx_virtual_model: 'mmaudio_v2',
  }
  assert.throws(
    () => projectStudioMusicFormParams(leftover),
    /MMAudio_prompt is active|sfx_text_weight is not supported/,
  )
  const projection = projectStudioMusicFormParams(neutralizeSfxOwnedFormFields(leftover))
  const command = createStudioMusicGenerationCommand(projection.params, 'music-sfx-form')
  assert.equal(command.input.params.prompt, leftover.prompt)
  assert.equal('MMAudio_prompt' in command.input.params, false)
  assert.equal('sfx_text_weight' in command.input.params, false)
  assert.equal('sfx_mode' in command.input.params, false)
})

test('music admission persists exact envelope before POST and validates a correlated queued receipt', { concurrency: false }, async () => {
  const value = command('music-submit')
  const calls: Array<{ url: string; init?: RequestInit }> = []
  globalThis.fetch = async (url, init) => {
    calls.push({ url: String(url), init })
    assert.deepEqual(pendingMusicGenerationCommands('music-workspace'), [value])
    return response(queuedReceipt(value))
  }

  const result = await submitMusicGenerationCommand(value, {
    submissionContext: { actor: 'wizard', workflowId: 'music-workflow' },
  })

  assert.equal(calls.length, 1)
  assert.equal(calls[0]?.url, '/api/v1/generation/commands')
  assert.deepEqual(bodyOf(calls[0]?.init), value)
  assert.equal((calls[0]?.init?.headers as Record<string, string>)['X-Hocus-UI-Surface'], 'wizard')
  assert.equal(result.operation, 'generation.music')
  assert.equal(result.result.job_id, 'job-music-submit')
  assert.deepEqual(pendingMusicGenerationCommands(), [])
})

test('a lost music response retries the exact JSON and intent without a new job ID', { concurrency: false }, async () => {
  const value = command('music-retry')
  const bodies: Record<string, unknown>[] = []
  let attempt = 0
  globalThis.fetch = async (_url, init) => {
    bodies.push(bodyOf(init))
    attempt += 1
    if (attempt === 1) throw new Error('connection lost after admission')
    return response({ ...queuedReceipt(value), replayed: true })
  }

  await assert.rejects(
    submitMusicGenerationCommand(value),
    error => error instanceof MusicGenerationCommandError && error.uncertain,
  )
  assert.deepEqual(pendingMusicGenerationCommands(), [value])

  const replay = await submitMusicGenerationCommand(value)
  assert.equal(replay.replayed, true)
  assert.equal(bodies.length, 2)
  assert.deepEqual(bodies[1], bodies[0])
  assert.equal((bodies[1]?.intent_id as string), value.intent_id)
  assert.deepEqual(pendingMusicGenerationCommands(), [])
})

test('an initial definitive 422 clears pending, while a later 401 after uncertainty retains recovery', { concurrency: false }, async () => {
  const invalid = command('music-invalid')
  globalThis.fetch = async () => response({ detail: { code: 'invalid_music', message: 'bad song' } }, 422)
  await assert.rejects(
    submitMusicGenerationCommand(invalid),
    error => error instanceof MusicGenerationCommandError && error.status === 422 && !error.uncertain,
  )
  assert.deepEqual(pendingMusicGenerationCommands(), [])

  const uncertain = command('music-auth-after-uncertain')
  let attempt = 0
  globalThis.fetch = async () => {
    attempt += 1
    if (attempt === 1) throw new Error('response lost after commit')
    if (attempt === 2) return response({ detail: 'authentication expired' }, 401)
    return response({ ...queuedReceipt(uncertain), replayed: true })
  }
  await assert.rejects(submitMusicGenerationCommand(uncertain), error => error instanceof MusicGenerationCommandError && error.uncertain)
  await assert.rejects(
    submitMusicGenerationCommand(uncertain),
    error => error instanceof MusicGenerationCommandError && error.status === 401 && error.uncertain,
  )
  assert.deepEqual(pendingMusicGenerationCommands(), [uncertain])
  await submitMusicGenerationCommand(uncertain)
  assert.deepEqual(pendingMusicGenerationCommands(), [])
})

test('same intent conflicts before a second POST when workspace or literal changes', { concurrency: false }, async () => {
  const original = command('music-conflict')
  const changed = command('music-conflict', {
    prompt: 'changed literal',
    workspace: 'other-workspace',
  })
  let calls = 0
  globalThis.fetch = async () => {
    calls += 1
    throw new Error('uncertain transport')
  }

  await assert.rejects(submitMusicGenerationCommand(original))
  await assert.rejects(
    submitMusicGenerationCommand(changed),
    error => error instanceof MusicGenerationCommandError && error.code === 'intent_conflict',
  )
  assert.equal(calls, 1)
  assert.deepEqual(pendingMusicGenerationCommands(), [original])
})

test('uncorrelated 200 and invalid GET receipts remain recoverable, valid GET clears exact workspace receipt', { concurrency: false }, async () => {
  const value = command('music-receipt / recovery')
  let attempt = 0
  globalThis.fetch = async () => {
    attempt += 1
    if (attempt === 1) return response({ receipt: { ...queuedReceipt(value).receipt, commandId: 'other-intent' } })
    return response({ receipt: queuedReceipt(value).receipt, task: { id: `task-${value.intent_id}`, status: 'queued' } })
  }
  await assert.rejects(
    submitMusicGenerationCommand(value),
    error => error instanceof MusicGenerationCommandError && error.code === 'invalid_receipt' && error.uncertain,
  )
  assert.deepEqual(pendingMusicGenerationCommands(), [value])

  globalThis.fetch = async () => response({ receipt: { version: 1, status: 'queued' } })
  await assert.rejects(
    fetchMusicGenerationCommandReceipt(value.input.workspace, value.intent_id),
    error => error instanceof MusicGenerationCommandError && error.code === 'invalid_receipt',
  )
  assert.deepEqual(pendingMusicGenerationCommands(), [value])

  let requestUrl = ''
  globalThis.fetch = async url => {
    requestUrl = String(url)
    return response({ receipt: queuedReceipt(value).receipt, task: { id: `task-${value.intent_id}`, status: 'queued' } })
  }
  const recovered = await fetchMusicGenerationCommandReceipt(value.input.workspace, value.intent_id)
  assert.equal(requestUrl, '/api/v1/generation/commands/receipt?workspace=music-workspace&intent_id=music-receipt%20%2F%20recovery')
  assert.equal(recovered.commandId, value.intent_id)
  assert.deepEqual(pendingMusicGenerationCommands(), [])
  assert.equal(pendingMusicGenerationCommand(value.intent_id), null)
})


test('Music3 still rejects blank or omitted captions before submission', () => {
  for (const caption of ['', '  ', undefined]) {
    assert.throws(() => command('music3-caption', { model_type: 'minimax_music3', alt_prompt: caption }), /alt_prompt/)
  }
})
