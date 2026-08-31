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
    Event: dom.window.Event,
    MessageEvent: dom.window.MessageEvent,
    MutationObserver: dom.window.MutationObserver,
  })
  Object.defineProperty(globalThis, 'navigator', {
    configurable: true,
    value: dom.window.navigator,
  })
}

installDom()

class QuietEventSource {
  onopen: ((event: Event) => void) | null = null
  onerror: ((event: Event) => void) | null = null

  addEventListener() {}

  close() {}
}

function task(status: 'failed' | 'running') {
  return {
    id: 'task-generation-retry-1',
    root_id: 'task-generation-retry-1',
    parent_id: null,
    kind: 'generation',
    title: 'Retryable render',
    workflow: 'video',
    status,
    phase: status,
    message: status === 'failed' ? 'Provider stopped' : 'Rendering again',
    detail: '',
    current: status === 'failed' ? 0 : 1,
    total: 10,
    progress: status === 'failed' ? 0 : 0.1,
    detail_current: 0,
    detail_total: 0,
    created_at: 1,
    queued_at: 1,
    started_at: 1,
    updated_at: status === 'failed' ? 2 : 3,
    completed_at: status === 'failed' ? 2 : null,
    attempt: status === 'failed' ? 1 : 2,
    max_attempts: 3,
    cancelable: status === 'running',
    resumable: status === 'failed',
    recoverable: true,
    error: status === 'failed' ? { message: 'Provider stopped', retryable: true } : null,
  }
}

test('failed Activity action keeps its task, exposes Retry, and clears after success', { concurrency: false }, async () => {
  const { render, screen, waitFor, fireEvent, cleanup } = await import('@testing-library/react')
  const { ActivityFooter } = await import('../src/components/ActivityFooter.tsx')
  const originalFetch = globalThis.fetch
  const originalEventSource = globalThis.EventSource
  let resumeCalls = 0

  Object.defineProperty(globalThis, 'EventSource', {
    configurable: true,
    value: QuietEventSource,
  })
  globalThis.fetch = async input => {
    const url = String(input)
    if (url.includes('/api/v1/tasks?')) {
      return new Response(JSON.stringify({
        workspace: 'default',
        tasks: [task('failed')],
        latest_event_id: 10,
      }), { headers: { 'content-type': 'application/json' } })
    }
    if (url.includes('/resume')) {
      resumeCalls += 1
      if (resumeCalls === 1) {
        return new Response(JSON.stringify({ detail: 'provider offline' }), {
          status: 503,
          headers: { 'content-type': 'application/json' },
        })
      }
      return new Response(JSON.stringify({ task: task('running') }), {
        headers: { 'content-type': 'application/json' },
      })
    }
    throw new Error(`Unexpected request: ${url}`)
  }

  try {
    render(<ActivityFooter />)
    await waitFor(() => assert.equal(screen.getByText('Provider stopped').textContent, 'Provider stopped'))
    fireEvent.click(screen.getByRole('button', { name: /Activity/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Resume' }))

    const visibleFailure = await screen.findByText('Resume failed: provider offline')
    assert.equal(visibleFailure.closest('[aria-live="polite"]')?.getAttribute('aria-live'), 'polite')
    assert.equal(screen.getByText('Retryable render').textContent, 'Retryable render')
    assert.equal(resumeCalls, 1)

    fireEvent.click(screen.getByRole('button', { name: 'Retry resume' }))
    await waitFor(() => assert.equal(resumeCalls, 2))
    await waitFor(() => assert.equal(screen.queryByText('Resume failed: provider offline'), null))
    assert.equal(screen.getByText('Retryable render').textContent, 'Retryable render')
  } finally {
    cleanup()
    globalThis.fetch = originalFetch
    Object.defineProperty(globalThis, 'EventSource', {
      configurable: true,
      value: originalEventSource,
    })
  }
})

test('clearing Activity history only hides terminal rows locally', { concurrency: false }, async () => {
  const { render, screen, waitFor, fireEvent, cleanup } = await import('@testing-library/react')
  const { ActivityFooter } = await import('../src/components/ActivityFooter.tsx')
  const originalFetch = globalThis.fetch
  const originalEventSource = globalThis.EventSource
  window.localStorage.clear()
  let taskFetches = 0

  Object.defineProperty(globalThis, 'EventSource', {
    configurable: true,
    value: QuietEventSource,
  })
  globalThis.fetch = async input => {
    const url = String(input)
    if (url.includes('/api/v1/tasks?')) {
      taskFetches += 1
      return new Response(JSON.stringify({
        workspace: 'default',
        tasks: [task('failed')],
        latest_event_id: 10,
      }), { headers: { 'content-type': 'application/json' } })
    }
    throw new Error(`Unexpected request: ${url}`)
  }

  try {
    render(<ActivityFooter />)
    await waitFor(() => assert.equal(screen.getByText('Provider stopped').textContent, 'Provider stopped'))
    fireEvent.click(screen.getByRole('button', { name: /Activity/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Clear activity history' }))
    await waitFor(() => assert.equal(screen.queryByText('Retryable render'), null))
    assert.equal(taskFetches, 1)
    assert.deepEqual(JSON.parse(window.localStorage.getItem('maestro-activity-hidden-v1:default') || '[]'), [task('failed').id])
  } finally {
    cleanup()
    window.localStorage.clear()
    globalThis.fetch = originalFetch
    Object.defineProperty(globalThis, 'EventSource', {
      configurable: true,
      value: originalEventSource,
    })
  }
})

test('Activity summary shows the most recent real completion instead of a rehydrated old failure', { concurrency: false }, async () => {
  const { render, screen, waitFor, cleanup } = await import('@testing-library/react')
  const { ActivityFooter } = await import('../src/components/ActivityFooter.tsx')
  const originalFetch = globalThis.fetch
  const originalEventSource = globalThis.EventSource

  Object.defineProperty(globalThis, 'EventSource', { configurable: true, value: QuietEventSource })
  const staleFailure = { ...task('failed'), id: 'old-failure', root_id: 'old-failure', created_at: 100, started_at: 100, completed_at: 160, updated_at: 9_999 }
  const recentSong = {
    ...task('failed'), id: 'new-song', root_id: 'new-song', title: 'Story song', status: 'completed',
    phase: 'completed', message: 'ACE-Step song ready', error: null, resumable: false,
    created_at: 200, started_at: 200, completed_at: 260, updated_at: 260,
  }
  globalThis.fetch = async input => {
    if (String(input).includes('/api/v1/tasks?')) {
      return new Response(JSON.stringify({ workspace: 'default', tasks: [staleFailure, recentSong], latest_event_id: 10 }), {
        headers: { 'content-type': 'application/json' },
      })
    }
    throw new Error(`Unexpected request: ${String(input)}`)
  }

  try {
    render(<ActivityFooter />)
    await waitFor(() => assert.equal(screen.getByText('ACE-Step song ready').textContent, 'ACE-Step song ready'))
    assert.equal(screen.queryByText('Provider stopped'), null)
  } finally {
    cleanup()
    globalThis.fetch = originalFetch
    Object.defineProperty(globalThis, 'EventSource', { configurable: true, value: originalEventSource })
  }
})
