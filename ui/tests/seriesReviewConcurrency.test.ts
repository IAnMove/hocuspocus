import assert from 'node:assert/strict'
import test from 'node:test'
import { JSDOM } from 'jsdom'
import { episode, jsonResponse, series, shot } from './seriesReviewFixtures'
import { useSeriesStore } from '../src/features/series/store'

const dom = new JSDOM('', { url: 'http://localhost/' })
Object.assign(globalThis, { window: dom.window, document: dom.window.document })
const tick = () => new Promise(resolve => setImmediate(resolve))

function reset() {
  const project = series(episode([shot('s1', 1)]))
  useSeriesStore.setState({ workspace: 'one', activeSeriesId: project.id, activeEpisodeId: 'ep1', dirty: false, saving: false,
    serverRevision: 7, library: { schema: 'series-library', version: 1, workspaceId: 'one', seriesOrder: [project.id], seriesById: { [project.id]: project } } })
}

function reply(revision: number) {
  return jsonResponse({ revision, episodeId: 'ep1', review: { mode: 'plan', shots: {} }, noteIds: {} })
}

test('simultaneous review changes reserve their turn before awaiting autosave', async t => {
  reset()
  const pending: Array<(value: Response) => void> = []
  t.mock.method(globalThis, 'fetch', () => new Promise<Response>(resolve => pending.push(resolve)))
  const first = useSeriesStore.getState().saveReview('ep1', { mode: 'plan' })
  const second = useSeriesStore.getState().saveReview('ep1', { mode: 'preview' })
  await tick()
  const concurrent = pending.length
  pending[0](reply(8))
  if (concurrent > 1) pending[1](reply(9))
  await first
  await tick()
  pending[1](reply(9))
  await second
  assert.equal(concurrent, 1)
  assert.equal(useSeriesStore.getState().serverRevision, 9)
})

test('a late review cannot downgrade a newer project or write into a different workspace', async t => {
  reset()
  let resolve!: (value: Response) => void
  t.mock.method(globalThis, 'fetch', () => new Promise<Response>(done => { resolve = done }))
  const saving = useSeriesStore.getState().saveReview('ep1', { mode: 'plan' })
  await tick()
  const current = useSeriesStore.getState().library
  useSeriesStore.setState({ serverRevision: 10, library: { ...current, seriesById: { 'mp-es': { ...current.seriesById['mp-es'], revision: 10 } } } })
  resolve(reply(8))
  await saving
  assert.equal(useSeriesStore.getState().serverRevision, 10)
  const old = useSeriesStore.getState().saveReview('ep1', { mode: 'plan' })
  await tick()
  useSeriesStore.setState({ workspace: 'two' })
  resolve(reply(11))
  await old
  assert.equal(useSeriesStore.getState().serverRevision, 10)
})

test('a queued review does not retarget the project selected during the wait', async t => {
  reset()
  const pending: Array<(value: Response) => void> = []
  t.mock.method(globalThis, 'fetch', () => new Promise<Response>(resolve => pending.push(resolve)))
  const first = useSeriesStore.getState().saveReview('ep1', { mode: 'plan' })
  const second = useSeriesStore.getState().saveReview('ep1', { mode: 'preview' })
  const rejected = assert.rejects(second, /changed/)
  await tick()
  useSeriesStore.setState({ workspace: 'two' })
  pending[0](reply(8))
  pending[1]?.(reply(9))
  await first
  // Drain the old implementation too, so a failed assertion cannot leave a save hanging.
  await tick()
  pending[1]?.(reply(9))
  await rejected
  assert.equal(pending.length, 1)
})

test('an unmount flush bound to another workspace is rejected before posting', async t => {
  reset()
  const fetch = t.mock.method(globalThis, 'fetch', async () => reply(8))
  await assert.rejects(useSeriesStore.getState().saveReview('ep1', { mode: 'plan' }, { workspace: 'old', seriesId: 'mp-es' }), /changed/)
  assert.equal(fetch.mock.callCount(), 0)
  await useSeriesStore.getState().saveReview('ep1', { mode: 'plan' })
  assert.equal(fetch.mock.callCount(), 1, 'a rejected queue entry does not block the next save')
})
