import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'
import { createCharacterKit } from '../src/lib/characterKit.ts'
import { episode, jsonResponse, series, shot } from './seriesReviewFixtures'

const dom = new JSDOM('<!doctype html><html lang="en"><body /></html>', { url: 'http://localhost/' })
Object.assign(globalThis, { window: dom.window, document: dom.window.document, localStorage: dom.window.localStorage, HTMLElement: dom.window.HTMLElement,
  HTMLSelectElement: dom.window.HTMLSelectElement, File: dom.window.File, Blob: dom.window.Blob, Event: dom.window.Event,
  MutationObserver: dom.window.MutationObserver, ResizeObserver: class { observe() {} disconnect() {} } })
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
dom.window.HTMLMediaElement.prototype.pause = () => {}

const image = (id: string, kind: 'image' | 'overlay' = 'image') => ({ id, name: id, source: `/${id}.png`, kind, alphaStatus: 'transparent' as const, reviewState: 'approved' as const })

function inesKit() {
  return { ...createCharacterKit('Inés'), id: 'mp-ines', base: image('base'), poses: { busto: image('busto'), perfil: image('perfil') },
    anchors: { base: { mouth: { offsetX: 0, offsetY: -18, scale: .05, rotation: 0 } } } }
}

function library() {
  return { version: 1 as const, revision: 3, activeId: 'mp-ines', kits: { 'mp-ines': inesKit() } }
}

test('a shot\'s face rig link opens the character\'s kit on the pose the shot uses', { concurrency: false }, async t => {
  const { useStore } = await import('../src/stores/useStore')
  const { useSeriesStore } = await import('../src/features/series/store')
  const { useCharacterEditorHandoff } = await import('../src/features/characters/characterEditorHandoff')
  const { openSeriesCharacterEditor } = await import('../src/features/series/seriesCharacterEditor')
  const original = globalThis.fetch
  t.after(() => { globalThis.fetch = original; useCharacterEditorHandoff.setState({ request: null }) })
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    if (String(input).includes('/character-kits/library')) return jsonResponse(library())
    throw new Error(`Unexpected request ${String(input)}`)
  }) as typeof fetch
  const project = series(episode([shot('s1', 1)]))
  useStore.setState({ activeWorkspace: 'plus-ultra', mediaFilter: 'series' })
  useSeriesStore.setState({ workspace: 'plus-ultra', activeSeriesId: project.id, activeEpisodeId: 'ep1', serverRevision: project.revision, hydrated: true, dirty: false,
    library: { schema: 'series-library', version: 1, workspaceId: 'plus-ultra', seriesOrder: [project.id], seriesById: { [project.id]: project } } })

  await openSeriesCharacterEditor('plus-ultra', project.id, 'ines', { poseId: 'busto' })
  assert.equal(useStore.getState().mediaFilter, 'characters')
  const request = useCharacterEditorHandoff.getState().request!
  assert.equal(request.kit.id, 'mp-ines')
  assert.equal(request.poseId, 'busto')
  // Same character, another shot: the open session moves to that pose; a pose the kit lacks opens the default one.
  await openSeriesCharacterEditor('plus-ultra', project.id, 'ines', { poseId: 'perfil' })
  assert.equal(useCharacterEditorHandoff.getState().request!.poseId, 'perfil')
  assert.equal(useCharacterEditorHandoff.getState().request!.sourceId, request.sourceId)
  await openSeriesCharacterEditor('plus-ultra', project.id, 'ines', { poseId: 'gone' })
  assert.equal(useCharacterEditorHandoff.getState().request!.poseId, undefined)
})

test('the speech workshop opens on the requested pose', { concurrency: false }, async t => {
  const { render, cleanup, waitFor } = await import('@testing-library/react')
  const { CharacterSpeechPreparation } = await import('../src/features/characters/CharacterSpeechPreparation')
  const original = globalThis.fetch
  t.after(() => { cleanup(); globalThis.fetch = original })
  globalThis.fetch = (async () => jsonResponse({ packs: [] })) as typeof fetch
  const services = { load: async () => library(), save: async () => library(), upload: async () => ({ filename: 'x.png', path: '/x.png', url: '/x.png' }) }
  const view = render(<CharacterSpeechPreparation workspace="plus-ultra" services={services as never} initialKitId="mp-ines" initialPoseId="busto" />)
  await waitFor(() => assert.equal((view.getByRole('combobox', { name: 'Editing pose' }) as HTMLSelectElement).value, 'busto'))
  assert.ok(view.getByTestId('speech-face-rig'))
})
