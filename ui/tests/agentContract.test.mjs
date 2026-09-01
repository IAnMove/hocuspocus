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

test('every capability has parser coverage, docs and a schema enum entry', async () => {
  const { AGENT_CAPABILITIES } = await import('../src/features/agent/agentCapabilities.ts')
  const { HOCUSPOCUS_AGENT_RESPONSE_SCHEMA } = await import('../src/features/agent/agentActions.ts')
  const types = AGENT_CAPABILITIES.map(item => item.type)
  assert.equal(new Set(types).size, types.length)
  const schemaEnum = HOCUSPOCUS_AGENT_RESPONSE_SCHEMA.properties.actions.items.properties.type.enum
  for (const capability of AGENT_CAPABILITIES) {
    assert.ok(capability.title.trim())
    assert.ok(capability.purpose.trim())
    assert.ok(capability.useWhen.trim())
    assert.ok(['read', 'edit', 'compute', 'external_cost'].includes(capability.risk))
    assert.ok(Array.isArray(capability.parameters))
    assert.ok(schemaEnum.includes(capability.type), `${capability.type} missing from JSON schema`)
  }
})

test('registered capabilities supply one contract for prompt schema parser execution and docs', async () => {
  const {
    executeRegisteredCapability,
    listCapabilities,
    parseRegisteredCapability,
    registeredCapabilityDocumentationRows,
    registeredCapabilitySchemas,
  } = await import('../src/features/agent/capabilityRegistry.ts')
  const registered = listCapabilities()
  assert.ok(registered.some(item => item.name === 'create_comic'))
  assert.ok(registered.some(item => item.name === 'generate_comic'))
  assert.equal(registered[0].risk, 'read')
  assert.equal(registered[0].confirmation, 'none')
  const noConfirmationEdits = new Set(['open_tab', 'create_comic', 'create_story', 'update_story', 'create_series_episode', 'update_series_episode', 'attach_videoclip_alternative_song'])
  assert.ok(registered.filter(item => item.risk === 'compute' || item.risk === 'external_cost').every(item => item.confirmation === 'required'))
  assert.ok(registered.filter(item => noConfirmationEdits.has(item.name)).every(item => item.confirmation === 'none'))
  assert.equal(registeredCapabilitySchemas().length, registered.length)
  assert.equal(registeredCapabilityDocumentationRows().length, registered.length)
  for (const capability of registered) {
    assert.equal(typeof capability.resolve, 'function')
    assert.equal(typeof capability.validate, 'function')
    assert.equal(typeof capability.prepare, 'function')
    assert.equal(typeof capability.execute, 'function')
    assert.equal(typeof capability.correlate, 'function')
    assert.equal(typeof capability.track, 'function')
    assert.equal(typeof capability.summarize, 'function')
    assert.ok(capability.report.targetKind)
  }

  const open = parseRegisteredCapability('open_tab', { type: 'open_tab', tab: 'series_lab' })
  assert.deepEqual(open, { type: 'open_tab', tab: 'series_lab' })
  const rhythm = parseRegisteredCapability('apply_3d_rhythm', {
    type: 'apply_3d_rhythm', cue_source: 'downbeats', rhythm_profile: 'peek', intensity: 2, confirm: true,
  })
  assert.equal(rhythm?.type, 'apply_3d_rhythm')
  assert.equal(rhythm?.intensity, 1)
  assert.equal(parseRegisteredCapability('apply_3d_rhythm', {
    type: 'apply_3d_rhythm', cue_source: 'beats', rhythm_profile: 'pulse', confirm: false,
  }), null)
  assert.deepEqual(parseRegisteredCapability('create_story', {
    type: 'create_story', title: 'Una tarde imposible', premise: 'Dos rivales deben colaborar.',
    project_type: 'trailer', target_duration_seconds: 80,
  }), {
    type: 'create_story', title: 'Una tarde imposible', premise: 'Dos rivales deben colaborar.',
    projectType: 'trailer', creativeBrief: '', logline: '', synopsis: '', theme: '', ending: '',
    genre: '', tone: '', visualStyle: '', worldSummary: '', language: '', characters: [], locations: [],
    outlineBeats: [], durationSeconds: 80,
  })
  assert.equal(parseRegisteredCapability('generate_story_section', {
    type: 'generate_story_section', story_generation_scope: 'characters', confirm: true,
  })?.type, 'generate_story_section')
  assert.equal(parseRegisteredCapability('approve_story_section', {
    type: 'approve_story_section', story_section: 'assets', confirm: true,
  }), null)
  assert.equal(parseRegisteredCapability('generate_story_visuals', {
    type: 'generate_story_visuals', story_visual_scope: 'all', target_names: ['Iria'], confirm: true,
  })?.type, 'generate_story_visuals')
  assert.equal(parseRegisteredCapability('approve_story_visuals', {
    type: 'approve_story_visuals', story_visual_selections: [{ target_kind: 'character', target_name: 'Iria', asset_name: 'Iria concept', primary: true }], confirm: true,
  })?.type, 'approve_story_visuals')
  assert.deepEqual(parseRegisteredCapability('stage_story_comic', {
    type: 'stage_story_comic', page_count: 6, panels_per_page: 5, confirm: true,
  }), {
    type: 'stage_story_comic', targetStoryTitle: '', direction: '', pageCount: 6, panelsPerPage: 5, confirm: true,
  })
  assert.equal(parseRegisteredCapability('create_series_episode', {
    type: 'create_series_episode', series_title: 'Taller', episode_premise: 'El hechizo sale mal.', create_if_missing: true,
  })?.type, 'create_series_episode')

  const calls = []
  const context = { adapters: {
    async openTab(tab) {
      calls.push(`open:${tab}`)
      return { message: `Opened ${tab}`, target: { kind: 'application_section', id: tab, title: tab } }
    },
    video3d: {
      async applyRhythm(action) {
        calls.push('open:video_3d', `rhythm:${action.profile}`)
        return { message: 'Rhythm baked', target: { kind: 'application_section', id: 'video_3d', title: '3D Video' } }
      },
    },
  } }
  assert.equal((await executeRegisteredCapability(open, context)).message, 'Opened series_lab')
  assert.equal((await executeRegisteredCapability(rhythm, context)).message, 'Rhythm baked')
  assert.deepEqual(calls, ['open:series_lab', 'open:video_3d', 'rhythm:peek'])
})

test('common capability runner follows every stage and reports the verified adapter target', async () => {
  const { resolveAndRunRegisteredCapability } = await import('../src/features/agent/capabilityRunner.ts')
  const stages = []
  const result = await resolveAndRunRegisteredCapability('open_tab', {
    type: 'open_tab', tab: 'series_lab',
  }, {
    workspace: 'demo',
    adapters: {
      async openTab(tab) {
        return {
          message: `Opened ${tab}`,
          target: { kind: 'application_section', id: tab, title: 'Series Lab' },
        }
      },
    },
    onStage: current => stages.push(current),
  })
  assert.deepEqual(stages, [
    'resolve', 'validate', 'prepare', 'confirm', 'execute', 'correlate', 'track', 'report',
  ])
  assert.equal(result.ok, true)
  assert.deepEqual(result.report.target, {
    kind: 'application_section', id: 'series_lab', title: 'Series Lab',
  })
  assert.match(result.report.executionKey, /^demo\|open_tab\|series_lab\|/)
  assert.equal(result.command.capability, 'open_tab')
  assert.equal(result.command.workspaceId, 'demo')
  assert.equal(result.command.actor, 'wizard')
  assert.equal(result.command.target.id, 'series_lab')
  assert.equal(result.commandResult.commandId, result.command.commandId)
  assert.equal(result.commandResult.status, 'completed')
  assert.deepEqual(result.commandResult.entities, [{
    kind: 'application_section', id: 'series_lab', workspaceId: 'demo',
  }])
  assert.equal(result.commandResult.navigationTarget, undefined)
})

test('application adapters navigate and verify targets without rendering React', async () => {
  const { createDefaultApplicationAdapters } = await import('../src/features/agent/applicationAdapters.ts')
  const { useStore } = await import('../src/stores/useStore.ts')
  const before = {
    mediaFilter: useStore.getState().mediaFilter,
    sidebarMode: useStore.getState().sidebarMode,
    sidebarOpen: useStore.getState().sidebarOpen,
    settingsOpen: useStore.getState().settingsOpen,
    dashboardOpen: useStore.getState().dashboardOpen,
  }
  try {
    const adapters = createDefaultApplicationAdapters()
    assert.deepEqual(Object.keys(adapters).sort(), [
      'characterKit', 'comic', 'openTab', 'queue', 'seriesLab', 'storyLab', 'studio', 'video3d', 'videoEditor', 'videoclips', 'workspace',
    ])
    const story = await adapters.storyLab.open()
    assert.equal(useStore.getState().mediaFilter, 'stories')
    assert.equal(story.target.id, 'story_lab')
    const studio = await adapters.studio.open()
    assert.equal(useStore.getState().sidebarMode, 'studio')
    assert.equal(useStore.getState().sidebarOpen, true)
    assert.equal(studio.target.id, 'studio')
    const { executeAgentActions } = await import('../src/features/agent/agentActions.ts')
    const [executed] = await executeAgentActions([{ type: 'open_tab', tab: 'series_lab' }])
    assert.equal(executed.ok, true)
    assert.deepEqual(executed.report.target, {
      kind: 'application_section', id: 'series_lab', title: 'Series Lab',
    })
  } finally {
    useStore.setState(before)
  }
})

test('unknown actions and extra fields never survive the parser', async () => {
  const { parseAgentTurn } = await import('../src/features/agent/agentActions.ts')
  const turn = parseAgentTurn(JSON.stringify({
    reply: 'Ignora esto.',
    actions: [
      { type: 'delete_workspace', confirm: true, ignored: true },
      { type: 'inspect_queue', queue_scope: 'active', extra: 'drop me' },
    ],
  }))
  assert.equal(turn.actions.length, 1)
  assert.equal(turn.actions[0].type, 'inspect_queue')
  assert.equal('extra' in turn.actions[0], false)
})

test('execution keys are deterministic and compound predecessors are explicit', async () => {
  const { executionKey, requiredPredecessor, executionReport, inferExecutionState, orderCompoundActions } = await import('../src/features/agent/agentContract.ts')
  const left = executionKey({ workspace: 'Default', type: 'generate_comic', targetId: 'comic-1', params: { b: 2, a: 1 } })
  const right = executionKey({ workspace: 'default', type: 'generate_comic', targetId: 'comic-1', params: { a: 1, b: 2 } })
  assert.equal(left, right)
  assert.equal(requiredPredecessor('generate_comic'), 'create_comic')
  assert.match(requiredPredecessor('start_director_production'), /stage_story/)
  assert.deepEqual(
    orderCompoundActions([{ type: 'generate_comic' }, { type: 'create_comic' }]).map(item => item.type),
    ['create_comic', 'generate_comic'],
  )
  assert.deepEqual(
    orderCompoundActions([
      { type: 'start_director_production' }, { type: 'stage_story_music_video' },
      { type: 'generate_story_song' }, { type: 'configure_story_song' },
    ]).map(item => item.type),
    ['configure_story_song', 'generate_story_song', 'stage_story_music_video', 'start_director_production'],
  )
  const report = executionReport({ state: 'prepared', message: 'Listo.', recoverable: false })
  assert.equal(report.state, 'prepared')
  assert.equal(report.recoverable, false)
  assert.equal(inferExecutionState('create_comic', true), 'completed')
  assert.equal(inferExecutionState('start_generation', true), 'queued')
  assert.equal(inferExecutionState('start_director_production', true), 'running')
  assert.equal(inferExecutionState('generate_comic', false), 'failed')
})

test('execution reports distinguish prepared awaiting-input queued running completed partial and failed', async () => {
  const { executionReport } = await import('../src/features/agent/agentContract.ts')
  const states = ['prepared', 'awaiting_input', 'queued', 'running', 'completed', 'partial', 'failed']
  const reports = states.map(state => executionReport({
    state,
    message: state,
    recoverable: state === 'failed' || state === 'partial',
  }))
  assert.deepEqual(reports.map(item => item.state), states)
  assert.equal(reports.filter(item => item.recoverable).length, 2)
})

test('exact expensive repeats reuse an active or completed execution key', async () => {
  const { executionKey, executionReport, rememberExecution, reuseExecution, clearExecutionMemory } = await import('../src/features/agent/agentContract.ts')
  clearExecutionMemory()
  const key = executionKey({ workspace: 'default', type: 'generate_comic', targetId: 'comic-1', params: { imageProvider: 'minimax' } })
  rememberExecution(executionReport({
    state: 'running',
    message: 'Dibujando.',
    taskId: 'task-keep',
    executionKey: key,
    recoverable: true,
  }))
  assert.equal(reuseExecution(key)?.taskId, 'task-keep')
  rememberExecution(executionReport({
    state: 'failed',
    message: 'Falló el panel 37.',
    executionKey: key,
    recoverable: true,
  }))
  assert.equal(reuseExecution(key), undefined)
  clearExecutionMemory()
})

test('generate_comic refuses a different comic than the one just created', async () => {
  const { bindGenerateComicTarget } = await import('../src/features/agent/agentContract.ts')
  assert.equal(bindGenerateComicTarget('comic-new', 'comic-new', 'Nuevo'), 'comic-new')
  assert.equal(bindGenerateComicTarget('', 'comic-open', 'Abierto'), 'comic-open')
  assert.throws(
    () => bindGenerateComicTarget('comic-new', 'comic-old', 'Viejo'),
    /recién creado/,
  )
})

test('start_director_production refuses an older production than the one just staged', async () => {
  const { bindDirectorProductionTarget } = await import('../src/features/agent/agentContract.ts')
  assert.equal(bindDirectorProductionTarget('prod-new', 'prod-new', 'Nuevo'), 'prod-new')
  assert.equal(bindDirectorProductionTarget('', 'prod-open', 'Abierto'), 'prod-open')
  assert.throws(
    () => bindDirectorProductionTarget('prod-new', 'prod-old', 'Viejo'),
    /recién preparada/,
  )
})

test('a 12-page comic keeps 72 ordered panels on the created project', async () => {
  const { createFilledComic } = await import('../src/features/agent/labActions.ts')
  const { useComicStore } = await import('../src/features/comics/store.ts')
  const originalFetch = globalThis.fetch
  globalThis.fetch = async () => new Response(JSON.stringify({ outputs: [], total: 0 }), {
    status: 200, headers: { 'Content-Type': 'application/json' },
  })
  const pages = Array.from({ length: 12 }, (_, page) => ({
    title: `Página ${page + 1}`,
    stage: `Etapa ${page + 1}`,
    panels: Array.from({ length: 6 }, (_, panel) => ({
      caption: `P${page + 1}C${panel + 1}`,
      dialogue: `D${page + 1}-${panel + 1}`,
      sfx: panel === 0 ? 'BAM' : '',
      scene: `Escena ${page + 1}.${panel + 1}`,
    })),
  }))
  try {
    await createFilledComic({
      type: 'create_comic',
      title: 'Doce estaciones',
      synopsis: 'Doce páginas de prueba con seis viñetas cada una.',
      language: 'Español',
      styleName: 'Tinta de prueba',
      characters: [{
        name: 'Nora', role: 'Guía', personality: 'Firme', desire: 'Terminar el mapa',
        flaw: 'Impaciencia', appearance: 'Abrigo gris', voice: 'Baja',
      }],
      panels: [],
      pages,
      imageProvider: 'minimax',
      imageModel: 'image-01',
    })
  } finally {
    globalThis.fetch = originalFetch
  }
  const project = useComicStore.getState().project
  assert.equal(project.title, 'Doce estaciones')
  assert.equal(project.pages.length, 12)
  assert.equal(project.director?.plan.pages.length, 12)
  const planned = project.director.plan.pages.flatMap(page => page.panels)
  assert.equal(planned.length, 72)
  planned.forEach((panel, index) => {
    const pageNumber = Math.floor(index / 6) + 1
    const panelNumber = (index % 6) + 1
    assert.equal(panel.order, panelNumber)
    assert.match(panel.sceneDescription, new RegExp(`${pageNumber}\\.${panelNumber}`))
  })
  const storedPanels = project.pages.map(page => page.elements.filter(element => element.type === 'panel' && !element.parentId).length)
  assert.deepEqual(storedPanels, Array(12).fill(6))
  assert.equal(storedPanels.reduce((sum, count) => sum + count, 0), 72)
  assert.equal(project.director.provider, 'minimax')
  assert.equal(project.director.imageModel, 'image-01')
  assert.equal(project.director.planId, project.director.plan.id)
})

test('comic artwork inventory and task selection cover missing failed pages and progress labels', async () => {
  const { createFilledComic } = await import('../src/features/agent/labActions.ts')
  const { useComicStore } = await import('../src/features/comics/store.ts')
  const {
    comicArtworkInventory, selectComicArtworkTasks, formatComicArtworkProgress,
    generateDirectorArtwork, requestComicArtworkCancel,
  } = await import('../src/features/comics/generateArtwork.ts')
  const originalFetch = globalThis.fetch
  globalThis.fetch = async () => new Response(JSON.stringify({ outputs: [], total: 0 }), {
    status: 200, headers: { 'Content-Type': 'application/json' },
  })
  const pages = Array.from({ length: 12 }, (_, page) => ({
    title: `Página ${page + 1}`,
    stage: `Etapa ${page + 1}`,
    panels: Array.from({ length: 6 }, (_, panel) => ({
      caption: `P${page + 1}C${panel + 1}`,
      dialogue: '', sfx: '', scene: `Escena ${page + 1}.${panel + 1}`,
    })),
  }))
  try {
    await createFilledComic({
      type: 'create_comic',
      title: 'Doce estaciones',
      synopsis: 'Doce páginas.',
      language: 'Español',
      styleName: 'Tinta',
      characters: [{
        name: 'Nora', role: 'Guía', personality: '', desire: '',
        flaw: '', appearance: 'Abrigo', voice: '',
      }],
      panels: [],
      pages,
      imageProvider: 'minimax',
      imageModel: 'image-01',
      factualBiography: false,
    })
  } finally {
    globalThis.fetch = originalFetch
  }
  const project = useComicStore.getState().project
  const inventory = comicArtworkInventory(project)
  assert.equal(inventory.pages, 12)
  assert.equal(inventory.panels, 72)
  assert.equal(inventory.pending, 72)
  assert.equal(inventory.provider, 'minimax')
  const missing = selectComicArtworkTasks(project, { scope: 'missing' })
  assert.equal(missing.length, 72)
  assert.equal(formatComicArtworkProgress(missing[20], 12, 72), 'página 4/12 · viñeta 21/72')
  const firstPage = selectComicArtworkTasks(project, { pages: [1] })
  assert.equal(firstPage.length, 6)
  const completedIds = project.director.plan.pages[0].panels.map(panel => panel.id)
  const failedId = project.director.plan.pages[6].panels[0].id
  useComicStore.getState().patchProject({
    director: {
      ...useComicStore.getState().project.director,
      completedPanelIds: completedIds,
      failedPanelIds: [failedId],
    },
  })
  const after = useComicStore.getState().project
  assert.equal(selectComicArtworkTasks(after, { scope: 'missing' }).length, 66)
  assert.equal(selectComicArtworkTasks(after, { scope: 'failed' })[0].plan.id, failedId)
  assert.equal(selectComicArtworkTasks(after, { scope: 'failed' })[0].globalIndex, 37)

  const progress = []
  const drawn = []
  const fakeAsset = index => ({
    id: `asset-${index}`,
    name: `panel-${index}.png`,
    kind: 'minimax',
    source: `blob:panel-${index}`,
    createdAt: new Date().toISOString(),
  })
  const first = await generateDirectorArtwork({
    scope: 'missing',
    onProgress: message => progress.push(message),
    drawPanel: async task => {
      if (task.globalIndex === 37) throw new Error('proveedor caído')
      drawn.push(task.globalIndex)
      return fakeAsset(task.globalIndex)
    },
  })
  assert.equal(first.generated, 65)
  assert.equal(first.failed, 1)
  assert.equal(first.cancelled, false)
  assert.ok(progress.some(message => message.includes('página 4/12 · viñeta 21/72')))
  const mid = useComicStore.getState().project
  assert.equal(mid.director.completedPanelIds.length, 71)
  assert.deepEqual(mid.director.failedPanelIds, [failedId])

  const resume = await generateDirectorArtwork({
    scope: 'failed',
    drawPanel: async task => {
      assert.equal(task.globalIndex, 37)
      return fakeAsset(37)
    },
  })
  assert.equal(resume.generated, 1)
  assert.equal(resume.failed, 0)
  assert.equal(useComicStore.getState().project.director.failedPanelIds.length, 0)

  useComicStore.getState().patchProject({
    director: { ...useComicStore.getState().project.director, completedPanelIds: [], failedPanelIds: [] },
  })
  const cancelPromise = generateDirectorArtwork({
    scope: 'missing',
    drawPanel: async task => {
      if (task.globalIndex === 20) requestComicArtworkCancel()
      return fakeAsset(task.globalIndex)
    },
  })
  const cancelled = await cancelPromise
  assert.equal(cancelled.cancelled, true)
  assert.equal(cancelled.generated, 20)
  assert.equal(useComicStore.getState().project.director.completedPanelIds.length, 20)
})

test('factual biography blocks render until review and snapshot exposes comic progress', async () => {
  const { createFilledComic, generateFilledComicArtwork } = await import('../src/features/agent/labActions.ts')
  const { buildAgentAppSnapshot } = await import('../src/features/agent/agentActions.ts')
  const originalFetch = globalThis.fetch
  globalThis.fetch = async () => new Response(JSON.stringify({ outputs: [], total: 0 }), {
    status: 200, headers: { 'Content-Type': 'application/json' },
  })
  try {
    await createFilledComic({
      type: 'create_comic',
      title: 'Vida de Ada',
      synopsis: 'Biografía.',
      language: 'Español',
      styleName: 'Tinta',
      characters: [{
        name: 'Ada', role: 'Protagonista', personality: '', desire: '',
        flaw: '', appearance: 'Abrigo', voice: '',
      }],
      panels: [{ caption: 'Hecho.', dialogue: '', sfx: '', scene: 'Un dato confirmado.' }],
      pages: [],
      imageProvider: 'minimax',
      imageModel: 'image-01',
      factualBiography: true,
    })
  } finally {
    globalThis.fetch = originalFetch
  }
  await assert.rejects(
    () => generateFilledComicArtwork({
      type: 'generate_comic', imageProvider: 'minimax', imageModel: 'image-01',
      scope: 'missing', pages: [], pilot: false, biographyReview: false, confirm: true,
    }),
    /biografía factual/,
  )
  const snapshot = buildAgentAppSnapshot()
  assert.equal(snapshot.comic.title, 'Vida de Ada')
  assert.equal(snapshot.comic.pages, 1)
  assert.equal(snapshot.comic.provider, 'minimax')
  assert.equal('pipeline_id' in snapshot.director, true)
})

test('wizard snapshot includes Story, Series, Video 3D, CharacterKit and Video Editor', async () => {
  const { useStoryStore, createStoryProject } = await import('../src/features/stories/store.ts')
  const { useSeriesStore } = await import('../src/features/series/store.ts')
  const { rememberCharacterKitLibrary, rememberVideo3dScene } = await import('../src/features/agent/wizardLabSession.ts')
  const { createCharacterKit } = await import('../src/lib/characterKit.ts')
  const { persistEditorDraft, RESOLUTIONS } = await import('../src/features/video-editor/editorDraft.ts')
  const { buildAgentAppSnapshot } = await import('../src/features/agent/agentActions.ts')
  const story = createStoryProject()
  story.title = 'La torre de sal'
  story.projectType = 'full_story'
  useStoryStore.setState({ project: story, projects: { [story.id]: story } })
  useSeriesStore.setState({
    activeSeriesId: 'series-1',
    activeEpisodeId: 'ep-1',
    library: {
      seriesOrder: ['series-1'],
      seriesById: {
        'series-1': {
          id: 'series-1', title: 'Mesa para cuatro',
          episodesById: { 'ep-1': { id: 'ep-1', title: 'Piloto', shots: [{ approvedAttemptId: 'a1', attempts: [] }, { approvedAttemptId: '', attempts: [{ status: 'failed' }] }] } },
        },
      },
    },
    renderRecovery: [],
  })
  const kit = createCharacterKit('Nora')
  rememberCharacterKitLibrary({ version: 1, revision: 1, activeId: kit.id, kits: { [kit.id]: kit } })
  rememberVideo3dScene({ scene_id: 'concierto', title: 'Concierto', layers: 4, state: 'ready' })
  persistEditorDraft([], 'corte-final', RESOLUTIONS[0], 30, 'default')
  const snapshot = buildAgentAppSnapshot()
  assert.equal(snapshot.context.schema, 'hocuspocus.wizard_context')
  assert.equal(snapshot.context.version, 1)
  assert.equal(snapshot.context.workspace.id, 'default')
  assert.equal(snapshot.story.title, 'La torre de sal')
  assert.equal(snapshot.story.project_id, story.id)
  assert.equal(snapshot.series.title, 'Mesa para cuatro')
  assert.equal(snapshot.series.episode_title, 'Piloto')
  assert.equal(snapshot.series.shots, 2)
  assert.equal(snapshot.series.approved, 1)
  assert.equal(snapshot.series.failed, 1)
  assert.equal(snapshot.video_3d.title, 'Concierto')
  assert.equal(snapshot.video_3d.layers, 4)
  assert.equal(snapshot.character_kit.title, 'Nora')
  assert.equal(snapshot.video_editor.title, 'corte-final')
})

test('a stale remote snapshot does not replace a newer local Wizard turn', async () => {
  const { applyRemoteWizardConversation } = await import('../src/features/agent/wizardConversationSync.ts')
  const localMessages = [
    { id: 'welcome', role: 'assistant', text: 'Hola', createdAt: 1 },
    { id: 'user-2', role: 'user', text: 'exporta el corte', createdAt: 2 },
    {
      id: 'asst-2', role: 'assistant', text: 'He encolado la exportación.', createdAt: 3,
      cards: [{ id: 'card-new', state: 'queued', message: 'Exportando', executionKey: 'k-new' }],
    },
  ]
  const staleRemote = [
    { id: 'welcome', role: 'assistant', text: 'Hola', createdAt: 1 },
  ]
  const raced = applyRemoteWizardConversation({
    localMessages,
    localRevision: 0,
    remoteMessages: staleRemote,
    remoteRevision: 4,
  })
  assert.equal(raced.source, 'local')
  assert.equal(raced.messages.at(-1).id, 'asst-2')
  assert.equal(raced.messages.at(-1).cards[0].id, 'card-new')
  assert.equal(raced.revision, 4)

  const reloaded = applyRemoteWizardConversation({
    localMessages: [{ id: 'fresh-welcome', role: 'assistant', text: 'Saludos', createdAt: 9 }],
    localRevision: 0,
    remoteMessages: [{
      id: 'asst-saved', role: 'assistant', text: 'He encolado la exportación.', createdAt: 3,
      cards: [{ id: 'card-saved', state: 'queued', taskId: 'export-99', executionKey: 'k-saved' }],
    }],
    remoteRevision: 4,
  })
  assert.equal(reloaded.source, 'remote')
  assert.equal(reloaded.messages[0].cards[0].taskId, 'export-99')
  assert.equal(reloaded.revision, 4)

  const emptyRemote = applyRemoteWizardConversation({
    localMessages,
    localRevision: 1,
    remoteMessages: [],
    remoteRevision: 0,
  })
  assert.equal(emptyRemote.source, 'local')
  assert.equal(emptyRemote.revision, 1)

  const switchedWorkspace = applyRemoteWizardConversation({
    localMessages: localMessages.slice(1),
    localRevision: 0,
    remoteMessages: [{ id: 'saved-in-b', role: 'user', text: 'mensaje remoto', createdAt: 1 }],
    remoteRevision: 7,
  })
  assert.equal(switchedWorkspace.source, 'local')
  assert.equal(switchedWorkspace.revision, 7)
  assert.deepEqual(
    switchedWorkspace.messages.map(message => message.id),
    ['saved-in-b', 'user-2', 'asst-2'],
  )
})

test('execution cards expose five controls and keep the same id on poll', async () => {
  const { cardFromReport, applyPollToCard } = await import('../src/features/agent/executionCards.ts')
  const card = cardFromReport({
    state: 'running',
    message: 'En curso',
    recoverable: true,
    taskId: 'task-1',
    target: { kind: 'video_editor', id: 'edit-1', title: 'edit-1' },
    executionKey: 'default|export_video_editor|edit-1|{}',
  })
  assert.equal(card.controls.open, true)
  assert.equal(card.controls.cancel, true)
  assert.equal(card.controls.resume, false)
  assert.equal(card.controls.viewErrors, false)
  assert.equal(card.controls.retryPending, false)
  const polled = applyPollToCard(card, { state: 'completed', message: 'Listo', outputNames: ['final.mp4'] })
  assert.equal(polled.id, card.id)
  assert.equal(polled.state, 'completed')
  assert.deepEqual(polled.outputNames, ['final.mp4'])
  const failed = cardFromReport({ state: 'failed', message: 'Error', recoverable: true })
  assert.equal(failed.controls.viewErrors, true)
  assert.equal(failed.controls.retryPending, true)
  assert.equal(failed.controls.resume, true)
})
