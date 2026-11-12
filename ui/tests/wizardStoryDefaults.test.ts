import assert from 'node:assert/strict'
import test from 'node:test'
import { JSDOM } from 'jsdom'
import type { SeriesEpisode, SeriesProject } from '../src/features/series/types'
import type { StoryProject } from '../src/features/stories/types'

const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
Object.assign(globalThis, { window: dom.window, document: dom.window.document,
  localStorage: dom.window.localStorage, Event: dom.window.Event, CustomEvent: dom.window.CustomEvent })
window.matchMedia = () => ({ matches: false }) as MediaQueryList

const respond = (body: unknown) => new Response(JSON.stringify(body), { headers: { 'Content-Type': 'application/json' } })

// The Wizard never blocks on questions, so it fills what the user left out.
// It must not invent a look, and it must say what it left unset.
const STORY_BASE = { title: 'El faro', premise: 'Una farera oye al mar pronunciar su nombre.' }
const SERIES_BASE = {
  series_title: 'Gradiente humano',
  series_premise: 'Un laboratorio promete una inteligencia que ni su equipo comprende.',
  episode_premise: 'Una demo para inversores revela las prioridades del laboratorio.',
  create_if_missing: true,
}
const LINE_BOTH_EN = 'Choices I made: style not set (the model decides), tone not set. Tell me if you want something else.'

async function createStoryReply(fields: Record<string, unknown>, workspace: string) {
  const { executeAgentActions, parseAgentTurn } = await import('../src/features/agent/agentActions')
  const { clearExecutionMemory } = await import('../src/features/agent/agentContract')
  const { useStore } = await import('../src/stores/useStore')
  const { useStoryStore } = await import('../src/features/stories/store')
  clearExecutionMemory()
  let library = { version: 2, revision: 1, activeId: '', projects: {} as Record<string, StoryProject> }
  let saved: StoryProject | undefined
  const originalFetch = globalThis.fetch
  globalThis.fetch = async (input, init) => {
    const url = String(typeof input === 'string' ? input : (input as Request).url)
    if (url.includes('/api/v1/stories/library') && (!init?.method || init.method === 'GET')) return respond(library)
    if (url.includes('/api/v1/stories/library') && init?.method === 'PUT') {
      const body = JSON.parse(String(init.body || '{}'))
      library = { ...body.library, revision: (body.library.revision || 0) + 1 }
      saved = Object.values(library.projects as Record<string, StoryProject>).find(project => project.title === STORY_BASE.title)
      return respond(library)
    }
    throw new Error(`Unexpected request: ${init?.method || 'GET'} ${url}`)
  }
  const originalLoadOutputs = useStore.getState().loadOutputs
  useStore.setState({ activeWorkspace: workspace, loadOutputs: async () => {} })
  useStoryStore.setState({ workspace: '', hydrated: false, loading: false, dirty: false, libraryConflicts: [], activeProjectOperations: {} })
  try {
    const turn = parseAgentTurn(JSON.stringify({ reply: 'Ready.', actions: [{ type: 'create_story', ...STORY_BASE, ...fields }] }))
    assert.equal(turn.actions.length, 1)
    const [result] = await executeAgentActions(turn.actions)
    assert.equal(result.ok, true, result.message)
    assert.ok(saved, 'the story was saved')
    return { project: saved as StoryProject, message: result.message }
  } finally {
    globalThis.fetch = originalFetch
    useStore.setState({ loadOutputs: originalLoadOutputs })
    clearExecutionMemory()
  }
}

test('create_story with no style or tone leaves them empty and says so', async () => {
  const { project, message } = await createStoryReply({}, 'wizard-defaults-story-none')
  assert.equal(project.visualStyle, '')
  assert.equal(project.characterVisualStyle, '')
  assert.equal(project.tone, '')
  assert.equal(project.world.visualLanguage, '')
  assert.equal(project.world.visualPrompt, '')
  assert.ok(project.characters.every(character => !/cinematic/i.test(character.visualPrompt)))
  assert.ok(message.includes(LINE_BOTH_EN), message)
  assert.equal(message.split('Choices I made').length, 2, 'one line, not two')
})

test('create_story keeps a style and a tone the user gave, exactly as written, and adds no line', async () => {
  const style = 'Hand-painted gouache, muted palette, visible brush strokes'
  const { project, message } = await createStoryReply({ visual_style: style, tone: 'Wry, tender' }, 'wizard-defaults-story-given')
  assert.equal(project.visualStyle, style)
  assert.equal(project.characterVisualStyle, style)
  assert.equal(project.world.visualLanguage, style)
  assert.equal(project.tone, 'Wry, tender')
  assert.doesNotMatch(message, /Choices I made|not set/)
})

test('create_story lists only what was really left unset', async () => {
  const styleOnly = await createStoryReply({ visual_style: 'Flat paper cut-out' }, 'wizard-defaults-story-style')
  assert.equal(styleOnly.project.visualStyle, 'Flat paper cut-out')
  assert.ok(styleOnly.message.includes('Choices I made: tone not set. Tell me if you want something else.'), styleOnly.message)
  assert.doesNotMatch(styleOnly.message, /style not set/)
  const toneOnly = await createStoryReply({ tone: 'Melancholic' }, 'wizard-defaults-story-tone')
  assert.equal(toneOnly.project.tone, 'Melancholic')
  assert.equal(toneOnly.project.visualStyle, '')
  assert.ok(toneOnly.message.includes('Choices I made: style not set (the model decides). Tell me if you want something else.'), toneOnly.message)
  assert.doesNotMatch(toneOnly.message, /tone not set/)
})

test('create_story counts a style recovered from the brief as set', async () => {
  const brief = 'Videoclip heavy metal con estética visual de animación adulta fantástica de la película Heavy Metal 1981.'
  const { project, message } = await createStoryReply(
    { project_type: 'music_video', creative_brief: brief }, 'wizard-defaults-story-brief',
  )
  assert.equal(project.visualStyle, brief)
  assert.ok(message.includes('Choices I made: tone not set. Tell me if you want something else.'), message)
  assert.doesNotMatch(message, /style not set/)
})

test('the line follows the interface language', async () => {
  const { setUiLanguage } = await import('../src/i18n/index')
  await setUiLanguage('es')
  try {
    const { message } = await createStoryReply({}, 'wizard-defaults-story-es')
    assert.ok(
      message.includes('He elegido: estilo sin fijar (decide el modelo), tono sin fijar. Dime si quieres otra cosa.'),
      message,
    )
  } finally {
    await setUiLanguage('en')
  }
})

test('a music video request has no invented tone, and a named look in the brief still wins over an empty style', async () => {
  const { newMusicVideoStoryAction, resolveMusicVideoVisualStyle } = await import('../src/features/stories/musicVideoLook')
  assert.equal(newMusicVideoStoryAction('Crea un videoclip sobre un faro').tone, '')
  assert.equal(newMusicVideoStoryAction('Make a music video about a lighthouse', 'en').tone, '')
  const brief = 'Videoclip heavy metal con estética de animación adulta de la película Heavy Metal 1981.'
  assert.equal(resolveMusicVideoVisualStyle('music_video', '', brief), brief)
  assert.equal(resolveMusicVideoVisualStyle('music_video', '', 'Un videoclip sobre un faro'), '')
  assert.equal(resolveMusicVideoVisualStyle('full_story', '', brief), '')
})

test('new Story and Series projects start with an empty tone, and a saved tone is kept', async () => {
  const { createStoryProject, normalizeStoryProject } = await import('../src/features/stories/model')
  const { normalizeSeriesProject } = await import('../src/features/series/model')
  assert.equal(createStoryProject().tone, '')
  assert.equal(normalizeStoryProject({ ...createStoryProject(), tone: '' }).tone, '')
  assert.equal(normalizeStoryProject({ ...createStoryProject(), tone: 'Cinematic' }).tone, 'Cinematic')
  assert.equal(normalizeSeriesProject({ id: 'series-a', title: 'A' })!.tone, '')
  assert.equal(normalizeSeriesProject({ id: 'series-a', title: 'A', tone: 'Cinematic' })!.tone, 'Cinematic')
})

async function seriesHarness(workspace: string) {
  const { emptySeriesLibrary } = await import('../src/features/series/model')
  const { useStore } = await import('../src/stores/useStore')
  const { useSeriesStore } = await import('../src/features/series/store')
  const { normalizeSeriesProject } = await import('../src/features/series/model')
  const library = emptySeriesLibrary(workspace)
  const saves: SeriesProject[] = []
  let episodeCount = 0
  const originalFetch = globalThis.fetch
  globalThis.fetch = async (input, init) => {
    const path = new URL(String(input), 'http://localhost').pathname
    const method = init?.method || 'GET'
    if (method === 'GET' && path === '/api/v1/series/library') return respond(library)
    if (method === 'GET' && ['/api/v1/series/plan/recovery', '/api/v1/series/render/recovery'].includes(path)) return respond({ jobs: [] })
    const body = JSON.parse(String(init?.body || '{}'))
    if (method === 'POST' && path === '/api/v1/series') {
      const series = normalizeSeriesProject({ id: 'series-saved', title: body.title,
        seasons: [{ id: 'season-saved', number: 1, title: 'Season 1', episodeOrder: [] }] })!
      library.seriesById[series.id] = series
      library.seriesOrder.push(series.id)
      return respond(series)
    }
    if (method === 'PUT' && path === '/api/v1/series/series-saved') {
      const saved: SeriesProject = { ...body.series, revision: body.baseRevision + 1 }
      library.seriesById[saved.id] = saved
      saves.push(saved)
      return respond(saved)
    }
    const series = library.seriesById['series-saved']
    if (method === 'POST' && path === '/api/v1/series/series-saved/canon/approve') {
      series.canon.approval = 'approved'
      return respond(series)
    }
    if (method === 'POST' && path === '/api/v1/series/series-saved/episodes') {
      episodeCount += 1
      const episode: SeriesEpisode = { ...body.episode, id: `episode-${episodeCount}` }
      series.episodesById[episode.id] = episode
      series.seasons[0].episodeOrder.push(episode.id)
      return respond(episode)
    }
    throw new Error(`Unexpected request: ${method} ${path}`)
  }
  useStore.setState({ activeWorkspace: workspace })
  useSeriesStore.setState({ workspace, library: emptySeriesLibrary(workspace), hydrated: false, dirty: false,
    loading: false, activeSeriesId: '', activeEpisodeId: '' })
  return { library, saves, restore: () => { globalThis.fetch = originalFetch } }
}

async function createEpisodeReply(fields: Record<string, unknown>) {
  const { executeAgentActions, parseAgentTurn } = await import('../src/features/agent/agentActions')
  const { clearExecutionMemory } = await import('../src/features/agent/agentContract')
  clearExecutionMemory()
  const turn = parseAgentTurn(JSON.stringify({ reply: 'Ready.', actions: [{ type: 'create_series_episode', ...SERIES_BASE, ...fields }] }))
  assert.equal(turn.actions.length, 1)
  const [result] = await executeAgentActions(turn.actions)
  return result
}

test('create_series_episode with no style or tone leaves them empty and says so; later episodes still work', async () => {
  const harness = await seriesHarness('wizard-defaults-series-none')
  try {
    const first = await createEpisodeReply({ episode_title: 'La demo' })
    assert.equal(first.ok, true, first.message)
    const series = harness.library.seriesById['series-saved']
    assert.equal(series.visualStyle, '')
    assert.equal(series.characterVisualStyle, '')
    assert.equal(series.cameraLanguage, '')
    assert.equal(series.tone, '')
    assert.ok(first.message.includes(LINE_BOTH_EN), first.message)
    assert.equal(first.message.split('Choices I made').length, 2, 'one line, not two')

    // The series has no style, but nothing is left to set up: the next episode must neither fail nor re-run the setup.
    const savesBefore = harness.saves.length
    const second = await createEpisodeReply({ episode_title: 'El postmortem' })
    assert.equal(second.ok, true, second.message)
    assert.equal(harness.saves.length, savesBefore, 'the second episode did not re-save the series')
    assert.equal(Object.keys(series.episodesById).length, 2)
    assert.doesNotMatch(second.message, /Choices I made/)

    // A style that arrives with a later episode is a Setup matter: it neither fails the episode (the setup would
    // re-save the approved canon as a draft and then refuse to approve it) nor re-saves the series.
    const third = await createEpisodeReply({ episode_title: 'La auditoría', visual_style: 'Flat gouache' })
    assert.equal(third.ok, true, third.message)
    assert.equal(harness.saves.length, savesBefore, 'the third episode did not re-save the series')
    assert.equal(Object.keys(series.episodesById).length, 3)
    assert.equal(series.canon.approval, 'approved')
  } finally {
    harness.restore()
  }
})

test('create_series_episode keeps a style and a tone the user gave, exactly as written, and adds no line', async () => {
  const harness = await seriesHarness('wizard-defaults-series-given')
  try {
    const style = 'Flat paper-cut animation with expressive geometric silhouettes'
    const result = await createEpisodeReply({ episode_title: 'La demo', visual_style: style, tone: 'Dry, observational' })
    assert.equal(result.ok, true, result.message)
    const series = harness.library.seriesById['series-saved']
    assert.equal(series.visualStyle, style)
    assert.equal(series.characterVisualStyle, style)
    assert.equal(series.tone, 'Dry, observational')
    assert.equal(series.cameraLanguage, '')
    assert.doesNotMatch(result.message, /Choices I made|not set/)
  } finally {
    harness.restore()
  }
})

test('create_series_episode lists only what was really left unset', async () => {
  const harness = await seriesHarness('wizard-defaults-series-partial')
  try {
    const result = await createEpisodeReply({ episode_title: 'La demo', visual_style: 'Flat paper cut-out' })
    assert.equal(result.ok, true, result.message)
    assert.ok(result.message.includes('Choices I made: tone not set. Tell me if you want something else.'), result.message)
    assert.doesNotMatch(result.message, /style not set/)
  } finally {
    harness.restore()
  }
})

test('create_series_episode on an existing series keeps its style and lists only what is still unset', async () => {
  const harness = await seriesHarness('wizard-defaults-series-existing')
  try {
    const { normalizeSeriesProject } = await import('../src/features/series/model')
    // A hand-made series: it has a style but no cast, so the Wizard runs the setup once.
    harness.library.seriesById['series-saved'] = normalizeSeriesProject({
      id: 'series-saved', title: SERIES_BASE.series_title, visualStyle: 'Ink wash on rice paper',
      seasons: [{ id: 'season-saved', number: 1, title: 'Season 1', episodeOrder: [] }],
    })!
    harness.library.seriesOrder.push('series-saved')
    const result = await createEpisodeReply({ episode_title: 'La demo', visual_style: 'Neon noir' })
    assert.equal(result.ok, true, result.message)
    const series = harness.library.seriesById['series-saved']
    assert.equal(series.visualStyle, 'Ink wash on rice paper', 'the series keeps its own style')
    assert.equal(series.tone, '')
    assert.ok(result.message.includes('Choices I made: tone not set. Tell me if you want something else.'), result.message)
    assert.doesNotMatch(result.message, /style not set/)
  } finally {
    harness.restore()
  }
})

test('a story with no style of its own is staged for the Director with no style, so there is no lock', async () => {
  const { buildShortFilmAdaptation, buildTrailerAdaptation, DEFAULT_TRAILER_DIRECTION } = await import('../src/features/stories/adaptations')
  const { createStoryProject } = await import('../src/features/stories/model')
  const FALLBACK = /Match the approved Story reference artwork/
  const bare = createStoryProject()
  assert.equal(bare.enforceVisualStyle, true)
  for (const adaptation of [
    buildShortFilmAdaptation(bare, 'A short film', 45, { preserveVisualStyle: true }),
    buildTrailerAdaptation(bare, DEFAULT_TRAILER_DIRECTION, 60, {
      format: 'theatrical', narration: 'hybrid', spoiler: 'balanced', intensity: 'rising',
      tagline: '', titleCards: false, preserveVisualStyle: true,
    }),
  ]) {
    assert.equal(adaptation.visualStyle, '')
    assert.doesNotMatch(adaptation.sceneDescription, FALLBACK)
  }
  // A style the person wrote is used exactly as before.
  const styled = { ...bare, visualStyle: 'Hand-painted gouache' }
  assert.equal(buildShortFilmAdaptation(styled, 'A short film', 45).visualStyle, 'Hand-painted gouache')
  const world = { ...bare, world: { ...bare.world, visualLanguage: 'Low sun, long shadows' } }
  assert.equal(buildShortFilmAdaptation(world, 'A short film', 45).visualStyle, 'Low sun, long shadows')
  // A story that has a style but does not enforce it keeps the reference-artwork sentence it always had.
  const notEnforced = { ...styled, enforceVisualStyle: false }
  assert.match(buildShortFilmAdaptation(notEnforced, 'A short film', 45).visualStyle, FALLBACK)
})
