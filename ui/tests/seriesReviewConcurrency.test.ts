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

test('shot edits and reviews share one queue before either request starts', async t => {
  reset()
  const pending: Array<(value: Response) => void> = []
  t.mock.method(globalThis, 'fetch', () => new Promise<Response>(resolve => pending.push(resolve)))
  const review = useSeriesStore.getState().saveReview('ep1', { mode: 'plan' })
  const edit = useSeriesStore.getState().editShot('ep1', { shot: 's1', changes: { duration: 4 } })
  await tick()
  const concurrent = pending.length
  pending[0](reply(8))
  pending[1]?.(jsonResponse({ revision: 9 }))
  await review
  await tick()
  pending[1](jsonResponse({ revision: 9 }))
  await edit
  assert.equal(concurrent, 1)
  assert.equal(useSeriesStore.getState().serverRevision, 9)
})

test('a late shot edit cannot downgrade revisions or enter another workspace', async t => {
  reset()
  let resolve!: (value: Response) => void
  t.mock.method(globalThis, 'fetch', () => new Promise<Response>(done => { resolve = done }))
  const saving = useSeriesStore.getState().editShot('ep1', { shot: 's1', changes: { duration: 4 } })
  await tick()
  const library = useSeriesStore.getState().library
  useSeriesStore.setState({ serverRevision: 10, library: { ...library, seriesById: { 'mp-es': { ...library.seriesById['mp-es'], revision: 10 } } } })
  resolve(jsonResponse({ revision: 8 }))
  await saving
  assert.equal(useSeriesStore.getState().serverRevision, 10)
  const old = useSeriesStore.getState().editShot('ep1', { shot: 's1', changes: { duration: 5 } })
  await tick()
  useSeriesStore.setState({ workspace: 'two' })
  resolve(jsonResponse({ revision: 11 }))
  await old
  assert.equal(useSeriesStore.getState().serverRevision, 10)
})

test('episode replies and project refreshes keep drafts and reject stale scopes', () => {
  for (const change of ['workspace', 'project', 'dirty', 'revision'] as const) {
    reset()
    const snapshot = useSeriesStore.getState().library.seriesById['mp-es']
    const scope = { workspace: 'one', seriesId: snapshot.id, snapshot }
    const incoming = { ...snapshot.episodesById.ep1, title: 'Remote episode' }
    if (change === 'workspace') useSeriesStore.setState({ workspace: 'two' })
    if (change === 'project') useSeriesStore.setState({ activeSeriesId: 'other' })
    if (change === 'dirty') useSeriesStore.setState({ dirty: true })
    if (change === 'revision') useSeriesStore.setState({ serverRevision: 10, library: { ...useSeriesStore.getState().library,
      seriesById: { 'mp-es': { ...snapshot, revision: 10 } } } })
    const before = useSeriesStore.getState().library.seriesById['mp-es']
    useSeriesStore.getState().acceptEpisode(snapshot.id, incoming, 8, scope)
    useSeriesStore.getState().adoptRemoteSeries({ ...snapshot, revision: 8, title: 'Remote project' }, scope)
    assert.equal(useSeriesStore.getState().library.seriesById['mp-es'], before, change)
    assert.equal(useSeriesStore.getState().dirty, change === 'dirty')
  }
})

test('a queued shot edit stays bound to its original workspace and does not post after switching', async t => {
  reset()
  let resolve!: (value: Response) => void
  const fetch = t.mock.method(globalThis, 'fetch', () => new Promise<Response>(done => { resolve = done }))
  const first = useSeriesStore.getState().saveReview('ep1', { mode: 'plan' })
  const second = useSeriesStore.getState().editShot('ep1', { shot: 's1', changes: { duration: 4 } })
  const rejected = assert.rejects(second, /changed/)
  await tick()
  useSeriesStore.setState({ workspace: 'two' })
  resolve(reply(8))
  await first
  await rejected
  assert.equal(fetch.mock.callCount(), 1)
})

test('an unchanged snapshot accepts the take approval and subsequent project refresh', () => {
  reset()
  const snapshot = useSeriesStore.getState().library.seriesById['mp-es']
  useSeriesStore.getState().acceptEpisode(snapshot.id, { ...snapshot.episodesById.ep1, title: 'Approved take' }, 8,
    { workspace: 'one', seriesId: snapshot.id, snapshot })
  const accepted = useSeriesStore.getState().library.seriesById[snapshot.id]
  assert.equal(accepted.episodesById.ep1.title, 'Approved take')
  assert.equal(useSeriesStore.getState().serverRevision, 8)
  useSeriesStore.getState().adoptRemoteSeries({ ...accepted, title: 'Refreshed', revision: 9 },
    { workspace: 'one', seriesId: snapshot.id, snapshot: accepted })
  assert.equal(useSeriesStore.getState().library.seriesById[snapshot.id].title, 'Refreshed')
  assert.equal(useSeriesStore.getState().serverRevision, 9)
})
