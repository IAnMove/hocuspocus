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
    Event: dom.window.Event,
    CustomEvent: dom.window.CustomEvent,
    KeyboardEvent: dom.window.KeyboardEvent,
    MessageEvent: dom.window.MessageEvent,
    MutationObserver: dom.window.MutationObserver,
  })
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
}

installDom()

class QuietEventSource {
  onopen: ((event: Event) => void) | null = null
  onerror: ((event: Event) => void) | null = null
  addEventListener() {}
  close() {}
}

function task(overrides: Record<string, unknown> = {}) {
  return {
    id: 'task-generation-retry-1',
    root_id: 'task-generation-retry-1',
    parent_id: null,
    kind: 'generation',
    title: 'Retryable render',
    workflow: 'generation',
    status: 'failed',
    phase: 'failed',
    message: 'Provider stopped',
    detail: '',
    current: 0,
    total: 10,
    progress: 0,
    detail_current: 0,
    detail_total: 0,
    created_at: 1,
    queued_at: 1,
    started_at: 1,
    updated_at: 2,
    completed_at: 2,
    attempt: 1,
    max_attempts: 3,
    cancelable: false,
    resumable: true,
    recoverable: true,
    error: { message: 'Provider stopped', retryable: true },
    metadata: { intent_id: 'intent-retry', receipt_id: 'intent-retry' },
    ...overrides,
  }
}

function jsonTasks(tasks: unknown[], workspace = 'default') {
  return new Response(JSON.stringify({ workspace, tasks, latest_event_id: 10 }), {
    headers: { 'content-type': 'application/json' },
  })
}

test('SSE duplicates and a late poll keep a single group, selection and expansion', { concurrency: false }, async () => {
  const { render, screen, waitFor, fireEvent, cleanup, act } = await import('@testing-library/react')
  const { ActivityFooter } = await import('../src/components/ActivityFooter.tsx')
  const originalFetch = globalThis.fetch
  const originalEventSource = globalThis.EventSource
  let emit: (event: MessageEvent<string>) => void = () => undefined
  class Events extends QuietEventSource {
    addEventListener(_type?: string, listener?: (event: MessageEvent<string>) => void) { if (listener) emit = listener }
  }
  const rows = [
    task({ id: 'older', root_id: 'older', title: 'Older task', created_at: 10, updated_at: 10, status: 'running', phase: 'running', resumable: false, cancelable: true, error: null, metadata: { intent_id: 'intent-old' } }),
    task({ id: 'newer', root_id: 'newer', title: 'Newer task', created_at: 20, updated_at: 20, status: 'running', phase: 'running', resumable: false, cancelable: true, error: null, metadata: { intent_id: 'intent-new' } }),
  ]
  let finishRefresh: (value: Response) => void = () => undefined
  let reads = 0
  globalThis.fetch = async () => ++reads === 1 ? jsonTasks(rows) : new Promise(resolve => { finishRefresh = resolve })
  Object.defineProperty(globalThis, 'EventSource', { configurable: true, value: Events })
  const event = (id: number, type: string, changes: object, taskId = 'older') => new MessageEvent('task', {
    data: JSON.stringify({ task_id: taskId, event_id: id, type, changes, timestamp: 30 }),
    lastEventId: String(id),
  })
  try {
    render(<ActivityFooter />)
    await waitFor(() => assert.equal(reads, 1))
    fireEvent.click(screen.getByRole('button', { name: /Activity/ }))
    await screen.findByText('Older task')
    const older = screen.getByText('Older task').closest('[data-group-id]') as HTMLElement
    fireEvent.click(older.querySelector('button.min-w-0') as HTMLElement)
    assert.equal(older.getAttribute('aria-current'), 'true')
    const panel = screen.getByTestId('activity-details')
    const order = () => [...panel.querySelectorAll('[title="Copy task ID"]')].map(node => node.textContent)
    assert.deepEqual(order(), ['newer', 'older'])
    await act(async () => {
      emit(event(11, 'task.progress', { updated_at: 30, message: 'Fresh progress', current: 5 }))
      emit(event(11, 'task.progress', { updated_at: 30, message: 'Fresh progress', current: 5 }))
      emit(event(12, 'resync_required', {}))
    })
    await act(async () => { finishRefresh(jsonTasks(rows)) })
    assert.deepEqual(order(), ['newer', 'older'])
    assert.equal(screen.getByTestId('activity-details'), panel)
    assert.equal(screen.getByText('Older task').closest('[data-group-id]')?.getAttribute('aria-current'), 'true')
    assert.equal(screen.getByRole('button', { name: /Activity/ }).getAttribute('aria-expanded'), 'true')
    assert.equal(panel.querySelectorAll('[data-group-id]').length, 2)
  } finally {
    cleanup()
    globalThis.fetch = originalFetch
    Object.defineProperty(globalThis, 'EventSource', { configurable: true, value: originalEventSource })
  }
})

test('workspace switches isolate tasks and do not keep the previous folder selected', { concurrency: false }, async () => {
  const { render, screen, waitFor, fireEvent, cleanup } = await import('@testing-library/react')
  const { ActivityFooter } = await import('../src/components/ActivityFooter.tsx')
  const { useStore } = await import('../src/stores/useStore.ts')
  const originalFetch = globalThis.fetch
  const originalEventSource = globalThis.EventSource
  const originalWorkspace = useStore.getState().activeWorkspace
  Object.defineProperty(globalThis, 'EventSource', { configurable: true, value: QuietEventSource })
  globalThis.fetch = async input => {
    const url = String(typeof input === 'string' ? input : (input as { url?: string }).url || input)
    const workspace = /[?&]workspace=([^&]+)/.exec(url)?.[1] || 'default'
    if (url.includes('/api/v1/tasks')) {
      return jsonTasks([
        task({
          id: `task-${workspace}`,
          root_id: `task-${workspace}`,
          title: `Task in ${workspace}`,
          status: 'running',
          phase: 'running',
          message: `${decodeURIComponent(workspace)} running`,
          error: null,
          resumable: false,
          cancelable: true,
          metadata: { intent_id: `intent-${workspace}`, workspace: decodeURIComponent(workspace) },
        }),
      ], decodeURIComponent(workspace))
    }
    return new Response(JSON.stringify({}), { headers: { 'content-type': 'application/json' } })
  }
  try {
    useStore.setState({ activeWorkspace: 'alpha' })
    render(<ActivityFooter />)
    await waitFor(() => assert.ok(screen.getAllByText('alpha running').length >= 1))
    fireEvent.click(screen.getByRole('button', { name: /Activity/ }))
    assert.ok(screen.getByText('Task in alpha'))
    useStore.setState({ activeWorkspace: 'beta' })
    await waitFor(() => assert.ok(screen.getAllByText('beta running').length >= 1), { timeout: 4000 })
    if (screen.queryByTestId('activity-details') == null) {
      fireEvent.click(screen.getByRole('button', { name: /Activity/ }))
    }
    await screen.findByText('Task in beta')
    assert.equal(screen.queryByText('Task in alpha'), null)
    assert.equal(screen.queryByText('alpha running'), null)
  } finally {
    cleanup()
    useStore.setState({ activeWorkspace: originalWorkspace })
    globalThis.fetch = originalFetch
    Object.defineProperty(globalThis, 'EventSource', { configurable: true, value: originalEventSource })
  }
})

test('admitted generation without an artifact is not shown completed', { concurrency: false }, async () => {
  const { render, screen, waitFor, fireEvent, cleanup } = await import('@testing-library/react')
  const { ActivityFooter } = await import('../src/components/ActivityFooter.tsx')
  const originalFetch = globalThis.fetch
  const originalEventSource = globalThis.EventSource
  Object.defineProperty(globalThis, 'EventSource', { configurable: true, value: QuietEventSource })
  globalThis.fetch = async input => {
    if (String(input).includes('/api/v1/tasks?')) {
      return jsonTasks([task({
        id: 'task-admitted',
        root_id: 'task-admitted',
        title: 'Queued image',
        status: 'queued',
        phase: 'queued',
        message: 'Waiting in queue',
        error: null,
        resumable: false,
        result_refs: [],
        backend_job_id: 'job-1',
        metadata: { intent_id: 'intent-admitted', receipt: { commandId: 'intent-admitted' } },
      })])
    }
    throw new Error(`Unexpected request: ${String(input)}`)
  }
  try {
    render(<ActivityFooter />)
    await waitFor(() => assert.ok(screen.getByText('Waiting in queue')))
    fireEvent.click(screen.getByRole('button', { name: /Activity/ }))
    const group = screen.getByText('Queued image').closest('[data-reading-state]')
    assert.equal(group?.getAttribute('data-reading-state'), 'admitted')
    assert.ok(screen.getByText('Admitted — waiting to run'))
    assert.equal(group?.textContent?.includes('Completed'), false)
  } finally {
    cleanup()
    globalThis.fetch = originalFetch
    Object.defineProperty(globalThis, 'EventSource', { configurable: true, value: originalEventSource })
  }
})

test('retry keeps the original receipt and Escape closes the panel with focus return', { concurrency: false }, async () => {
  const { render, screen, waitFor, fireEvent, cleanup } = await import('@testing-library/react')
  const { ActivityFooter } = await import('../src/components/ActivityFooter.tsx')
  const { openAgentActivityDetails } = await import('../src/lib/uiBus.ts')
  const originalFetch = globalThis.fetch
  const originalEventSource = globalThis.EventSource
  Object.defineProperty(globalThis, 'EventSource', { configurable: true, value: QuietEventSource })
  globalThis.fetch = async input => {
    const url = String(input)
    if (url.includes('/api/v1/tasks?')) return jsonTasks([task()])
    if (url.includes('/resume')) {
      return new Response(JSON.stringify({
        task: task({
          status: 'running',
          phase: 'running',
          message: 'Rendering again',
          error: null,
          attempt: 2,
          cancelable: true,
          resumable: false,
          completed_at: null,
          updated_at: 5,
        }),
      }), { headers: { 'content-type': 'application/json' } })
    }
    throw new Error(`Unexpected request: ${url}`)
  }
  try {
    render(<ActivityFooter />)
    await waitFor(() => assert.ok(screen.getByText('Provider stopped')))
    const toggle = screen.getByRole('button', { name: /Activity/ })
    toggle.focus()
    fireEvent.click(toggle)
    const group = await screen.findByText('Retryable render')
    assert.equal(group.closest('[data-receipt-id]')?.getAttribute('data-receipt-id'), 'intent-retry')
    fireEvent.click(screen.getByRole('button', { name: 'Resume' }))
    await waitFor(() => assert.ok(screen.getAllByText('Rendering again').length >= 1))
    assert.equal(screen.getByText('Retryable render').closest('[data-receipt-id]')?.getAttribute('data-receipt-id'), 'intent-retry')
    assert.equal(screen.getByText('Retryable render').closest('[data-intent-id]')?.getAttribute('data-intent-id'), 'intent-retry')
    openAgentActivityDetails({ taskId: 'task-generation-retry-1', intentId: 'intent-retry' })
    await waitFor(() => assert.equal(screen.getByText('Retryable render').closest('[data-group-id]')?.getAttribute('aria-current'), 'true'))
    assert.ok(screen.getByTestId('activity-details').className.includes('z-[110]'))
    fireEvent.keyDown(document, { key: 'Escape', bubbles: true })
    fireEvent.keyDown(window, { key: 'Escape', bubbles: true })
    await waitFor(() => assert.equal(screen.queryByTestId('activity-details'), null))
    assert.equal(screen.getByRole('button', { name: /Activity/ }).getAttribute('aria-expanded'), 'false')
  } finally {
    cleanup()
    globalThis.fetch = originalFetch
    Object.defineProperty(globalThis, 'EventSource', { configurable: true, value: originalEventSource })
  }
})
