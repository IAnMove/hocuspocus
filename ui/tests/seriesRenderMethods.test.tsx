import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { readFileSync } from 'node:fs'
import { JSDOM } from 'jsdom'
import type { SeriesProject } from '../src/features/series/types'
import { seriesRenderCandidates } from '../src/features/series/productionMethods'

const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
Object.assign(globalThis, { window: dom.window, document: dom.window.document, localStorage: dom.window.localStorage,
  sessionStorage: dom.window.sessionStorage, HTMLElement: dom.window.HTMLElement, Event: dom.window.Event,
  MutationObserver: dom.window.MutationObserver })
window.matchMedia = () => ({ matches: false }) as MediaQueryList

function fixture() {
  const series: SeriesProject = JSON.parse(readFileSync(new URL('../../docs/series-lab/example-series-library-v1.json', import.meta.url), 'utf8')).seriesById.series_signal
  const episode = Object.values(series.episodesById)[0]
  series.allowedProductionMethods = ['animation_2d']
  for (const shot of episode.shots) { shot.productionMethod = 'animation_2d'; shot.attempts = []; shot.approvedAttemptId = undefined }
  return { series, episode }
}

test('Review routes a 2D-only episode to shot production instead of offering an empty AI render', async t => {
  const { render, fireEvent, cleanup } = await import('@testing-library/react')
  const { SeriesReviewPanel } = await import('../src/features/series/SeriesReviewPanel')
  const { series, episode } = fixture()
  const originalFetch = globalThis.fetch, opened: string[] = [], rendered: string[] = []
  globalThis.fetch = async (input, init) => {
    assert.equal(init?.method ?? 'GET', 'GET', `Unexpected mutation: ${input}`)
    return new Response(JSON.stringify({ jobs: [] }))
  }
  t.after(() => { cleanup(); globalThis.fetch = originalFetch })
  const view = render(<SeriesReviewPanel workspace="default" series={series} episode={episode} job={null} setJob={() => {}}
    reload={async () => {}} saveNow={async () => series} updateEpisode={() => {}}
    startRender={async mode => { rendered.push(mode) }} onOpenShots={id => { opened.push(id ?? '') }} />)
  assert.equal(view.queryByRole('button', { name: 'Generate AI draft takes (0)' }), null)
  assert.equal(view.queryByRole('button', { name: /Prepare 2D shots/ }), null)
  fireEvent.click(view.getByRole('button', { name: /History and attempts/ }))
  fireEvent.click(view.getByRole('button', { name: 'Open production for shot 1' }))
  assert.equal(opened.at(-1), episode.shots[0].id)
  assert.deepEqual(rendered, [])
  assert.equal(view.queryByRole('button', { name: 'Edit and regenerate' }), null)
})

test('render eligibility respects allowed methods, last failure, bulk approvals and explicit replacement of an approved AI take', () => {
  const { series, episode } = fixture(), seed = structuredClone(episode.shots[0])
  series.allowedProductionMethods = ['generated_video', 'animation_2d', 'animation_3d', 'imported_video']
  const attempt = { id: 'take', status: 'failed' } as typeof seed.attempts[number]
  episode.shots = [
    { ...seed, id: 'ai', productionMethod: 'generated_video', attempts: [attempt] },
    { ...seed, id: 'recovered', productionMethod: 'generated_video', attempts: [attempt, { ...attempt, id: 'new', status: 'completed' }] },
    { ...seed, id: 'approved', productionMethod: 'generated_video', approvedAttemptId: 'kept' },
    ...(['animation_2d', 'animation_3d', 'imported_video'] as const).map(method => ({ ...seed, id: method, productionMethod: method, attempts: [attempt] })),
  ]
  assert.deepEqual(seriesRenderCandidates(series, episode, 'missing').map(shot => shot.id), ['ai', 'recovered'])
  assert.deepEqual(seriesRenderCandidates(series, episode, 'failed').map(shot => shot.id), ['ai'])
  assert.deepEqual(seriesRenderCandidates(series, episode, 'selected', ['approved', 'animation_2d']).map(shot => shot.id), ['approved'])
  assert.equal(episode.shots[2].approvedAttemptId, 'kept')
  series.allowedProductionMethods = ['animation_2d']
  assert.deepEqual(seriesRenderCandidates(series, episode, 'all'), [])
})

test('episode progress distinguishes reference approval from video takes and links missing entities and pending takes by id', async t => {
  const { render, fireEvent, cleanup } = await import('@testing-library/react')
  const { SeriesEpisodeProgress } = await import('../src/features/series/SeriesEpisodeProgress')
  const { series, episode } = fixture()
  const location = series.locations.find(item => item.id === episode.shots[0].locationId)!
  episode.canonSnapshot.characters = structuredClone(series.characters)
  episode.canonSnapshot.locations = structuredClone(series.locations)
  episode.canonSnapshot.assets = structuredClone(series.assets)
  episode.canonSnapshot.approvedReferenceAssetIds = Object.keys(series.assets)
  const frozenLocation = (episode.canonSnapshot.locations as typeof series.locations).find(item => item.id === location.id)!
  frozenLocation.referenceAssetIds = []
  for (const variant of frozenLocation.variants) variant.referenceAssetIds = []
  const references: unknown[] = [], opened: string[] = [], reviewed: string[] = []
  const shot = episode.shots[0]
  episode.shots = [shot, { ...structuredClone(shot), id: 'review-me', order: 2,
    attempts: [{ id: 'new-take', status: 'completed' } as typeof shot.attempts[number]] }]
  t.after(cleanup)
  const view = render(<SeriesEpisodeProgress series={series} episode={episode}
    onOpenReferences={(room, id) => references.push([room, id])} onOpenShot={id => opened.push(id)} onReviewShot={id => reviewed.push(id)} />)
  fireEvent.click(view.getByRole('button', { name: location.name, exact: true }))
  assert.deepEqual(references, [['locations', location.id]], 'one reference link despite multiple shots using it')
  fireEvent.click(view.getByRole('button', { name: 'Prepare shot 1', exact: true }))
  fireEvent.click(view.getByRole('button', { name: 'Review take for shot 2', exact: true }))
  assert.deepEqual(opened, [shot.id]); assert.deepEqual(reviewed, ['review-me'])
  assert.ok(view.getByText('Video takes: 1 to create · 1 awaiting approval · 0 of 2 approved.'))
  assert.equal(episode.shots[1].approvedAttemptId, undefined, 'showing a generated draft must not approve it')
})

test('Wizard refuses an AI render for native-only shots before submitting a job or asking for native-audio consent', async t => {
  const { useStore } = await import('../src/stores/useStore')
  const { useSeriesStore } = await import('../src/features/series/store')
  const { emptySeriesLibrary } = await import('../src/features/series/model')
  const { renderSeriesShots } = await import('../src/features/series/actions')
  const { series, episode } = fixture()
  series.bestEffortLipSyncAcknowledged = false
  const library = { ...emptySeriesLibrary('default'), seriesOrder: [series.id], seriesById: { [series.id]: series } }
  useStore.setState({ activeWorkspace: 'default' })
  useSeriesStore.setState({ workspace: 'default', hydrated: true, loading: false, dirty: false, library,
    activeSeriesId: series.id, activeEpisodeId: episode.id, serverRevision: series.revision })
  const originalFetch = globalThis.fetch, requests: string[] = []
  globalThis.fetch = async (input, init) => {
    assert.equal(init?.method ?? 'GET', 'GET')
    requests.push(String(input))
    assert.match(String(input), /series\/library/)
    return new Response(JSON.stringify(library))
  }
  t.after(() => { globalThis.fetch = originalFetch })
  await assert.rejects(renderSeriesShots({ seriesTitle: series.title, targetEpisodeTitle: episode.title,
    mode: 'missing', shotIds: [], confirm: true }), /No AI video shots/)
  assert.equal(requests.length, 1)
})
