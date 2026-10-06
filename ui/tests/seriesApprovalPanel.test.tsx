import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'
import { episode, jsonResponse, series, shot, take } from './seriesReviewFixtures'
import type { SeriesEpisodeReview, SeriesReviewChange } from '../src/features/series/types'

const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
Object.assign(globalThis, { window: dom.window, document: dom.window.document, localStorage: dom.window.localStorage, sessionStorage: dom.window.sessionStorage,
  HTMLElement: dom.window.HTMLElement, Event: dom.window.Event, CustomEvent: dom.window.CustomEvent, MutationObserver: dom.window.MutationObserver })
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })

type Call = { method: string; path: string; body?: Record<string, unknown> }

/** A server double: applies review changes to its own review and answers like the real endpoint. */
function installServer(t: { after: (fn: () => void) => void }, initial: SeriesEpisodeReview = { mode: 'direct', shots: {} }) {
  const calls: Call[] = []
  const review: SeriesEpisodeReview = structuredClone(initial)
  let revision = 7, noteCount = 0
  const original = globalThis.fetch
  t.after(() => { globalThis.fetch = original })
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input), path = url.replace(/^.*\/api\/v1/, '').split('?')[0]
    const body = init?.body ? JSON.parse(String(init.body)) : undefined
    calls.push({ method: init?.method ?? 'GET', path, body })
    if (path === '/series/native-render/recovery') return jsonResponse({ jobs: [] })
    if (path.endsWith('/native-render')) return jsonResponse({ jobId: 'native-9', seriesId: 'mp-es', episodeId: 'ep1', current: 0, total: 1, status: 'queued', mode: review.mode, waiting: [], items: [{ shotId: 's1', stage: 'voices', status: 'queued', pass: 'preview' }] })
    if (path.endsWith('/review')) {
      const change = body as SeriesReviewChange
      if (change.mode) review.mode = change.mode
      const noteIds: Record<string, string> = {}
      for (const item of change.shots || []) {
        const entry = review.shots[item.shotId] ??= { plan: 'pending', preview: 'pending', notes: [] }
        if (item.plan) entry.plan = item.plan
        if (item.preview) { entry.preview = item.preview; if (entry.plan !== 'approved' && item.preview === 'approved') entry.plan = 'approved' }
        if (item.note) {
          const id = item.note.id || `note_${++noteCount}`
          entry.notes = entry.notes.filter(note => note.id !== id)
          if (item.note.text) entry.notes.push({ id, at: '2026-10-06T10:00:00Z', stage: item.note.stage || 'plan', text: item.note.text, by: 'user' })
          noteIds[item.shotId] = id
        }
      }
      revision += 1
      return jsonResponse({ revision, episodeId: 'ep1', episodeUpdatedAt: `2026-10-06T10:00:0${revision % 10}Z`, review: structuredClone(review), noteIds })
    }
    return jsonResponse({ outputs: [], total: 0, kits: {} })
  }) as typeof fetch
  return { calls, posts: () => calls.filter(call => call.method === 'POST' && call.path.endsWith('/review')).map(call => call.body) }
}

async function mount(initialReview?: SeriesEpisodeReview) {
  const { render, cleanup } = await import('@testing-library/react')
  const { useSeriesStore } = await import('../src/features/series/store')
  const { SeriesApprovalPanel } = await import('../src/features/series/SeriesApprovalPanel')
  const ep = episode([
    shot('s1', 1, { dialogueBeats: [{ id: 'b1', characterId: 'ines', text: 'Excelencia.', emotion: '', delivery: '' }],
      layout2d: { cast: [{ characterId: 'ines', poseId: 'busto', x: 56 }] }, attempts: [take('a1')] }),
    shot('s2', 2, { sceneId: 'scene-2' }),
  ], initialReview)
  const project = series(ep)
  useSeriesStore.setState({ workspace: 'plus-ultra', library: { schema: 'series-library', version: 1, workspaceId: 'plus-ultra', seriesOrder: [project.id], seriesById: { [project.id]: project } },
    activeSeriesId: project.id, activeEpisodeId: ep.id, serverRevision: project.revision, dirty: false, saving: false, hydrated: true })
  const faceRig: Array<[string, string | undefined]> = []
  function Live() {
    const current = useSeriesStore(state => state.library.seriesById['mp-es'])
    return <SeriesApprovalPanel workspace="plus-ultra" series={current} episode={current.episodesById.ep1} reload={async () => {}}
      updateEpisode={() => {}} saveNow={async () => null} onOpenFaceRig={(id, pose) => faceRig.push([id, pose])} />
  }
  return { view: render(<Live />), cleanup, faceRig, store: useSeriesStore }
}

test('approving a plan posts it, shows it and can be undone; the face rig link names the shot pose', { concurrency: false }, async t => {
  const server = installServer(t, { mode: 'plan', shots: {} })
  const { view, cleanup, faceRig, store } = await mount({ mode: 'plan', shots: {} })
  t.after(cleanup)
  const { fireEvent, waitFor, within } = await import('@testing-library/react')
  const card = within(view.getByTestId('series-approval-s1'))
  assert.match(view.getByText(/Approve the plan of 2 shots/).textContent || '', /2 shots/)
  fireEvent.click(card.getByRole('button', { name: 'Approve plan' }))
  await waitFor(() => assert.ok(card.getByText('Plan: approved')))
  assert.deepEqual(server.posts()[0], { workspace: 'plus-ultra', shots: [{ shotId: 's1', plan: 'approved' }] })
  assert.equal(store.getState().serverRevision, 8, 'the reply revision becomes the base of the next save')
  fireEvent.click(card.getByRole('button', { name: 'Undo' }))
  await waitFor(() => assert.deepEqual(server.posts()[1], { workspace: 'plus-ultra', shots: [{ shotId: 's1', plan: 'pending' }] }))
  fireEvent.click(card.getByRole('button', { name: /Open Capitana Inés Valdés's mouth/ }))
  assert.deepEqual(faceRig, [['ines', 'busto']])
})

test('request change marks the plan and the notes box saves as you type, reusing its note id', { concurrency: false }, async t => {
  const server = installServer(t, { mode: 'plan', shots: {} })
  const { view, cleanup } = await mount({ mode: 'plan', shots: {} })
  t.after(cleanup)
  const { fireEvent, waitFor, within } = await import('@testing-library/react')
  const card = within(view.getByTestId('series-approval-s1'))
  fireEvent.click(card.getByRole('button', { name: 'Request change' }))
  await waitFor(() => assert.ok(card.getByText('Plan: changes requested')))
  const box = card.getByLabelText('Your note (plan)')
  assert.equal(document.activeElement, box, 'request change focuses the note')
  fireEvent.change(box, { target: { value: 'Inés más a la izquierda' } })
  await waitFor(() => assert.equal(server.posts().length, 2), { timeout: 3000 })
  assert.deepEqual(server.posts()[1], { workspace: 'plus-ultra', shots: [{ shotId: 's1', note: { text: 'Inés más a la izquierda', stage: 'plan' } }] })
  await waitFor(() => assert.ok(card.getByText('Saved')))
  fireEvent.change(box, { target: { value: 'Inés más a la izquierda, mirando a Rayo' } })
  await waitFor(() => assert.equal(server.posts().length, 3), { timeout: 3000 })
  assert.deepEqual(server.posts()[2], { workspace: 'plus-ultra', shots: [{ shotId: 's1', note: { id: 'note_1', text: 'Inés más a la izquierda, mirando a Rayo', stage: 'plan' } }] })
  // The filter shows only that shot.
  fireEvent.click(view.getByRole('tab', { name: 'Changes requested (1)' }))
  await waitFor(() => assert.equal(view.queryByTestId('series-approval-s2'), null))
  assert.ok(view.getByTestId('series-approval-s1'))
})

test('the mode selector saves the mode; re-render posts the shot to the server render', { concurrency: false }, async t => {
  const server = installServer(t)
  const { view, cleanup } = await mount()
  t.after(cleanup)
  const { fireEvent, waitFor, within } = await import('@testing-library/react')
  fireEvent.click(view.getByRole('radio', { name: 'Plan + preview' }))
  await waitFor(() => assert.deepEqual(server.posts()[0], { workspace: 'plus-ultra', mode: 'preview' }))
  await waitFor(() => assert.equal(view.getByRole('radio', { name: 'Plan + preview' }).getAttribute('aria-checked'), 'true'))
  fireEvent.click(within(view.getByTestId('series-approval-s1')).getByRole('button', { name: 'Re-render this shot' }))
  await waitFor(() => assert.ok(server.calls.some(call => call.path.endsWith('/native-render'))))
  const started = server.calls.find(call => call.path.endsWith('/native-render'))!
  assert.deepEqual(started.body, { workspace: 'plus-ultra', approve: false, shotIds: ['s1'] })
  assert.equal(started.path, '/series/mp-es/episodes/ep1/native-render')
})

test('re-rendering the shots with changes asks the server for only those', { concurrency: false }, async t => {
  const server = installServer(t, { mode: 'plan', shots: {} })
  const { view, cleanup } = await mount({ mode: 'plan', shots: {} })
  t.after(cleanup)
  const { fireEvent, waitFor } = await import('@testing-library/react')
  fireEvent.click(view.getByRole('button', { name: 'Re-render shots with changes' }))
  await waitFor(() => assert.ok(server.calls.some(call => call.path.endsWith('/native-render'))))
  assert.deepEqual(server.calls.find(call => call.path.endsWith('/native-render'))!.body, { workspace: 'plus-ultra', approve: false, changed: true })
})

test('a preview is approved with the take it is about', { concurrency: false }, async t => {
  const server = installServer(t, { mode: 'preview', shots: { s1: { plan: 'approved', preview: 'pending', notes: [] } } })
  const { view, cleanup } = await mount({ mode: 'preview', shots: { s1: { plan: 'approved', preview: 'pending', notes: [] } } })
  t.after(cleanup)
  const { fireEvent, waitFor, within } = await import('@testing-library/react')
  const card = within(view.getByTestId('series-approval-s1'))
  fireEvent.click(card.getByRole('button', { name: 'Approve preview' }))
  await waitFor(() => assert.deepEqual(server.posts()[0], { workspace: 'plus-ultra', shots: [{ shotId: 's1', preview: 'approved', attemptId: 'a1' }] }))
  // Shot 2 has no take yet: its preview cannot be approved until it renders.
  const second = within(view.getByTestId('series-approval-s2'))
  assert.ok(second.getByText('No preview yet'))
})

test('a decision an agent or the Wizard made says so on the card', { concurrency: false }, async t => {
  const review: SeriesEpisodeReview = { mode: 'plan', shots: {
    s1: { plan: 'approved', planAt: '2026-10-06T10:00:00Z', planBy: 'agent', preview: 'pending', notes: [] },
    s2: { plan: 'changes', planAt: '2026-10-06T10:00:00Z', planBy: 'user', preview: 'pending',
      notes: [{ id: 'note_1', at: '2026-10-06T10:00:00Z', stage: 'plan', text: 'Otro plano', by: 'wizard' }] },
  } }
  installServer(t, review)
  const { view, cleanup } = await mount(review)
  t.after(cleanup)
  const { within } = await import('@testing-library/react')
  assert.ok(within(view.getByTestId('series-approval-s1')).getByText('Plan: approved · by an agent'))
  const second = within(view.getByTestId('series-approval-s2'))
  assert.ok(second.getByText('Plan: changes requested'), 'a person’s decision needs no label')
  assert.ok(second.getByText(/^Wizard ·/))
})
