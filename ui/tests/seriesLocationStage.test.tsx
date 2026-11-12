import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'

const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
Object.assign(globalThis, { window: dom.window, document: dom.window.document, localStorage: dom.window.localStorage,
  HTMLElement: dom.window.HTMLElement, Event: dom.window.Event, CustomEvent: dom.window.CustomEvent })
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })

const OFFICE = { horizon: 0.22, ref: { baseY: 0.72, heightPct: 0.62, heightM: 2 } }
const series = { id: 'ls', assets: { plate: { id: 'plate', workspaceId: 'cast', kind: 'image', uri: 'https://example.test/office.png', metadata: {} } } } as never
const location = (stage?: unknown) => ({ id: 'office', name: 'Office', referenceAssetIds: ['plate'], layout2d: stage ? { stage } : {} }) as never

type Request = { method: string; url: string; body?: Record<string, unknown> }
function mockFetch(t: { after: (fn: () => void) => void }, replies: Array<unknown | { status: number; body: unknown }>) {
  const requests: Request[] = []
  const original = globalThis.fetch
  t.after(() => { globalThis.fetch = original })
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    requests.push({ method: init?.method ?? 'GET', url: String(input).replace(/^.*\/api\/v1/, ''), body: init?.body ? JSON.parse(String(init.body)) : undefined })
    const reply = replies.shift() as { status?: number; body?: unknown } | undefined
    const failing = reply && typeof reply === 'object' && 'status' in reply && 'body' in reply
    return new Response(JSON.stringify(failing ? reply!.body : reply), { status: failing ? reply!.status : 200, headers: { 'Content-Type': 'application/json' } })
  }) as typeof fetch
  return requests
}

async function mount(t: { after: (fn: () => void) => void }, stage?: unknown) {
  const testing = await import('@testing-library/react')
  const { SeriesLocationStage } = await import('../src/features/series/SeriesLocationStage')
  const { useSeriesStore } = await import('../src/features/series/store')
  t.after(testing.cleanup)
  const counter = { reloaded: 0 }
  useSeriesStore.setState({ reload: async () => { counter.reloaded++ } })
  return { ...testing, counter, view: testing.render(<SeriesLocationStage workspace="cast" series={series} location={location(stage)} />) }
}

const fill = (fireEvent: (typeof import('@testing-library/react'))['fireEvent'], view: ReturnType<(typeof import('@testing-library/react'))['render']>,
  values: Record<string, string>) => { for (const [label, value] of Object.entries(values)) fireEvent.change(view.getByLabelText(label), { target: { value } }) }

test('the numbers move the overlay lines over the plate as percentages and save posts them to the stage route', async t => {
  const requests = mockFetch(t, [{ locationId: 'office', stage: OFFICE, affectedShots: ['s1', 's3'], revision: 4 }])
  const { view, fireEvent, waitFor, counter } = await mount(t)
  assert.equal((view.getByRole('button', { name: 'Save stage' }) as HTMLButtonElement).disabled, true, 'nothing to save yet')
  assert.equal((view.getByLabelText('Reference height (m)') as HTMLInputElement).value, '2', 'a door by default')
  fill(fireEvent, view, { 'Horizon (eye line)': '0.22', 'Reference foot (y)': '0.72', 'Reference height (fraction)': '0.62' })
  const top = (id: string) => (view.getByTestId(`stage-line-${id}`) as HTMLElement).style.top
  assert.deepEqual([top('horizon'), top('base'), top('top')], ['22%', '72%', '10%'])
  assert.ok(view.getByText('These numbers put the camera 1.61 m high (about 1.6 m is eye level).'), 'the camera height the numbers imply')
  assert.equal(view.queryByTestId('stage-line-floor'), null, 'no far floor, no line')
  fill(fireEvent, view, { 'Far floor (y, optional)': '0.6' })
  assert.equal(top('floor'), '60%')
  fill(fireEvent, view, { 'Far floor (y, optional)': '' })
  fireEvent.click(view.getByRole('button', { name: 'Save stage' }))
  await waitFor(() => assert.ok(view.getByText('Stage saved. 2 2D shots in this location will render again.')))
  assert.deepEqual(requests, [{ method: 'POST', url: '/series/ls/locations/office/stage', body: { workspace: 'cast', horizon: 0.22, ref: { baseY: 0.72, heightPct: 0.62, heightM: 2 } } }])
  assert.equal(counter.reloaded, 1, 'the open series is reloaded')
})

test('a stage the server would refuse is not sent and says what is wrong', async t => {
  const requests = mockFetch(t, [])
  const { view, fireEvent } = await mount(t)
  fill(fireEvent, view, { 'Horizon (eye line)': '0.5', 'Reference foot (y)': '0.72', 'Reference height (fraction)': '0.62' })
  assert.ok(view.getByText(/put the camera 0\.71 m high; eye level is about 1\.6 m\. Re-read the horizon/), 'an odd camera height is flagged, not blocked')
  assert.equal((view.getByRole('button', { name: 'Save stage' }) as HTMLButtonElement).disabled, false)
  fill(fireEvent, view, { 'Horizon (eye line)': '0.8', 'Reference foot (y)': '0.72', 'Reference height (fraction)': '0.62' })
  assert.ok(view.getByText('The reference foot must be below the horizon.'))
  assert.equal((view.getByRole('button', { name: 'Save stage' }) as HTMLButtonElement).disabled, true)
  fill(fireEvent, view, { 'Horizon (eye line)': '0.2', 'Far floor (y, optional)': '0.1' })
  assert.ok(view.getByText('The far floor must be below the horizon (0 to 1).'))
  fill(fireEvent, view, { 'Far floor (y, optional)': '', 'Reference height (fraction)': '' })
  assert.ok(view.getByText('Reference height (fraction) is missing or out of range.'))
  assert.deepEqual(requests, [])
})

test('looking at the grid sends the numbers as a proposal, shows the image and lets the horizon guess fill the field', async t => {
  const grid = { locationId: 'office', plate: { file: 'day.png', width: 1920, height: 1088 }, grid: { file: 'stage-check-office-ab.png', url: '/api/v1/file/stage-check-office-ab.png?workspace=cast', step: 0.1, width: 1280, height: 725 },
    stage: null, proposal: OFFICE, how: 'LOOK', suggestion: { suggestion: { horizon: 0.31, kind: 'converging_lines', confidence: 'medium' }, note: 'A guess' } }
  const requests = mockFetch(t, [grid])
  const { view, fireEvent, waitFor } = await mount(t, OFFICE)
  fireEvent.click(view.getByRole('button', { name: 'Look at the grid' }))
  await waitFor(() => assert.ok(view.getByTestId('stage-grid')))
  assert.deepEqual(requests, [{ method: 'POST', url: '/series/ls/locations/office/stage/check', body: { workspace: 'cast', horizon: 0.22, ref: { baseY: 0.72, heightPct: 0.62, heightM: 2 } } }])
  assert.match((view.getByTestId('stage-grid') as HTMLImageElement).src, /stage-check-office-ab\.png\?workspace=cast$/)
  assert.ok(view.getByText('Horizon guess 0.31 (confidence medium).'))
  assert.ok(view.getByText(/Only a guess: a room has no visible horizon/))
  fireEvent.click(view.getByRole('button', { name: 'Use as horizon' }))
  assert.equal((view.getByLabelText('Horizon (eye line)') as HTMLInputElement).value, '0.31', 'only the field changes: nothing is saved')
  assert.equal(requests.length, 1)
})

test('a saved stage fills the form and can be removed; a server error is shown', async t => {
  const requests = mockFetch(t, [{ status: 422, body: { detail: { code: 'invalid_stage', message: 'stage.horizon must be a number from 0 to 0.95' } } },
    { locationId: 'office', stage: null, affectedShots: ['s1'], revision: 5 }])
  const { view, fireEvent, waitFor, counter } = await mount(t, { ...OFFICE, floorTop: 0.6 })
  assert.equal((view.getByLabelText('Far floor (y, optional)') as HTMLInputElement).value, '0.6')
  assert.equal((view.getByTestId('stage-line-floor') as HTMLElement).style.top, '60%')
  fireEvent.click(view.getByRole('button', { name: 'Save stage' }))
  await waitFor(() => assert.ok(view.getByText(/stage\.horizon must be a number from 0 to 0\.95/)))
  fireEvent.click(view.getByRole('button', { name: 'Remove stage' }))
  await waitFor(() => assert.ok(view.getByText('Stage removed: shots are sized by their framing again.')))
  assert.deepEqual(requests[1], { method: 'POST', url: '/series/ls/locations/office/stage', body: { workspace: 'cast', clear: true } })
  assert.equal((view.getByLabelText('Horizon (eye line)') as HTMLInputElement).value, '')
  assert.equal(counter.reloaded, 1)
})
