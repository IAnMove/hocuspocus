import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'

const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
Object.assign(globalThis, { window: dom.window, document: dom.window.document, localStorage: dom.window.localStorage,
  HTMLElement: dom.window.HTMLElement, Event: dom.window.Event, CustomEvent: dom.window.CustomEvent })
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })

test('a Spanish episode gets an English version translated, edited line by line and assembled', async t => {
  const { render, fireEvent, cleanup, waitFor, within } = await import('@testing-library/react')
  const { SeriesLanguageVersions } = await import('../src/features/series/SeriesLanguageVersions')
  const { useSeriesStore } = await import('../src/features/series/store')
  t.after(cleanup)
  useSeriesStore.setState({ reload: async () => {} })
  const requests: { method: string; url: string; body?: Record<string, unknown> }[] = []
  const original = globalThis.fetch
  t.after(() => { globalThis.fetch = original })
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input).replace(/^.*\/api\/v1/, '')
    const body = init?.body ? JSON.parse(String(init.body)) as Record<string, unknown> : undefined
    requests.push({ method: init?.method ?? 'GET', url, body })
    const reply = url.includes('/recovery') ? { jobs: [] } : url.includes('/assembly/start') ? { jobId: 'cut-1', status: 'queued' }
      : { revision: 3, language: 'english', missingLines: [], version: { dialogue: {}, cards: {}, approvedAttemptIds: {}, assemblyAssetIds: [] } }
    return new Response(JSON.stringify(reply), { status: 200, headers: { 'Content-Type': 'application/json' } })
  }) as typeof fetch
  const shot = (id: string, beats: Array<[string, string, string]>) => ({ id, attempts: [], dialogueBeats: beats.map(([beat, who, text]) => ({ id: beat, characterId: who, text, emotion: '', delivery: '' })) })
  const episode = { id: 'ep1', title: 'Piloto', shots: [shot('s1', [['b1', 'kevin', 'Vale, Gary.'], ['b2', 'gary', '¡Hola!']])] } as never
  const series = { id: 'uv', spokenLanguage: 'Español de España', language: 'Español' } as never

  const view = render(<SeriesLanguageVersions workspace="cast" series={series} episode={episode} />)
  const add = view.getByLabelText('Add') as HTMLSelectElement
  assert.ok(![...add.options].some(option => option.value === 'spanish'), 'the original language is not offered')
  fireEvent.change(add, { target: { value: 'english' } })
  fireEvent.click(view.getByRole('button', { name: 'Translate with AI' }))
  await waitFor(() => assert.ok(requests.some(item => item.url === '/series/uv/episodes/ep1/language-versions/english/translate')))

  const withVersion = { ...(episode as object), languageVersions: { english: { dialogue: { b1: 'Okay, Gary.' }, cards: {}, approvedAttemptIds: {}, assemblyAssetIds: [] } } } as never
  view.rerender(<SeriesLanguageVersions workspace="cast" series={series} episode={withVersion} />)
  fireEvent.click(view.getByRole('button', { name: 'English' }))
  assert.equal((view.getByLabelText('Translation of b1') as HTMLTextAreaElement).value, 'Okay, Gary.')
  assert.ok(view.getByText('1 lines still need text'))
  fireEvent.change(view.getByLabelText('Translation of b2'), { target: { value: 'Hi!' } })
  fireEvent.click(view.getByRole('button', { name: 'Save lines' }))
  await waitFor(() => assert.ok(requests.some(item => item.method === 'PUT')))
  assert.deepEqual(requests.find(item => item.method === 'PUT')!.body, { workspace: 'cast', version: { dialogue: { b2: 'Hi!' } } })
  fireEvent.click(view.getByRole('button', { name: 'Assemble this version' }))
  await waitFor(() => assert.ok(requests.some(item => item.url.endsWith('/assembly/start'))))
  assert.deepEqual(requests.find(item => item.url.endsWith('/assembly/start'))!.body, { workspace: 'cast', language: 'english', burnSubtitles: true })
  assert.equal(within(view.getByTestId('series-language-versions')).queryByTestId('series-server-render'), null, 'render waits for every line')
})
