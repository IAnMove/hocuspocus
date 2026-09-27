import assert from 'node:assert/strict'
import test from 'node:test'
import { JSDOM } from 'jsdom'

const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
Object.assign(globalThis, { window: dom.window, document: dom.window.document,
  localStorage: dom.window.localStorage, Event: dom.window.Event, CustomEvent: dom.window.CustomEvent })
window.matchMedia = () => ({ matches: false })

const { parseAgentTurn } = await import('../src/features/agent/agentActions.ts')
const { getCapability } = await import('../src/features/agent/capabilityRegistry.ts')
const { prepareAudio, queueSfxPack } = await import('../src/features/studio/actions.ts')
const { useStore } = await import('../src/stores/useStore.ts')
const guide = '/api/v1/file/guide.mp4?workspace=source'
const literal = '  Rain on a tin roof.\nKeep this exact.  '
const rawAction = { type: 'prepare_audio', audio_sub_mode: 'sfx', model_type: 'mmaudio_v2',
  prompt: literal, negative_prompt: '', duration_seconds: 3, seed: 20260909,
  inference_steps: 25, guidance_scale: 4.5, output_count: 1, sfx_text_weight: 1.2 }
const parse = raw => parseAgentTurn(JSON.stringify({ reply: 'Prepared', actions: [raw] })).actions[0]

async function withStudio(callback) {
  const before = useStore.getState()
  try {
    useStore.setState({ modelsLoaded: true,
      models: [{ model_type: 'mmaudio_v2', name: 'MMAudio v2', family: 'audio', is_downloaded: true }],
      activeWorkspace: 'sfx-output', generationMode: 'audio', audioSubMode: 'speech',
      params: { ...before.params, model_type: 'mmaudio_v2', prompt: 'old',
        video_guide: guide, seed: 8, repeat_generation: 4, MMAudio_neg_prompt: 'old negative' },
      durationSeconds: 120,
      setGenerationMode: mode => useStore.setState({ generationMode: mode }),
      setAudioSubMode: subMode => useStore.setState({ audioSubMode: subMode }),
      loadModelOptions: before.loadModelOptions,
    })
    await callback()
  } finally { useStore.setState(before) }
}

test('Wizard SFX capability shares its parser and preserves literal fields through preparation', async () => {
  const action = parse({ ...rawAction, video_guide: guide })
  const capability = getCapability('prepare_audio')
  assert.deepEqual(capability.resolve({ ...rawAction, video_guide: guide }), action)
  assert.equal(action.prompt, literal)
  assert.equal(action.negativePrompt, '')
  assert.equal(action.videoGuide, guide)
  assert.equal(action.sfxTextWeight, 1.2)
  assert.equal(action.seed, 20260909)
  const withLanguage = { ...action, languageIntent: { conversationLanguage: 'es',
    contentLanguage: 'es', technicalPromptLanguage: 'en', verbatimSegments: [] } }
  assert.equal(await capability.prepare(withLanguage), withLanguage)
  assert.ok(capability.parameters.includes('video_guide'))
  assert.ok(capability.parameters.includes('sfx_text_weight'))
})

test('SFX parser rejects unsupported controls and unsafe guides instead of clamping', () => {
  for (const invalid of [
    { duration_seconds: 0 }, { duration_seconds: 21, video_guide: null },
    { seed: 1.5 }, { guidance_scale: -1 }, { inference_steps: 24 }, { output_count: 2 },
    { sfx_text_weight: 5.1 }, { video_guide: '' }, { video_guide: '/tmp/guide.mp4' },
    { video_guide: 'https://example.com/guide.mp4' },
  ]) assert.equal(parse({ ...rawAction, ...invalid }), undefined, JSON.stringify(invalid))
})

test('SFX preparation applies native controls, retains an omitted guide and explicitly clears null', async () => {
  await withStudio(async () => {
    await prepareAudio(parse(rawAction))
    let state = useStore.getState()
    assert.equal(state.audioSubMode, 'sfx')
    assert.equal(state.params.prompt, literal)
    assert.equal(state.params.MMAudio_prompt, literal)
    assert.equal(state.params.MMAudio_neg_prompt, '')
    assert.equal(state.params.seed, 20260909)
    assert.equal(state.params.guidance_scale, 4.5)
    assert.equal(state.params.num_inference_steps, 25)
    assert.equal(state.params.repeat_generation, 1)
    assert.equal(state.params.sfx_text_weight, 1.2)
    assert.equal(state.params.video_guide, guide)
    assert.equal(state.durationSeconds, 3)
    await prepareAudio(parse({ ...rawAction, video_guide: null }))
    state = useStore.getState()
    assert.equal(state.params.video_guide, undefined)
    assert.equal(state.params.MMAudio_neg_prompt, '')
  })
})

test('SFX preparation validates the effective guide before any form mutation', async () => {
  await withStudio(async () => {
    const long = parse({ ...rawAction, duration_seconds: 21 })
    // An omitted guide may preserve a video; only the server probes its duration.
    await prepareAudio(long)
    assert.equal(useStore.getState().durationSeconds, 21)
    useStore.getState().setParams({ video_guide: undefined })
    const before = useStore.getState()
    await assert.rejects(prepareAudio(long), /duration/i)
    assert.equal(useStore.getState(), before)
    await assert.rejects(prepareAudio({ ...parse(rawAction), videoGuide: '' }), /video_guide/i)
    assert.equal(useStore.getState(), before)
  })
})

for (const settleWithFailure of [false, true]) {
  test(`entering SFX clears H3 constraints and ignores a late options ${settleWithFailure ? 'failure' : 'response'}`, async () => {
    const before = useStore.getState()
    const fetchBefore = globalThis.fetch
    let finish
    const options = { fps: 30, frames_minimum: 155, frames_maximum: 601,
      guidance_max_phases: 1, default_guidance_scale: 7 }
    const requests = []
    globalThis.fetch = async url => {
      const href = String(url)
      if (href.endsWith('/model-selections') || href.includes('/outputs')) {
        return new Response(JSON.stringify({ outputs: [], total: 0 }), { headers: { 'content-type': 'application/json' } })
      }
      requests.push(href)
      assert.match(href, /model-options.*minimax_h3/)
      return new Promise((resolve, reject) => {
        finish = () => settleWithFailure ? reject(new Error('late request failed'))
          : resolve(new Response(JSON.stringify(options), { headers: { 'content-type': 'application/json' } }))
      })
    }
    try {
      useStore.setState({ generationMode: 'video', audioSubMode: 'speech', modelsLoaded: true,
        models: [{ model_type: 'mmaudio_v2', name: 'MMAudio v2', family: 'tts', is_downloaded: true }],
        selectedModelPerAudioSubMode: {}, selectedModelPerMode: { audio: 'mmaudio_v2' }, activeWorkspace: 'sfx-output',
        params: { ...before.params, model_type: 'minimax_h3', video_guide: guide },
        modelOptions: options, durationSeconds: 5.166666666666667 })
      const pending = useStore.getState().loadModelOptions('minimax_h3')
      assert.equal(useStore.getState().modelOptionsLoading, true)
      await prepareAudio(parse(rawAction))
      assert.equal(useStore.getState().modelOptions, null)
      assert.equal(useStore.getState().modelOptionsLoading, false)
      assert.equal(useStore.getState().durationSeconds, 3)
      assert.equal(useStore.getState().params.video_guide, guide)
      const prepared = useStore.getState()
      finish()
      await pending
      assert.equal(useStore.getState(), prepared, 'obsolete completion must not mutate the SFX form')
      assert.equal(requests.length, 1, 'MMAudio must not fetch backend options or LoRAs')
      // Returning to Audio with its persisted virtual selection must also clear
      // options without relying on setAudioSubMode changing the sub-tab.
      useStore.setState({ generationMode: 'video', modelOptions: options,
        selectedModelPerMode: { audio: 'mmaudio_v2' } })
      useStore.getState().setGenerationMode('audio')
      assert.equal(useStore.getState().modelOptions, null)
      assert.equal(requests.length, 1)
    } finally {
      globalThis.fetch = fetchBefore
      useStore.setState(before)
    }
  })
}


const pack = {
  type: 'queue_sfx_pack', confirm: true, style: 'audio test', modelType: 'mmaudio_v2',
  clips: [
    { name: 'hit', prompt: 'impact', durationSeconds: 2 },
    { name: 'whoosh', prompt: 'whoosh', durationSeconds: 3 },
    { name: 'hit-again', prompt: 'impact', durationSeconds: 2 },
  ],
}
const packContext = { actor: 'wizard', capability: 'queue_sfx_pack', commandId: 'pack-intent', workflowId: 'workflow-1' }
function packReceipt(id) {
  return { version: 1, commandId: id, operation: 'generation.sfx', status: 'queued',
    entities: [], artifacts: [], taskIds: [`task-${id}`], pipelineIds: [],
    result: { task_id: `task-${id}`, job_id: `job-${id}`, workspace: 'sfx-output', status: 'queued' } }
}

function simulatedAdmissions({ failAt = 0, changeWorkspace = false } = {}) {
  const receipts = new Map()
  const attempts = []
  let fail = failAt
  useStore.setState({ jobs: [], startGeneration: async (_scheduled, context) => {
    const params = structuredClone(useStore.getState().params)
    attempts.push({ context, params })
    if (attempts.length === fail) throw new Error('native admission unavailable')
    if (!receipts.has(context.commandId)) receipts.set(context.commandId, packReceipt(context.commandId))
    if (changeWorkspace) useStore.setState({ activeWorkspace: 'other-workspace' })
    // No synthetic UI job: a receipt replay need not append anything locally.
    return receipts.get(context.commandId)
  } })
  return { receipts, attempts, recover: () => { fail = 0 } }
}

test('SFX packs keep distinct child intents, replay the same pack and allow a deliberate new pack', async () => {
  await withStudio(async () => {
    const native = simulatedAdmissions()
    const result = await queueSfxPack(pack, packContext)
    assert.equal(result.status, 'queued')
    assert.equal(native.receipts.size, 3, 'identical clips at different indices are different intentions')
    assert.equal(result.taskIds.length, 3)
    assert.equal(new Set(native.attempts.map(a => a.context.commandId)).size, 3)
    assert.ok(native.attempts.every(a => a.context.workflowId === 'workflow-1'))
    const replay = await queueSfxPack(pack, packContext)
    assert.equal(native.receipts.size, 3)
    assert.deepEqual(replay.taskIds, result.taskIds)
    assert.deepEqual(replay.artifacts[0].metadata.receipts, result.artifacts[0].metadata.receipts)
    await queueSfxPack(pack, { ...packContext, commandId: 'another-pack' })
    assert.equal(native.receipts.size, 6)
  })
})

test('SFX partial submission retains prior receipts and recovers without creating their jobs again', async () => {
  await withStudio(async () => {
    const native = simulatedAdmissions({ failAt: 2 })
    const partial = await queueSfxPack(pack, packContext)
    assert.equal(partial.status, 'partial')
    assert.equal(native.attempts.length, 2, 'stop before attempting the third clip')
    assert.equal(partial.taskIds.length, 1)
    assert.equal(partial.artifacts[0].metadata.receipts.length, 1)
    assert.equal(partial.error.details.nextClipIndex, 1)
    assert.equal(partial.error.details.pendingIntentIds.length, 2)
    native.recover()
    const recovered = await queueSfxPack(pack, packContext)
    assert.equal(recovered.status, 'queued')
    assert.equal(native.receipts.size, 3)
    assert.equal(recovered.taskIds[0], partial.taskIds[0])
  })
})

test('SFX pack stops when the workspace changes and preserves the original task destination', async () => {
  await withStudio(async () => {
    const native = simulatedAdmissions({ changeWorkspace: true })
    const result = await queueSfxPack(pack, packContext)
    assert.equal(result.status, 'partial')
    assert.equal(native.attempts.length, 1)
    assert.equal(result.entities[0].workspaceId, 'sfx-output')
    assert.equal(result.taskIds.length, 1)
  })
})

test('SFX pack rejects an oversized parent before mutating or admitting and reports missing receipts as failure', async () => {
  await withStudio(async () => {
    const before = useStore.getState()
    await assert.rejects(queueSfxPack(pack, { ...packContext, commandId: 'p'.repeat(160) }), /identif/i)
    assert.equal(useStore.getState(), before)
    useStore.setState({ startGeneration: async () => undefined })
    const result = await queueSfxPack(pack, packContext)
    assert.equal(result.status, 'failed')
    assert.deepEqual(result.taskIds, [])
    assert.equal(result.error.details.pendingIntentIds.length, 3)
  })
})

test('registered Wizard SFX pack preserves partial results, every receipt and canonical task IDs', async () => {
  await withStudio(async () => {
    const { createDefaultApplicationAdapters } = await import('../src/features/agent/applicationAdapters.ts')
    const { resolveAndRunRegisteredCapability } = await import('../src/features/agent/capabilityRunner.ts')
    const native = simulatedAdmissions({ failAt: 3 })
    const result = await resolveAndRunRegisteredCapability('queue_sfx_pack', {
      type: 'queue_sfx_pack', confirm: true, model_type: 'mmaudio_v2', visual_style: 'test',
      sfx_clips: pack.clips.map(clip => ({ name: clip.name, prompt: clip.prompt, duration_seconds: clip.durationSeconds })),
    }, { workspace: 'sfx-output', adapters: createDefaultApplicationAdapters(), availability: {
      location: { tab: 'studio' }, labs: { story: { project_id: '' }, series: { series_id: '', episode_id: '', shots: 0, approved: 0 } },
    } })
    assert.equal(result.report.state, 'partial')
    assert.equal(result.commandResult.status, 'partial')
    assert.equal(result.commandResult.taskIds.length, 2)
    assert.equal(result.commandResult.artifacts[0].metadata.receipts.length, 2)
    assert.equal(result.report.metadata.receipts.length, 2)
    assert.equal(result.commandResult.error.code, 'sfx_pack_incomplete')
    assert.equal(native.receipts.size, 2)
  })
})


test('SFX pack parsing preserves literal descriptions and explicit empty negatives without language suffixes', async () => {
  const raw = { type: 'queue_sfx_pack', confirm: true, negative_prompt: '',
    sfx_clips: [{ name: 'rain', prompt: literal, duration_seconds: 3 }] }
  const capability = getCapability('queue_sfx_pack')
  const action = capability.resolve(raw)
  const prepared = await capability.prepare({ ...action, languageIntent: {
    conversationLanguage: 'es', contentLanguage: 'es', technicalPromptLanguage: 'en', verbatimSegments: [],
  } })
  assert.equal(prepared.clips[0].prompt, literal)
  assert.equal(prepared.negativePrompt, '')
  assert.equal(capability.resolve({ ...raw, sfx_clips: [...raw.sfx_clips, { name: 'invalid', prompt: '' }] }), null)
  assert.equal(capability.resolve({ ...raw, sfx_clips: Array(13).fill(raw.sfx_clips[0]) }), null)
  await withStudio(async () => {
    const native = simulatedAdmissions()
    await queueSfxPack(prepared, packContext)
    assert.equal(native.attempts[0].params.MMAudio_prompt, literal)
    assert.equal(native.attempts[0].params.MMAudio_neg_prompt, '')
  })
})

test('Wizard keeps every admitted SFX receipt if final navigation fails', async () => {
  await withStudio(async () => {
    const { createDefaultApplicationAdapters } = await import('../src/features/agent/applicationAdapters.ts')
    const native = simulatedAdmissions()
    useStore.setState({ sidebarOpen: false, setSidebarOpen: () => undefined })
    const outcome = await createDefaultApplicationAdapters().studio.queueSfxPack(pack, packContext)
    assert.equal(outcome.report.state, 'queued')
    assert.equal(outcome.commandResult.taskIds.length, 3)
    assert.equal(outcome.metadata.receipts.length, 3)
    assert.equal(typeof outcome.metadata.presentationWarning, 'string')
    assert.equal(native.receipts.size, 3)
  })
})


test('explicit SFX pack reconciliation retains its chosen model and empty negative prompt', async () => {
  const { reconcileAgentTurnWithRequest } = await import('../src/features/agent/agentActions.ts')
  const action = { ...pack, negativePrompt: '', modelType: 'mmaudio_nsfw' }
  const result = await reconcileAgentTurnWithRequest('Create and enqueue one SFX pack now.', { reply: 'Prepared', actions: [action] })
  assert.equal(result.actions[0].modelType, 'mmaudio_nsfw')
  assert.equal(result.actions[0].negativePrompt, '')
  assert.deepEqual(result.actions[0].clips, pack.clips)
})


const authoredPackRequest = 'Create and enqueue an SFX pack using mmaudio_v2. Preserve these clips:\n'
  + JSON.stringify(pack.clips.map(clip => ({ name: clip.name, prompt: clip.prompt, duration_seconds: clip.durationSeconds })))
  + '\nUse negative_prompt="". Generate from text without a video guide.'

test('an authored SFX JSON pack survives a missing or rewritten LLM proposal without video fallback', async () => {
  const { reconcileAgentTurnWithRequest } = await import('../src/features/agent/agentActions.ts')
  for (const actions of [[], [{ ...pack, clips: [{ name: 'wrong', prompt: 'rewritten', durationSeconds: 9 }] }]]) {
    const turn = await reconcileAgentTurnWithRequest(authoredPackRequest, { reply: 'Old report', actions })
    assert.deepEqual(turn.actions[0].clips, pack.clips)
    assert.equal(turn.actions[0].modelType, 'mmaudio_v2')
    assert.equal(turn.actions[0].negativePrompt, '')
    assert.deepEqual(turn.actions.map(action => action.type), ['queue_sfx_pack'])
  }
})

test('missing or ambiguous SFX pack data cannot launch a different media mode', async () => {
  const { reconcileAgentTurnWithRequest } = await import('../src/features/agent/agentActions.ts')
  for (const request of [
    'Create an SFX pack without a video guide.',
    authoredPackRequest + '\n[{"name":"second","prompt":"ambiguous","duration_seconds":1}]',
  ]) {
    const turn = await reconcileAgentTurnWithRequest(request, { reply: 'Generate video', actions: [] })
    assert.deepEqual(turn.actions, [])
    assert.equal(turn.rejections[0].actionType, 'queue_sfx_pack')
  }
})


test('an explicit unsupported SFX model does not become the default model', async () => {
  const { reconcileAgentTurnWithRequest } = await import('../src/features/agent/agentActions.ts')
  const request = authoredPackRequest.replace('using mmaudio_v2', 'using model_type="unsupported-model"')
  const turn = await reconcileAgentTurnWithRequest(request, { reply: 'Fallback', actions: [pack] })
  assert.deepEqual(turn.actions, [])
  assert.equal(turn.rejections[0].actionType, 'queue_sfx_pack')
})
