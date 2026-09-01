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

test('stageStoryComic keeps Comics navigation instead of Story Lab', { concurrency: false }, async t => {
  const workspace = 'wizard-comic-staging'
  const [{ useStore }, { useStoryStore, createStoryProject, normalizeStoryProject }, { defaultApplicationAdapters }] = await Promise.all([
    import('../src/stores/useStore.ts'),
    import('../src/features/stories/store.ts'),
    import('../src/features/agent/applicationAdapters.ts'),
  ])
  const project = normalizeStoryProject({
    ...createStoryProject(),
    title: 'La torre de sal',
    premise: 'Un mapa secreto abre un capítulo autoconclusivo.',
    logline: 'Una cartógrafa descubre que el mapa miente.',
  })
  let savedLibrary = {
    version: 2,
    revision: 1,
    activeId: project.id,
    projects: { [project.id]: project },
  }
  const originalFetch = globalThis.fetch
  const before = {
    mediaFilter: useStore.getState().mediaFilter,
    sidebarMode: useStore.getState().sidebarMode,
    sidebarOpen: useStore.getState().sidebarOpen,
    settingsOpen: useStore.getState().settingsOpen,
    dashboardOpen: useStore.getState().dashboardOpen,
    activeWorkspace: useStore.getState().activeWorkspace,
  }
  t.after(() => {
    globalThis.fetch = originalFetch
    useStore.setState(before)
    window.localStorage.removeItem(`maestro-story-library-v2:${workspace}`)
    window.localStorage.removeItem('maestro-story-comic-draft')
  })
  globalThis.fetch = async (input, init = {}) => {
    const url = String(input)
    const method = init.method || 'GET'
    const json = body => new Response(JSON.stringify(body), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    })
    if (url.includes('/api/v1/stories/library') && method === 'PUT') {
      const body = JSON.parse(String(init.body || '{}'))
      savedLibrary = { ...body.library, revision: (savedLibrary.revision || 1) + 1 }
      return json(savedLibrary)
    }
    if (url.includes('/api/v1/stories/library')) return json(savedLibrary)
    if (url.includes('/api/v1/outputs')) return json({ outputs: [], total: 0 })
    return json({})
  }

  useStore.setState({
    activeWorkspace: workspace,
    mediaFilter: 'stories',
    sidebarMode: 'studio',
    sidebarOpen: false,
    settingsOpen: false,
    dashboardOpen: false,
  })
  useStoryStore.setState({
    workspace,
    project,
    projects: { [project.id]: project },
    libraryRevision: 1,
    dirty: false,
    hydrated: true,
    loading: false,
    saveError: null,
    libraryConflicts: [],
    activeProjectOperations: {},
  })

  const outcome = await defaultApplicationAdapters.storyLab.stageComic({
    type: 'stage_story_comic',
    targetStoryTitle: project.title,
    direction: 'Un capítulo autoconclusivo sobre el mapa.',
    pageCount: 4,
    panelsPerPage: 5,
    confirm: true,
  })

  assert.equal(useStore.getState().mediaFilter, 'comics')
  assert.notEqual(useStore.getState().mediaFilter, 'stories')
  assert.equal(useStore.getState().sidebarMode, 'director')
  assert.equal(useStore.getState().sidebarOpen, true)
  assert.match(outcome.message, /capítulo editable/)
  assert.match(outcome.message, /Comic Director/)
})

test('startDirectorProduction hydrates a persisted production that is not loaded yet', { concurrency: false }, async t => {
  const workspace = 'wizard-director-hydrate'
  const [{ useStore }, { useStoryStore, createStoryProject, normalizeStoryProject }, { defaultApplicationAdapters }] = await Promise.all([
    import('../src/stores/useStore.ts'),
    import('../src/features/stories/store.ts'),
    import('../src/features/agent/applicationAdapters.ts'),
  ])
  const production = {
    id: 'prod-persisted-1',
    kind: 'film',
    title: 'La torre · short film',
    createdAt: new Date().toISOString(),
    sourceVersion: 1,
    status: 'staged',
    targetSnapshot: { pipelineId: 'pipe-already-running' },
  }
  const project = normalizeStoryProject({
    ...createStoryProject(),
    title: 'La torre de sal',
    premise: 'Un mapa secreto abre un capítulo autoconclusivo.',
    productions: [production],
  })
  const savedLibrary = {
    version: 2,
    revision: 4,
    activeId: project.id,
    projects: { [project.id]: project },
  }
  const originalFetch = globalThis.fetch
  const before = {
    mediaFilter: useStore.getState().mediaFilter,
    sidebarMode: useStore.getState().sidebarMode,
    sidebarOpen: useStore.getState().sidebarOpen,
    settingsOpen: useStore.getState().settingsOpen,
    dashboardOpen: useStore.getState().dashboardOpen,
    activeWorkspace: useStore.getState().activeWorkspace,
    directorStoryProductionHandoff: useStore.getState().directorStoryProductionHandoff,
  }
  const placeholder = createStoryProject()
  t.after(() => {
    globalThis.fetch = originalFetch
    useStore.setState(before)
    window.localStorage.removeItem(`maestro-story-library-v2:${workspace}`)
  })
  globalThis.fetch = async (input, init = {}) => {
    const url = String(input)
    const json = body => new Response(JSON.stringify(body), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    })
    if (url.includes('/api/v1/stories/library')) return json(savedLibrary)
    if (url.includes('/api/v1/outputs')) return json({ outputs: [], total: 0 })
    return json({})
  }

  useStore.setState({
    activeWorkspace: workspace,
    directorStoryProductionHandoff: {
      workspace,
      projectId: project.id,
      productionId: production.id,
    },
    settingsOpen: false,
    dashboardOpen: false,
  })
  useStoryStore.setState({
    workspace: 'unloaded',
    project: placeholder,
    projects: { [placeholder.id]: placeholder },
    libraryRevision: 0,
    dirty: false,
    hydrated: false,
    loading: false,
    saveError: null,
    libraryConflicts: [],
    activeProjectOperations: {},
  })

  const outcome = await defaultApplicationAdapters.storyLab.startDirectorProduction({
    type: 'start_director_production',
    targetStoryTitle: project.title,
    kind: 'film',
    confirm: true,
  })

  assert.match(outcome.message, /ya estaba iniciada/)
  assert.equal(outcome.target.id, production.id)
  assert.equal(useStoryStore.getState().projects[project.id]?.productions[0]?.id, production.id)
})

test('generate_story_section, generate_comic and generate_comic_panel publish onStep progress', { concurrency: false }, async t => {
  const { executeAgentActions } = await import('../src/features/agent/agentActions.ts')
  const { defaultApplicationAdapters } = await import('../src/features/agent/applicationAdapters.ts')
  const { clearExecutionMemory } = await import('../src/features/agent/agentContract.ts')
  clearExecutionMemory()

  const steps = []
  const originalProposal = defaultApplicationAdapters.storyLab.generateProposal
  const originalGenerate = defaultApplicationAdapters.comic.generate
  const originalPanel = defaultApplicationAdapters.comic.generatePanel
  t.after(() => {
    defaultApplicationAdapters.storyLab.generateProposal = originalProposal
    defaultApplicationAdapters.comic.generate = originalGenerate
    defaultApplicationAdapters.comic.generatePanel = originalPanel
    clearExecutionMemory()
  })

  defaultApplicationAdapters.storyLab.generateProposal = async (_action, onStep) => {
    onStep?.('story-section-progress')
    return { message: 'Propuesta lista', target: { kind: 'story', id: 'story-1', title: 'La torre' } }
  }
  defaultApplicationAdapters.comic.generate = async (_action, _expected, onStep) => {
    onStep?.('comic-progress')
    return {
      message: 'Viñetas dibujadas',
      state: 'completed',
      target: { kind: 'comic', id: 'comic-1', title: 'Capítulo' },
    }
  }
  defaultApplicationAdapters.comic.generatePanel = async (_page, _panel, onStep) => {
    onStep?.('panel-progress')
    return { message: 'Viñeta regenerada', target: { kind: 'comic', id: 'comic-1', title: 'Capítulo' } }
  }

  await executeAgentActions([{
    type: 'generate_story_section',
    targetStoryTitle: 'La torre de sal',
    scope: 'world',
    instruction: 'Haz más concretas sus reglas.',
    confirm: true,
  }], message => steps.push(message))
  await executeAgentActions([{
    type: 'generate_comic',
    imageProvider: 'keep',
    imageModel: '',
    scope: 'missing',
    pages: [],
    pilot: false,
    biographyReview: false,
    confirm: true,
  }], message => steps.push(message))
  await executeAgentActions([{
    type: 'generate_comic_panel',
    pageNumber: 1,
    panelNumber: 2,
    confirm: true,
  }], message => steps.push(message))

  assert.ok(steps.includes('story-section-progress'), `missing story progress in ${JSON.stringify(steps)}`)
  assert.ok(steps.includes('comic-progress'), `missing comic progress in ${JSON.stringify(steps)}`)
  assert.ok(steps.includes('panel-progress'), `missing panel progress in ${JSON.stringify(steps)}`)
})
