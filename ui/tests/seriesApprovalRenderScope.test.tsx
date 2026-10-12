import assert from 'node:assert/strict'
import test from 'node:test'
import { JSDOM } from 'jsdom'
import { useApprovalRender } from '../src/features/series/useApprovalRender'
import { jsonResponse } from './seriesReviewFixtures'

const dom = new JSDOM('', { url: 'http://localhost/' })
Object.assign(globalThis, { window: dom.window, document: dom.window.document })
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
const job = (episodeId: string, status = 'running') => ({ jobId: `job-${episodeId}`, seriesId: 'series', episodeId, status, items: [], createdAt: 1 })

test('changing episode removes the old job and ignores its outstanding polling reply', async t => {
  const { renderHook, act, waitFor } = await import('@testing-library/react')
  let poll!: () => void, resolve!: (value: Response) => void, reloads = 0
  const cancelled: string[] = []
  t.mock.method(window, 'setInterval', (fn: () => void) => { poll = fn; return 1 })
  t.mock.method(window, 'clearInterval', () => {})
  t.mock.method(globalThis, 'fetch', (input: unknown, init?: RequestInit) => {
    const url = String(input)
    if (url.includes('/recovery')) return Promise.resolve(jsonResponse({ jobs: [job('A')] }))
    if (init?.method === 'POST') { cancelled.push(url); return Promise.resolve(jsonResponse(job('A', 'cancelled'))) }
    return new Promise<Response>(done => { resolve = done })
  })
  const view = renderHook(({ episode }) => useApprovalRender('W', 'series', episode, async () => { reloads++ }), { initialProps: { episode: 'A' } })
  t.after(view.unmount)
  await waitFor(() => assert.equal(view.result.current.job?.episodeId, 'A'))
  act(() => poll())
  view.rerender({ episode: 'B' })
  await act(async () => {})
  const afterSwitch = view.result.current.job
  await act(async () => { resolve(jsonResponse(job('A', 'completed'))) })
  act(() => view.result.current.stop())
  assert.equal(afterSwitch, undefined)
  assert.equal(view.result.current.job, undefined)
  assert.equal(reloads, 0)
  assert.deepEqual(cancelled, [])
})

test('a late start response cannot replace the new episode job or its busy state', async t => {
  const { renderHook, act } = await import('@testing-library/react')
  let resolve!: (value: Response) => void
  t.mock.method(globalThis, 'fetch', (input: unknown, init?: RequestInit) => {
    if (init?.method !== 'POST') return Promise.resolve(jsonResponse({ jobs: [] }))
    if (String(input).includes('/A/')) return new Promise<Response>(done => { resolve = done })
    return Promise.resolve(jsonResponse(job('B')))
  })
  const view = renderHook(({ episode }) => useApprovalRender('W', 'series', episode, async () => {}), { initialProps: { episode: 'A' } })
  t.after(view.unmount)
  await act(async () => {})
  let first!: Promise<void>
  act(() => { first = view.result.current.start() })
  view.rerender({ episode: 'B' })
  await act(async () => { await view.result.current.start() })
  await act(async () => { resolve(jsonResponse(job('A'))); await first })
  assert.equal(view.result.current.job?.episodeId, 'B')
  assert.equal(view.result.current.busy, false)
})
