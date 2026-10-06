import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { createCharacterKit } from '../src/lib/characterKit.ts'
import { episode, series, shot, take } from './seriesReviewFixtures'
import { installDom, installServer } from './seriesInspectorServer'
import type { SeriesProject, SeriesShot } from '../src/features/series/types'

installDom()

const image = (id: string) => ({ id, name: id, source: `/${id}.png`, kind: 'image' as const, alphaStatus: 'transparent' as const, reviewState: 'approved' as const })
const KITS = { version: 1, revision: 3, kits: { 'mp-ines': { ...createCharacterKit('Inés'), id: 'mp-ines', base: image('base'), poses: { busto: image('busto'), perfil: image('perfil') } } } }
const RIFLE = { objectId: 'f1', file: 'fusil.glb', add: true, scale: 0.16, hold: { carrier: 'e1', hand: 'right' } }

function shots(): SeriesShot[] {
  return [
    shot('s1', 1, { dialogueBeats: [{ id: 's1_b0', characterId: 'ines', text: 'Excelencia.', emotion: '', delivery: 'firme' }],
      layout2d: { cast: [{ characterId: 'ines', poseId: 'busto', x: 56 }], sfx: [{ file: 'sfx-boom.wav', at: 0.4, volume: 0.8 }],
        fx: [{ kind: 'vignette', at: 0, duration: 30, intensity: 0.5 }] }, attempts: [take('a1', { completedAt: '2026-10-06T10:00:00Z' })] }),
    shot('s2', 2, { productionMethod: 'animation_3d', durationSeconds: 5, dialogueBeats: [], visibleCharacterIds: [],
      scene3d: { template: 'user-plaga', cast: [], objects: [{ objectId: 'e1', file: 'escolta.glb', add: true, clips: [{ clip: 'Aim', start: 0 }] }, RIFLE], quality: 'final' } }),
    shot('s3', 3, { productionMethod: 'imported_video', durationSeconds: 5.2, attempts: [take('a3')], layout2d: { sfx: [] } }),
  ]
}

async function mount(t: { after: (fn: () => void) => void }, options: { editorDocument?: unknown } = {}) {
  const { render, cleanup } = await import('@testing-library/react')
  const { useSeriesStore } = await import('../src/features/series/store')
  const { useStore } = await import('../src/stores/useStore')
  const { useShotInspector } = await import('../src/features/series/inspector/inspectorStore')
  const { SeriesApprovalPanel } = await import('../src/features/series/SeriesApprovalPanel')
  useShotInspector.setState({ episodes: {} })
  const project: SeriesProject = series(episode(shots()))
  const server = installServer(t, project, { kits: KITS, ...options })
  useStore.setState({ activeWorkspace: 'plus-ultra', mediaFilter: 'series' })
  useSeriesStore.setState({ workspace: 'plus-ultra', library: { schema: 'series-library', version: 1, workspaceId: 'plus-ultra', seriesOrder: [project.id], seriesById: { [project.id]: project } },
    activeSeriesId: project.id, activeEpisodeId: 'ep1', serverRevision: project.revision, dirty: false, saving: false, hydrated: true })
  function Live() {
    const current = useSeriesStore(state => state.library.seriesById['mp-es'])
    return <SeriesApprovalPanel workspace="plus-ultra" series={current} episode={current.episodesById.ep1} saveNow={async () => null} onOpenFaceRig={() => {}} />
  }
  const view = render(<Live />)
  t.after(cleanup)
  return { view, server, store: useSeriesStore }
}

async function open(view: Awaited<ReturnType<typeof mount>>['view'], order: number) {
  const { fireEvent, waitFor } = await import('@testing-library/react')
  fireEvent.click(view.getByRole('button', { name: `Open shot ${order}` }))
  await waitFor(() => assert.ok(view.getByTestId('series-shot-inspector')))
}

test('the model sends only what a part changed, keeps an empty own layer list and says what a render regenerates', async () => {
  const { regeneration, sectionChanges, shotParts, planCast } = await import('../src/features/series/inspector/model')
  const script = { lines: [{ who: 'ines', spanish: 'Hola' }], layers: [{ file: 'a.png' }], sfx: [{ file: 'b.wav' }] }
  assert.equal(sectionChanges('lines', { lines: [{ who: 'ines', spanish: 'Hola' }] }, script), null)
  assert.deepEqual(sectionChanges('lines', { lines: [{ who: 'ines', spanish: 'Adiós' }] }, script), { lines: [{ who: 'ines', spanish: 'Adiós' }] })
  assert.deepEqual(sectionChanges('sfx', { sfx: [] }, script), { sfx: null }, 'an emptied list removes the key')
  assert.deepEqual(sectionChanges('set', { layers: [] }, script), { layers: [] }, 'an empty own layer list turns the location layers off')
  assert.deepEqual(sectionChanges('set', {}, script), { layers: null })
  const [two, three, video] = shots()
  assert.deepEqual(shotParts(two, {}), ['cast', 'lines', 'set', 'props', 'fx', 'sfx', 'sound', 'plan', 'takes'])
  assert.deepEqual(shotParts(three, {}).slice(0, 2), ['scene3d', 'cast3d'])
  assert.deepEqual(shotParts(video, {}), ['video', 'lines', 'set', 'sfx', 'sound', 'takes'])
  const line = { beatId: 's1_b0', number: 1, characterId: 'ines', text: 'x', recorded: false, voice: true }
  const fresh = regeneration(two, [line], undefined)
  assert.equal(fresh.renders, true)
  assert.deepEqual(fresh.record.map(item => item.beatId), ['s1_b0'])
  assert.equal(fresh.stale, false, 'nothing changed after its take')
  assert.equal(regeneration(two, [], Date.parse('2026-10-06T11:00:00Z')).stale, true, 'edited after its take')
  assert.equal(regeneration(two, [{ ...line, recorded: true, newerThanTake: true }], undefined).stale, true, 'a line recorded after the take')
  assert.equal(regeneration(video, [], undefined).renders, false, 'a video take gets its sound at the cut')
  const project = series(episode(shots()))
  const kits = KITS as never
  assert.deepEqual(planCast(project, two, kits).map(figure => [figure.name, figure.src, figure.x]), [['Capitana Inés Valdés', '/busto.png', 56]])
})

test('a line is edited in place and saved through the shot edit; the shot is merged and asks to be rendered again', { concurrency: false }, async t => {
  const { view, server, store } = await mount(t)
  const { fireEvent, waitFor, within } = await import('@testing-library/react')
  await open(view, 1)
  const lines = within(await waitFor(() => view.getByTestId('series-inspector-s1-lines')))
  await waitFor(() => assert.ok(lines.getByText('Excelencia.')))
  assert.ok(lines.getByText(/firme/), 'the delivery is shown with the line')
  fireEvent.click(lines.getByRole('button', { name: 'Edit' }))
  fireEvent.change(lines.getByLabelText('Text (Spanish)'), { target: { value: 'Excelencia, la nave es suya.' } })
  assert.ok(lines.getByText('unsaved'))
  fireEvent.click(lines.getByRole('button', { name: 'Save' }))
  await waitFor(() => assert.equal(server.posts('/shots/edit').length, 1))
  assert.deepEqual(server.posts('/shots/edit')[0], { workspace: 'plus-ultra', shot: 's1', stored: true,
    changes: { lines: [{ who: 'ines', spanish: 'Excelencia, la nave es suya.', delivery: 'firme' }] } })
  await waitFor(() => assert.equal(store.getState().library.seriesById['mp-es'].episodesById.ep1.shots[0].dialogueBeats[0].text, 'Excelencia, la nave es suya.'))
  assert.equal(store.getState().serverRevision, 8, 'the edit\'s revision is the base of the next save')
  await waitFor(() => assert.ok(lines.getByText(/Saved \(Dialogue\)\. Its take no longer shows this plan/)), 'the part says what its save did')
  assert.ok(lines.getByRole('button', { name: 'Re-render this shot' }), 'and offers the render right there')
  const bar = within(view.getByTestId('series-inspector-regenerate'))
  assert.ok(bar.getByText('This shot changed after its take.'))
  await waitFor(() => assert.ok(bar.getByText(/records the voice of 1 line \(#1 Capitana Inés Valdés\)/)))
})

test('one line is recorded now and played in place; the take is then older than it', { concurrency: false }, async t => {
  const { view, server } = await mount(t)
  const { fireEvent, waitFor, within } = await import('@testing-library/react')
  await open(view, 1)
  const lines = within(await waitFor(() => view.getByTestId('series-inspector-s1-lines')))
  fireEvent.click(await waitFor(() => lines.getByRole('button', { name: 'Record voice' })))
  await waitFor(() => assert.deepEqual(server.posts('/voices')[0], { workspace: 'plus-ultra', line: 's1_b0', retake: false }))
  await waitFor(() => assert.ok(lines.getByRole('button', { name: 'Play line 1' })), { timeout: 5000 })
  assert.ok(lines.getByText('newer than the take'))
  assert.ok(lines.getByRole('button', { name: 'New take' }), 'a recorded line can be taken again')
  assert.ok(within(view.getByTestId('series-inspector-regenerate')).getByText(/A line was recorded after the take/))
})

test('a character changes pose in place and an unsaved draft survives leaving the shot', { concurrency: false }, async t => {
  const { view, server } = await mount(t)
  const { fireEvent, waitFor, within } = await import('@testing-library/react')
  await open(view, 1)
  const cast = within(await waitFor(() => view.getByTestId('series-inspector-s1-cast')))
  fireEvent.click(cast.getByRole('button', { name: 'Edit' }))
  fireEvent.change(await waitFor(() => cast.getByLabelText('Pose')), { target: { value: 'perfil' } })
  // Leave without saving: the draft is kept and the tile says so.
  fireEvent.click(view.getByRole('button', { name: 'All shots' }))
  await waitFor(() => assert.ok(within(view.getByTestId('series-approval-s1')).getByText('unsaved')))
  await open(view, 1)
  const again = within(await waitFor(() => view.getByTestId('series-inspector-s1-cast')))
  assert.equal((again.getByLabelText('Pose') as HTMLSelectElement).value, 'perfil')
  fireEvent.click(again.getByRole('button', { name: 'Save' }))
  await waitFor(() => assert.equal(server.posts('/shots/edit').length, 1))
  assert.deepEqual(server.posts('/shots/edit')[0]?.changes, { cast: [{ characterId: 'ines', poseId: 'perfil', x: 56 }] })
})

test('sound effects and screen effects read in words and edit as lists', { concurrency: false }, async t => {
  const { view, server } = await mount(t)
  const { fireEvent, waitFor, within } = await import('@testing-library/react')
  await open(view, 1)
  const sfx = within(await waitFor(() => view.getByTestId('series-inspector-s1-sfx')))
  assert.ok(sfx.getByText('sfx-boom.wav') && sfx.getByText(/at 0.4 s/))
  assert.ok(sfx.getByRole('button', { name: 'Play sfx-boom.wav' }))
  fireEvent.click(sfx.getByRole('button', { name: 'Edit' }))
  fireEvent.change(sfx.getByLabelText('Volume (0–1)'), { target: { value: '0.5' } })
  fireEvent.change(sfx.getByLabelText('Length (s)'), { target: { value: '0.3' } })
  fireEvent.click(sfx.getByRole('button', { name: 'Save' }))
  await waitFor(() => assert.deepEqual(server.posts('/shots/edit')[0]?.changes, { sfx: [{ file: 'sfx-boom.wav', at: 0.4, volume: 0.5, length: 0.3 }] }))
  const fx = within(view.getByTestId('series-inspector-s1-fx'))
  assert.ok(fx.getByText(/vignette · at 0 s · 30 s · intensity 0.5/))
})

test('a 3D shot lists its objects and opens its scene in the Video 3D editor; saving there writes the shot back', { concurrency: false }, async t => {
  const { applyScene3DTemplate } = await import('../src/features/scene3d/templates')
  const document = applyScene3DTemplate('two-shot')
  const { view, server } = await mount(t, { editorDocument: document })
  const { fireEvent, render, waitFor, within } = await import('@testing-library/react')
  const { useSceneDocumentHandoff } = await import('../src/features/sceneFx/handoff')
  const { useShotEditSession } = await import('../src/features/series/shotEditSession')
  const { useStore } = await import('../src/stores/useStore')
  const received: unknown[] = []
  function Editor() { useSceneDocumentHandoff('3d', raw => { received.push(raw) }); return null }
  render(<Editor />)
  await open(view, 2)
  const scene = within(await waitFor(() => view.getByTestId('series-inspector-s2-scene3d')))
  assert.ok(scene.getByText(/template user-plaga · final quality/))
  assert.ok(scene.getByText(/in e1's right hand/), 'the rifle says who carries it')
  assert.ok(scene.getByText(/plays Aim/))
  fireEvent.click(scene.getByRole('button', { name: 'Edit in Video 3D' }))
  await waitFor(() => assert.equal(received.length, 1))
  assert.equal(server.calls.find(call => call.path.endsWith('/scene3d/editor'))?.path, '/series/mp-es/episodes/ep1/shots/s2/scene3d/editor')
  const session = useShotEditSession.getState().session!
  assert.equal(session.target, 'plan')
  assert.equal(useStore.getState().mediaFilter, 'world3d')
  const { saveScene3DPlan } = await import('../src/features/series/inspector/scene3dPlan')
  await saveScene3DPlan(session, document)
  assert.deepEqual(server.posts('/scene3d/from-editor')[0], { workspace: 'plus-ultra', document: JSON.parse(JSON.stringify(document)) })
  const edit = server.posts('/shots/edit')[0] as { changes: { scene3d: { scene: string } } }
  assert.equal(edit.changes.scene3d.scene, 'mp-es-ep1-plan-0a.world3d.scene.json')
  assert.equal(useShotEditSession.getState().session, null)
  const { useShotInspector } = await import('../src/features/series/inspector/inspectorStore')
  assert.equal(useStore.getState().mediaFilter, 'series')
  await waitFor(() => assert.equal(useShotInspector.getState().episodes['plus-ultra/mp-es/ep1']?.openShotId, 's2'), 'back on the same shot')
})

test('a video take shows how its sound plays at the cut and saves its clip sound without a render', { concurrency: false }, async t => {
  const { view, server } = await mount(t)
  const { fireEvent, waitFor, within } = await import('@testing-library/react')
  await open(view, 3)
  const video = within(await waitFor(() => view.getByTestId('series-inspector-s3-video')))
  assert.ok(video.getByText(/keeps its own sound/))
  assert.ok(within(view.getByTestId('series-shot-inspector')).getByText(/is not rendered again/))
  fireEvent.click(video.getByRole('button', { name: 'Edit' }))
  fireEvent.change(video.getByLabelText('The clip\'s own sound'), { target: { value: 'drop' } })
  fireEvent.click(video.getByRole('button', { name: 'Save' }))
  await waitFor(() => assert.deepEqual(server.posts('/shots/edit')[0]?.changes, { clipAudio: 'drop' }))
  assert.equal(server.posts('/native-render').length, 0)
})
