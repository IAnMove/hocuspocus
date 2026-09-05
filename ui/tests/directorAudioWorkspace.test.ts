import assert from 'node:assert/strict'
import test from 'node:test'
import { JSDOM } from 'jsdom'

const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
Object.assign(globalThis, {
  window: dom.window,
  document: dom.window.document,
  localStorage: dom.window.localStorage,
  Event: dom.window.Event,
  CustomEvent: dom.window.CustomEvent,
})
window.matchMedia = () => ({ matches: false }) as MediaQueryList

test('an adopted song keeps its origin workspace through trim and analysis', { concurrency: false }, async t => {
  const { useStore } = await import('../src/stores/useStore')
  const originalFetch = globalThis.fetch
  const originalReconnect = useStore.getState().reconnectJobs
  const originalConsoleError = console.error
  const requests: Array<{ url: string; body?: Record<string, unknown> }> = []

  t.after(() => {
    globalThis.fetch = originalFetch
    console.error = originalConsoleError
    useStore.setState({ reconnectJobs: originalReconnect })
  })

  console.error = () => {}

  globalThis.fetch = async (input, init = {}) => {
    const url = String(input)
    const body = typeof init.body === 'string' ? JSON.parse(init.body) : undefined
    requests.push({ url, body })
    if (url.endsWith('/api/v1/audio/adopt')) {
      return Response.json({ filename: 'song.wav', path: 'song.wav', url: '/song.wav' })
    }
    if (url.endsWith('/api/v1/audio/trim')) {
      return Response.json({ filename: 'trimmed.wav', path: 'trimmed.wav', url: '/trimmed.wav', start: 1, end: 5, duration: 4 })
    }
    if (url.endsWith('/api/v1/audio/analyze/jobs') && init.method === 'POST') {
      return Response.json({ job_id: 'analysis-test', task_id: 'task-test', root_task_id: 'task-test' })
    }
    if (url.endsWith('/api/v1/audio/analyze/jobs/analysis-test')) {
      return Response.json({ status: 'failed', message: 'Expected test stop', error: 'Expected test stop' })
    }
    throw new Error(`Unexpected request: ${url}`)
  }

  useStore.setState({
    activeWorkspace: 'currently-open',
    reconnectJobs: async () => {},
  })
  await useStore.getState().directorAdoptAndAnalyze(
    { audio_path: 'song.wav', workspace: 'song-origin' },
    'Song from another workspace',
    { trimStart: 1, trimEnd: 5 },
  )

  const bodyFor = (suffix: string) => requests.find(request => request.url.endsWith(suffix))?.body
  assert.equal(bodyFor('/api/v1/audio/adopt')?.workspace, 'song-origin')
  assert.equal(bodyFor('/api/v1/audio/trim')?.workspace, 'song-origin')
  assert.equal(bodyFor('/api/v1/audio/analyze/jobs')?.workspace, 'song-origin')
})
