import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'

const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
Object.assign(globalThis, { window: dom.window, document: dom.window.document, localStorage: dom.window.localStorage,
  HTMLElement: dom.window.HTMLElement, Event: dom.window.Event, CustomEvent: dom.window.CustomEvent })
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })

test('a series starts from a template in the chosen language', async t => {
  const { render, fireEvent, cleanup, waitFor } = await import('@testing-library/react')
  const { SeriesTemplatePicker } = await import('../src/features/series/SeriesTemplatePicker')
  const { useSeriesStore } = await import('../src/features/series/store')
  t.after(cleanup)
  const created: Array<[string, string]> = []
  useSeriesStore.setState({ newSeriesFromTemplate: async (id: string, language: 'es' | 'en') => { created.push([id, language]) } })
  const asked: string[] = []
  const original = globalThis.fetch
  t.after(() => { globalThis.fetch = original })
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    const url = String(input)
    asked.push(url.replace(/^.*\/api\/v1/, ''))
    const spanish = url.includes('language=es')
    const templates = [{ id: 'cutout-satire', title: spanish ? 'Sátira de recortables' : 'Cutout satire', description: '', characters: ['Ana', 'Leo'], locations: [], pilotShots: 5 }]
    return new Response(JSON.stringify({ templates }), { status: 200, headers: { 'Content-Type': 'application/json' } })
  }) as typeof fetch

  const view = render(<SeriesTemplatePicker onCreate={task => void task()} />)
  fireEvent.change(view.getByLabelText('Language'), { target: { value: 'es' } })
  await waitFor(() => assert.ok(view.getByText('Sátira de recortables')))
  assert.ok(view.getByText('Cast: Ana, Leo · pilot of 5 2D shots'))
  fireEvent.click(view.getByRole('button', { name: 'Create “Sátira de recortables”' }))
  await waitFor(() => assert.deepEqual(created, [['cutout-satire', 'es']]))
  assert.ok(asked.includes('/series/templates?language=es'))
})

test('a server without templates leaves the picker empty instead of breaking the library', async t => {
  const { render, cleanup, waitFor } = await import('@testing-library/react')
  const { SeriesTemplatePicker } = await import('../src/features/series/SeriesTemplatePicker')
  t.after(cleanup)
  const original = globalThis.fetch
  t.after(() => { globalThis.fetch = original })
  let asked = 0
  globalThis.fetch = (async () => { asked++; return new Response(JSON.stringify({ id: 'series_signal', title: 'Signal' }), { status: 200, headers: { 'Content-Type': 'application/json' } }) }) as typeof fetch
  const view = render(<SeriesTemplatePicker onCreate={() => {}} />)
  await waitFor(() => assert.equal(asked, 1))
  assert.ok(view.getByTestId('series-template-picker'))
  assert.equal(view.queryAllByRole('listitem').length, 0)
})
