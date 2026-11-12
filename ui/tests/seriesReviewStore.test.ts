import assert from 'node:assert/strict'
import test from 'node:test'
import { JSDOM } from 'jsdom'
import { episode, jsonResponse, series, shot } from './seriesReviewFixtures'

const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
Object.assign(globalThis, { window: dom.window, document: dom.window.document, localStorage: dom.window.localStorage })

test('a review reply merges into the episode without dropping an edit made while it was in flight', async t => {
  const { useSeriesStore } = await import('../src/features/series/store')
  const project = series(episode([shot('s1', 1)]))
  useSeriesStore.setState({ workspace: 'plus-ultra', library: { schema: 'series-library', version: 1, workspaceId: 'plus-ultra', seriesOrder: [project.id], seriesById: { [project.id]: project } },
    activeSeriesId: project.id, activeEpisodeId: 'ep1', serverRevision: 7, dirty: false, saving: false })
  const calls: Array<{ method: string; path: string; body: Record<string, unknown> }> = []
  let answer: (() => void) | undefined
  const original = globalThis.fetch
  t.after(() => { globalThis.fetch = original })
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input).replace(/^.*\/api\/v1/, '')
    const body = JSON.parse(String(init?.body || '{}'))
    calls.push({ method: init?.method || 'GET', path, body })
    if (path.endsWith('/review')) {
      await new Promise<void>(resolve => { answer = resolve })
      return jsonResponse({ revision: 8, episodeId: 'ep1', episodeUpdatedAt: '2026-10-06T11:00:00Z', noteIds: {},
        review: { mode: 'plan', shots: { s1: { plan: 'approved', preview: 'pending', notes: [] } } } })
    }
    // The autosave after the reply: it must be based on the reply's revision.
    return jsonResponse({ ...body.series, revision: Number(body.baseRevision) + 1 })
  }) as typeof fetch

  const saving = useSeriesStore.getState().saveReview('ep1', { mode: 'plan', shots: [{ shotId: 's1', plan: 'approved' }] })
  await new Promise(resolve => setTimeout(resolve, 10))
  useSeriesStore.getState().updateSeries(current => ({ ...current, title: 'Más allá del Plan (montaje)' }))
  // An autosave asked for now waits for the review instead of racing it with revision 7.
  const autosave = useSeriesStore.getState().saveNow()
  answer?.()
  const reply = await saving
  await autosave
  assert.equal(reply.revision, 8)
  const state = useSeriesStore.getState()
  const stored = state.library.seriesById['mp-es']
  assert.equal(stored.title, 'Más allá del Plan (montaje)', 'the local edit survives the merge')
  assert.equal(stored.episodesById.ep1.review?.shots.s1.plan, 'approved')
  const put = calls.find(call => call.method === 'PUT')
  assert.ok(put, 'the edit is saved after the review')
  assert.equal(put!.body.baseRevision, 8)
  assert.equal(calls.filter(call => call.method === 'PUT').length, 1)
  assert.equal(state.dirty, false)
})
