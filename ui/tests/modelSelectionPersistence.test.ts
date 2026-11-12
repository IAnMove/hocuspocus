// Per-mode model choices are mirrored to the server (PUT /api/v1/model-selections) and to localStorage.
// The server refuses the WHOLE payload when it holds a mode it does not know, so a Tools visit
// ('tools' owns no model) used to poison every later save, and a recipe's model was only saved by
// whatever save happened next.
import assert from 'node:assert/strict'
import test from 'node:test'
import { JSDOM } from 'jsdom'

const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
Object.assign(globalThis, { window: dom.window, document: dom.window.document,
  localStorage: dom.window.localStorage, Event: dom.window.Event, CustomEvent: dom.window.CustomEvent })
window.matchMedia = (() => ({ matches: false })) as typeof window.matchMedia
const { useStore } = await import('../src/stores/useStore')
const { _loadSettings, _persistModelSelections } = await import('../src/stores/modeSettingsPersistence')
const { _globalModelSelectionModes } = await import('../src/stores/servicesSlice')

const SERVER_MODES = new Set(['image', 'video', 'audio', 'model3d', 'avatar'])   // app/services/model_visibility.py _MODEL_SELECTION_MODES
const MODELS = [
  { model_type: 'qwen_image_21', name: 'Qwen', family: 'qwen', is_downloaded: true },
  { model_type: 'flux2_klein_9b', name: 'Flux 2 Klein 9B', family: 'flux2', is_downloaded: true },
  { model_type: 'ltx2_22B_distilled_1_1', name: 'LTX-2.3', family: 'ltx2', is_downloaded: true, fps: 24 },
] as never

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })

/** Records every PUT /model-selections; answers 400 for a mode the server does not know, like the real route. */
async function withServer(run: (puts: Record<string, string>[]) => Promise<void>, extra?: (url: string) => Response | null) {
  const before = useStore.getState(), beforeFetch = globalThis.fetch
  const puts: Record<string, string>[] = []
  try {
    localStorage.clear()
    globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.includes('model-selections') && init?.method === 'PUT') {
        const body = JSON.parse(String(init.body)).selected_models as Record<string, string>
        puts.push(body)
        const bad = Object.keys(body).find(mode => !SERVER_MODES.has(mode))
        if (bad) return json({ detail: `Unknown generation mode: ${bad}.` }, 400)
        return json({ selected_models: body })
      }
      return extra?.(url) ?? json({})
    }) as typeof fetch
    await run(puts)
  } finally {
    await new Promise(resolve => setTimeout(resolve, 20))
    _globalModelSelectionModes.clear()
    localStorage.clear()
    useStore.setState(before); globalThis.fetch = beforeFetch
  }
}

test('Image -> Tools -> Image never sends or stores a tools model selection', async () => {
  await withServer(async puts => {
    useStore.setState({ generationMode: 'image', selectedModelPerMode: { image: 'qwen_image_21' }, models: MODELS,
      params: { ...useStore.getState().params, model_type: 'qwen_image_21' },
      loadModelOptions: async () => {}, loadLoras: async () => {} })
    useStore.getState().setGenerationMode('tools')
    useStore.getState().setGenerationMode('image')
    await new Promise(resolve => setTimeout(resolve, 30))
    assert.ok(puts.length > 0)
    for (const body of puts) {
      assert.deepEqual(Object.keys(body).filter(mode => !SERVER_MODES.has(mode)), [], `PUT carried ${JSON.stringify(body)}`)
    }
    const stored = JSON.parse(localStorage.getItem('maestro_mode_settings') || '{}')
    assert.equal('tools' in (stored.selectedModelPerMode || {}), false)
    const state = useStore.getState()
    for (const map of [state.selectedModelPerMode, state.savedParamsPerMode, state.savedLoraPerMode, state.savedPromptPerMode]) {
      assert.equal('tools' in map, false, 'Tools bookkeeping leaked into a per-mode map')
    }
    assert.equal(state.generationMode, 'image')
    assert.equal(state.selectedModelPerMode.image, 'qwen_image_21')
  })
})

test('a browser that already stored a tools selection is healed on load and on every PUT', async () => {
  await withServer(async puts => {
    localStorage.setItem('maestro_mode_settings', JSON.stringify({ generationMode: 'image',
      selectedModelPerMode: { image: 'qwen_image_21', tools: 'qwen_image_21' }, savedParamsPerMode: {} }))
    assert.deepEqual(_loadSettings()?.selectedModelPerMode, { image: 'qwen_image_21' })
    _persistModelSelections({ image: 'qwen_image_21', tools: 'qwen_image_21', video: '' } as never)
    await new Promise(resolve => setTimeout(resolve, 30))
    assert.deepEqual(puts, [{ image: 'qwen_image_21' }])
  })
})

const RECIPE = { id: 'r1', name: 'Look', description: '', model_type: 'ltx2_22B_distilled_1_1', mode: 'video',
  prompt_example: 'a quiet street', loras: [], params: { video_length: 97, num_inference_steps: 8 } }
const recipeRoute = (url: string) => url.includes('/api/v1/recipes/r1') ? json(RECIPE) : null

test('applying a video recipe saves its model right away', async () => {
  await withServer(async puts => {
    useStore.setState({ generationMode: 'image', selectedModelPerMode: { image: 'qwen_image_21' }, models: MODELS,
      loadModelOptions: async () => {}, loadLoras: async () => {} })
    await useStore.getState().applyRecipe('r1')
    await new Promise(resolve => setTimeout(resolve, 30))
    assert.equal(useStore.getState().selectedModelPerMode.video, RECIPE.model_type)
    assert.equal(puts.some(body => body.video === RECIPE.model_type), true, `no PUT carried the recipe model: ${JSON.stringify(puts)}`)
  }, recipeRoute)
})

test('applying a recipe overrides a mode that followed the production profile', async () => {
  await withServer(async puts => {
    _globalModelSelectionModes.add('video')
    useStore.setState({ generationMode: 'video', selectedModelPerMode: { video: 'some_other_video_model' }, models: MODELS,
      loadModelOptions: async () => {}, loadLoras: async () => {} })
    await useStore.getState().applyRecipe('r1')
    await new Promise(resolve => setTimeout(resolve, 30))
    assert.equal(puts.some(body => body.video === RECIPE.model_type), true, `no PUT carried the recipe model: ${JSON.stringify(puts)}`)
  }, recipeRoute)
})

test('applying an image recipe saves its model right away', async () => {
  const imageRecipe = { ...RECIPE, id: 'r2', model_type: 'qwen_image_21', mode: 'image', params: {} }
  await withServer(async puts => {
    useStore.setState({ generationMode: 'video', selectedModelPerMode: { video: 'ltx2_22B_distilled_1_1' }, models: MODELS,
      loadModelOptions: async () => {}, loadLoras: async () => {} })
    await useStore.getState().applyRecipe('r2')
    await new Promise(resolve => setTimeout(resolve, 30))
    assert.equal(useStore.getState().selectedModelPerMode.image, 'qwen_image_21')
    assert.equal(puts.some(body => body.image === 'qwen_image_21'), true, `no PUT carried the recipe model: ${JSON.stringify(puts)}`)
  }, url => url.includes('/api/v1/recipes/r2') ? json(imageRecipe) : null)
})
