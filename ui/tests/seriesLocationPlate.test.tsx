import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'

const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
Object.assign(globalThis, { window: dom.window, document: dom.window.document, localStorage: dom.window.localStorage,
  HTMLElement: dom.window.HTMLElement, Event: dom.window.Event, CustomEvent: dom.window.CustomEvent })
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })

test('a location renders a saved Video 3D scene as its 2D background and reloads when it is ready', async t => {
  const { render, fireEvent, cleanup, waitFor } = await import('@testing-library/react')
  const { SeriesLocationPlate } = await import('../src/features/series/SeriesLocationPlate')
  const { useSeriesStore } = await import('../src/features/series/store')
  t.after(cleanup)
  let reloaded = 0
  useSeriesStore.setState({ reload: async () => { reloaded++ } })
  const requests: { method: string; url: string; body?: Record<string, unknown> }[] = []
  const replies = [{ locationId: 'lab', status: 'rendering', progress: 0.5 }, { locationId: 'lab', status: 'done', assetId: 'a1' }]
  const original = globalThis.fetch
  t.after(() => { globalThis.fetch = original })
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input).replace(/^.*\/api\/v1/, '')
    const body = init?.body ? JSON.parse(String(init.body)) as Record<string, unknown> : undefined
    requests.push({ method: init?.method ?? 'GET', url, body })
    const reply = url.startsWith('/outputs') ? { outputs: [{ name: 'lab-orbit.world3d.scene.json', url: '/x', type: 'scene' }, { name: 'cut.scene.json', url: '/y', type: 'scene' }], total: 2 }
      : init?.method === 'POST' ? { locationId: 'lab', status: 'rendering', progress: 0 }
        : requests.filter(item => item.url.includes('/plate3d') && item.method === 'GET').length === 1 ? { locationId: 'lab', status: 'none' } : replies.shift()
    return new Response(JSON.stringify(reply), { status: 200, headers: { 'Content-Type': 'application/json' } })
  }) as typeof fetch
  const series = { id: 'uv' } as never
  const location = { id: 'lab', name: 'Lab' } as never

  const view = render(<SeriesLocationPlate workspace="cast" series={series} location={location} pollMs={5} />)
  const picker = view.getByLabelText('Video 3D scene') as HTMLSelectElement
  await waitFor(() => assert.equal(picker.options.length, 2), 'only Video 3D scenes are offered')
  assert.equal((view.getByRole('button', { name: 'Render 3D background' }) as HTMLButtonElement).disabled, true)
  fireEvent.change(picker, { target: { value: 'lab-orbit.world3d.scene.json' } })
  fireEvent.change(view.getByLabelText('Loop (s)'), { target: { value: '8' } })
  fireEvent.click(view.getByRole('button', { name: 'Render 3D background' }))
  await waitFor(() => assert.ok(view.getByText('3D background ready: 2D shots in this location use it.')))
  assert.deepEqual(requests.find(item => item.method === 'POST')!.body, { workspace: 'cast', scene: 'lab-orbit.world3d.scene.json', seconds: 8 })
  assert.equal(requests.find(item => item.method === 'POST')!.url, '/series/uv/locations/lab/plate3d')
  assert.equal(reloaded, 1)
})
