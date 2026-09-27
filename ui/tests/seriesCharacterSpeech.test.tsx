import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { readFileSync } from 'node:fs'
import { JSDOM } from 'jsdom'
import { emptyCharacterKitLibrary } from '../src/lib/characterKit'
import type { SeriesProject } from '../src/features/series/types'

const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
Object.assign(globalThis, { window: dom.window, document: dom.window.document, localStorage: dom.window.localStorage,
  sessionStorage: dom.window.sessionStorage, HTMLElement: dom.window.HTMLElement, HTMLInputElement: dom.window.HTMLInputElement,
  HTMLSelectElement: dom.window.HTMLSelectElement, Event: dom.window.Event, MutationObserver: dom.window.MutationObserver })
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
window.matchMedia = () => ({ matches: false }) as MediaQueryList

test('Series opens the exact character in Character Creator, preserves a draft and saves its reusable voice and return destination', async t => {
  const { render, fireEvent, waitFor, cleanup, configure } = await import('@testing-library/react')
  configure({ asyncUtilTimeout: 5000 })
  const { SeriesCharacterSpeech } = await import('../src/features/series/SeriesCharacterSpeech')
  const { CharacterCreatorPanel } = await import('../src/features/characters/CharacterCreatorPanel')
  const { useSeriesStore } = await import('../src/features/series/store')
  const { useStore } = await import('../src/stores/useStore')
  const { useCharacterEditorHandoff } = await import('../src/features/characters/characterEditorHandoff')
  const { openSeriesCharacterEditor, useSeriesCharacterReturn } = await import('../src/features/series/seriesCharacterEditor')
  const originalFetch = globalThis.fetch
  let library = emptyCharacterKitLibrary(), writes = 0
  globalThis.fetch = async (input, init) => {
    const url = String(input)
    if (url.includes('/character-kits/library')) {
      if (init?.method === 'PATCH') {
        const body = JSON.parse(String(init.body))
        assert.equal(body.workspace, 'source')
        assert.equal(body.baseRevision, library.revision)
        assert.equal(body.kit.speech3d, undefined)
        library = { ...library, revision: library.revision + 1, kits: { ...library.kits, [body.kit.id]: body.kit } }
        writes++
      }
      return new Response(JSON.stringify(library))
    }
    if (url.includes('/outputs')) return new Response(JSON.stringify({ outputs: [], total: 0 }))
    if (url.includes('/api/v1/series/') && init?.method === 'PUT') {
      const body = JSON.parse(String(init.body))
      return new Response(JSON.stringify({ ...body.series, revision: body.baseRevision + 1 }))
    }
    throw new Error(`Unexpected request: ${init?.method || 'GET'} ${url}`)
  }
  t.after(() => { cleanup(); globalThis.fetch = originalFetch; useCharacterEditorHandoff.setState({ request: null }) })
  const series: SeriesProject = JSON.parse(readFileSync(new URL('../../docs/series-lab/example-series-library-v1.json', import.meta.url), 'utf8')).seriesById.series_signal
  series.characters[0].voiceProfile = {}
  series.characters[0].referenceAssetIds = []
  series.characters[0].primaryReferenceAssetId = undefined
  const characterId = series.characters[0].id, episodeId = Object.keys(series.episodesById)[0]
  useStore.setState({ activeWorkspace: 'source', mediaFilter: 'series' })
  useSeriesStore.setState({ workspace: 'source', activeSeriesId: series.id, activeEpisodeId: episodeId, serverRevision: series.revision,
    hydrated: true, dirty: false, library: { schemaVersion: 1, workspace: 'source', seriesOrder: [series.id], seriesById: { [series.id]: series } } })
  function Form() {
    const current = useSeriesStore(state => state.library.seriesById[series.id])
    const filter = useStore(state => state.mediaFilter)
    if (filter === 'characters') return <CharacterCreatorPanel />
    return <SeriesCharacterSpeech workspace="source" series={current} character={current.characters[0]} saveNow={useSeriesStore.getState().saveNow} onPatch={() => {}} />
  }
  const view = render(<Form />)
  fireEvent.click(view.getByRole('button', { name: 'Configure in Character Creator' }))
  const voice = await view.findByTestId('character-voice')
  await waitFor(() => assert.equal(view.getByTestId('save-character').hasAttribute('disabled'), false))
  assert.equal(useStore.getState().mediaFilter, 'characters')
  assert.equal((view.getByTestId('saved-character') as HTMLSelectElement).disabled, true)
  assert.equal(view.queryByRole('button', { name: 'Configure in Character Creator' }), null, 'no compressed inline editor')
  fireEvent.change(voice, { target: { value: 'serena' } })
  assert.equal((view.getByRole('button', { name: 'Return to the character in Series Lab' }) as HTMLButtonElement).disabled, true)
  const draftId = useCharacterEditorHandoff.getState().request!.kit.id
  await assert.rejects(openSeriesCharacterEditor('source', series.id, series.characters[1].id), /Another configuration/)
  view.unmount()
  const reopened = render(<Form />)
  await waitFor(() => assert.equal((reopened.getByTestId('character-voice') as HTMLSelectElement).value, 'serena'))
  assert.equal(useCharacterEditorHandoff.getState().request!.kit.id, draftId)
  fireEvent.click(reopened.getByTestId('save-character'))
  await waitFor(() => assert.equal(useSeriesStore.getState().library.seriesById[series.id].characters[0].voiceProfile?.characterKitRef?.workspace, 'source'))
  const ref = useSeriesStore.getState().library.seriesById[series.id].characters[0].voiceProfile!.characterKitRef!
  assert.equal(library.kits[ref.id].voice?.voiceId, 'serena')
  assert.equal(writes, 1)
  await waitFor(() => assert.equal((reopened.getByRole('button', { name: 'Return to the character in Series Lab' }) as HTMLButtonElement).disabled, false))
  fireEvent.click(reopened.getByRole('button', { name: 'Return to the character in Series Lab' }))
  await waitFor(() => assert.equal(useStore.getState().mediaFilter, 'series'))
  assert.equal(useSeriesCharacterReturn.getState().source?.characterId, characterId)
  assert.equal(useSeriesStore.getState().activeEpisodeId, episodeId)
  fireEvent.click(reopened.getByRole('button', { name: 'Configure in Character Creator' }))
  await waitFor(() => assert.equal((reopened.getByTestId('character-voice') as HTMLSelectElement).value, 'serena'))
  assert.equal((reopened.getByTestId('saved-character') as HTMLSelectElement).value, ref.id)
  assert.equal(writes, 1, 'opening existing configuration must not create another character or a generation')
  // Saving from the ordinary toolbar must also release the session when navigating by tabs.
  fireEvent.click(reopened.getByTestId('save-character'))
  await waitFor(() => assert.equal(useCharacterEditorHandoff.getState().request!.saved, true))
  await openSeriesCharacterEditor('source', series.id, series.characters[1].id)
  assert.equal(useCharacterEditorHandoff.getState().request!.sourceId, `source/${series.id}/${series.characters[1].id}`)
  useStore.setState({ activeWorkspace: 'elsewhere' })
  await assert.rejects(useCharacterEditorHandoff.getState().request!.onSaved(library.kits[ref.id]), /project changed/)
})
