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
    MutationObserver: dom.window.MutationObserver,
    localStorage: dom.window.localStorage,
  })
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
}

installDom()

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), {
  status,
  headers: { 'content-type': 'application/json' },
})

const liveJob = {
  job_id: 'job-1', status: 'running', progress: 40, step: 2, total_steps: 5, phase: 'Sampling',
  message: 'Sampling', output_files: [], error: null, created_at: 1_700_000_000,
}

/** Capture the store's reconnect timers so the test drives each poll by hand. */
function captureTimers() {
  const scheduled: Array<{ run: () => void; delay: number }> = []
  const original = window.setTimeout
  window.setTimeout = ((handler: TimerHandler, delay?: number) => {
    scheduled.push({ run: () => { (handler as () => void)() }, delay: delay ?? 0 })
    return scheduled.length
  }) as typeof window.setTimeout
  return {
    scheduled,
    async tick() {
      const next = scheduled.shift()
      assert.ok(next, 'a poll was scheduled')
      next.run()
      // Let the fetch promise chain inside the poll settle.
      for (let i = 0; i < 6; i += 1) await Promise.resolve()
      await new Promise(resolve => original.call(window, resolve, 0))
      return next.delay
    },
    restore() { window.setTimeout = original },
  }
}

test('a leftover status ends polling and keeps the tile as interrupted', { concurrency: false }, async () => {
  const { useStore } = await import('../src/stores/useStore.ts')
  const previousFetch = globalThis.fetch
  const timers = captureTimers()
  globalThis.fetch = async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.endsWith('/api/v1/jobs')) return json({ jobs: [liveJob] })
    if (url.includes('/api/v1/status/job-1')) {
      // Recovery documents carry no step/total_steps/phase.
      return json({
        job_id: 'job-1', status: 'interrupted', progress: 0, output_files: [], error: null,
        message: 'Generation was interrupted and is waiting for resume or discard.', recoverable: true,
      })
    }
    throw new Error(`Unexpected request ${url}`)
  }
  useStore.setState({ jobs: [], isGenerating: false, maybeRefreshGallery: async () => {} } as never)
  try {
    await useStore.getState().reconnectJobs()
    assert.equal(useStore.getState().jobs.length, 1)
    assert.equal(useStore.getState().isGenerating, true)
    assert.equal(timers.scheduled.length, 1)

    await timers.tick()
    const [job] = useStore.getState().jobs
    assert.equal(job.status, 'interrupted')
    assert.equal(job.step, 0)
    assert.equal(job.totalSteps, 0)
    assert.equal(job.phase, '')
    assert.match(job.message, /waiting for resume or discard/)
    assert.equal(useStore.getState().isGenerating, false)
    assert.equal(timers.scheduled.length, 0, 'no further poll is scheduled')
  } finally {
    timers.restore()
    globalThis.fetch = previousFetch
    useStore.setState({ jobs: [], isGenerating: false } as never)
  }
})

test('reconnected jobs survive an outage with backoff and vanish only on 404', { concurrency: false }, async () => {
  const { useStore } = await import('../src/stores/useStore.ts')
  const previousFetch = globalThis.fetch
  const timers = captureTimers()
  let mode: 'offline' | 'gateway' | 'gone' = 'offline'
  globalThis.fetch = async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.endsWith('/api/v1/jobs')) return json({ jobs: [liveJob] })
    if (url.includes('/api/v1/status/job-1')) {
      if (mode === 'offline') throw new TypeError('Failed to fetch')
      if (mode === 'gateway') return new Response('Bad Gateway', { status: 502 })
      return json({ detail: 'Job not found' }, 404)
    }
    throw new Error(`Unexpected request ${url}`)
  }
  useStore.setState({ jobs: [], isGenerating: false, maybeRefreshGallery: async () => {} } as never)
  try {
    await useStore.getState().reconnectJobs()
    assert.equal(useStore.getState().jobs.length, 1)

    const first = await timers.tick()
    assert.equal(first, 2000)
    assert.equal(useStore.getState().jobs.length, 1, 'one failure keeps the tile')
    assert.equal(useStore.getState().jobs[0].phase, 'Sampling')

    mode = 'gateway'
    const second = await timers.tick()
    assert.equal(second, 4000, 'the retry delay doubles after a failure')
    assert.equal(useStore.getState().jobs.length, 1, 'a 502 keeps the tile')
    assert.equal(useStore.getState().jobs[0].phase, 'Sampling')

    const third = await timers.tick()
    assert.equal(third, 8000)
    assert.equal(useStore.getState().jobs.length, 1)
    assert.match(useStore.getState().jobs[0].phase, /Connection lost/)
    assert.equal(useStore.getState().jobs[0].status, 'running')

    mode = 'gone'
    const fourth = await timers.tick()
    assert.equal(fourth, 16000)
    assert.equal(useStore.getState().jobs.length, 0, 'a 404 removes the job')
    assert.equal(timers.scheduled.length, 0)
  } finally {
    timers.restore()
    globalThis.fetch = previousFetch
    useStore.setState({ jobs: [], isGenerating: false } as never)
  }
})

test('an interrupted tile offers resume and discard through the recovery queue', { concurrency: false }, async () => {
  const { render, screen, fireEvent, waitFor, cleanup } = await import('@testing-library/react')
  const { JobPlaceholder } = await import('../src/components/MainContent/MainContent.tsx')
  const { useStore } = await import('../src/stores/useStore.ts')
  const previousFetch = globalThis.fetch
  const posted: string[] = []
  let reconnects = 0
  let dismissed = 0
  globalThis.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (init?.method === 'POST' && url.includes('/api/v1/jobs/recovery/')) {
      posted.push(url.slice(url.indexOf('/api')))
      return json(url.endsWith('/resume') ? { resumed: [], count: 1 } : { discarded: 1 })
    }
    throw new Error(`Unexpected request ${url}`)
  }
  useStore.setState({ reconnectJobs: async () => { reconnects += 1 } } as never)
  const job = {
    id: 'job-1', status: 'interrupted' as const, progress: 0, step: 0, totalSteps: 0, phase: '',
    message: 'Generation was interrupted and is waiting for resume or discard.', outputFiles: [], error: null,
  }
  try {
    const view = render(<JobPlaceholder job={job} onStop={() => {}} onDismiss={() => { dismissed += 1 }} />)
    assert.ok(screen.getByText('Interrupted'))
    assert.equal(screen.queryByRole('button', { name: /Stop/ }), null)
    fireEvent.click(screen.getByRole('button', { name: 'Resume' }))
    await waitFor(() => assert.equal(reconnects, 1))
    assert.deepEqual(posted, ['/api/v1/jobs/recovery/resume'])
    assert.equal(dismissed, 1)

    view.rerender(<JobPlaceholder job={job} onStop={() => {}} onDismiss={() => { dismissed += 1 }} />)
    fireEvent.click(screen.getByRole('button', { name: 'Discard' }))
    await waitFor(() => assert.equal(dismissed, 2))
    assert.deepEqual(posted, ['/api/v1/jobs/recovery/resume', '/api/v1/jobs/recovery/discard'])
    assert.equal(reconnects, 1)
  } finally {
    cleanup()
    globalThis.fetch = previousFetch
  }
})
