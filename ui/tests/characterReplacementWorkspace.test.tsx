import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'
import type { ApiOutput } from '../src/api/outputs'

const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
Object.assign(globalThis, {
  window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement,
  Event: dom.window.Event, CustomEvent: dom.window.CustomEvent, MutationObserver: dom.window.MutationObserver,
  localStorage: dom.window.localStorage, IS_REACT_ACT_ENVIRONMENT: true,
})
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })

const asset = (name: string, type: 'video' | 'image'): ApiOutput => ({
  name, type, url: `/api/v1/uploads/${name}`, mode: null, created_at: 1, size: 1,
})

async function fixture() {
  const { render, fireEvent, act, waitFor, cleanup } = await import('@testing-library/react')
  const { useStore } = await import('../src/stores/useStore')
  const sessions = await import('../src/features/characterReplacement/session')
  const actions = await import('../src/features/characterReplacement/actions')
  const { CharacterReplacementWorkspace } = await import('../src/features/characterReplacement/CharacterReplacementWorkspace')
  const { setUiLanguage } = await import('../src/i18n')
  await setUiLanguage('en')
  const initial = useStore.getState()
  const originalSessions = sessions.useReplacementSessions.getState()
  const originalFetch = globalThis.fetch
  useStore.setState({
    activeWorkspace: 'replacement-test', editVideoPath: '', editVideoUrl: '',
    models: [{ model_type: 'flux2_klein_9b', name: 'Flux 2 Klein 9B', family: 'flux', architecture: 'flux2_klein_9b', supports_ref_images: true, is_downloaded: false }] as never,
    loadOutputs: async () => {},
  })
  sessions.useReplacementSessions.setState({ sessions: {} })
  globalThis.fetch = async input => { throw new Error(`Unexpected request: ${String(input)}`) }
  return {
    render: () => render(<CharacterReplacementWorkspace />), fireEvent, act, waitFor, setUiLanguage, useStore, actions,
    session: () => sessions.useReplacementSessions.getState().sessions['replacement-test'],
    seed: (patch: Partial<ReturnType<typeof sessions.newReplacementSession>>) => {
      sessions.useReplacementSessions.setState({ sessions: {
        'replacement-test': { ...sessions.newReplacementSession('Replace only the person.\nKeep “¡Hola!” exactly.', asset('source.mp4', 'video')),
          duration: 8.2, width: 832, height: 480,
          frame: { url: '/api/v1/uploads/frame.png', path: 'frame.png', time: 3.1, width: 832, height: 480 },
          character: asset('character.png', 'image'), ...patch },
      } })
    },
    async close() {
      cleanup()
      sessions.useReplacementSessions.setState(originalSessions)
      useStore.setState(initial)
      globalThis.fetch = originalFetch
      await setUiLanguage('en')
    },
  }
}

test('Character replacement shows three localized steps and preserves its editable draft when navigating back', async () => {
  const f = await fixture()
  try {
    const view = f.render()
    assert.ok(view.getByRole('heading', { name: 'Replace character' }))
    assert.equal(view.getAllByRole('region').length, 3)
    assert.ok(view.getByText('Viggle-Animate Pruned 20B'))
    assert.equal(view.getByRole('button', { name: 'Generate replacement frame' }).hasAttribute('disabled'), true)
    assert.equal(view.getByRole('button', { name: 'Generate video with Viggle' }).hasAttribute('disabled'), true)
    const prompt = view.getByLabelText('Replacement instruction') as HTMLTextAreaElement
    assert.match(prompt.value, /Replace the character in image 1/)
    f.fireEvent.change(prompt, { target: { value: 'Keep this exact draft.\n“Hola”.' } })
    await f.act(async () => { await f.setUiLanguage('es') })
    assert.ok(view.getByRole('heading', { name: 'Cambiar personaje' }))
    assert.ok(view.getByRole('button', { name: 'Generar fotograma sustituto' }))
    assert.ok(view.getByRole('button', { name: 'Generar vídeo con Viggle' }))
    view.unmount()
    const restored = f.render()
    assert.equal((restored.getByLabelText('Instrucción de sustitución') as HTMLTextAreaElement).value, 'Keep this exact draft.\n“Hola”.')
    assert.equal(restored.container.querySelectorAll('[class*="overflow-y-auto"]').length, 0)
  } finally { await f.close() }
})

test('Choosing the playhead frame is explicit and uses the native video time', async () => {
  const f = await fixture()
  f.seed({ frame: null, character: null, duration: 0 })
  const requests: Array<Record<string, unknown>> = []
  globalThis.fetch = async (input, init) => {
    assert.equal(String(input), '/api/v1/extract-frames')
    requests.push(JSON.parse(String(init?.body)))
    return Response.json({ start_url: '/api/v1/uploads/chosen.png', start_path: 'chosen.png' })
  }
  try {
    const view = f.render()
    const video = view.container.querySelector('video')!
    video.pause = () => {}
    Object.defineProperties(video, { duration: { value: 8.2 }, videoWidth: { value: 832 }, videoHeight: { value: 480 } })
    f.fireEvent.loadedMetadata(video)
    assert.equal(requests.length, 0)
    f.fireEvent.change(view.getByLabelText(/^Frame position/), { target: { value: '3.1' } })
    assert.equal(video.currentTime, 3.1)
    assert.equal(requests.length, 0)
    f.fireEvent.click(view.getByRole('button', { name: 'Use this frame' }))
    await f.waitFor(() => assert.ok(view.getByRole('img', { name: 'Selected original frame' })))
    assert.equal(requests.length, 1)
    assert.equal(requests[0].start_time, 3.1)
    assert.equal(requests[0].workspace, 'replacement-test')
    assert.equal(f.session().frame?.time, 3.1)
    assert.match(view.getByText(/Frame captured at/).textContent || '', /0:03.1/)
  } finally { await f.close() }
})

test('Each workspace starts with explicit inputs and never inherits Studio uploads', async () => {
  const f = await fixture()
  try {
    f.useStore.setState({ editVideoPath: '/api/v1/uploads/studio.mp4', editVideoUrl: '/api/v1/uploads/studio.mp4' })
    const view = f.render()
    assert.equal(view.container.querySelector('video'), null)
    assert.equal(f.session().source, null)
    await f.act(async () => { f.actions.editReplacementSession('replacement-test', { source: asset('chosen.mp4', 'video') }, 'source') })
    assert.equal(view.container.querySelector('video')?.getAttribute('src'), '/api/v1/uploads/chosen.mp4')
    await f.act(async () => { f.useStore.setState({ activeWorkspace: 'another-workspace' }) })
    assert.equal(view.container.querySelector('video'), null)
    await f.act(async () => { f.useStore.setState({ activeWorkspace: 'replacement-test' }) })
    assert.equal(view.container.querySelector('video')?.getAttribute('src'), '/api/v1/uploads/chosen.mp4')
  } finally { await f.close() }
})

test('One click sequence generates one exact frame job; edits invalidate its dependent result', async () => {
  const f = await fixture()
  f.seed({})
  let resolveStatus!: (response: Response) => void
  const status = new Promise<Response>(resolve => { resolveStatus = resolve })
  const posts: Array<Record<string, unknown>> = []
  globalThis.fetch = async (input, init) => {
    const url = String(input)
    if (url.includes('/defaults/')) return Response.json({ num_inference_steps: 4 })
    if (url === '/api/v1/generate') { posts.push(JSON.parse(String(init?.body))); return Response.json({ job_id: 'exact-frame' }) }
    assert.equal(url, '/api/v1/status/exact-frame')
    return status
  }
  try {
    const view = f.render()
    const generate = view.getByRole('button', { name: 'Generate replacement frame' })
    f.fireEvent.click(generate)
    f.fireEvent.click(generate)
    assert.equal(view.getByRole('button', { name: 'Cancel task' }).hasAttribute('disabled'), true)
    await f.waitFor(() => assert.equal(f.session().imageJob?.id, 'exact-frame'))
    assert.equal(posts.length, 1)
    assert.deepEqual(posts[0].image_refs, ['/api/v1/uploads/frame.png', '/api/v1/uploads/character.png'])
    assert.equal(posts[0].prompt, 'Replace only the person.\nKeep “¡Hola!” exactly.')
    assert.equal(generate.hasAttribute('disabled'), true)
    assert.equal(view.getByRole('button', { name: 'Cancel task' }).hasAttribute('disabled'), false)
    await f.act(async () => {
      f.useStore.setState({ outputs: [{ name: 'unrelated.png', url: '/api/v1/file/unrelated.png', type: 'image' }] as never })
      resolveStatus(Response.json({ job_id: 'exact-frame', status: 'completed', output_files: ['exact-frame.png'], progress: 100, error: null }))
    })
    await f.waitFor(() => assert.equal(view.getByRole('img', { name: 'Generated replacement frame' }).getAttribute('src'), '/api/v1/file/exact-frame.png?workspace=replacement-test'), { timeout: 4000 })
    assert.equal(f.session().imageJob?.id, 'exact-frame')
    assert.equal(view.getByRole('button', { name: 'Generate video with Viggle' }).hasAttribute('disabled'), false)
    await f.act(async () => { f.actions.editReplacementSession('replacement-test', { source: asset('different.mp4', 'video') }, 'source') })
    assert.equal(f.session().frame, null)
    assert.equal(f.session().replacement, null)
    assert.equal(view.queryByRole('img', { name: 'Generated replacement frame' }), null)
    assert.equal(view.getByRole('button', { name: 'Generate video with Viggle' }).hasAttribute('disabled'), true)
  } finally { await f.close() }
})

test('Video generation uses the whole source and shows its own job result', async () => {
  const f = await fixture()
  f.seed({ frameTime: 3.1, replacement: { url: '/api/v1/uploads/replacement.png', path: 'replacement.png' } })
  const posts: Array<Record<string, unknown>> = []
  globalThis.fetch = async (input, init) => {
    const url = String(input)
    if (url === '/api/v1/recast') { posts.push(JSON.parse(String(init?.body))); return Response.json({ job_id: 'exact-video' }) }
    assert.equal(url, '/api/v1/status/exact-video')
    return Response.json({ job_id: 'exact-video', status: 'completed', output_files: ['exact-video.mp4'], progress: 100, error: null })
  }
  const originalCreate = document.createElement.bind(document)
  try {
    const view = f.render()
    document.createElement = ((tag: string, options?: ElementCreationOptions) => {
      const element = originalCreate(tag, options)
      if (tag === 'video') {
        Object.defineProperties(element, { videoWidth: { value: 832 }, videoHeight: { value: 480 } })
        ;(element as HTMLVideoElement).load = () => {}
      }
      if (tag === 'img') Object.defineProperties(element, { naturalWidth: { value: 832 }, naturalHeight: { value: 480 } })
      if (tag === 'video' || tag === 'img') queueMicrotask(() => element.dispatchEvent(new dom.window.Event(tag === 'video' ? 'loadedmetadata' : 'load')))
      return element
    }) as typeof document.createElement
    const generate = view.getByRole('button', { name: 'Generate video with Viggle' })
    f.fireEvent.click(generate)
    f.fireEvent.click(generate)
    await f.waitFor(() => assert.equal(view.getByLabelText('Video with the replacement character').getAttribute('src'), '/api/v1/file/exact-video.mp4?workspace=replacement-test'))
    assert.equal(posts.length, 1)
    assert.equal(posts[0].model_type, 'viggle_animate')
    assert.equal(posts[0].start_time, 0)
    assert.equal(posts[0].end_time, 8.2)
    assert.equal(posts[0].ref_image_path, '/api/v1/uploads/replacement.png')
    assert.equal(f.session().videoJob?.id, 'exact-video')
  } finally { document.createElement = originalCreate; await f.close() }
})
