import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { readFileSync } from 'node:fs'
import { JSDOM } from 'jsdom'
import type { SeriesProject } from '../src/features/series/types'
import { createCharacterKit, type CharacterKitAsset } from '../src/lib/characterKit'
import { applySeriesLipSync, seriesLipSyncFingerprint, seriesLipSyncIssues } from '../src/features/series/nativeLipSync'
import { lipSyncCandidates } from '../src/features/series/nativeTake'
import { evaluateSceneLayer } from '../src/lib/sceneTimeline'

const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
Object.assign(globalThis, { window: dom.window, document: dom.window.document, localStorage: dom.window.localStorage,
  sessionStorage: dom.window.sessionStorage, HTMLElement: dom.window.HTMLElement, Event: dom.window.Event })
window.matchMedia = () => ({ matches: false }) as MediaQueryList

async function fixture() {
  const { buildSeriesShotScene } = await import('../src/features/series/shotScene')
  const { animateSeriesDraft } = await import('../src/features/series/nativeDraftScene')
  const series: SeriesProject = JSON.parse(readFileSync(new URL('../../docs/series-lab/example-series-library-v1.json', import.meta.url), 'utf8')).seriesById.series_signal
  const episode = Object.values(series.episodesById)[0], shot = episode.shots[0]
  series.allowedProductionMethods = ['animation_2d']; shot.productionMethod = 'animation_2d'; shot.attempts = []; shot.approvedAttemptId = undefined
  episode.shots = [shot]; shot.durationSeconds = 6
  episode.canonSnapshot = { revision: 1, characters: series.characters, locations: series.locations, assets: series.assets }
  const kit = createCharacterKit('Configured actor')
  const asset: CharacterKitAsset = { id: 'pose', name: 'Mouthless base', source: '/mouthless.png', kind: 'image', alphaStatus: 'transparent', reviewState: 'approved' }
  kit.base = asset; kit.anchors.base = { mouth: { offsetX: 1, offsetY: -18, scale: .08, rotation: 0 } }
  for (const state of ['closed', 'small', 'wide', 'round'] as const) kit.mouth[state] = { ...asset, id: state, source: `/${state}.png`, kind: 'overlay' }
  const character = series.characters.find(item => item.id === shot.visibleCharacterIds[0])!
  character.voiceProfile = { characterKitRef: { workspace: 'default', id: kit.id } }
  shot.dialogueBeats = [{ id: 'first', characterId: character.id, text: 'Hello, how are you?' },
    { id: 'second', characterId: character.id, text: 'We are ready.' }] as typeof shot.dialogueBeats
  const library = { version: 1 as const, revision: 1, activeId: kit.id, kits: { [kit.id]: kit } }
  const prepared = buildSeriesShotScene('default', series, episode, shot)
  if (prepared.dimension !== '2d') throw new Error('Expected 2D')
  const scene = animateSeriesDraft({ ...prepared.document,
    audioTracks: shot.dialogueBeats.map((beat, i) => ({ id: beat.id, filename: `${beat.id}.wav`, name: character.name,
      kind: 'speech' as const, startTime: i === 0 ? .5 : 4, volume: 1, prompt: beat.text })),
    dialogueBeats: shot.dialogueBeats.map((beat, i) => ({ id: beat.id, text: beat.text, start: i === 0 ? .5 : 4,
      end: i === 0 ? 2.5 : 5, mouthLayerIds: [], audioTrackId: beat.id, confidence: 'aligned-audio' as const })) }, shot)
  return { series, episode, shot, kit, library, scene, character }
}

test('saved mouth layers follow the exact speaker, retain the wiped base and motion, and close between repeated turns', async () => {
  const { scene, series, shot, library, character } = await fixture()
  const before = structuredClone(scene)
  const result = applySeriesLipSync(scene, 'default', series, shot, library, { [character.id]: '/transparent-mouthless.png' })
  assert.deepEqual(scene, before)
  assert.deepEqual(result.audioTracks, before.audioTracks)
  const body = result.layers.find(layer => layer.id === character.id)!
  assert.equal(body.source, '/transparent-mouthless.png')
  assert.deepEqual(body.animation, before.layers.find(layer => layer.id === character.id)!.animation)
  const mouths = result.layers.filter(layer => layer.faceBinding?.role === 'mouth')
  assert.equal(mouths.length, 4)
  assert.ok(mouths.every(layer => layer.relationship?.targetLayerId === character.id))
  assert.ok(result.dialogueBeats!.every(beat => beat.mouthLayerIds.length === 4 && beat.confidence === 'known-text'))
  const closed = mouths.find(layer => layer.faceBinding!.state === 'closed')!
  for (const time of [0, .2, 3, 3.8, 5.8]) {
    assert.equal(evaluateSceneLayer(closed, time).opacity, 1)
    assert.ok(mouths.filter(layer => layer !== closed).every(layer => evaluateSceneLayer(layer, time).opacity === 0))
  }
  assert.ok(mouths.some(layer => layer !== closed && layer.animation.keyframes!.filter(frame => frame.opacity === 1).length > 1))
  const again = applySeriesLipSync(result, 'default', series, shot, library)
  assert.equal(again.layers.length, result.layers.length)
})

test('pending mouths, a changed pose and missing placement remain explicit blockers', async () => {
  const { series, shot, library, kit, character } = await fixture()
  kit.mouth.wide!.reviewState = 'pending'
  assert.deepEqual(seriesLipSyncIssues('default', series, [shot], library), [{ id: character.id, name: character.name, reason: 'mouths' }])
  kit.base!.reviewState = 'pending'
  assert.equal(seriesLipSyncIssues('default', series, [shot], library)[0].reason, 'pose')
  kit.base!.reviewState = 'approved'; kit.mouth.wide!.reviewState = 'approved'; kit.anchors = {}
  assert.equal(seriesLipSyncIssues('default', series, [shot], library)[0].reason, 'placement')
  assert.equal(seriesLipSyncIssues('other-workspace', series, [shot], library)[0].reason, 'link')
})

test('lipsync retakes reuse saved scenes and skip current versions, approved takes and active renders', async () => {
  const { series, episode, shot, library, kit } = await fixture()
  const template = Object.values(series.assets)[0]
  const take = { ...template, id: 'video', kind: 'video' as const, metadata: { productionMethod: 'animation_2d', sceneFilename: 'scene.json', lipSyncFingerprint: '' } }
  series.assets.video = take
  shot.attempts = [{ id: 'take', status: 'completed', outputAssetIds: ['video'] }] as typeof shot.attempts
  assert.equal(lipSyncCandidates('default', series, episode, library).length, 1)
  take.metadata.lipSyncFingerprint = seriesLipSyncFingerprint('default', series, shot, library)
  assert.equal(lipSyncCandidates('default', series, episode, library).length, 0)
  kit.anchors.base.mouth.offsetX += 1
  assert.equal(lipSyncCandidates('default', series, episode, library).length, 1)
  shot.approvedAttemptId = 'take'
  assert.equal(lipSyncCandidates('default', series, episode, library).length, 0)
  shot.approvedAttemptId = undefined; shot.attempts.push({ ...shot.attempts[0], id: 'active', status: 'running' })
  assert.equal(lipSyncCandidates('default', series, episode, library).length, 0)
})

test('changing dialogue cannot silently reuse an older voice recording', async () => {
  const { scene, series, shot, library } = await fixture()
  shot.dialogueBeats[0].text = 'A newly edited line'
  assert.throws(() => applySeriesLipSync(scene, 'default', series, shot, library), /saved audio does not match/)
})

test('cutouts of a mouthless pose never reuse the original baked-mouth image', async () => {
  const { characterCutout } = await import('../src/features/series/characterCutout')
  const { series } = await fixture(), original = Object.values(series.assets)[0]
  series.assets.originalCutout = { ...original, id: 'original-cutout', kind: 'image', metadata: { backgroundRemoved: true, sourceAssetId: original.id } }
  series.assets.wipedCutout = { ...original, id: 'wiped-cutout', kind: 'image', metadata: { backgroundRemoved: true, sourceAssetId: original.id, sourceKey: 'wiped-v2' } }
  assert.equal(characterCutout(series, original)?.id, 'original-cutout')
  assert.equal(characterCutout(series, original, 'wiped-v2')?.id, 'wiped-cutout')
  assert.equal(characterCutout(series, original, 'wiped-v3'), undefined)
})

test('the lipsync panel lists the missing character and blocks updates until saved mouths are ready', async t => {
  const { render, cleanup, waitFor } = await import('@testing-library/react')
  const { SeriesLipSyncPreparation } = await import('../src/features/series/SeriesLipSyncPreparation')
  const { series, episode, library, kit, character } = await fixture()
  kit.mouth = {}
  const fetch = globalThis.fetch
  globalThis.fetch = async () => new Response(JSON.stringify(library))
  t.after(() => { cleanup(); globalThis.fetch = fetch })
  const view = render(<SeriesLipSyncPreparation workspace="default" series={series} episode={episode} />)
  await waitFor(() => assert.ok(view.getByText(/Prepare, approve and save all four mouth shapes/)))
  assert.ok(view.getByRole('button', { name: character.name }))
  assert.equal((view.getByRole('button', { name: /Update lip sync in generated takes/ }) as HTMLButtonElement).disabled, true)
})
