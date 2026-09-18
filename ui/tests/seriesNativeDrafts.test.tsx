import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { readFileSync } from 'node:fs'
import { JSDOM } from 'jsdom'
import type { SeriesProject, SeriesAsset } from '../src/features/series/types'

const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
Object.assign(globalThis, { window: dom.window, document: dom.window.document, localStorage: dom.window.localStorage,
  sessionStorage: dom.window.sessionStorage, HTMLElement: dom.window.HTMLElement, Event: dom.window.Event })
window.matchMedia = () => ({ matches: false }) as MediaQueryList

function fixture() {
  const series: SeriesProject = JSON.parse(readFileSync(new URL('../../docs/series-lab/example-series-library-v1.json', import.meta.url), 'utf8')).seriesById.series_signal
  const episode = Object.values(series.episodesById)[0]
  series.allowedProductionMethods = ['animation_2d']
  for (const shot of episode.shots) { shot.productionMethod = 'animation_2d'; shot.attempts = []; shot.approvedAttemptId = undefined }
  return { series, episode }
}

test('native batch resumes only missing permitted 2D takes and preserves drafts, finals and active jobs', async () => {
  const { nativeDraftCandidates } = await import('../src/features/series/nativeBatch')
  const { series, episode } = fixture(), shot = episode.shots[0]
  const attempt = { id: 'try', status: 'completed' } as typeof shot.attempts[number]
  episode.shots = [shot, { ...shot, id: 'draft', attempts: [attempt] }, { ...shot, id: 'final', approvedAttemptId: 'final' },
    { ...shot, id: 'active', attempts: [{ ...attempt, status: 'running' }] }, { ...shot, id: 'import', productionMethod: 'imported_video' }]
  assert.deepEqual(nativeDraftCandidates(series, episode).map(item => item.id), [shot.id])
  series.allowedProductionMethods = ['generated_video']
  assert.deepEqual(nativeDraftCandidates(series, episode), [])
})

test('cutout derivatives retain original references, approval and concurrent edits, and are reused by source identity', async () => {
  const { characterCutout } = await import('../src/features/series/characterCutout')
  const { mergeSeriesReferenceImport } = await import('../src/features/series/referenceImages')
  const { series } = fixture()
  const original = Object.values(series.assets)[0]
  const asset: SeriesAsset = { ...original, id: 'cutout', ownerType: 'series', ownerId: series.id, kind: 'image', uri: 'transparent.png',
    metadata: { sourceAssetId: original.id, backgroundRemoved: true } }
  const before = structuredClone(series)
  const merged = mergeSeriesReferenceImport({ ...series, premise: 'Concurrent edit' }, { asset, series: { ...series, revision: series.revision + 1 } })
  assert.deepEqual(merged.characters, before.characters)
  assert.deepEqual(merged.canon, before.canon)
  assert.equal(merged.premise, 'Concurrent edit')
  assert.equal(characterCutout(merged, original)?.id, 'cutout')
  assert.equal(characterCutout(merged, { ...original, id: 'changed-image' }), undefined)
})

test('automatic blocking uses editable keyframes with visible motion and preserves dialogue and background', async () => {
  const { buildSeriesShotScene } = await import('../src/features/series/shotScene')
  const { animateSeriesDraft } = await import('../src/features/series/nativeDraftScene')
  const { series, episode } = fixture(), shot = episode.shots[0]
  episode.canonSnapshot = { revision: 1, characters: series.characters, locations: series.locations, assets: series.assets }
  const prepared = buildSeriesShotScene('default', series, episode, shot)
  assert.equal(prepared.dimension, '2d')
  if (prepared.dimension !== '2d') return
  const animated = animateSeriesDraft(prepared.document, shot)
  const person = animated.layers.find(layer => layer.id === shot.visibleCharacterIds[0])!
  assert.ok(person.animation.keyframes!.length > 2)
  assert.ok(new Set(person.animation.keyframes!.map(frame => frame.y)).size > 1)
  assert.deepEqual(animated.dialogueBeats, prepared.document.dialogueBeats)
  assert.equal(animated.layers[0].source, prepared.document.layers[0].source)
  assert.equal(prepared.document.layers.find(layer => layer.id === person.id)?.animation.keyframes, undefined)
})

test('export waits for the exact image layers to load before painting', async () => {
  const { waitForSceneImages } = await import('../src/lib/sceneMediaReady')
  const root = document.createElement('div'), img = document.createElement('img')
  img.dataset.layerId = 'character'; root.append(img)
  Object.defineProperty(img, 'complete', { value: true })
  Object.defineProperty(img, 'naturalWidth', { value: 640 })
  await waitForSceneImages(root, [{ id: 'character', type: 'image', source: 'character.png', visible: true }] as Parameters<typeof waitForSceneImages>[1])
})

test('voice recovery reconnects the admitted job after reload without submitting the dialogue again', async t => {
  const { submitSeriesSpeech } = await import('../src/features/series/nativeDraftScene')
  const fetch = globalThis.fetch
  let submissions = 0
  globalThis.fetch = async (_input, init) => {
    if (init?.method === 'POST') { submissions++; return new Response(JSON.stringify({ job_id: 'voice-one', status: 'queued' })) }
    return new Response(JSON.stringify({ job_id: 'voice-one', status: 'completed', output_files: ['voice.wav'] }))
  }
  t.after(() => { globalThis.fetch = fetch; localStorage.removeItem('speech-recovery') })
  const first = await submitSeriesSpeech({ prompt: 'Hello' }, 'speech-recovery')
  const recovered = await submitSeriesSpeech({ prompt: 'Hello' }, 'speech-recovery')
  assert.equal(first.job_id, recovered.job_id)
  assert.equal(submissions, 1)
})

test('Shots opens a completed native take with an empty AI manifest and links to its generated video', async t => {
  const { render, fireEvent, cleanup } = await import('@testing-library/react')
  const { SeriesShotsPanel } = await import('../src/features/series/SeriesShotsPanel')
  const { series, episode } = fixture(), shot = episode.shots[0]
  episode.shots = [{ ...shot, dialogueBeats: [], referenceManifest: {} as typeof shot.referenceManifest,
    attempts: [{ id: 'native-take', status: 'completed', model: 'animation_2d', elapsedMs: 0, outputAssetIds: [] } as typeof shot.attempts[number]] }]
  const fetch = globalThis.fetch, reviewed: string[] = []
  globalThis.fetch = async () => new Response(JSON.stringify({ outputs: [], total: 0, kits: {} }))
  t.after(() => { cleanup(); globalThis.fetch = fetch })
  const view = render(<SeriesShotsPanel workspace="default" series={series} episode={episode}
    updateSeries={() => {}} updateEpisode={() => {}} replaceSeries={() => {}} saveNow={async () => series}
    onAcknowledgeLipSync={async () => {}} onRender={() => {}} onReviewShot={id => reviewed.push(id)} />)
  assert.ok(view.getByText('Video generated · awaiting review'))
  fireEvent.click(view.getByRole('button', { name: 'View generated take', exact: true }))
  assert.deepEqual(reviewed, [shot.id])
})

test('viewing a regenerated shot previews its new draft while keeping the approved original for assembly', async t => {
  const { render, cleanup, waitFor } = await import('@testing-library/react')
  const { SeriesReviewPanel } = await import('../src/features/series/SeriesReviewPanel')
  const { series, episode } = fixture(), shot = episode.shots[0]
  const asset = Object.values(series.assets)[0]
  series.assets.old = { ...asset, id: 'old', kind: 'video', uri: 'old.mp4' }
  series.assets.new = { ...asset, id: 'new', kind: 'video', uri: 'new.mp4' }
  shot.dialogueBeats = []
  shot.attempts = ['old', 'new'].map(id => ({ id, status: 'completed', outputAssetIds: [id], retryCount: 0 })) as typeof shot.attempts
  shot.approvedAttemptId = 'old'; episode.shots = [shot]
  const fetch = globalThis.fetch
  globalThis.fetch = async () => new Response(JSON.stringify({ kits: {}, jobs: [] }))
  t.after(() => { cleanup(); globalThis.fetch = fetch })
  const view = render(<SeriesReviewPanel workspace="default" series={series} episode={episode} requestedShotId={shot.id}
    job={null} setJob={() => {}} reload={async () => {}} startRender={async () => {}} updateEpisode={() => {}} saveNow={async () => series} />)
  await waitFor(() => assert.ok(view.container.querySelector('video')?.src.includes('new.mp4')))
  assert.equal(shot.approvedAttemptId, 'old')
})
