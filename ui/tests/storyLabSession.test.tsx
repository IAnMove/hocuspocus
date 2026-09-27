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
    Event: dom.window.Event,
    MutationObserver: dom.window.MutationObserver,
    localStorage: dom.window.localStorage,
  })
  Object.defineProperty(globalThis, 'navigator', {
    configurable: true,
    value: dom.window.navigator,
  })
}

installDom()

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(next => { resolve = next })
  return { promise, resolve }
}

const json = (body: unknown) => new Response(JSON.stringify(body), {
  headers: { 'content-type': 'application/json' },
})
const project = (id: string, title: string, updatedAt: string) => ({ id, title, updatedAt })
const library = (
  projects: Record<string, ReturnType<typeof project>>,
  activeId = Object.keys(projects)[0],
  revision = 0,
) => ({ version: 2, revision, activeId, projects })

test('existing local draft is restored from localStorage without a status fetch', {
  concurrency: false,
}, async () => {
  const { render, screen, cleanup } = await import('@testing-library/react')
  const {
    persistStoryLabJob,
    persistStoryLabSessionRecord,
    storyJobKey,
    storyResultKey,
    useStoryLabSession,
  } = await import('../src/features/stories/storyLabSession.ts')
  const workspace = 'lab'
  const projectId = 'story-1'
  const record = {
    jobId: 'job-1',
    scope: 'world' as const,
    result: { world: { summary: 'A restored tower' } },
    generateImagesAfterApply: true,
  }
  persistStoryLabJob(workspace, projectId, record.jobId)
  persistStoryLabSessionRecord(workspace, projectId, record)
  assert.equal(window.localStorage.getItem(storyJobKey(workspace, projectId)), 'job-1')
  assert.equal(
    window.localStorage.getItem(storyResultKey(workspace, projectId)),
    JSON.stringify(record),
  )

  let statusCalls = 0
  function Probe() {
    const session = useStoryLabSession({
      workspace,
      projectId,
      loadWorkspace: async () => {},
      getStoryGenerationStatus: async () => {
        statusCalls += 1
        throw new Error('status should not run when a local draft exists')
      },
    })
    return (
      <div>
        <p>{`job:${session.recoveryJobId}`}</p>
        <p>{`scope:${session.pendingDraft?.scope || ''}`}</p>
        <p>{`selected:${session.pendingDraft?.selected.join(',') || ''}`}</p>
        <p>{`images:${session.pendingDraft?.generateImagesAfterApply ? 'yes' : 'no'}`}</p>
        <p>{`summary:${(session.pendingDraft?.result.world as { summary?: string } | undefined)?.summary || ''}`}</p>
      </div>
    )
  }

  try {
    render(<Probe />)
    assert.equal(screen.getByText('job:job-1').textContent, 'job:job-1')
    assert.equal(screen.getByText('scope:world').textContent, 'scope:world')
    assert.equal(screen.getByText('selected:world.summary').textContent, 'selected:world.summary')
    assert.equal(screen.getByText('images:yes').textContent, 'images:yes')
    assert.equal(screen.getByText('summary:A restored tower').textContent, 'summary:A restored tower')
    await new Promise(resolve => window.setTimeout(resolve, 0))
    assert.equal(statusCalls, 0)
  } finally {
    cleanup()
    window.localStorage.removeItem(storyJobKey(workspace, projectId))
    window.localStorage.removeItem(storyResultKey(workspace, projectId))
  }
})

test('recovered server result is ignored after workspace or project change', {
  concurrency: false,
}, async () => {
  const { render, screen, waitFor, cleanup } = await import('@testing-library/react')
  const {
    persistStoryLabJob,
    storyJobKey,
    storyResultKey,
    useStoryLabSession,
  } = await import('../src/features/stories/storyLabSession.ts')
  persistStoryLabJob('lab-a', 'story-a', 'job-a')
  const pending: Array<{ jobId: string; resolve: (value: { status: string; result: { result: Record<string, unknown> } }) => void }> = []
  let recovered = 0

  function Probe({ workspace, projectId }: { workspace: string; projectId: string }) {
    const session = useStoryLabSession({
      workspace,
      projectId,
      loadWorkspace: async () => {},
      getStoryGenerationStatus: jobId => new Promise(resolve => {
        pending.push({ jobId, resolve })
      }),
      onRecoveredServerResult: () => { recovered += 1 },
    })
    return (
      <div>
        <p>{`job:${session.recoveryJobId || 'none'}`}</p>
        <p>{session.pendingDraft ? 'has-draft' : 'no-draft'}</p>
      </div>
    )
  }

  try {
    const view = render(<Probe workspace="lab-a" projectId="story-a" />)
    await waitFor(() => assert.equal(pending.length, 1))
    assert.equal(pending[0].jobId, 'job-a')
    view.rerender(<Probe workspace="lab-b" projectId="story-b" />)
    await waitFor(() => assert.equal(screen.getByText('job:none').textContent, 'job:none'))
    pending[0].resolve({
      status: 'completed',
      result: { result: { world: { summary: 'Stale remote tower' } } },
    })
    await new Promise(resolve => window.setTimeout(resolve, 0))
    assert.equal(recovered, 0)
    assert.equal(screen.getByText('no-draft').textContent, 'no-draft')
    assert.equal(window.localStorage.getItem(storyResultKey('lab-a', 'story-a')), null)
    assert.equal(window.localStorage.getItem(storyJobKey('lab-a', 'story-a')), 'job-a')
  } finally {
    cleanup()
    window.localStorage.removeItem(storyJobKey('lab-a', 'story-a'))
    window.localStorage.removeItem(storyResultKey('lab-a', 'story-a'))
  }
})

test('loadWorkspace discards a stale remote library after the workspace changes', {
  concurrency: false,
}, async t => {
  const staleWs = 'g02-stale-remote'
  const currentWs = 'g02-current-remote'
  const idleWs = 'g02-idle-remote'
  const staleLibrary = library({
    'story-stale': project('story-stale', 'Stale remote Story', '2026-08-16T12:00:00Z'),
  }, 'story-stale', 4)
  const currentLibrary = library({
    'story-current': project('story-current', 'Current remote Story', '2026-08-16T13:00:00Z'),
  }, 'story-current', 7)
  const staleFetch = deferred<void>()
  const currentFetch = deferred<void>()
  let staleGets = 0
  let currentGets = 0
  const originalFetch = globalThis.fetch
  const { useStoryStore } = await import('../src/features/stories/store.ts')
  t.after(() => {
    globalThis.fetch = originalFetch
    window.localStorage.removeItem(`maestro-story-library-v2:${staleWs}`)
    window.localStorage.removeItem(`maestro-story-library-v2:${currentWs}`)
    window.localStorage.removeItem(`maestro-story-library-v2:${idleWs}`)
    useStoryStore.setState({
      workspace: 'default',
      hydrated: false,
      loading: false,
      libraryConflicts: [],
      saveError: null,
    })
  })
  globalThis.fetch = async (input, init = {}) => {
    const url = String(input)
    const method = init.method || 'GET'
    if (method === 'PUT' && String(url).endsWith('/api/v1/stories/library')) {
      const body = JSON.parse(String(init.body || '{}'))
      return json({ ...body.library, revision: (body.library?.revision || 0) + 1 })
    }
    if (url.includes(`workspace=${staleWs}`)) {
      staleGets += 1
      await staleFetch.promise
      return json(staleLibrary)
    }
    if (url.includes(`workspace=${currentWs}`)) {
      currentGets += 1
      await currentFetch.promise
      return json(currentLibrary)
    }
    throw new Error(`Unexpected request: ${method} ${url}`)
  }

  useStoryStore.setState({
    workspace: idleWs,
    hydrated: false,
    loading: false,
    libraryConflicts: [],
    saveError: null,
  })
  const first = useStoryStore.getState().loadWorkspace(staleWs)
  const started = Date.now()
  while (staleGets === 0 && Date.now() - started < 2000) {
    await new Promise(resolve => setTimeout(resolve, 5))
  }
  assert.equal(staleGets, 1)
  assert.equal(useStoryStore.getState().workspace, staleWs)

  const second = useStoryStore.getState().loadWorkspace(currentWs)
  while (currentGets === 0 && Date.now() - started < 2000) {
    await new Promise(resolve => setTimeout(resolve, 5))
  }
  assert.equal(currentGets, 1)
  assert.equal(useStoryStore.getState().workspace, currentWs)

  staleFetch.resolve()
  await first
  assert.equal(useStoryStore.getState().workspace, currentWs)
  assert.notEqual(useStoryStore.getState().project.id, 'story-stale')
  assert.equal(useStoryStore.getState().projects['story-stale'], undefined)

  currentFetch.resolve()
  await second
  assert.equal(useStoryStore.getState().workspace, currentWs)
  assert.equal(useStoryStore.getState().project.id, 'story-current')
  assert.equal(useStoryStore.getState().project.title, 'Current remote Story')
  assert.equal(useStoryStore.getState().hydrated, true)
})
