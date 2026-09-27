import assert from 'node:assert/strict'
import test from 'node:test'
import { JSDOM } from 'jsdom'

const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
Object.assign(globalThis, { window: dom.window, document: dom.window.document,
  localStorage: dom.window.localStorage, Event: dom.window.Event, CustomEvent: dom.window.CustomEvent })

const { useStore } = await import('../src/stores/useStore')

const options = {
  model_type: 'director_override',
  resolution_preset_order: ['540p', '720p'],
  resolution_presets: {
    '540p': { values: { '16:9': '960x544', '9:16': '544x960' } },
    '720p': { values: { '16:9': '1280x704', '9:16': '704x1280' } },
  },
  supports_auto_aspect: false,
}

function fixture(profileAspect: '16:9' | '9:16') {
  const initial = useStore.getState()
  const previousFetch = globalThis.fetch
  const profile = structuredClone(initial.productionProfile)
  profile.video.model = 'global_model'
  profile.video.settings.aspectRatio = profileAspect
  const puts: Array<Record<string, unknown>> = []
  useStore.setState({
    productionProfile: profile,
    // The Director picked its own video model, so it does not inherit the global one.
    selectedModelPerMode: { ...initial.selectedModelPerMode, video: 'director_override' },
    directorAspectRatio: '9:16',
    directorResolution: '720p',
    modelOptions: null,
  })
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url.endsWith('/api/v1/model-options/director_override')) return Response.json(options)
    if (url.endsWith('/api/v1/production-profile') && init?.method === 'PUT') {
      const body = JSON.parse(String(init.body))
      puts.push(body)
      return Response.json({ configured: true, profile: body.profile })
    }
    if (url.endsWith('/api/v1/production-profile')) return Response.json({ configured: true, profile })
    return Response.json({})
  }) as typeof fetch
  return { puts, close: () => { globalThis.fetch = previousFetch; useStore.setState(initial) } }
}

test('the Director follows the global aspect ratio even with its own video model', async () => {
  const { close } = fixture('16:9')
  try {
    await useStore.getState().loadProductionProfile()
    const state = useStore.getState()
    assert.equal(state.directorAspectRatio, '16:9')
    assert.equal(state.directorResolution, '720p')
    assert.equal(state.selectedModelPerMode.video, 'director_override')
  } finally {
    close()
  }
})

test('a Story Lab resolution and aspect change updates the profile and the Director', async () => {
  const { puts, close } = fixture('16:9')
  try {
    await useStore.getState().setSharedVideoFormat('540p', '9:16')
    const state = useStore.getState()
    assert.equal(state.directorResolution, '540p')
    assert.equal(state.directorAspectRatio, '9:16')
    const saved = puts[0].profile as { video: { settings: { resolution: string; aspectRatio: string } } }
    assert.deepEqual(
      [saved.video.settings.resolution, saved.video.settings.aspectRatio],
      ['540p', '9:16'],
    )
    assert.equal(state.selectedModelPerMode.video, 'director_override')
  } finally {
    close()
  }
})

test('choosing a ratio in the Director saves it to the global profile only', async () => {
  const { puts, close } = fixture('16:9')
  try {
    await useStore.getState().setSharedVideoAspectRatio('9:16')
    const state = useStore.getState()
    assert.equal(state.directorAspectRatio, '9:16')
    assert.equal(state.productionProfile.video.settings.aspectRatio, '9:16')
    assert.equal(puts.length, 1)
    const saved = puts[0].profile as { video: { model: string; settings: { aspectRatio: string } } }
    assert.equal(saved.video.settings.aspectRatio, '9:16')
    assert.equal(saved.video.model, 'global_model')
    assert.equal(state.selectedModelPerMode.video, 'director_override')
  } finally {
    close()
  }
})
