import assert from 'node:assert/strict'
import test from 'node:test'
import { JSDOM } from 'jsdom'
const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' })
Object.assign(globalThis, { window: dom.window, document: dom.window.document, localStorage: dom.window.localStorage })
const { useStore } = await import('../src/stores/useStore')
const { imageSettingsMode } = await import('../src/features/studio/imageSettingsRestore')
const { snapshotStudioImageIntent, normalizeStudioImageParams, resolveStudioImageMedia } = await import('../src/features/studio/prepareGeneration')
const { editOutputImage, addOutputImageReference } = await import('../src/features/studio/imageInputActions')
const { createStudioImageGenerationCommand } = await import('../src/features/studio/generationSpec')
const initial = useStore.getState()
const originalFetch = globalThis.fetch
const originalBitmap = globalThis.createImageBitmap
const options = { image_outputs: true, inpaint_support: true, image_source_support: true, image_ref_inpaint: true,
  image_ref_choices: { choices: [['Subject', 'KI'], ['Object', 'I']] }, max_image_refs: 10,
  default_num_inference_steps: 40, default_guidance_scale: 1,
  image_edit_modes: { default: 0, choices: [['Masked denoising', 0]] } }
const saved = { model_type: 'qwen_image_21', image_mode: 1, prompt: 'Synthetic blue cube', resolution: '1024x1024',
  num_inference_steps: 17, guidance_scale: 0, seed: 37, sample_solver: 'default', batch_size: 2,
  image_guide: '/api/v1/uploads/source.png', image_mask: '/api/v1/uploads/mask.png', model_mode: 0,
  masking_strength: .6, denoising_strength: .35, video_prompt_type: 'VAGKI',
  image_refs: ['/api/v1/file/ref.png?workspace=source-project'], remove_background_images_ref: 1,
  activated_loras: ['style.safetensors'], loras_multipliers: '.75' }
const json = (body: unknown) => new Response(JSON.stringify(body), { headers: { 'Content-Type': 'application/json' } })
const png = () => new Response('SYNTHETIC_IMAGE', { headers: { 'Content-Type': 'image/png' } })
const tick = () => new Promise(resolve => setTimeout(resolve, 0))
function setup(extra = {}) {
  useStore.setState({ ...initial, generationMode: 'image', imageStudioIntent: 'new', activeWorkspace: 'audit', browsingUploads: false,
    params: { ...initial.params, model_type: 'qwen_image_21' }, modelOptions: options as never,
    models: [{ model_type: 'qwen_image_21', family: 'qwen', name: 'Qwen' }] as never,
    selectedOutputMeta: { params: saved } as never, loadLoras: async () => {}, imageRefs: [], imageStudioDrafts: {}, ...extra }, true)
  globalThis.fetch = async input => String(input).includes('/model-options/') ? json(options) : png()
}
test.afterEach(() => { useStore.setState(initial, true); globalThis.fetch = originalFetch; globalThis.createImageBitmap = originalBitmap })

test('restoring an edit retains source geometry without changing the saved canvas', async () => {
  setup()
  let closed = false
  globalThis.createImageBitmap = (async () => ({ width: 1920, height: 1080, close: () => { closed = true } })) as typeof createImageBitmap
  assert.equal(await useStore.getState().loadSettingsFromOutput(), true)
  assert.deepEqual(useStore.getState().imageSourceSize, { source: saved.image_guide, width: 1920, height: 1080 })
  assert.equal(useStore.getState().params.resolution, saved.resolution)
  assert.equal(closed, true)
})

test('saved edits round trip source, mask, references, sampling, LoRAs and zero CFG', async () => {
  setup()
  assert.equal(await useStore.getState().loadSettingsFromOutput(), true)
  const state = useStore.getState()
  assert.equal(state.imageStudioIntent, 'edit')
  for (const [key, value] of Object.entries(saved)) assert.deepEqual((state.params as unknown as Record<string, unknown>)[key], value, key)
  assert.equal(state.selectedModelPerMode.image, saved.model_type)
  assert.equal(state.removeBackgroundRefs, true)
  assert.deepEqual(state.loraWeights, { 'style.safetensors': [.75] })
  const intent = snapshotStudioImageIntent(state), { params } = normalizeStudioImageParams(intent)
  await resolveStudioImageMedia(intent, params, { uploadImage: async () => { throw new Error('Saved references must not upload again') },
    uploadAudio: async () => { throw new Error('Unexpected audio') }, resolveReferences: async refs => refs as string[] })
  for (const key of ['image_guide', 'image_mask', 'image_refs', 'sample_solver', 'batch_size', 'model_mode', 'guidance_scale']) {
    assert.deepEqual(params[key], saved[key as keyof typeof saved], key)
  }
  const command = createStudioImageGenerationCommand({ ...params, workspace: 'audit' }, 'audit-restore')
  assert.equal(command.input.params.image_guide, saved.image_guide)
  assert.deepEqual(command.input.params.image_refs, saved.image_refs)
})

test('restoring a second output cannot be overwritten by the first reference download', async () => {
  setup({ selectedOutputMeta: { params: { ...saved, image_guide: '', image_mask: '', image_refs: ['/api/v1/uploads/a.png'] } } })
  const deferred = new Map<string, (response: Response) => void>()
  globalThis.fetch = async input => String(input).includes('/model-options/') ? json(options)
    : new Promise<Response>(resolve => deferred.set(String(input), resolve))
  const first = useStore.getState().loadSettingsFromOutput()
  await tick()
  useStore.setState({ selectedOutputMeta: { params: { ...saved, prompt: 'Synthetic B', image_guide: '', image_mask: '', image_refs: ['/api/v1/uploads/b.png'] } } as never })
  const second = useStore.getState().loadSettingsFromOutput()
  await tick()
  deferred.get('/api/v1/uploads/b.png')!(png())
  assert.equal(await second, true)
  deferred.get('/api/v1/uploads/a.png')!(png())
  assert.equal(await first, false)
  assert.equal(useStore.getState().params.prompt, 'Synthetic B')
  assert.deepEqual(useStore.getState().imageRefs.map(file => file.name), ['b.png'])
})

test('editing the form while model options load cancels a saved-settings restore', async () => {
  setup()
  let finish!: (response: Response) => void
  globalThis.fetch = async () => new Promise(resolve => { finish = resolve })
  const pending = useStore.getState().loadSettingsFromOutput()
  await tick()
  useStore.getState().setParam('prompt', 'Keep my new draft')
  finish(json(options))
  assert.equal(await pending, false)
  assert.equal(useStore.getState().params.prompt, 'Keep my new draft')
  assert.equal(useStore.getState().imageStudioIntent, 'new')
})

test('missing media fails without merging an earlier source or changing model and draft', async () => {
  setup()
  useStore.getState().setParam('image_guide', '/api/v1/uploads/previous.png')
  const before = useStore.getState()
  globalThis.fetch = async input => String(input).includes('/model-options/') ? json(options) : new Response('', { status: 404 })
  await assert.rejects(useStore.getState().loadSettingsFromOutput(), /HTTP 404/)
  assert.equal(useStore.getState().params, before.params)
  assert.equal(useStore.getState().modelOptions, before.modelOptions)
})

test('recipes commit tuned values after defaults and clear prior edit inputs', async () => {
  setup({ imageStudioIntent: 'edit', params: { ...initial.params, image_guide: '/api/v1/uploads/previous.png' } })
  globalThis.fetch = async input => String(input).includes('/recipes/') ? json({ model_type: 'qwen_image_21', mode: 'image',
    prompt_example: 'Synthetic recipe', loras: [], params: { num_inference_steps: 17, guidance_scale: 2.3, resolution: '1248x832' } }) : json(options)
  await useStore.getState().applyRecipe('synthetic')
  assert.equal(useStore.getState().params.num_inference_steps, 17)
  assert.equal(useStore.getState().params.guidance_scale, 2.3)
  assert.equal(useStore.getState().params.image_guide, undefined)
  assert.equal(useStore.getState().imageStudioIntent, 'new')
  useStore.getState().setImageStudioIntent('edit')
  assert.equal(useStore.getState().params.image_guide, '/api/v1/uploads/previous.png')
})

test('video sidecars stay out of image restore when the catalog is empty or the model is gone', () => {
  const empty = { models: [] } as never
  assert.equal(imageSettingsMode({
    model_type: 'wan_2_2_i2v', generation_mode: 'video', image_mode: 2, video_length: 81, prompt: 'Extend clip',
  }, empty), false)
  assert.equal(imageSettingsMode({
    model_type: 'ltx2_19b', image_mode: 1, video_length: 97, prompt: 'I2V frames',
  }, empty), false)
  assert.equal(imageSettingsMode({
    model_type: 'qwen_image_21_uncensored_gguf_q6_k', image_mode: 1, prompt: 'Hidden still',
  }, empty), true)
  assert.equal(imageSettingsMode({
    model_type: 'flux_dev', generation_mode: 'image', image_mode: 1, prompt: 'Still',
  }, empty), true)
})

test('loading a video does not switch Studio to Image before models have loaded', async () => {
  const video = { model_type: 'wan_2_2_i2v', generation_mode: 'video', image_mode: 2, video_length: 81,
    prompt: 'Keep this as video', resolution: '1280x720', num_inference_steps: 8, guidance_scale: 5 }
  setup({ generationMode: 'video', models: [], modelsLoaded: false, imageStudioIntent: 'chooser',
    selectedOutputMeta: { params: video } as never })
  await useStore.getState().loadSettingsFromOutput()
  assert.equal(useStore.getState().generationMode, 'video')
  assert.equal(useStore.getState().imageStudioIntent, 'chooser')
  assert.equal(useStore.getState().params.prompt, video.prompt)
  assert.equal(useStore.getState().params.image_mode, 2)
  assert.equal(useStore.getState().params.video_length, 81)
})

test('hidden saved Qwen IDs restore into image mode without appearing in the model catalog', async () => {
  const hidden = 'qwen_image_21_uncensored_gguf_q6_k'
  setup({ generationMode: 'video', selectedOutputMeta: { params: { ...saved, model_type: hidden } } })
  await useStore.getState().loadSettingsFromOutput()
  assert.equal(useStore.getState().generationMode, 'image')
  assert.equal(useStore.getState().params.model_type, hidden)
  assert.equal(useStore.getState().selectedModelPerMode.image, hidden)
  assert.equal(useStore.getState().models.some(model => model.model_type === hidden), false)
})

test('gallery reference action enters a visible reference flow and preserves its source workspace', async () => {
  setup()
  const seen: string[] = []
  globalThis.fetch = async input => { seen.push(String(input)); return png() }
  assert.equal(await addOutputImageReference('reference.png', 'another-project'), true)
  assert.equal(useStore.getState().imageStudioIntent, 'character')
  assert.equal(snapshotStudioImageIntent(useStore.getState()).imageRefs.length, 1)
  assert.deepEqual(seen, ['/api/v1/file/reference.png?workspace=another-project'])
})

test('edit this image uses the selected result and saved settings without requiring its original inputs', async () => {
  setup()
  const seen: string[] = []
  globalThis.fetch = async input => {
    const url = String(input); seen.push(url)
    if (url.includes('/model-options/')) return json(options)
    if (url.includes('/metadata')) return json({ params: saved })
    return png()
  }
  await editOutputImage('result.png', 'audit')
  assert.equal(useStore.getState().imageStudioIntent, 'edit')
  assert.equal(useStore.getState().params.image_guide, '/api/v1/file/result.png?workspace=audit')
  assert.equal(useStore.getState().params.image_mask, undefined)
  assert.deepEqual(useStore.getState().imageRefs, [])
  assert.equal(useStore.getState().params.seed, 37)
  assert.equal(seen.some(url => url.includes('source.png') || url.includes('mask.png') || url.includes('ref.png')), false)
})

test('create and edit keep independent steps, CFG, seed, sampler, LoRAs and output count', () => {
  setup()
  useStore.getState().setParams({ num_inference_steps: 17, guidance_scale: 2, seed: 37, activated_loras: ['first'], sample_solver: 'default' })
  useStore.setState({ loraWeights: { first: [.7] }, outputCount: 3 })
  useStore.getState().setImageStudioIntent('edit')
  useStore.getState().setParams({ num_inference_steps: 8, guidance_scale: 1, seed: 99, activated_loras: [], sample_solver: 'lightning' })
  useStore.getState().setImageStudioIntent('new')
  const state = useStore.getState()
  assert.equal(state.params.num_inference_steps, 17)
  assert.equal(state.params.guidance_scale, 2)
  assert.equal(state.params.seed, 37)
  assert.equal(state.params.sample_solver, 'default')
  assert.deepEqual(state.loraWeights, { first: [.7] })
  assert.equal(state.outputCount, 3)
})
