import assert from 'node:assert/strict'
import test from 'node:test'
import { isCompositorVideo, sceneFromLibraryPayload, sceneLibraryTitle } from '../src/lib/sceneLibrary.ts'

test('compositor videos are the 3D Video MP4s, not ordinary clips', () => {
  assert.equal(isCompositorVideo({ type: 'video', mode: '3d-scene-compositor', name: 'loop.mp4' }), true)
  assert.equal(isCompositorVideo({ type: 'video', mode: 'video', name: '2026-08-25-22h21m13s_station-runner_3d_509c26.mp4' }), true)
  assert.equal(isCompositorVideo({ type: 'video', mode: 'video', name: 'minimax_h3_clip.mp4' }), false)
  assert.equal(isCompositorVideo({ type: 'scene', mode: null, name: 'station.scene.json' }), false)
})

test('library titles drop timestamps and 3D export suffixes', () => {
  assert.equal(sceneLibraryTitle('2026-08-25-22h21m09s_Station-loop-tall-lamp_99c2ad.scene.json'), 'Station loop tall lamp')
  assert.equal(sceneLibraryTitle('2026-08-25-22h21m13s_station-runner_3d_509c26.mp4'), 'station runner')
})

test('a saved scene JSON and a 3D clip sidecar both open as Scene Animator scenes', () => {
  const scene = {
    version: 1,
    name: 'Station loop runner',
    width: 1280,
    height: 720,
    duration: 10,
    layers: [{ id: 'plate', name: 'Plate', type: 'image', source: '/api/v1/file/plate.jpg', visible: true, z: 0, transform: { x: 50, y: 50, scale: 1, opacity: 1 }, animation: { start: { x: 50, y: 50, scale: 1 }, end: { x: 50, y: 50, scale: 1 }, duration: 10, curve: 'linear' } }],
  }
  assert.equal(sceneFromLibraryPayload(scene).name, 'Station loop runner')
  assert.equal(sceneFromLibraryPayload({ params: { scene } }).name, 'Station loop runner')
  assert.throws(() => sceneFromLibraryPayload({ params: { prompt: 'no scene' } }))
})

test('saved scene lookup accepts only an exact filename or visible title', async () => {
  const { sceneOutputMatchesName } = await import('../src/lib/sceneLibrary.ts')
  const file = { name: '2026-08-30-14h05m02s_Concierto-arcano_a1b2c3.scene.json' }

  assert.equal(sceneLibraryTitle(file.name), 'Concierto arcano')
  assert.equal(sceneOutputMatchesName(file, file.name), true)
  assert.equal(sceneOutputMatchesName(file, 'Concierto arcano'), true)
  assert.equal(sceneOutputMatchesName(file, 'concierto-ÁRCANO'), true)
  assert.equal(sceneOutputMatchesName(file, 'Concierto'), false)
  assert.equal(sceneOutputMatchesName(file, ''), false)
})
