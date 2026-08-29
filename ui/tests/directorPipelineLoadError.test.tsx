import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'

function installDom() {
  const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' })
  Object.assign(globalThis, {
    window: dom.window,
    document: dom.window.document,
    HTMLElement: dom.window.HTMLElement,
    HTMLButtonElement: dom.window.HTMLButtonElement,
    HTMLSelectElement: dom.window.HTMLSelectElement,
    HTMLMediaElement: dom.window.HTMLMediaElement,
    Event: dom.window.Event,
    MutationObserver: dom.window.MutationObserver,
  })
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
  return dom
}

installDom()

function pipeline(id: string, scene: string) {
  return {
    version: 1, pipeline_id: id, created_at: 1, completed_at: null,
    status: 'completed', pipeline_type: 'music_video', scene_description: scene,
    reference_image_path: null, auto_mode: true, seamless: false, image_model: 'flux',
    video_model: 'wan', llm_log: null, clips: [], output_files: [], total_time_sec: 1,
  }
}

test('Director keeps the previous pipeline visible and retries a failed selection', { concurrency: false }, async t => {
  const { render, screen, waitFor, fireEvent, cleanup } = await import('@testing-library/react')
  const { DirectorDashboard } = await import('../src/components/DirectorDashboard/DirectorDashboard.tsx')
  const { useStore } = await import('../src/stores/useStore.ts')
  const previous = pipeline('previous', 'Previous pipeline remains visible')
  const next = pipeline('next', 'New pipeline loaded after retry')
  let attempts = 0
  const originalFetch = globalThis.fetch
  const originalConsoleError = console.error
  t.after(() => {
    globalThis.fetch = originalFetch
    console.error = originalConsoleError
    cleanup()
  })
  console.error = () => undefined
  globalThis.fetch = async (input: string | URL | Request) => {
    const url = String(input)
    const path = url.split('?')[0]
    if (path.endsWith('/api/v1/director/pipelines')) {
      return new Response(JSON.stringify({ pipelines: [{
        id: 'next', status: next.status, pipeline_type: next.pipeline_type,
        created_at: next.created_at, clip_count: 0, output_count: 0,
        scene_description: next.scene_description, workspace: 'default',
      }] }), { headers: { 'content-type': 'application/json' } })
    }
    if (url.endsWith('/api/v1/director/pipelines/next')) {
      attempts += 1
      if (attempts === 1) return new Response('temporarily unavailable', { status: 503 })
      return new Response(JSON.stringify(next), { headers: { 'content-type': 'application/json' } })
    }
    throw new Error(`Unexpected request: ${url}`)
  }

  useStore.setState({
    dashboardOpen: true,
    dashboardLoading: false,
    dashboardLoadError: null,
    dashboardRetryPipelineId: null,
    dashboardPipelineList: [{
      id: 'previous', status: previous.status, pipeline_type: previous.pipeline_type,
      created_at: previous.created_at, clip_count: 0, output_count: 0,
      scene_description: previous.scene_description, workspace: 'default',
    }, {
      id: 'next', status: next.status, pipeline_type: next.pipeline_type,
      created_at: next.created_at, clip_count: 0, output_count: 0,
      scene_description: next.scene_description, workspace: 'default',
    }],
    dashboardSelectedPipeline: previous,
  })

  const view = render(<DirectorDashboard />)
  await useStore.getState().loadSavedPipeline('next')
  await screen.findByRole('alert')
  assert.match(screen.getByText('Previous pipeline remains visible').textContent || '', /Previous pipeline remains visible/)
  assert.equal(useStore.getState().dashboardSelectedPipeline?.pipeline_id, 'previous')

  fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
  await waitFor(() => assert.equal(useStore.getState().dashboardSelectedPipeline?.pipeline_id, 'next'))
  assert.equal(screen.queryByRole('alert'), null)
  assert.match(screen.getByText('New pipeline loaded after retry').textContent || '', /New pipeline loaded after retry/)
  assert.equal(attempts, 2)
  view.unmount()
})
