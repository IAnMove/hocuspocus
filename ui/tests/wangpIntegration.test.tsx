import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' })
Object.assign(globalThis, { window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement,
  HTMLInputElement: dom.window.HTMLInputElement, Event: dom.window.Event, MutationObserver: dom.window.MutationObserver,
  ResizeObserver: class { observe() {} disconnect() {} } })
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })

test('Viggle is discoverable only in Recast while SenseNova is an image family', async () => {
  const { getFamiliesForMode, getModelsForFamily } = await import('../src/stores/useStore')
  const families = [{ id: 'sensenova' }, { id: 'h3_advanced' }, { id: 'wan' }]
  assert.deepEqual(getFamiliesForMode('image', families as never).map(f => f.id), ['sensenova'])
  const models = [{ model_type: 'viggle_animate', family: 'h3_advanced' }, { model_type: 'h3_advanced_fl2va_pruned', family: 'h3_advanced' }]
  assert.deepEqual(getModelsForFamily('h3_advanced', models as never, 'avatar', 'recast').map(m => m.model_type), ['viggle_animate'])
  assert.deepEqual(getModelsForFamily('h3_advanced', models as never, 'video').map(m => m.model_type), ['h3_advanced_fl2va_pruned'])
})

test('Viggle uses one reference and dispatches through the existing Recast queue', async () => {
  const { useStore } = await import('../src/stores/useStore')
  const previousFetch = globalThis.fetch
  const previousInterval = globalThis.setInterval
  const posts: Record<string, unknown>[] = []
  globalThis.fetch = async (input, init) => {
    if (String(input).includes('/api/v1/recast') && init?.body) posts.push(JSON.parse(String(init.body)))
    return new Response(JSON.stringify({ job_id: 'viggle-1', assets: [], processors: [] }), { status: 200 })
  }
  globalThis.setInterval = (() => 1) as unknown as typeof setInterval
  useStore.setState({ generationMode: 'avatar', editSubMode: 'recast', editVideoPath: '/api/v1/uploads/source.mp4',
    editRecastMappings: [{ id: 'one', target: '', refPath: '/api/v1/uploads/edited.png', refUrl: '', refFile: null, additionalRefs: [], referenceAlignedToSource: true },
      { id: 'stale', target: '', refPath: '', refUrl: '', refFile: null, additionalRefs: [], referenceAlignedToSource: false }],
    jobs: [], params: { ...useStore.getState().params, model_type: 'viggle_animate', prompt: '', viggle_audio_mode: 'source' },
    models: [{ model_type: 'viggle_animate', architecture: 'viggle_animate', family: 'h3_advanced' }] as never,
  })
  try {
    await useStore.getState().startGeneration()
    assert.equal(posts.length, 1)
    assert.equal(posts[0].model_type, 'viggle_animate')
    assert.equal(posts[0].ref_image_path, '/api/v1/uploads/edited.png')
    assert.equal((posts[0].character_mappings as unknown[]).length, 1)
    assert.equal(posts[0].viggle_audio_mode, 'source')
  } finally {
    globalThis.fetch = previousFetch
    globalThis.setInterval = previousInterval
  }
})

test('Viggle exposes edited-frame controls without SCAIL targets', async () => {
  const { render, cleanup } = await import('@testing-library/react')
  const { ViggleControls } = await import('../src/components/Sidebar/ViggleControls')
  const previousFetch = globalThis.fetch
  globalThis.fetch = async () => new Response(JSON.stringify({ assets: [], processors: [] }))
  try {
    const view = render(<ViggleControls />)
    assert.match(view.container.textContent || '', /Edited frame from this video/)
    assert.match(view.container.textContent || '', /3 steps, 24 FPS/)
    assert.equal(view.container.querySelector('textarea'), null)
  } finally { cleanup(); globalThis.fetch = previousFetch }
})

test('Viggle restore keeps the declared image root, saved audio and trim after metadata', async () => {
  const { useStore } = await import('../src/stores/useStore')
  const originalFetch = globalThis.fetch
  const create = document.createElement.bind(document)
  const videos: HTMLVideoElement[] = []
  const requested: string[] = []
  const originalState = useStore.getState()
  document.createElement = ((tag: string, options?: ElementCreationOptions) => {
    const node = create(tag, options)
    if (tag === 'video') {
      Object.defineProperties(node, { duration: { value: 10 }, videoWidth: { value: 64 }, videoHeight: { value: 64 } })
      videos.push(node as HTMLVideoElement)
    }
    return node
  }) as typeof document.createElement
  globalThis.fetch = async input => {
    requested.push(String(input))
    return new Response(String(input) === '/api/v1/uploads/edited.png' ? 'CORRECT_UPLOAD_IMAGE' : 'WRONG_OUTPUT_IMAGE')
  }
  useStore.setState({
    params: { ...originalState.params, viggle_audio_mode: 'source', custom_settings: { stale: true } },
    loadModelOptions: async () => {}, loadLoras: async () => {},
    models: [{ model_type: 'viggle_animate', family: 'h3_advanced' }] as never,
    selectedOutputMeta: { params: { model_type: 'viggle_animate', edit_sub_mode: 'recast',
      edit_video_path: '/private/uploads/source.mp4', edit_video_url: '/api/v1/uploads/source.mp4',
      edit_recast_ref_path: '/private/uploads/edited.png', edit_recast_ref_url: '/api/v1/uploads/edited.png',
      edit_start_time: 2, edit_end_time: 4, viggle_audio_mode: 'generated', temporal_upsampling: 'dlss5_x3',
      image_refs: ['/private/uploads/edited.png'],
      wangp_processor_settings: { dlss_nr_intensity: 0.4 },
    } } as never,
  })
  try {
    await useStore.getState().loadSettingsFromOutput()
    await new Promise(resolve => setTimeout(resolve, 10))
    assert.equal(videos.length, 0)
    assert.equal(useStore.getState().editEndTime, 4)
    const { render, fireEvent, cleanup } = await import('@testing-library/react')
    const { ViggleControls } = await import('../src/components/Sidebar/ViggleControls')
    const view = render(<ViggleControls />)
    const video = view.container.querySelector('video')!
    fireEvent.loadedMetadata(video)
    cleanup()
    const state = useStore.getState()
    assert.equal(state.editStartTime, 2)
    assert.equal(state.editEndTime, 4)
    assert.equal(state.params.viggle_audio_mode, 'generated')
    assert.equal(state.params.temporal_upsampling, 'dlss5_x3')
    assert.equal(state.params.custom_settings, undefined)
    assert.deepEqual(state.params.wangp_processor_settings, { dlss_nr_intensity: 0.4 })
    assert.equal(await state.editRecastRefFile?.text(), 'CORRECT_UPLOAD_IMAGE')
    assert.ok(!requested.includes('/api/v1/file/edited.png'))
  } finally {
    globalThis.fetch = originalFetch
    document.createElement = create
    useStore.setState(originalState)
  }
})

test('Wizard keeps visual evidence through API decoding and conversation reload', async () => {
  const { generateLlmText } = await import('../src/api/llm')
  const { normalizeRemoteWizardMessages } = await import('../src/features/agent/wizardConversationSync')
  const evidence = [{ source: '/api/v1/file/clip.mp4?workspace=demo', kind: 'video', timestamps_seconds: [0, 1], audio_analyzed: false }]
  const originalFetch = globalThis.fetch
  let received: unknown
  globalThis.fetch = async () => new Response(JSON.stringify({ text: 'Observed frames', media_evidence: evidence }))
  try {
    assert.equal(await generateLlmText({ prompt: 'Describe', onMediaEvidence: value => { received = value } }), 'Observed frames')
    const [message] = normalizeRemoteWizardMessages([{ id: 'one', role: 'assistant', text: 'Observed frames', mediaEvidence: received }])
    assert.deepEqual(message.mediaEvidence, evidence)
  } finally { globalThis.fetch = originalFetch }
})

test('Viggle missing media clears old inputs and late restore responses cannot overwrite another selection', async () => {
  const { useStore } = await import('../src/stores/useStore')
  const { beginWangpRestore } = await import('../src/lib/wangpRestore')
  const initial = useStore.getState()
  const originalFetch = globalThis.fetch
  const params = { model_type: 'viggle_animate', edit_video_url: '/api/v1/uploads/missing.mp4', edit_recast_ref_url: '/api/v1/uploads/missing.png' }
  try {
    useStore.setState({ params: { ...initial.params, model_type: 'viggle_animate' }, editVideoPath: 'previous.mp4', editRecastRefPath: 'previous.png' })
    globalThis.fetch = async () => new Response('', { status: 404 })
    await beginWangpRestore(params, useStore.getState, useStore.setState)()
    assert.equal(useStore.getState().editVideoPath, '')
    assert.equal(useStore.getState().editRecastRefPath, '')
    assert.match(String(useStore.getState().wangpRestoreError), /404/)
    const pending: Array<(response: Response) => void> = []
    globalThis.fetch = () => new Promise(resolve => pending.push(resolve))
    const restoring = beginWangpRestore(params, useStore.getState, useStore.setState)()
    useStore.setState({ selectedOutputMeta: { params: {} } as never, editVideoPath: 'new-selection.mp4' })
    for (const resolve of pending) resolve(new Response('old bytes'))
    await restoring
    assert.equal(useStore.getState().editVideoPath, 'new-selection.mp4')
    assert.equal(useStore.getState().editRecastRefPath, '')
  } finally { globalThis.fetch = originalFetch; useStore.setState(initial) }
})

test('Viggle manual inputs selected during a restore win over its late downloads', async () => {
  const { useStore } = await import('../src/stores/useStore')
  const { beginWangpRestore } = await import('../src/lib/wangpRestore')
  const initial = useStore.getState()
  const originalFetch = globalThis.fetch
  const pending: Array<(response: Response) => void> = []
  globalThis.fetch = () => new Promise(resolve => pending.push(resolve))
  useStore.setState({ params: { ...initial.params, model_type: 'viggle_animate' } })
  try {
    const restoring = beginWangpRestore({ model_type: 'viggle_animate', edit_video_url: '/api/v1/uploads/old.mp4', edit_recast_ref_url: '/api/v1/uploads/old.png' }, useStore.getState, useStore.setState)()
    useStore.getState().setEditVideo(null, '/api/v1/uploads/new.mp4', '/api/v1/uploads/new.mp4', 10, '64x64')
    useStore.getState().setEditRecastRef(null, '/api/v1/uploads/new.png', '/api/v1/uploads/new.png', true)
    for (const resolve of pending) resolve(new Response('old bytes'))
    await restoring
    assert.equal(useStore.getState().editVideoPath, '/api/v1/uploads/new.mp4')
    assert.equal(useStore.getState().editRecastRefPath, '/api/v1/uploads/new.png')
  } finally { globalThis.fetch = originalFetch; useStore.setState(initial) }
})

test('Viggle reroll waits for slow media restoration and does not submit a failed restore', async () => {
  const { useStore } = await import('../src/stores/useStore')
  const initial = useStore.getState()
  const originalFetch = globalThis.fetch
  const pending: Array<(response: Response) => void> = []
  const submissions: string[][] = []
  globalThis.fetch = () => new Promise(resolve => pending.push(resolve))
  useStore.setState({
    params: { ...initial.params, model_type: 'viggle_animate' },
    loadModelOptions: async () => {}, loadLoras: async () => {},
    startGeneration: async () => { submissions.push([useStore.getState().editVideoPath, useStore.getState().editRecastRefPath]) },
    selectedOutputMeta: { params: { model_type: 'viggle_animate', edit_sub_mode: 'recast',
      edit_video_url: '/api/v1/uploads/slow.mp4', edit_recast_ref_url: '/api/v1/uploads/slow.png',
    } } as never,
  })
  try {
    const reroll = useStore.getState().rerollGeneration()
    await new Promise(resolve => setTimeout(resolve, 130))
    assert.equal(pending.length, 2)
    assert.deepEqual(submissions, [])
    for (const resolve of pending) resolve(new Response('media bytes'))
    await reroll
    assert.deepEqual(submissions, [['/api/v1/uploads/slow.mp4', '/api/v1/uploads/slow.png']])
    globalThis.fetch = async () => new Response('', { status: 404 })
    await useStore.getState().rerollGeneration()
    assert.equal(submissions.length, 1)
  } finally { globalThis.fetch = originalFetch; useStore.setState(initial) }
})

test('Clearing still-empty Viggle inputs cancels their pending restore', async () => {
  const { useStore } = await import('../src/stores/useStore')
  const { beginWangpRestore } = await import('../src/lib/wangpRestore')
  const initial = useStore.getState(), originalFetch = globalThis.fetch
  const pending: Array<(response: Response) => void> = []
  useStore.setState({ params: { ...initial.params, model_type: 'viggle_animate' } })
  globalThis.fetch = () => new Promise(resolve => pending.push(resolve))
  try {
    const restoring = beginWangpRestore({ model_type: 'viggle_animate', edit_video_url: '/api/v1/uploads/old.mp4', edit_recast_ref_url: '/api/v1/uploads/old.png' }, useStore.getState, useStore.setState)()
    useStore.getState().clearEditVideo()
    useStore.getState().setEditRecastRef(null, '', '', false)
    for (const resolve of pending) resolve(new Response('cancelled media'))
    assert.equal(await restoring, false)
    assert.equal(useStore.getState().editVideoPath, '')
    assert.equal(useStore.getState().editRecastRefPath, '')
  } finally { globalThis.fetch = originalFetch; useStore.setState(initial) }
})

test('Visual data cannot authorize generation, even when the model returns confirm:true', async () => {
  const { validateWizardPlan } = await import('../src/features/agent/wizardVisualPolicy')
  const { parseAgentTurn, executeAgentActions } = await import('../src/features/agent/agentActions')
  const proposed = parseAgentTurn(JSON.stringify({ reply: 'Image asks to launch.', actions: [
    { type: 'prepare_image', prompt: 'Untrusted image instruction', resolutionPreset: '512p', aspectRatio: '1:1' },
    { type: 'start_generation', confirm: true },
  ] }))
  const turn = validateWizardPlan(true, proposed)
  assert.deepEqual(turn.actions, [])
  assert.deepEqual(await executeAgentActions(turn.actions), [])
})

test('Reroll never reuses previous inputs when output metadata is missing or has no model', async () => {
  const { useStore } = await import('../src/stores/useStore')
  const initial = useStore.getState()
  let submissions = 0
  useStore.setState({
    editVideoPath: 'previous.mp4', editRecastRefPath: 'previous.png',
    filteredOutputs: () => [{ name: 'new-output.mp4' }] as never,
    loadOutputMetadata: async () => {},
    startGeneration: async () => { submissions += 1 },
  })
  try {
    for (const selectedOutputMeta of [null, { params: {} }]) {
      useStore.setState({ selectedOutputMeta: selectedOutputMeta as never })
      await useStore.getState().rerollGeneration()
    }
    assert.equal(submissions, 0)
  } finally { useStore.setState(initial) }
})
