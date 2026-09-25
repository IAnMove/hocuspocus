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

const { STUDIO_IMAGE_PARAM_KEYS } = await import('../src/features/studio/generationSpec.ts')
const {
  normalizeStudioImageParams,
  snapshotStudioImageIntent,
  prepareStudioImageCommand,
} = await import('../src/features/studio/prepareGeneration.ts')
const {
  startStudioImageGeneration,
  startStudioImageGenerationFromStore,
} = await import('../src/features/studio/startGeneration.ts')

const LITERAL_PROMPT = 'Taller de luz ámbar — mañana\n第二行: café crème\nkeep this composition literal'

function imageSource(overrides: Record<string, unknown> = {}) {
  return {
    generationMode: 'image',
    activeWorkspace: 'studio-h11',
    params: {
      prompt: LITERAL_PROMPT,
      model_type: 'pi_flux2',
      resolution: '512x512',
      num_inference_steps: 4,
      guidance_scale: 1,
      seed: 42,
      image_mode: 1,
      video_length: 1,
      generation_mode: 'image',
      negative_prompt: 'borroso\ndo not rewrite',
      repeat_generation: 1,
      activated_loras: [],
      loras_multipliers: '',
      skip_steps_cache_type: '',
      skip_steps_multiplier: 0.08,
      skip_steps_start_step_perc: 25,
      settings_version: 2.52,
      minimax_h3_turbo_mode: false,
      ...(overrides.params as Record<string, unknown> | undefined),
    },
    modelOptions: null,
    models: [{ model_type: 'pi_flux2', name: 'Flux 2' }],
    llmStatus: { loaded: false },
    imageRefs: [],
    imageRefType: '',
    removeBackgroundRefs: false,
    startImage: null,
    endImage: null,
    clips: [],
    singlePromptMode: false,
    spatialUpsampling: '',
    filmGrainIntensity: 0,
    filmGrainSaturation: 0.5,
    voiceCloneEnabled: false,
    voiceCloneMode: 'single',
    voiceCloneRefs: [],
    directorVoiceRef: null,
    directorVoiceRefPath: null,
    directorIdentityGuidanceScale: 1,
    resolutionPreset: '720p',
    aspectRatio: '16:9',
    editReturnTarget: null,
    jobs: [],
    savedParamsPerMode: {},
    ...overrides,
    params: {
      prompt: LITERAL_PROMPT,
      model_type: 'pi_flux2',
      resolution: '512x512',
      num_inference_steps: 4,
      guidance_scale: 1,
      seed: 42,
      image_mode: 1,
      video_length: 1,
      generation_mode: 'image',
      negative_prompt: 'borroso\ndo not rewrite',
      repeat_generation: 1,
      activated_loras: [],
      loras_multipliers: '',
      skip_steps_cache_type: '',
      skip_steps_multiplier: 0.08,
      skip_steps_start_step_perc: 25,
      settings_version: 2.52,
      minimax_h3_turbo_mode: false,
      ...(overrides.params as Record<string, unknown> | undefined),
    },
  }
}

function receiptFor(command: { intent_id: string; input: { workspace: string } }) {
  return {
    version: 1 as const,
    commandId: command.intent_id,
    operation: 'generation.image',
    status: 'queued' as const,
    entities: [],
    artifacts: [],
    taskIds: ['task-' + command.intent_id],
    pipelineIds: [],
    result: {
      job_id: 'job-' + command.intent_id,
      task_id: 'task-' + command.intent_id,
      workspace: command.input.workspace,
      status: 'queued' as const,
    },
    commandVersion: 2 as const,
    fingerprintVersion: 2 as const,
    contentFingerprint: 'a'.repeat(64),
  }
}

function recordingPorts() {
  const jobs: Array<Record<string, unknown>> = []
  const sent: Array<{ intent_id: string; input: { workspace: string; params: Record<string, unknown> } }> = []
  let sends = 0
  const ports = {
    unloadLlm: async () => undefined,
    uploadImage: async () => ({ path: '/api/v1/uploads/x.png', url: '/api/v1/uploads/x.png' }),
    uploadAudio: async () => ({ path: '/api/v1/uploads/a.wav' }),
    resolveReferences: async (references: unknown[]) => references.map(String),
    send: async (command: { intent_id: string; input: { workspace: string; params: Record<string, unknown> } }) => {
      sends += 1
      sent.push(command)
      return receiptFor(command)
    },
    now: () => 1_700_000_000_000,
    newIntentId: () => 'generated-intent',
    prependJob: (job: Record<string, unknown>) => { jobs.push(job) },
    admitJob: (placeholder: Record<string, unknown>, admitted: ReturnType<typeof receiptFor>) => {
      placeholder.id = admitted.result.job_id
      placeholder.taskId = admitted.result.task_id
      placeholder.status = 'queued'
    },
    failJob: (placeholder: Record<string, unknown>, message: string) => {
      placeholder.id = placeholder.id || 'submit-fail-1'
      placeholder.status = 'failed'
      placeholder.message = message
      placeholder.error = message
    },
  }
  return { jobs, sent, sendCount: () => sends, ports }
}

test('two edit sources × two lines freeze four independent single-output commands', async () => {
  let state = imageSource({ imageStudioIntent: 'edit', params: { prompt: 'red\n\nblue\r\n', repeat_generation: 4, batch_size: 3 },
    imageBatch: { enabled: true, perLine: true, sources: [{ url: '/api/v1/uploads/a.png' }, { url: '/api/v1/uploads/b.png' }] } })
  const { ports, sent, jobs } = recordingPorts()
  const host = { get: () => state, set: () => {} }
  const work = startStudioImageGenerationFromStore(host, undefined, { actor: 'user', commandId: 'batch' }, {
    ...ports, startPolling: () => {},
  })
  state = imageSource({ activeWorkspace: 'changed', params: { prompt: 'changed' } })
  await work
  assert.deepEqual(sent.map(item => [item.input.params.image_guide, item.input.params.prompt]), [
    ['/api/v1/uploads/a.png', 'red'], ['/api/v1/uploads/a.png', 'blue'],
    ['/api/v1/uploads/b.png', 'red'], ['/api/v1/uploads/b.png', 'blue'],
  ])
  assert.equal(new Set(sent.map(item => item.intent_id)).size, 4)
  assert.equal(jobs.length, 4)
  for (const item of sent) {
    assert.equal(item.input.workspace, 'studio-h11')
    assert.equal(item.input.params.repeat_generation, 1)
    assert.equal(item.input.params.batch_size, 1)
    assert.equal(item.input.params.video_prompt_type, 'V')
  }
})

test('Qwen Layered batch keeps the requested layer count instead of pinning batch_size to 1', async () => {
  const state = imageSource({
    imageStudioIntent: 'edit',
    modelOptions: { image_source_support: true, image_source_required: true, image_layer_count: { min: 1, max: 16, default: 4 } },
    params: { prompt: 'separate clothing', batch_size: 6, repeat_generation: 3 },
    imageBatch: { enabled: true, perLine: false, sources: [{ url: '/api/v1/uploads/a.png' }, { url: '/api/v1/uploads/b.png' }] },
  })
  const { ports, sent } = recordingPorts()
  await startStudioImageGenerationFromStore({ get: () => state, set: () => {} }, undefined, { actor: 'user', commandId: 'layered' }, {
    ...ports, startPolling: () => {},
  })
  assert.equal(sent.length, 2)
  for (const item of sent) {
    assert.equal(item.input.params.batch_size, 6)
    assert.equal(item.input.params.repeat_generation, 1)
    assert.equal(item.input.params.video_prompt_type, 'V')
  }
})

test('whole prompt keeps newlines and a partial batch failure leaves the other tasks queued', async () => {
  const state = imageSource({ imageStudioIntent: 'edit', imageBatch: { enabled: true, perLine: false,
    sources: [{ url: '/api/v1/uploads/a.png' }, { url: '/api/v1/uploads/b.png' }] } })
  const { ports, sent, jobs } = recordingPorts()
  let fail = true
  await assert.rejects(startStudioImageGenerationFromStore({ get: () => state, set: () => {} }, undefined,
    { actor: 'user', commandId: 'partial' }, { ...ports, startPolling: () => {}, send: async command => {
      if (fail) { fail = false; throw new Error('temporary failure') }
      return ports.send(command)
    } }), /1.*2/)
  assert.equal(jobs[0].status, 'failed')
  assert.equal(jobs[1].status, 'queued')
  assert.equal(sent[0].input.params.prompt, LITERAL_PROMPT)
  await (jobs[0].retry as () => Promise<unknown>)()
  assert.equal(sent[1].intent_id, 'partial-1')
  assert.equal(sent[1].input.params.prompt, LITERAL_PROMPT)
  assert.equal(sent[1].input.params.image_guide, '/api/v1/uploads/a.png')
})

test('an empty or oversized image batch is rejected before submitting any jobs', () => {
  const { ports, jobs } = recordingPorts()
  for (const sources of [[], Array.from({ length: 101 }, (_, n) => ({ url: `/api/v1/uploads/${n}.png` }))]) {
    const state = imageSource({ imageStudioIntent: 'edit', imageBatch: { enabled: true, perLine: false, sources } })
    assert.throws(() => startStudioImageGenerationFromStore({ get: () => state, set: () => {} }, undefined, undefined, ports), /100/)
  }
  assert.equal(jobs.length, 0)
})

test('normalize keeps the literal prompt and does not invent catalog fields', () => {
  const intent = snapshotStudioImageIntent(imageSource())
  const { params } = normalizeStudioImageParams(intent, undefined, {
    actor: 'user',
    capability: 'start_generation',
    commandId: 'intent-normalize',
  })
  assert.equal(params.prompt, LITERAL_PROMPT)
  assert.equal(params.negative_prompt, 'borroso\ndo not rewrite')
  assert.equal(params.video_length, 1)
  assert.equal(params.image_mode, 1)
  assert.equal(params.generation_mode, 'image')
  assert.equal(params.workspace, 'studio-h11')
  assert.equal(params.skip_steps_cache_type, undefined)
  assert.equal(params.skip_steps_multiplier, undefined)
  const derived = new Set([
    'generation_mode', 'workspace', 'video_length', 'image_mode', 'provenance',
    'spatial_upsampling', 'film_grain_intensity', 'film_grain_saturation',
    'voice_clone_enabled', 'voice_clone_mode', 'voice_clone_refs',
    'perturbation_switch',
  ])
  for (const key of Object.keys(params)) {
    if (key in intent.params || derived.has(key)) continue
    assert.fail('invented param ' + key)
  }
})

test('a blank image prompt fails before a generation job is created', async () => {
  const intent = snapshotStudioImageIntent(imageSource({ params: { prompt: '   ' } }))
  const { sent, ports } = recordingPorts()
  await assert.rejects(
    () => startStudioImageGeneration(intent, ports),
    /addPromptHint|non-blank|prompt/i,
  )
  assert.equal(sent.length, 0)
})

test('the same frozen intent yields the same effective command and prompt', async () => {
  const intent = snapshotStudioImageIntent(imageSource({
    params: { image_guide: '/api/v1/uploads/guide.png' },
  }))
  const first = normalizeStudioImageParams(intent)
  const second = normalizeStudioImageParams(intent)
  assert.deepEqual(first.params, second.params)
  const prepared = await prepareStudioImageCommand(
    first.params,
    'same-intent',
    async references => references.map(String),
  )
  assert.equal(prepared.command.intent_id, 'same-intent')
  assert.equal(prepared.command.input.params.prompt, LITERAL_PROMPT)
  assert.equal(prepared.params.prompt, LITERAL_PROMPT)
  assert.equal(prepared.params.video_length, 1)
  assert.equal(prepared.params.image_mode, 1)
  for (const key of Object.keys(prepared.command.input.params)) {
    assert.equal(STUDIO_IMAGE_PARAM_KEYS.includes(key as typeof STUDIO_IMAGE_PARAM_KEYS[number]), true)
  }
})

test('UI edits during await cannot mix the snapshotted image request', async () => {
  let state = imageSource({ llmStatus: { loaded: true } })
  const host = {
    get: () => state,
    set: (partial: object | ((current: typeof state) => object)) => {
      const next = typeof partial === 'function' ? partial(state) : partial
      state = { ...state, ...next }
    },
  }
  const { sent, ports } = recordingPorts()
  let releaseUnload: () => void = () => undefined
  const started = startStudioImageGenerationFromStore(host, undefined, {
    actor: 'user',
    commandId: 'frozen-intent',
  }, {
    ...ports,
    unloadLlm: () => new Promise(resolve => { releaseUnload = resolve }),
  })
  state = imageSource({
    params: { prompt: 'MUTATED AFTER CLICK', seed: 999 },
    llmStatus: { loaded: true },
  })
  releaseUnload()
  const receipt = await started
  assert.equal(sent.length, 1)
  assert.equal(sent[0].input.params.prompt, LITERAL_PROMPT)
  assert.equal(sent[0].input.params.seed, 42)
  assert.equal(sent[0].intent_id, 'frozen-intent')
  assert.equal(receipt?.result.job_id, 'job-frozen-intent')
  assert.equal(receipt?.result.task_id, 'task-frozen-intent')
})

test('replacing local source and mask during preparation cannot erase the frozen image command', async () => {
  const { rememberLocalImage, forgetLocalImage } = await import('../src/lib/localEditImages.ts')
  const source = rememberLocalImage(new File(['original source'], 'source.png', { type: 'image/png' }))
  const mask = rememberLocalImage(new File(['original mask'], 'mask.png', { type: 'image/png' }))
  const intent = snapshotStudioImageIntent(imageSource({ imageStudioIntent: 'edit', llmStatus: { loaded: true },
    modelOptions: { inpaint_support: true }, params: { image_guide: source, image_mask: mask, video_prompt_type: 'VAG' } }))
  const { sent, ports } = recordingPorts(), originalFetch = globalThis.fetch
  const uploaded: string[] = []
  globalThis.fetch = (async (_input, init) => {
    const file = (init?.body as FormData).get('file') as File
    uploaded.push(await file.text())
    return new Response(JSON.stringify({ filename: file.name, url: `/api/v1/uploads/${file.name}` }))
  }) as typeof fetch
  let release!: () => void
  try {
    const started = startStudioImageGeneration(intent, { ...ports, unloadLlm: () => new Promise(resolve => { release = resolve }) })
    forgetLocalImage(source)
    forgetLocalImage(mask)
    release()
    await started
    assert.equal(sent.length, 1)
    assert.deepEqual(uploaded, ['original source', 'original mask'])
    assert.equal(sent[0].input.params.image_guide, '/api/v1/uploads/source.png')
    assert.equal(sent[0].input.params.image_mask, '/api/v1/uploads/mask.png')
  } finally { globalThis.fetch = originalFetch; forgetLocalImage(source); forgetLocalImage(mask) }
})

test('the same intent is admitted once and retry keeps the same ids', async () => {
  const intent = snapshotStudioImageIntent(imageSource())
  const { sent, ports, sendCount } = recordingPorts()
  let release: () => void = () => undefined
  const gate = new Promise<void>(resolve => { release = resolve })
  const delayed = {
    ...ports,
    send: async (command: Parameters<typeof ports.send>[0]) => {
      await gate
      return ports.send(command)
    },
  }
  const context = { actor: 'user' as const, commandId: 'shared-intent' }
  const first = startStudioImageGeneration(intent, delayed, undefined, context)
  const second = startStudioImageGeneration(intent, delayed, undefined, context)
  release()
  const [left, right] = await Promise.all([first, second])
  assert.equal(sendCount(), 1)
  assert.equal(left?.commandId, 'shared-intent')
  assert.equal(right?.commandId, 'shared-intent')
  assert.equal(left?.result.job_id, 'job-shared-intent')
  assert.equal(right?.result.job_id, 'job-shared-intent')
  const retry = await startStudioImageGeneration(intent, ports, undefined, context)
  assert.equal(retry?.commandId, 'shared-intent')
  assert.equal(retry?.result.task_id, 'task-shared-intent')
  assert.equal(sent.every(command => command.intent_id === 'shared-intent'), true)
})

test('prepare uploads in-tab local-edit tokens before resolving command references', async () => {
  const urls = globalThis.URL as typeof URL & {
    createObjectURL?: (file: Blob) => string
    revokeObjectURL?: (url: string) => void
  }
  urls.createObjectURL ??= () => 'blob:local-edit-test'
  urls.revokeObjectURL ??= () => undefined
  const { rememberLocalImage } = await import('../src/lib/localEditImages.ts')
  const originalFetch = globalThis.fetch
  const uploaded: string[] = []
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.includes('/api/v1/upload')) {
      uploaded.push(url)
      return {
        ok: true,
        json: async () => ({ filename: 'from-disk.png', url: '/api/v1/uploads/from-disk.png', path: '/tmp/from-disk.png' }),
      }
    }
    throw new Error('unexpected fetch ' + url)
  }) as typeof fetch
  try {
    const token = rememberLocalImage(new File(['pixels'], 'from-disk.png', { type: 'image/png' }))
    const seen: unknown[][] = []
    const prepared = await prepareStudioImageCommand(
      {
        ...normalizeStudioImageParams(snapshotStudioImageIntent(imageSource({
          params: { image_guide: token, image_mask: token },
        }))).params,
      },
      'local-edit-intent',
      async references => {
        seen.push(references)
        return references.map(String)
      },
    )
    assert.deepEqual(uploaded, ['/api/v1/upload', '/api/v1/upload'])
    assert.deepEqual(seen, [['/api/v1/uploads/from-disk.png', '/api/v1/uploads/from-disk.png']])
    assert.equal(prepared.command.input.params.image_guide, '/api/v1/uploads/from-disk.png')
    assert.equal(prepared.command.input.params.image_mask, '/api/v1/uploads/from-disk.png')
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('a rejected prepare does not POST and keeps the failed job identity local', async () => {
  const intent = snapshotStudioImageIntent(imageSource({
    params: { image_guide: '/api/v1/uploads/guide.png' },
  }))
  const { sent, jobs, ports } = recordingPorts()
  await startStudioImageGeneration(intent, {
    ...ports,
    resolveReferences: async () => { throw new Error('reference failed') },
  }, undefined, { actor: 'user', commandId: 'rejected-intent' })
  assert.equal(sent.length, 0)
  assert.equal(jobs.length, 1)
  assert.equal(jobs[0].status, 'failed')
  assert.equal(jobs[0].id, 'submit-fail-1')
  assert.match(String(jobs[0].error), /reference failed/)
})

test('cancel polling uses the admitted job id from the receipt', async () => {
  const intent = snapshotStudioImageIntent(imageSource())
  const { jobs, ports } = recordingPorts()
  const polled: string[] = []
  const receipt = await startStudioImageGeneration(intent, {
    ...ports,
    startPolling: jobId => { polled.push(jobId) },
  }, undefined, { actor: 'user', commandId: 'cancel-intent' })
  assert.equal(receipt?.result.job_id, 'job-cancel-intent')
  assert.deepEqual(polled, ['job-cancel-intent'])
  assert.equal(jobs[0].id, 'job-cancel-intent')
  assert.equal(jobs[0].taskId, 'task-cancel-intent')
})

test('the queue tile appears synchronously while preparation is blocked', async () => {
  const intent = snapshotStudioImageIntent(imageSource({ llmStatus: { loaded: true } }))
  const { jobs, sent, ports } = recordingPorts()
  let release!: () => void
  const work = startStudioImageGeneration(intent, { ...ports,
    unloadLlm: () => new Promise(resolve => { release = resolve }),
  })
  assert.equal(jobs.length, 1)
  assert.equal(jobs[0].status, 'queued')
  assert.equal(sent.length, 0)
  release()
  await work
  assert.equal(jobs.length, 1)
})

test('retry after an uncertain POST replays the exact command without uploading again', async () => {
  const intent = snapshotStudioImageIntent(imageSource({ params: { image_guide: '/api/v1/uploads/source.png' } }))
  const { jobs, ports } = recordingPorts()
  let resolutions = 0
  const commands: unknown[] = []
  await startStudioImageGeneration(intent, { ...ports,
    resolveReferences: async refs => { resolutions++; return refs.map(String) },
    send: async command => {
      commands.push(command)
      if (commands.length === 1) throw new Error('Connection lost')
      return receiptFor(command)
    },
  }, undefined, { actor: 'user', commandId: 'uncertain-request' })
  assert.equal(jobs[0].error, 'Connection lost')
  const retry = jobs[0].retry as () => Promise<unknown>
  await Promise.all([retry(), retry()])
  assert.equal(commands.length, 2)
  assert.deepEqual(commands[0], commands[1])
  assert.equal(resolutions, 1)
})

test('retry of an admitted job keeps the frozen settings with a new command ID', async () => {
  const source = imageSource()
  const intent = snapshotStudioImageIntent(source)
  const { jobs, sent, ports } = recordingPorts()
  await startStudioImageGeneration(intent, ports, undefined, { actor: 'user', commandId: 'first-attempt' })
  source.params.prompt = 'Changed after submit'
  await (jobs[0].retry as () => Promise<unknown>)()
  assert.equal(sent.length, 2)
  assert.notEqual(sent[0].intent_id, sent[1].intent_id)
  assert.equal(sent[1].input.params.prompt, LITERAL_PROMPT)
})

test('upload failures keep their reason and can be retried', async () => {
  const intent = snapshotStudioImageIntent(imageSource({ imageRefType: 'I',
    imageRefs: [new File(['image'], 'reference.png', { type: 'image/png' })] }))
  const { jobs, ports, sent } = recordingPorts()
  let fail = true
  await startStudioImageGeneration(intent, { ...ports, uploadImage: async file => {
    if (fail) throw new Error('Upload rejected: disk full')
    return ports.uploadImage(file)
  } })
  assert.equal(jobs.length, 1)
  assert.match(String(jobs[0].error), /disk full/)
  assert.equal(sent.length, 0)
  fail = false
  await (jobs[0].retry as () => Promise<unknown>)()
  assert.equal(sent.length, 1)
})

for (const selector of ['', 'V', 'VAG']) {
  test(`Qwen batch enables source conditioning and clears mask flags from ${selector || 'empty'}`, async () => {
    const state = imageSource({ imageStudioIntent: 'edit',
      params: { model_type: 'qwen_image_21', video_prompt_type: selector },
      imageBatch: { enabled: true, perLine: false,
        sources: [{ url: '/api/v1/uploads/a.png' }, { url: '/api/v1/uploads/b.png' }] } })
    const { ports, sent } = recordingPorts()
    await startStudioImageGenerationFromStore({ get: () => state, set: () => {} }, undefined, undefined,
      { ...ports, startPolling: () => {}, send: async command => {
        assert.equal(command.input.params.video_prompt_type, 'V')
        assert.equal(command.input.params.image_mask, undefined)
        return ports.send(command)
      } })
    assert.equal(sent.length, 2)
    assert.equal(state.params.video_prompt_type, selector)
  })
}
