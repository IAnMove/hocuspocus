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
