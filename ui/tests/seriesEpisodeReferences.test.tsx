import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { readFileSync } from 'node:fs'
import { JSDOM } from 'jsdom'
import type { SeriesProject } from '../src/features/series/types'

const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
Object.assign(globalThis, { window: dom.window, document: dom.window.document, localStorage: dom.window.localStorage,
  sessionStorage: dom.window.sessionStorage, HTMLElement: dom.window.HTMLElement, Event: dom.window.Event,
  MutationObserver: dom.window.MutationObserver })
window.matchMedia = () => ({ matches: false }) as MediaQueryList

function fixture() {
  const series: SeriesProject = JSON.parse(readFileSync(new URL('../../docs/series-lab/example-series-library-v1.json', import.meta.url), 'utf8')).seriesById.series_signal
  const episode = Object.values(series.episodesById)[0]
  const shot = episode.shots[0]
  shot.visibleCharacterIds = [series.characters[0].id, series.characters[1].id]
  shot.speakingCharacterIds = []
  shot.locationId = series.locations[0].id
  episode.shots = [shot, { ...structuredClone(shot), id: 'second-shot', order: 2 }]
  episode.canonSnapshot.characters = structuredClone(series.characters)
  episode.canonSnapshot.locations = structuredClone(series.locations)
  episode.canonSnapshot.assets = {}
  episode.canonSnapshot.approvedReferenceAssetIds = []
  return { series, episode }
}

test('batch generates each missing subject once, keeps existing images, and resumes after a partial failure without approval', async () => {
  const { generateMissingEpisodeReferences } = await import('../src/features/series/episodeReferencePreparation')
  const { seriesEntityImage } = await import('../src/features/series/shotReferences')
  const { series, episode } = fixture()
  const originalSnapshot = structuredClone(episode.canonSnapshot)
  const originalImage = seriesEntityImage(series.characters[0], series.assets)
  assert.ok(originalImage)
  series.characters[1].referenceAssetIds = ['nonexistent-asset']
  series.characters[1].primaryReferenceAssetId = undefined
  series.locations[0].referenceAssetIds = []
  const generated: string[] = []
  let failLocation = true
  const options: Parameters<typeof generateMissingEpisodeReferences>[0] = {
    workspace: 'source', episodeId: episode.id, current: async () => series, progress: () => {}, accept: () => {},
    generate: async (workspace, current, target, request) => {
      assert.equal(workspace, 'source')
      await request.beforeImport()
      if (target.kind === 'location' && failLocation) { failLocation = false; throw new Error('image provider unavailable') }
      generated.push(target.id)
      const entity = (target.kind === 'character' ? current.characters : current.locations).find(item => item.id === target.id)!
      const asset = { ...originalImage, id: `new-${target.id}`, uri: `assets/${target.id}.png`, kind: 'image' as const }
      entity.referenceAssetIds = [asset.id]; entity.approval = 'draft'; current.assets[asset.id] = asset
      current.canon.approval = 'draft'
      return { series: current, asset }
    },
  }
  await assert.rejects(generateMissingEpisodeReferences(options), /image provider unavailable/)
  assert.deepEqual(generated, [series.characters[1].id])
  await generateMissingEpisodeReferences(options)
  assert.deepEqual(generated, [series.characters[1].id, series.locations[0].id])
  await generateMissingEpisodeReferences(options)
  assert.equal(generated.length, 2)
  assert.equal(seriesEntityImage(series.characters[0], series.assets)?.id, originalImage.id)
  assert.equal(series.canon.approval, 'draft')
  assert.deepEqual(episode.canonSnapshot, originalSnapshot)
})

test('Shots offers existing approved images directly and incorporates them without generating or changing takes', async t => {
  const { render, fireEvent, waitFor, cleanup } = await import('@testing-library/react')
  const { SeriesEpisodeReferences } = await import('../src/features/series/SeriesEpisodeReferences')
  const { useSeriesStore } = await import('../src/features/series/store')
  const { useStore } = await import('../src/stores/useStore')
  const { seriesShotReferences } = await import('../src/features/series/shotReferences')
  const { series, episode } = fixture()
  const beforeShots = structuredClone(episode.shots)
  const requests: string[] = []
  const originalFetch = globalThis.fetch
  globalThis.fetch = async (input, init) => {
    requests.push(String(input))
    assert.match(String(input), new RegExp(`/episodes/${episode.id}/references/refresh$`))
    assert.equal(init?.method, 'POST')
    assert.deepEqual(JSON.parse(String(init.body)), { workspace: 'source', baseRevision: series.revision })
    const updated = structuredClone(series)
    updated.revision++
    Object.assign(updated.episodesById[episode.id].canonSnapshot, {
      characters: series.characters, locations: series.locations, assets: series.assets,
      approvedReferenceAssetIds: Object.keys(series.assets),
    })
    return new Response(JSON.stringify(updated))
  }
  t.after(() => { cleanup(); globalThis.fetch = originalFetch })
  useStore.setState({ activeWorkspace: 'source' })
  useSeriesStore.setState({ workspace: 'source', activeSeriesId: series.id, activeEpisodeId: episode.id,
    hydrated: true, dirty: false, serverRevision: series.revision,
    library: { schemaVersion: 1, workspace: 'source', seriesOrder: [series.id], seriesById: { [series.id]: series } } })
  assert.equal(seriesShotReferences(series, episode, episode.shots[0]).locationState, 'availableInSeries')
  function Panel() {
    const current = useSeriesStore(state => state.library.seriesById[series.id])
    return <SeriesEpisodeReferences workspace="source" series={current} episode={current.episodesById[episode.id]} />
  }
  const view = render(<Panel />)
  assert.equal((view.getByRole('button', { name: 'Generate all missing references (0)' }) as HTMLButtonElement).disabled, true)
  fireEvent.click(view.getByRole('button', { name: 'Use approved references in this episode' }))
  await waitFor(() => assert.match(view.getByRole('status').textContent!, /Approved references incorporated/))
  const current = useSeriesStore.getState().library.seriesById[series.id]
  assert.ok(seriesShotReferences(current, current.episodesById[episode.id], episode.shots[0]).ready)
  assert.deepEqual(current.episodesById[episode.id].shots, beforeShots)
  assert.equal(requests.length, 1)
})
