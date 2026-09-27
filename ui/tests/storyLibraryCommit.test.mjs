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
window.matchMedia = () => ({ matches: false })

function mockLibraryFetch(t, workspace, savedLibrary, options = {}) {
  const putBodies = []
  const originalFetch = globalThis.fetch
  t.after(() => {
    globalThis.fetch = originalFetch
    window.localStorage.removeItem(`maestro-story-library-v2:${workspace}`)
  })
  globalThis.fetch = async (input, init = {}) => {
    const url = String(input)
    if (url.includes('/api/v1/stories/library?')) {
      return new Response(JSON.stringify(savedLibrary.value), {
        headers: { 'content-type': 'application/json' },
      })
    }
    if (url.endsWith('/api/v1/stories/library') && init.method === 'PUT') {
      const body = JSON.parse(String(init.body || '{}'))
      putBodies.push(body.library)
      if (options.conflictFirst && putBodies.length === 1) {
        return new Response(JSON.stringify({
          detail: {
            code: 'story_library_revision_conflict',
            message: 'expected 1, current 2',
            expectedRevision: 1,
            currentRevision: savedLibrary.value.revision,
          },
        }), { status: 409, headers: { 'content-type': 'application/json' } })
      }
      savedLibrary.value = { ...body.library, revision: body.baseRevision + 1 }
      return new Response(JSON.stringify(savedLibrary.value), {
        headers: { 'content-type': 'application/json' },
      })
    }
    throw new Error(`Unexpected request: ${url}`)
  }
  return { putBodies }
}

test('409 song persist retries without dropping a local-only sibling story', { concurrency: false }, async t => {
  const workspace = 'story-commit-keep-sibling'
  const { createStoryProject, normalizeStoryProject, useStoryStore, commitStoryProjectMutation } = await import('../src/features/stories/store.ts')
  const active = normalizeStoryProject({
    ...createStoryProject('music_video'),
    title: 'Canción activa',
  })
  const sibling = normalizeStoryProject({
    ...createStoryProject(),
    title: 'Borrador local',
  })
  const savedLibrary = {
    value: {
      version: 2,
      revision: 2,
      activeId: active.id,
      projects: { [active.id]: active },
    },
  }
  const mock = mockLibraryFetch(t, workspace, savedLibrary, { conflictFirst: true })
  useStoryStore.setState({
    workspace,
    project: active,
    projects: { [active.id]: active, [sibling.id]: sibling },
    libraryRevision: 1,
    dirty: true,
    hydrated: true,
    loading: false,
    saveError: null,
    libraryConflicts: [],
    activeProjectOperations: {},
  })

  const library = await commitStoryProjectMutation(
    workspace,
    useStoryStore.getState(),
    active.id,
    source => normalizeStoryProject({ ...source, title: 'Canción guardada' }),
  )

  assert.equal(mock.putBodies.length, 2)
  assert.ok(mock.putBodies[1].projects[sibling.id], 'retry PUT must keep the unsaved sibling')
  assert.equal(mock.putBodies[1].projects[sibling.id].title, 'Borrador local')
  assert.equal(library.projects[sibling.id].title, 'Borrador local')
  assert.equal(library.projects[active.id].title, 'Canción guardada')
})

test('saveStoryProjectMutation keeps a local-only sibling after a 409 reload', { concurrency: false }, async t => {
  const workspace = 'story-save-keep-sibling'
  const { createStoryProject, normalizeStoryProject, useStoryStore, saveStoryProjectMutation } = await import('../src/features/stories/store.ts')
  const active = normalizeStoryProject({
    ...createStoryProject('music_video'),
    title: 'Historia A',
  })
  const sibling = normalizeStoryProject({
    ...createStoryProject(),
    title: 'Historia nueva',
  })
  const savedLibrary = {
    value: {
      version: 2,
      revision: 2,
      activeId: active.id,
      projects: { [active.id]: active },
    },
  }
  mockLibraryFetch(t, workspace, savedLibrary, { conflictFirst: true })
  useStoryStore.setState({
    workspace,
    project: active,
    projects: { [active.id]: active, [sibling.id]: sibling },
    libraryRevision: 1,
    dirty: true,
    hydrated: true,
    loading: false,
    saveError: null,
    libraryConflicts: [],
    activeProjectOperations: {},
  })

  await saveStoryProjectMutation(
    workspace,
    useStoryStore.getState(),
    active.id,
    source => normalizeStoryProject({ ...source, title: 'Historia A guardada' }),
  )

  const state = useStoryStore.getState()
  assert.ok(state.projects[sibling.id], 'sibling must survive save + loadWorkspace')
  assert.equal(state.projects[sibling.id].title, 'Historia nueva')
  assert.equal(state.projects[active.id].title, 'Historia A guardada')
})
