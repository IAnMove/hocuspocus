import assert from 'node:assert/strict'
import test from 'node:test'
import { JSDOM } from 'jsdom'
import type { SeriesEpisode, SeriesProject } from '../src/features/series/types'

const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
Object.assign(globalThis, { window: dom.window, document: dom.window.document,
  localStorage: dom.window.localStorage, Event: dom.window.Event, CustomEvent: dom.window.CustomEvent })
window.matchMedia = () => ({ matches: false }) as MediaQueryList

for (const resumeDraft of [false, true]) {
test(`a creative series plan ${resumeDraft ? 'resumes an empty draft' : 'creates a series'} over LAN HTTP and reports persisted premises without rendering`, async (t) => {
  const cryptoDescriptor = Object.getOwnPropertyDescriptor(globalThis, 'crypto')!
  const getRandomValues = globalThis.crypto.getRandomValues.bind(globalThis.crypto)
  Object.defineProperty(globalThis, 'crypto', { configurable: true, value: { getRandomValues } })
  t.after(() => Object.defineProperty(globalThis, 'crypto', cryptoDescriptor))
  assert.equal(typeof globalThis.crypto.randomUUID, 'undefined')
  const { parseAgentTurn } = await import('../src/features/agent/agentActions')
  const { validateWizardPlan } = await import('../src/features/agent/wizardVisualPolicy')
  const { createFilledSeriesEpisode } = await import('../src/features/series/actions')
  const { useSeriesStore } = await import('../src/features/series/store')
  const { emptySeriesLibrary, normalizeSeriesProject } = await import('../src/features/series/model')
  const { useStore } = await import('../src/stores/useStore')
  const workspace = `creative-direction-test-${resumeDraft}`
  const library = emptySeriesLibrary(workspace)
  if (resumeDraft) {
    library.seriesOrder.push('series-saved')
    library.seriesById['series-saved'] = normalizeSeriesProject({ id: 'series-saved', title: 'Gradiente humano',
      seasons: [{ id: 'season-saved', number: 1, title: 'Season 1', episodeOrder: [] }] })!
  }
  const writes: string[] = []
  const originalFetch = globalThis.fetch
  const respond = (body: unknown) => new Response(JSON.stringify(body), { headers: { 'Content-Type': 'application/json' } })
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
      writes.push('create-series')
      return respond(series)
    }
    if (method === 'PUT' && path === '/api/v1/series/series-saved') {
      assert.equal(body.baseRevision, library.seriesById['series-saved'].revision)
      const saved: SeriesProject = { ...body.series, premise: 'Premisa canónica guardada por el servidor.', revision: body.baseRevision + 1 }
      library.seriesById[saved.id] = saved
      writes.push('save-world')
      return respond(saved)
    }
    const series = library.seriesById['series-saved']
    if (method === 'POST' && path === '/api/v1/series/series-saved/canon/approve') {
      series.canon.approval = 'approved'
      writes.push('prepare-new-canon')
      return respond(series)
    }
    if (method === 'POST' && path === '/api/v1/series/series-saved/episodes') {
      assert.equal(series.canon.approval, 'approved')
      assert.equal(body.episode.outline.beats.length, 3)
      const episode: SeriesEpisode = { ...body.episode, id: 'episode-saved',
        premise: 'El piloto guardado enfrenta al equipo a una demostración imposible.' }
      series.episodesById[episode.id] = episode
      series.seasons[0].episodeOrder.push(episode.id)
      writes.push('save-episode')
      return respond(episode)
    }
    throw new Error(`Unexpected request (including any media generation): ${method} ${path}`)
  }
  useStore.setState({ activeWorkspace: workspace })
  useSeriesStore.setState({ workspace, library: emptySeriesLibrary(workspace), hydrated: false, dirty: false,
    loading: false, activeSeriesId: '', activeEpisodeId: '' })
  try {
    const turn = validateWizardPlan(false, parseAgentTurn(JSON.stringify({ reply: 'An invented result.',
      intent: { kind: 'action', execution: 'prepare', goal: 'Develop the supplied AI workplace satire as a series and pilot', question: '' },
      actions: [{ type: 'create_series_episode', series_title: 'Gradiente humano',
        series_premise: 'Un laboratorio americano promete una inteligencia que ni su equipo comprende.',
        episode_title: 'La demo', episode_premise: 'Una demo para inversores revela las prioridades del laboratorio.',
        visual_style: 'Flat paper-cut animation with expressive geometric silhouettes.',
        world_summary: 'Un laboratorio ficticio entre investigación, marketing y rivalidades.',
        characters: [{ name: 'Ada', role: 'Investigadora', desire: 'Comprender su modelo' },
          { name: 'Max', role: 'Director', desire: 'Cerrar financiación' }, { name: 'Lina', role: 'Ingeniera', desire: 'Medir la realidad' }],
        locations: [{ name: 'Laboratorio', purpose: 'Las demos y sus consecuencias', description: 'Una oficina con una sala de servidores.' }],
        outline_beats: ['Prometen una demo.', 'El modelo contradice el discurso.', 'El equipo decide qué mostrar.'],
        create_if_missing: true, known_universe: false }],
    })))
    assert.equal(turn.actions.length, 1)
    const action = turn.actions[0]
    assert.equal(action.type, 'create_series_episode')
    if (action.type !== 'create_series_episode') throw new Error('Missing episode action')
    const receipt = await createFilledSeriesEpisode(action)
    assert.deepEqual(writes, [...(resumeDraft ? [] : ['create-series']), 'save-world', 'prepare-new-canon', 'save-episode'])
    assert.deepEqual(library.seriesOrder, ['series-saved'])
    const saved = library.seriesById['series-saved']
    assert.deepEqual(Object.keys(saved.episodesById), ['episode-saved'])
    assert.equal(saved.characters.length, 3)
    assert.equal(saved.locations.length, 1)
    assert.equal(saved.sourceMode, 'original')
    assert.equal(useSeriesStore.getState().activeEpisodeId, 'episode-saved')
    const message = String(receipt.artifacts[0].metadata?.summary)
    assert.match(message, /Premisa canónica guardada por el servidor/)
    assert.match(message, /El piloto guardado enfrenta al equipo/)
    assert.doesNotMatch(message, /An invented result|Una demo para inversores/)
    assert.equal(receipt.navigationTarget?.entity.id, 'episode-saved')
  } finally {
    globalThis.fetch = originalFetch
  }
})
}
