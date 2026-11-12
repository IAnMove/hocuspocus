import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { episode, series, shot, take } from './seriesReviewFixtures'
import { installDom, installServer } from './seriesInspectorServer'
import type { SeriesEpisodeReview } from '../src/features/series/types'

installDom()

function project(initialReview?: SeriesEpisodeReview) {
  return series(episode([
    shot('s1', 1, { dialogueBeats: [{ id: 'b1', characterId: 'ines', text: 'Excelencia.', emotion: '', delivery: '' }],
      layout2d: { cast: [{ characterId: 'ines', poseId: 'busto', x: 56 }] }, attempts: [take('a1')] }),
    shot('s2', 2, { sceneId: 'scene-2' }),
  ], initialReview))
}

/** The server double first, then the tab on the same series. */
async function mount(t: { after: (fn: () => void) => void }, initialReview?: SeriesEpisodeReview) {
  const { render, cleanup } = await import('@testing-library/react')
  const { useSeriesStore } = await import('../src/features/series/store')
  const { useShotInspector } = await import('../src/features/series/inspector/inspectorStore')
  const { SeriesApprovalPanel } = await import('../src/features/series/SeriesApprovalPanel')
  useShotInspector.setState({ episodes: {} })
  const start = project(initialReview)
  const server = installServer(t, start)
  const ep = start.episodesById.ep1
  useSeriesStore.setState({ workspace: 'plus-ultra', library: { schema: 'series-library', version: 1, workspaceId: 'plus-ultra', seriesOrder: [start.id], seriesById: { [start.id]: start } },
    activeSeriesId: start.id, activeEpisodeId: ep.id, serverRevision: start.revision, dirty: false, saving: false, hydrated: true })
  const faceRig: Array<[string, string | undefined, string | undefined]> = []
  function Live() {
    const current = useSeriesStore(state => state.library.seriesById['mp-es'])
    return <SeriesApprovalPanel workspace="plus-ultra" series={current} episode={current.episodesById.ep1} saveNow={async () => null}
      onOpenFaceRig={(id, pose, shotId) => faceRig.push([id, pose, shotId])} />
  }
  const view = render(<Live />)
  t.after(cleanup)
  return { view, faceRig, store: useSeriesStore, server }
}

test('every shot is a tile grouped by scene; a tile approves its plan, undoes it and opens the shot', { concurrency: false }, async t => {
  const { view, store, server } = await mount(t, { mode: 'plan', shots: {} })
  const { fireEvent, waitFor, within } = await import('@testing-library/react')
  assert.ok(view.getByText('Scene 1 · La nave') && view.getByText(/^Scene 2/))
  const tile = within(view.getByTestId('series-approval-s1'))
  assert.ok(tile.getByText('#1') && tile.getByText('2D') && tile.getByText(/Capitana Inés Valdés:/))
  assert.ok(within(view.getByTestId('series-approval-s2')).getByText('plan only'), 'a shot without a take shows its plan')
  fireEvent.click(tile.getByRole('button', { name: 'Approve plan' }))
  await waitFor(() => assert.ok(tile.getByText('Plan: approved')))
  assert.deepEqual(server.posts('/review')[0], { workspace: 'plus-ultra', shots: [{ shotId: 's1', plan: 'approved' }] })
  assert.equal(store.getState().serverRevision, 8, 'the reply revision becomes the base of the next save')
  fireEvent.click(tile.getByRole('button', { name: 'Undo' }))
  await waitFor(() => assert.deepEqual(server.posts('/review')[1], { workspace: 'plus-ultra', shots: [{ shotId: 's1', plan: 'pending' }] }))
  fireEvent.click(tile.getByRole('button', { name: 'Open' }))
  await waitFor(() => assert.ok(view.getByTestId('series-shot-inspector')))
  assert.ok(view.getByRole('heading', { name: /Shot #1/ }))
  fireEvent.click(view.getByRole('button', { name: 'All shots' }))
  await waitFor(() => assert.ok(view.getByTestId('series-approval-s2')))
})

test('in the inspector, request change marks the plan and the notes box saves as you type, reusing its note id', { concurrency: false }, async t => {
  const { view, server } = await mount(t, { mode: 'plan', shots: {} })
  const { fireEvent, waitFor } = await import('@testing-library/react')
  fireEvent.click(view.getByRole('button', { name: 'Open shot 1' }))
  await waitFor(() => assert.ok(view.getByTestId('series-shot-inspector')))
  fireEvent.click(view.getByRole('button', { name: 'Request change' }))
  await waitFor(() => assert.ok(view.getByText('Plan: changes requested')))
  const box = view.getByLabelText('Your note (plan)')
  assert.equal(document.activeElement, box, 'request change focuses the note')
  fireEvent.change(box, { target: { value: 'Inés más a la izquierda' } })
  await waitFor(() => assert.equal(server.posts('/review').length, 2), { timeout: 3000 })
  assert.deepEqual(server.posts('/review')[1], { workspace: 'plus-ultra', shots: [{ shotId: 's1', note: { text: 'Inés más a la izquierda', stage: 'plan' } }] })
  await waitFor(() => assert.ok(view.getByText('Saved')))
  fireEvent.change(box, { target: { value: 'Inés más a la izquierda, mirando a Rayo' } })
  await waitFor(() => assert.equal(server.posts('/review').length, 3), { timeout: 3000 })
  assert.deepEqual(server.posts('/review')[2], { workspace: 'plus-ultra', shots: [{ shotId: 's1', note: { id: 'note_1', text: 'Inés más a la izquierda, mirando a Rayo', stage: 'plan' } }] })
  // Back in the grid, the filter shows only that shot.
  fireEvent.click(view.getByRole('button', { name: 'All shots' }))
  fireEvent.click(view.getByRole('tab', { name: 'Changes requested (1)' }))
  await waitFor(() => assert.equal(view.queryByTestId('series-approval-s2'), null))
  assert.ok(view.getByTestId('series-approval-s1'))
})

test('the mode selector saves the mode; the inspector re-renders just its shot on the server', { concurrency: false }, async t => {
  const { view, server } = await mount(t)
  const { fireEvent, waitFor } = await import('@testing-library/react')
  fireEvent.click(view.getByRole('radio', { name: 'Plan + preview' }))
  await waitFor(() => assert.deepEqual(server.posts('/review')[0], { workspace: 'plus-ultra', mode: 'preview' }))
  await waitFor(() => assert.equal(view.getByRole('radio', { name: 'Plan + preview' }).getAttribute('aria-checked'), 'true'))
  fireEvent.click(view.getByRole('button', { name: 'Open shot 1' }))
  await waitFor(() => assert.ok(view.getByTestId('series-inspector-regenerate')))
  fireEvent.click(view.getByRole('button', { name: 'Re-render this shot' }))
  await waitFor(() => assert.ok(server.calls.some(call => call.path.endsWith('/native-render'))))
  const started = server.calls.find(call => call.path.endsWith('/native-render'))!
  assert.deepEqual(started.body, { workspace: 'plus-ultra', approve: false, shotIds: ['s1'] })
  assert.equal(started.path, '/series/mp-es/episodes/ep1/native-render')
})

test('re-rendering the shots with changes asks the server for only those', { concurrency: false }, async t => {
  const { view, server } = await mount(t, { mode: 'plan', shots: {} })
  const { fireEvent, waitFor } = await import('@testing-library/react')
  fireEvent.click(view.getByRole('button', { name: 'Re-render shots with changes' }))
  await waitFor(() => assert.ok(server.calls.some(call => call.path.endsWith('/native-render'))))
  assert.deepEqual(server.calls.find(call => call.path.endsWith('/native-render'))!.body, { workspace: 'plus-ultra', approve: false, changed: true })
})

test('a preview is approved with the take it is about; a shot without a take cannot be', { concurrency: false }, async t => {
  const review: SeriesEpisodeReview = { mode: 'preview', shots: { s1: { plan: 'approved', preview: 'pending', notes: [] }, s2: { plan: 'approved', preview: 'pending', notes: [] } } }
  const { view, server } = await mount(t, review)
  const { fireEvent, waitFor, within } = await import('@testing-library/react')
  fireEvent.click(within(view.getByTestId('series-approval-s1')).getByRole('button', { name: 'Approve preview' }))
  await waitFor(() => assert.deepEqual(server.posts('/review')[0], { workspace: 'plus-ultra', shots: [{ shotId: 's1', preview: 'approved', attemptId: 'a1' }] }))
  const second = within(view.getByTestId('series-approval-s2'))
  assert.equal((second.getByRole('button', { name: 'Approve preview' }) as HTMLButtonElement).disabled, true)
})

test('a decision an agent or the Wizard made says so on the tile', { concurrency: false }, async t => {
  const review: SeriesEpisodeReview = { mode: 'plan', shots: {
    s1: { plan: 'approved', planAt: '2026-10-06T10:00:00Z', planBy: 'agent', preview: 'pending', notes: [] },
    s2: { plan: 'changes', planAt: '2026-10-06T10:00:00Z', planBy: 'user', preview: 'pending',
      notes: [{ id: 'note_1', at: '2026-10-06T10:00:00Z', stage: 'plan', text: 'Otro plano', by: 'wizard' }] },
  } }
  const { view } = await mount(t, review)
  const { fireEvent, waitFor, within } = await import('@testing-library/react')
  assert.ok(within(view.getByTestId('series-approval-s1')).getByText('Plan: approved · by an agent'))
  const second = within(view.getByTestId('series-approval-s2'))
  assert.ok(second.getByText('Plan: changes requested'), 'a person’s decision needs no label')
  fireEvent.click(second.getByRole('button', { name: 'Open' }))
  await waitFor(() => assert.ok(view.getByText(/^Wizard ·/)), 'the inspector lists the Wizard’s note')
})

test('arrows go to the next and previous shot and Escape closes; a face rig link names the open shot', { concurrency: false }, async t => {
  const { view, faceRig } = await mount(t)
  const { fireEvent, waitFor, within } = await import('@testing-library/react')
  fireEvent.click(view.getByRole('button', { name: 'Open shot 1' }))
  await waitFor(() => assert.ok(view.getByTestId('series-inspector-s1-cast')))
  fireEvent.click(within(view.getByTestId('series-inspector-s1-cast')).getByRole('button', { name: /Open Capitana Inés Valdés in Characters/ }))
  assert.deepEqual(faceRig, [['ines', 'busto', 's1']])
  fireEvent.keyDown(window, { key: 'ArrowRight' })
  await waitFor(() => assert.ok(view.getByRole('heading', { name: /Shot #2/ })))
  fireEvent.keyDown(window, { key: 'ArrowLeft' })
  await waitFor(() => assert.ok(view.getByRole('heading', { name: /Shot #1/ })))
  fireEvent.keyDown(window, { key: 'Escape' })
  await waitFor(() => assert.equal(view.queryByTestId('series-shot-inspector'), null))
})
