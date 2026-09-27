import assert from 'node:assert/strict'
import test from 'node:test'
import { JSDOM } from 'jsdom'
import { concreteImageResolution, referenceImageResolution } from '../src/lib/imageResolution.ts'
import { fitRectangle, paintFit, fitFile } from '../src/lib/imageFit.ts'
import { estimatedRemainingSeconds, phaseCatalogKey } from '../src/features/activity/taskPresentation.ts'
const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' })
Object.assign(globalThis, { window: dom.window, document: dom.window.document, localStorage: dom.window.localStorage })
const { useStore } = await import('../src/stores/useStore.ts')
const { emptyImageStudioDraft } = await import('../src/features/studio/imageStudioIntent.ts')
const { snapshotStudioImageIntent, normalizeStudioImageParams, resolveStudioImageMedia } = await import('../src/features/studio/prepareGeneration.ts')

function extractFrameFetch() {
  return async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.includes('extract-frames')) {
      return Response.json({
        start_path: 'source-frame.png', start_url: '/api/v1/uploads/source-frame.png', session_started_at: 1,
      })
    }
    if (url.includes('model-selections')) return Response.json({})
    return new Response('FRAME', { headers: { 'content-type': 'image/png' } })
  }
}

async function drainStoreFetches() {
  await new Promise(resolve => setTimeout(resolve, 0))
  await new Promise(resolve => setTimeout(resolve, 0))
}

test('prepareImage leaves Edit/Character so a create request cannot reuse the leftover canvas', async () => {
  const initial = useStore.getState()
  const { prepareImage } = await import('../src/features/studio/actions.ts')
  const model = {
    model_type: 'qwen_image_21', name: 'Qwen 2.1', family: 'qwen', architecture: 'qwen_image_21',
    is_i2v: false, is_t2v: false, guidance_max_phases: 1, fps: 1, is_downloaded: true,
  }
  try {
    useStore.setState({
      modelsLoaded: true, generationMode: 'image', imageStudioIntent: 'edit', imageStudioDrafts: {},
      families: [{ id: 'qwen', label: 'Qwen', order: 1 }], models: [model],
      enabledModels: new Set(['qwen_image_21']),
      loadModelOptions: async () => {}, loadOutputs: async () => {},
      params: { ...initial.params, model_type: 'qwen_image_21', image_guide: 'local-edit:portrait',
        image_mask: 'local-edit:mask', video_prompt_type: 'VAG', prompt: 'old edit' },
    })
    await prepareImage({ prompt: 'a mountain landscape at dusk' })
    const state = useStore.getState()
    assert.equal(state.imageStudioIntent, 'new')
    assert.equal(state.params.prompt, 'a mountain landscape at dusk')
    assert.equal(state.params.image_guide, undefined)
    assert.equal(state.imageStudioDrafts.edit?.params.image_guide, 'local-edit:portrait')
    const intent = snapshotStudioImageIntent(state)
    const { params } = normalizeStudioImageParams(intent)
    assert.equal(params.image_guide, undefined)
    assert.equal(params.image_mask, undefined)
    await prepareImage({ prompt: 'extend the canvas', outpaintMargins: '10 10 10 10' })
    assert.equal(useStore.getState().imageStudioIntent, 'edit')
    assert.equal(useStore.getState().params.video_guide_outpainting, '10 10 10 10')
    useStore.setState({
      imageStudioIntent: 'character', imageRefs: [],
      params: { ...useStore.getState().params, image_refs: [] },
    })
    await prepareImage({ prompt: 'a red bicycle' })
    assert.equal(useStore.getState().imageStudioIntent, 'new')
    assert.doesNotThrow(() => snapshotStudioImageIntent(useStore.getState()))
  } finally { useStore.setState(initial, true) }
})

test('edit, create and character restore separate drafts and submit only active resources', async () => {
  const initial = useStore.getState()
  try {
    useStore.setState({ generationMode: 'image', imageStudioIntent: 'chooser', imageStudioDrafts: {} })
    useStore.getState().setImageStudioIntent('edit')
    useStore.getState().setParams({ image_guide: 'local-edit:source', image_mask: 'local-edit:mask', video_prompt_type: 'VAG', prompt: 'Edit this' })
    useStore.getState().setImageStudioIntent('new')
    assert.equal(useStore.getState().params.image_guide, undefined)
    assert.equal(useStore.getState().params.image_mask, undefined)
    useStore.getState().setParam('prompt', 'Create this')
    useStore.getState().setImageStudioIntent('character')
    const file = new File(['ref'], 'ref.png', { type: 'image/png' })
    useStore.setState({ imageRefs: [file], imageRefType: 'KI' })
    useStore.getState().setImageStudioIntent('edit')
    assert.equal(useStore.getState().params.prompt, 'Edit this')
    assert.equal(useStore.getState().params.image_mask, 'local-edit:mask')
    assert.deepEqual(useStore.getState().imageRefs, [])
    useStore.getState().setImageStudioIntent('new')
    assert.equal(useStore.getState().params.prompt, 'Create this')
    const intent = snapshotStudioImageIntent({ ...useStore.getState(), imageRefs: [file], imageRefType: 'KI',
      params: { ...useStore.getState().params, image_guide: 'hidden', image_mask: 'hidden', image_refs: ['hidden'], video_prompt_type: 'VAGKI' },
    })
    const { params } = normalizeStudioImageParams(intent)
    let uploads = 0
    await resolveStudioImageMedia(intent, params, {
      uploadImage: async () => { uploads++; throw new Error('hidden upload') },
      uploadAudio: async () => { throw new Error('hidden upload') }, resolveReferences: async () => [],
    })
    assert.equal(uploads, 0)
    for (const key of ['image_guide', 'image_mask', 'image_refs']) assert.equal(params[key], undefined)
    assert.equal(params.video_prompt_type, '')
    useStore.getState().setImageStudioIntent('character')
    assert.deepEqual(useStore.getState().imageRefs, [file])
    assert.equal(useStore.getState().params.image_guide, undefined)
    useStore.getState().resetImageStudio()
    assert.deepEqual(useStore.getState().imageStudioDrafts, {})
    assert.deepEqual(useStore.getState().imageRefs, [])
    assert.equal(useStore.getState().params.image_refs, undefined)
  } finally { useStore.setState(initial, true) }
})

test('Qwen sizes align to 32 and auto aspect retains source at both pixel budgets', () => {
  const model = 'qwen_image_21_uncensored_gguf_q4_k_m'
  assert.equal(concreteImageResolution('1280x720', model), '1280x736')
  assert.equal(concreteImageResolution('auto', model), '1024x1024')
  for (const preset of ['auto', '720p', '1080p']) {
    for (const [w, h] of [[1920, 1080], [800, 1600], [1301, 997]]) {
      const [width, height] = referenceImageResolution(w, h, preset, model).split('x').map(Number)
      assert.equal(width % 32, 0)
      assert.equal(height % 32, 0)
      assert.ok(Math.abs(width / height - w / h) < .06)
    }
  }
  const initial = useStore.getState()
  try {
    useStore.setState({ generationMode: 'image', aspectRatio: 'auto', params: { ...initial.params, model_type: model, image_guide: 'photo' }, imageSourceSize: { source: 'photo', width: 1920, height: 1080 } })
    useStore.getState().setResolutionPreset('1080p')
    assert.equal(useStore.getState().params.resolution, referenceImageResolution(1920, 1080, '1080p', model))
    useStore.getState().setResolutionPreset('720p')
    assert.equal(useStore.getState().params.resolution, referenceImageResolution(1920, 1080, '720p', model))
  } finally { useStore.setState(initial, true) }
})

test('fit aligns a differently sized mask with source geometry and exports PNG', async () => {
  const calls: unknown[][] = []
  const original = dom.window.HTMLCanvasElement.prototype.getContext
  dom.window.HTMLCanvasElement.prototype.getContext = (() => ({ fillRect: (...args: unknown[]) => calls.push(['fill', ...args]), drawImage: (...args: unknown[]) => calls.push(['draw', ...args]) })) as never
  try {
    for (const mode of ['contain', 'cover', 'stretch'] as const) {
      calls.length = 0
      const source = { width: 200, height: 100 } as HTMLImageElement
      const mask = { width: 20, height: 10 } as HTMLImageElement
      const canvas = paintFit(source, 100, 100, mode)
      paintFit(mask, 100, 100, mode, source, true)
      assert.equal(calls[0][0], 'draw', 'source must not fill an opaque background')
      assert.equal(calls[1][0], 'fill', 'mask padding preserves pixels')
      assert.deepEqual(calls[0].slice(2), calls[2].slice(2))
      canvas.toBlob = (cb, mime) => { assert.equal(mime, 'image/png'); cb(new Blob(['png'], { type: mime })) }
      assert.equal((await fitFile(canvas, 'fitted.png')).type, 'image/png')
    }
    assert.deepEqual(fitRectangle(200, 100, 100, 100, 'contain'), { x: 0, y: 25, width: 100, height: 50 })
    assert.deepEqual(fitRectangle(200, 100, 100, 100, 'cover'), { x: -50, y: 0, width: 200, height: 100 })
  } finally { dom.window.HTMLCanvasElement.prototype.getContext = original }
})

test('footer identifies native phases and estimates sampling without loading time', () => {
  const task = { id: 'qwen', status: 'running', phase: 'Denoising | 3m', created_at: 100, started_at: 100,
    updated_at: 260, current: 10, total: 40, provider: 'local', metadata: { adapter: 'generation', inference_started_at: 240, inference_start_step: 0 } }
  assert.equal(phaseCatalogKey(task), 'inference')
  assert.equal(estimatedRemainingSeconds(task, 260_000), 60)
  for (const [phase, key] of [['Encoding Prompt | 1m', 'encodingText'], ['Encoding Reference Images | 1m', 'encodingImages'], ['VAE Decoding | 3m', 'decoding']]) {
    assert.equal(phaseCatalogKey({ ...task, phase }), key)
    assert.equal(estimatedRemainingSeconds({ ...task, phase }, 260_000), undefined)
  }
  assert.equal(estimatedRemainingSeconds({ ...task, current: 1 }, 260_000), undefined)
})

for (const finish of ['skipAnchorPhase', 'cancelAnchorReturn', 'applyOutputAsAnchor'] as const)
test(`Edit Anything keeps its extracted frame and restores the prior draft after ${finish}`, async () => {
  const initial = useStore.getState()
  const originalFetch = globalThis.fetch
  const old = new File(['old'], 'old-character.png', { type: 'image/png' })
  const savedDraft = { ...emptyImageStudioDraft(), imageRefs: [old], imageRefType: 'I',
    params: { prompt: 'Prior reference draft', seed: 37, num_inference_steps: 17, guidance_scale: 0 } }
  const model = {
    model_type: 'qwen_image_21', name: 'Qwen', family: 'qwen', architecture: 'qwen_image_21',
    is_i2v: false, is_t2v: false, is_downloaded: true,
  }
  globalThis.fetch = extractFrameFetch()
  try {
    useStore.setState({
      generationMode: 'avatar', editSubMode: 'recast', activeWorkspace: 'audit',
      editVideoPath: 'source.mp4', editVideoDuration: 3, editStartTime: 0, editEndTime: 3,
      params: { ...initial.params, model_type: 'viggle_animate' },
      selectedModelPerMode: { ...initial.selectedModelPerMode, image: 'qwen_image_21' },
      families: [{ id: 'qwen', label: 'Qwen', order: 1 }], models: [model],
      imageStudioIntent: 'chooser', imageRefs: [],
      imageStudioDrafts: { character: savedDraft },
      loadModelOptions: async () => {}, loadLoras: async () => {},
    })
    await useStore.getState().sendFrameToImageMode('recast')
    const state = useStore.getState()
    assert.equal(state.generationMode, 'image')
    assert.equal(state.imageStudioIntent, 'character')
    assert.equal(state.imageRefs[0]?.name, 'recast_frame.png')
    assert.equal(snapshotStudioImageIntent(state).imageRefs[0]?.name, 'recast_frame.png')
    state.setImageStudioIntent('new')
    state.setImageStudioIntent('character')
    assert.equal(useStore.getState().imageRefs[0]?.name, 'recast_frame.png')
    useStore.setState({ browsingUploads: false, outputs: [{ name: 'edited-frame.png',
      url: '/api/v1/file/edited-frame.png?workspace=audit', type: 'image', mode: 'image', size: 1, created_at: 2 }] })
    await useStore.getState()[finish]()
    assert.equal(useStore.getState().imageStudioDrafts.character, savedDraft)
    useStore.getState().setGenerationMode('image')
    useStore.getState().setImageStudioIntent('character')
    assert.equal(useStore.getState().imageRefs[0]?.name, 'old-character.png')
    assert.equal(useStore.getState().imageStudioDrafts.character?.imageRefs[0]?.name, 'old-character.png')
    assert.equal(useStore.getState().params.prompt, savedDraft.params.prompt)
    assert.equal(useStore.getState().params.guidance_scale, 0)
    assert.equal(useStore.getState().params.seed, 37)
  } finally {
    await drainStoreFetches()
    globalThis.fetch = originalFetch
    useStore.setState(initial, true)
  }
})

test('Edit Anything return drops a trip-only Character extract when there was no prior draft', async () => {
  const initial = useStore.getState()
  const originalFetch = globalThis.fetch
  const model = {
    model_type: 'qwen_image_21', name: 'Qwen', family: 'qwen', architecture: 'qwen_image_21',
    is_i2v: false, is_t2v: false, is_downloaded: true,
  }
  globalThis.fetch = extractFrameFetch()
  try {
    useStore.setState({
      generationMode: 'avatar', editSubMode: 'recast', activeWorkspace: 'audit',
      editVideoPath: 'source.mp4', editVideoDuration: 3, editStartTime: 0, editEndTime: 3,
      params: { ...initial.params, model_type: 'viggle_animate' },
      selectedModelPerMode: { ...initial.selectedModelPerMode, image: 'qwen_image_21' },
      families: [{ id: 'qwen', label: 'Qwen', order: 1 }], models: [model],
      imageStudioIntent: 'chooser', imageRefs: [], imageStudioDrafts: {},
      loadModelOptions: async () => {}, loadLoras: async () => {},
    })
    await useStore.getState().sendFrameToImageMode('recast')
    assert.equal(useStore.getState().imageRefs[0]?.name, 'recast_frame.png')
    useStore.getState().cancelAnchorReturn()
    assert.equal(useStore.getState().imageStudioDrafts.character, undefined)
    useStore.getState().setGenerationMode('image')
    useStore.getState().setImageStudioIntent('character')
    assert.deepEqual(useStore.getState().imageRefs, [])
  } finally {
    await drainStoreFetches()
    globalThis.fetch = originalFetch
    useStore.setState(initial, true)
  }
})

test('skipping or cancelling without an active trip preserves the existing reference draft', async () => {
  const initial = useStore.getState(), originalFetch = globalThis.fetch
  const draft = { ...emptyImageStudioDraft(), params: { prompt: 'Keep this draft', seed: 37 } }
  globalThis.fetch = extractFrameFetch()
  try {
    useStore.setState({ generationMode: 'avatar', editReturnTarget: null, imageStudioDrafts: { character: draft } })
    useStore.getState().skipAnchorPhase()
    assert.equal(useStore.getState().imageStudioDrafts.character, draft)
    useStore.getState().cancelAnchorReturn()
    assert.equal(useStore.getState().imageStudioDrafts.character, draft)
  } finally { await drainStoreFetches(); useStore.setState(initial, true); globalThis.fetch = originalFetch }
})

test('background model catalog refresh preserves edits made while the request is pending', async () => {
  const initial = useStore.getState()
  const originalFetch = globalThis.fetch
  let finish!: (response: Response) => void
  const requests: string[] = []
  globalThis.fetch = async input => {
    requests.push(String(input))
    return new Promise<Response>(resolve => { finish = resolve })
  }
  try {
    useStore.setState({ modelsLoaded: true, generationMode: 'image', imageStudioIntent: 'edit',
      params: { ...initial.params, model_type: 'qwen_image_21', prompt: 'A blue ceramic vase', image_guide: 'local-edit:source' },
      resolutionPreset: '720p', aspectRatio: '3:2', modelOptionsLoading: false })
    const pending = useStore.getState().loadModels()
    useStore.getState().setParams({ prompt: 'A green ceramic vase', image_mask: 'local-edit:mask', resolution: '1248x832' })
    const before = useStore.getState()
    finish(new Response(JSON.stringify({ families: [], models: [{ model_type: 'qwen_image_21', name: 'Qwen', is_downloaded: true }] })))
    await pending
    const after = useStore.getState()
    assert.deepEqual(requests, ['/api/v1/models'])
    assert.equal(after.params, before.params)
    assert.equal(after.modelOptions, before.modelOptions)
    assert.equal(after.generationMode, 'image')
    assert.equal(after.imageStudioIntent, 'edit')
    assert.equal(after.aspectRatio, '3:2')
    assert.equal(after.resolutionPreset, '720p')
    assert.equal(after.models[0].is_downloaded, true)
  } finally { globalThis.fetch = originalFetch; useStore.setState(initial, true) }
})
