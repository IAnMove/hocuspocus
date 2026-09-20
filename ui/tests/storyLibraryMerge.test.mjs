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
  })
  Object.defineProperty(globalThis, 'navigator', {
    configurable: true,
    value: dom.window.navigator,
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
const pendingSong = {
  id: 'song-1',
  name: '',
  source: '',
  prompt: 'cinematic dream pop',
  lyrics: '[Verse]\nLa noche canta',
  provider: 'minimax',
  model: 'music-3.0',
  durationSeconds: 30,
  createdAt: '2026-09-19T10:00:00Z',
  status: 'pending',
}
const readySong = {
  ...pendingSong,
  name: 'opening.wav',
  source: '/api/v1/file/opening.wav',
  status: 'ready',
}
const storyWithSong = (title, updatedAt, candidate, extra = {}) => ({
  id: 'story',
  title,
  updatedAt,
  music: {
    cues: [{ id: 'cue-1', title: 'Opening', candidates: [candidate] }],
    candidates: [],
    ...extra.music,
  },
  ...extra,
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

test('409 mutation rebase keeps local-only siblings and mutates the remote story', async () => {
  const { rebaseStoryMutationBaseline } = await import('../src/features/stories/library.ts')
  const result = rebaseStoryMutationBaseline(
    'shared',
    library({
      shared: project('shared', 'Local pending song', '2026-08-16T13:00:00Z'),
      draft: project('draft', 'Unsaved sibling', '2026-08-16T13:05:00Z'),
    }, 'shared', 1),
    library({
      shared: project('shared', 'Remote ready song', '2026-08-16T12:00:00Z'),
    }, 'shared', 2),
  )
  assert.equal(result.revision, 2)
  assert.equal(result.projects.shared.title, 'Remote ready song')
  assert.equal(result.projects.draft.title, 'Unsaved sibling')
})

test('409 mutation rebase keeps newer local sibling edits', async () => {
  const { rebaseStoryMutationBaseline } = await import('../src/features/stories/library.ts')
  const result = rebaseStoryMutationBaseline(
    'shared',
    library({
      shared: project('shared', 'Local shared', '2026-08-16T11:00:00Z'),
      sibling: project('sibling', 'Local sibling edit', '2026-08-16T13:00:00Z'),
    }, 'shared', 1),
    library({
      shared: project('shared', 'Remote shared', '2026-08-16T12:00:00Z'),
      sibling: project('sibling', 'Stale sibling', '2026-08-16T12:00:00Z'),
    }, 'shared', 2),
  )
  assert.equal(result.projects.shared.title, 'Remote shared')
  assert.equal(result.projects.sibling.title, 'Local sibling edit')
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

test('newer local title edit keeps a remotely published song instead of the pending reservation', async () => {
  const { mergeStoryLibraries } = await import('../src/features/stories/library.ts')
  const result = mergeStoryLibraries(
    library({
      story: storyWithSong('Edited while generating', '2026-09-19T11:05:00Z', pendingSong),
    }, 'story', 6),
    library({
      story: storyWithSong('Night Choir', '2026-09-19T10:00:00Z', readySong),
    }, 'story', 7),
  )
  const cue = result.library.projects.story.music.cues[0]
  assert.equal(result.library.projects.story.title, 'Edited while generating')
  assert.equal(cue.candidates[0].status, 'ready')
  assert.equal(cue.candidates[0].source, '/api/v1/file/opening.wav')
  assert.equal(cue.candidates[0].name, 'opening.wav')
  assert.equal(result.conflicts.length, 0)
  assert.equal(result.needsRemoteSync, true)
})

test('a published local song is not replaced by a newer remote pending reservation', async () => {
  const { mergeStoryLibraries } = await import('../src/features/stories/library.ts')
  const result = mergeStoryLibraries(
    library({
      story: storyWithSong('Night Choir', '2026-09-19T10:00:00Z', readySong),
    }, 'story', 6),
    library({
      story: storyWithSong('Retitled remotely', '2026-09-19T11:05:00Z', pendingSong),
    }, 'story', 7),
  )
  const cue = result.library.projects.story.music.cues[0]
  assert.equal(result.library.projects.story.title, 'Retitled remotely')
  assert.equal(cue.candidates[0].status, 'ready')
  assert.equal(cue.candidates[0].source, '/api/v1/file/opening.wav')
  assert.equal(result.conflicts.length, 0)
})

test('pending vs ready on an otherwise equal Story is not a conflict', async () => {
  const { mergeStoryLibraries } = await import('../src/features/stories/library.ts')
  const result = mergeStoryLibraries(
    library({
      story: storyWithSong('Night Choir', '2026-09-19T10:00:00Z', pendingSong),
    }, 'story', 6),
    library({
      story: storyWithSong('Night Choir', '2026-09-19T10:00:00Z', readySong),
    }, 'story', 7),
  )
  const cue = result.library.projects.story.music.cues[0]
  assert.equal(cue.candidates[0].status, 'ready')
  assert.equal(result.conflicts.length, 0)
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
