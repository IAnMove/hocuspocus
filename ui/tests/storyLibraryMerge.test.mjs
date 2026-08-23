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
    MutationObserver: dom.window.MutationObserver,
  })
  return dom
}

installDom()

const project = (id, title, updatedAt) => ({ id, title, updatedAt })
const library = (projects, activeId = Object.keys(projects)[0], revision = 0) => ({
  version: 2,
  revision,
  activeId,
  projects,
})

test('keeps the newer local Story and schedules remote sync', async () => {
  const { mergeStoryLibraries } = await import('../src/features/stories/library.ts')
  const result = mergeStoryLibraries(
    library({ story: project('story', 'Local newer', '2026-08-16T12:00:00Z') }),
    library({ story: project('story', 'Remote older', '2026-08-16T11:00:00Z') }),
  )
  assert.equal(result.library.projects.story.title, 'Local newer')
  assert.equal(result.conflicts.length, 0)
  assert.equal(result.needsRemoteSync, true)
})

test('keeps the newer remote Story without a conflict', async () => {
  const { mergeStoryLibraries } = await import('../src/features/stories/library.ts')
  const result = mergeStoryLibraries(
    library({ story: project('story', 'Local older', '2026-08-16T11:00:00Z') }),
    library({ story: project('story', 'Remote newer', '2026-08-16T12:00:00Z') }),
  )
  assert.equal(result.library.projects.story.title, 'Remote newer')
  assert.equal(result.conflicts.length, 0)
  assert.equal(result.needsRemoteSync, false)
})

test('preserves Stories exclusive to either local or remote library', async () => {
  const { mergeStoryLibraries } = await import('../src/features/stories/library.ts')
  const result = mergeStoryLibraries(
    library({ local: project('local', 'Only local', '2026-08-16T11:00:00Z') }, 'local'),
    library({ remote: project('remote', 'Only remote', '2026-08-16T12:00:00Z') }, 'remote'),
  )
  assert.deepEqual(Object.keys(result.library.projects).sort(), ['local', 'remote'])
  assert.equal(result.library.activeId, 'local')
  assert.equal(result.needsRemoteSync, true)
})

test('shows an equal-timestamp divergent Story as a conflict without remote sync', async () => {
  const { mergeStoryLibraries } = await import('../src/features/stories/library.ts')
  const result = mergeStoryLibraries(
    library({ story: project('story', 'Local copy', '2026-08-16T12:00:00Z') }),
    library({ story: project('story', 'Remote copy', '2026-08-16T12:00:00Z') }),
  )
  assert.equal(result.library.projects.story.title, 'Local copy')
  assert.deepEqual(result.conflicts.map(conflict => conflict.id), ['story'])
  assert.equal(result.needsRemoteSync, false)
})

test('renders conflict details as an accessible visible alert', async () => {
  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { StoryLibraryConflictNotice } = await import('../src/features/stories/StoryLibraryConflictNotice.tsx')
  const resolutions = []
  render(React.createElement(StoryLibraryConflictNotice, { conflicts: [{
    id: 'story', title: 'Conflict story',
    localUpdatedAt: '2026-08-16T12:00:00Z', remoteUpdatedAt: '2026-08-16T12:00:00Z',
    localProject: project('story', 'Local copy', '2026-08-16T12:00:00Z'),
    remoteProject: project('story', 'Remote copy', '2026-08-16T12:00:00Z'),
  }], onResolve: (id, resolution) => resolutions.push([id, resolution]) }))
  assert.ok(screen.getByRole('alert'))
  assert.match(screen.getByRole('alert').textContent, /Conflict story/)
  fireEvent.click(screen.getByRole('button', { name: 'Use remote' }))
  assert.deepEqual(resolutions, [['story', 'remote']])
  cleanup()
})

test('a first remote load does not promote the synthetic local fallback', { concurrency: false }, async t => {
  const workspace = 'remote-only-library-test'
  window.localStorage.removeItem(`maestro-story-library-v2:${workspace}`)
  const originalFetch = globalThis.fetch
  t.after(() => {
    globalThis.fetch = originalFetch
    window.localStorage.removeItem(`maestro-story-library-v2:${workspace}`)
  })
  globalThis.fetch = async input => {
    const url = String(input)
    assert.match(url, new RegExp(`stories/library\\?workspace=${workspace}$`))
    return new Response(JSON.stringify(library({
      remote: project('remote', 'Existing remote Story', '2026-08-16T12:00:00Z'),
    }, 'remote')), { headers: { 'content-type': 'application/json' } })
  }

  const { useStoryStore } = await import('../src/features/stories/store.ts')
  await useStoryStore.getState().loadWorkspace(workspace)

  assert.equal(useStoryStore.getState().project.id, 'remote')
  assert.deepEqual(Object.keys(useStoryStore.getState().projects), ['remote'])
})

test('a backend revision conflict refetches, merges, and retries at the new revision', { concurrency: false }, async t => {
  const workspace = 'story-revision-retry-test'
  const storageKey = `maestro-story-library-v2:${workspace}`
  const { useStoryStore, createStoryProject } = await import('../src/features/stories/store.ts')
  const localProject = {
    ...createStoryProject(),
    id: 'shared-story',
    title: 'Local unsaved edit',
    updatedAt: '2026-08-16T14:00:00Z',
  }
  const remoteProject = {
    ...localProject,
    title: 'Remote older edit',
    updatedAt: '2026-08-16T12:00:00Z',
  }
  window.localStorage.setItem(storageKey, JSON.stringify(
    library({ 'shared-story': localProject }, 'shared-story', 0),
  ))
  useStoryStore.setState({ hydrated: false, loading: false, libraryConflicts: [] })
  const originalFetch = globalThis.fetch
  const putBaseRevisions = []
  let getCount = 0
  t.after(() => {
    globalThis.fetch = originalFetch
    useStoryStore.setState({ hydrated: false, loading: false })
    window.localStorage.removeItem(storageKey)
  })
  globalThis.fetch = async (input, init) => {
    const url = String(input)
    if (url.includes('/api/v1/stories/library?')) {
      getCount += 1
      const revision = getCount === 1 ? 1 : 2
      return new Response(JSON.stringify(
        library({ 'shared-story': remoteProject }, 'shared-story', revision),
      ), { headers: { 'content-type': 'application/json' } })
    }
    if (url.endsWith('/api/v1/stories/library') && init?.method === 'PUT') {
      const body = JSON.parse(String(init.body))
      putBaseRevisions.push(body.baseRevision)
      if (putBaseRevisions.length === 1) {
        return new Response(JSON.stringify({ detail: {
          code: 'story_library_revision_conflict',
          message: 'expected 1, current 2',
          expectedRevision: 1,
          currentRevision: 2,
        } }), { status: 409, headers: { 'content-type': 'application/json' } })
      }
      return new Response(JSON.stringify({ ...body.library, revision: 3 }), {
        headers: { 'content-type': 'application/json' },
      })
    }
    throw new Error(`Unexpected request: ${url}`)
  }

  await useStoryStore.getState().loadWorkspace(workspace)
  const deadline = Date.now() + 4_000
  while (Date.now() < deadline && useStoryStore.getState().libraryRevision !== 3) {
    await new Promise(resolve => setTimeout(resolve, 25))
  }

  assert.deepEqual(putBaseRevisions, [1, 2])
  assert.equal(getCount, 2)
  assert.equal(useStoryStore.getState().libraryRevision, 3)
  assert.equal(useStoryStore.getState().project.title, 'Local unsaved edit')
  assert.equal(useStoryStore.getState().saveError, null)
  assert.deepEqual(useStoryStore.getState().libraryConflicts, [])
})
