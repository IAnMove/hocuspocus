import assert from 'node:assert/strict'
import test from 'node:test'
import React, { useState } from 'react'
import { readFileSync } from 'node:fs'
import { JSDOM } from 'jsdom'
import { emptyCharacterKitLibrary } from '../src/lib/characterKit'
import type { SeriesProject } from '../src/features/series/types'

const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
Object.assign(globalThis, { window: dom.window, document: dom.window.document, localStorage: dom.window.localStorage,
  sessionStorage: dom.window.sessionStorage, HTMLElement: dom.window.HTMLElement, HTMLInputElement: dom.window.HTMLInputElement,
  HTMLSelectElement: dom.window.HTMLSelectElement, Event: dom.window.Event, MutationObserver: dom.window.MutationObserver })
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })

test('an unlinked Series character saves a reusable voice without a GLB and reopens the same identity', async t => {
  const { render, fireEvent, waitFor, cleanup } = await import('@testing-library/react')
  const { SeriesCharacterSpeech } = await import('../src/features/series/SeriesCharacterSpeech')
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
    throw new Error(`Unexpected request: ${init?.method || 'GET'} ${url}`)
  }
  t.after(() => { cleanup(); globalThis.fetch = originalFetch })
  let series: SeriesProject = JSON.parse(readFileSync(new URL('../../docs/series-lab/example-series-library-v1.json', import.meta.url), 'utf8')).seriesById.series_signal
  series.characters[0].voiceProfile = {}
  series.characters[0].referenceAssetIds = []
  series.characters[0].primaryReferenceAssetId = undefined
  const characterId = series.characters[0].id
  function Form() {
    const [current, setCurrent] = useState(series)
    return <SeriesCharacterSpeech workspace="source" series={current} character={current.characters[0]} saveNow={async () => series}
      onPatch={patch => setCurrent(previous => (series = { ...previous, characters: previous.characters.map(character => character.id === characterId
        ? { ...character, voiceProfile: { ...character.voiceProfile, ...patch } } : character) }))} />
  }
  const view = render(<Form />)
  fireEvent.click(view.getByRole('button', { name: 'Configure voice and lip sync' }))
  const voice = await view.findByTestId('character-voice')
  await waitFor(() => assert.equal(voice.closest('fieldset')?.parentElement?.closest('fieldset')?.disabled, false))
  fireEvent.change(voice, { target: { value: 'serena' } })
  fireEvent.click(view.getByTestId('save-character'))
  await waitFor(() => assert.equal(series.characters[0].voiceProfile?.characterKitRef?.workspace, 'source'))
  const ref = series.characters[0].voiceProfile!.characterKitRef!
  assert.equal(library.kits[ref.id].voice?.voiceId, 'serena')
  assert.equal(writes, 1)
  fireEvent.click(view.getByRole('button', { name: 'Close configuration' }))
  await waitFor(() => assert.ok(view.getByRole('button', { name: 'Edit voice and lip sync' })))
  fireEvent.click(view.getByRole('button', { name: 'Edit voice and lip sync' }))
  await waitFor(() => assert.equal((view.getByTestId('character-voice') as HTMLSelectElement).value, 'serena'))
  assert.equal((view.getByTestId('saved-character') as HTMLSelectElement).value, ref.id)
  assert.equal(writes, 1, 'opening existing configuration must not create another character or a generation')
})
