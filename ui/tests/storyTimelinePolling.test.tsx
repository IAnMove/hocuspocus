import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'

function installDom() {
  const dom = new JSDOM('<!doctype html><html><body></body></html>', {
    url: 'http://localhost/',
  })
  Object.assign(globalThis, {
    window: dom.window,
    document: dom.window.document,
    HTMLElement: dom.window.HTMLElement,
    HTMLButtonElement: dom.window.HTMLButtonElement,
    HTMLMediaElement: dom.window.HTMLMediaElement,
    Event: dom.window.Event,
    MutationObserver: dom.window.MutationObserver,
  })
  Object.defineProperty(globalThis, 'navigator', {
    configurable: true,
    value: dom.window.navigator,
  })
}

installDom()

const production = {
  id: 'production-1',
  kind: 'film' as const,
  title: 'Terminal timeline',
  createdAt: '2026-08-16T00:00:00Z',
  sourceVersion: 1,
  targetSnapshot: { pipelineId: 'pipeline-terminal-1' },
  status: 'staged' as const,
}

function pipeline(status = 'completed') {
  return {
    version: 1,
    pipeline_id: 'pipeline-terminal-1',
    created_at: 1,
    completed_at: status === 'completed' ? 2 : null,
    status,
    pipeline_type: 'short_film',
    scene_description: 'A finished scene',
    reference_image_path: null,
    auto_mode: true,
    seamless: false,
    image_model: 'flux',
    video_model: 'minimax_h3',
    llm_log: null,
    clips: [],
    output_files: [],
    total_time_sec: 1,
  }
}

test('terminal story timeline does not schedule another poll', { concurrency: false }, async () => {
  const { render, screen, waitFor, cleanup } = await import('@testing-library/react')
  const { StoryProductionTimeline } = await import('../src/features/stories/StoryProductionTimeline.tsx')
  const originalFetch = globalThis.fetch
  const originalSetTimeout = window.setTimeout
  const originalClearTimeout = window.clearTimeout
  const scheduled: Array<{ callback: TimerHandler; delay: number | undefined }> = []
  let fetches = 0

  globalThis.fetch = async () => {
    fetches += 1
    return new Response(JSON.stringify(pipeline()), {
      headers: { 'content-type': 'application/json' },
    })
  }
  window.setTimeout = ((callback: TimerHandler, delay?: number) => {
    scheduled.push({ callback, delay })
    return scheduled.length
  }) as typeof window.setTimeout
  window.clearTimeout = (() => {}) as typeof window.clearTimeout

  try {
    render(<StoryProductionTimeline production={production} initiallyOpen />)
    await screen.findByText(/Pipeline pipeline-terminal-1/)
    await waitFor(() => assert.equal(fetches, 1))
    assert.equal(scheduled.length, 0)
  } finally {
    cleanup()
    globalThis.fetch = originalFetch
    window.setTimeout = originalSetTimeout
    window.clearTimeout = originalClearTimeout
  }
})

test('successful manual timeline refresh clears an error and cancels retry polling', { concurrency: false }, async () => {
  const { render, screen, waitFor, fireEvent, cleanup } = await import('@testing-library/react')
  const { StoryProductionTimeline } = await import('../src/features/stories/StoryProductionTimeline.tsx')
  const originalFetch = globalThis.fetch
  const originalSetTimeout = window.setTimeout
  const originalClearTimeout = window.clearTimeout
  const scheduled = new Map<number, TimerHandler>()
  const cleared: number[] = []
  let nextTimer = 0
  let fetches = 0

  globalThis.fetch = async () => {
    fetches += 1
    if (fetches === 1) return new Response('unavailable', { status: 503 })
    return new Response(JSON.stringify(pipeline()), {
      headers: { 'content-type': 'application/json' },
    })
  }
  window.setTimeout = ((callback: TimerHandler) => {
    nextTimer += 1
    scheduled.set(nextTimer, callback)
    return nextTimer
  }) as typeof window.setTimeout
  window.clearTimeout = ((timer: number | undefined) => {
    if (typeof timer === 'number') {
      cleared.push(timer)
      scheduled.delete(timer)
    }
  }) as typeof window.clearTimeout

  try {
    render(<StoryProductionTimeline production={production} initiallyOpen />)
    await screen.findByText('Failed to load pipeline (503)')
    assert.equal(scheduled.size, 1)

    fireEvent.click(screen.getByRole('button', { name: 'Refresh timeline' }))
    await waitFor(() => assert.equal(fetches, 2))
    await screen.findByText(/Pipeline pipeline-terminal-1/)
    assert.equal(screen.queryByText('Failed to load pipeline (503)'), null)
    assert.deepEqual(cleared, [1])
    assert.equal(scheduled.size, 0)
  } finally {
    cleanup()
    globalThis.fetch = originalFetch
    window.setTimeout = originalSetTimeout
    window.clearTimeout = originalClearTimeout
  }
})
