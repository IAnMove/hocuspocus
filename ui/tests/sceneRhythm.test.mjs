import assert from 'node:assert/strict'
import test from 'node:test'
import { applySceneRhythmToLayer, buildSceneRhythmMap } from '../src/lib/sceneRhythm.ts'
import { evaluateSceneLayer } from '../src/lib/sceneTimeline.ts'

const analysis = {
  duration: 4,
  sample_rate: 44_100,
  bpm: 120,
  beats: [
    { time: 0, strength: .6 },
    { time: .5, strength: .8 },
    { time: 1, strength: .7 },
    { time: 1.5, strength: 1 },
  ],
  downbeats: [0, 1.5],
  sections: [],
  onset_envelope: [],
  lyrics: null,
  vocals_path: null,
}

const layer = {
  id: 'ship',
  name: 'Ship',
  type: 'model3d',
  source: 'ship.glb',
  visible: true,
  z: 2,
  transform: { x: 20, y: 50, scale: 1, opacity: 1, rotation: 0 },
  animation: {
    start: { x: 20, y: 50, scale: 1, opacity: 1, rotation: 0 },
    end: { x: 80, y: 50, scale: 1, opacity: 1, rotation: 0 },
    duration: 2,
    curve: 'linear',
  },
}

test('rhythm map offsets audio beats onto the scene and marks downbeats', () => {
  const map = buildSceneRhythmMap(analysis, .25, 1.4)
  assert.deepEqual(map.cues.map(cue => cue.time), [.25, .75, 1.25])
  assert.equal(map.cues[0].downbeat, true)
  assert.equal(map.cues[1].downbeat, false)
})
test('downbeat mode emits only the strongest structural cue positions', () => {
  const map = buildSceneRhythmMap(analysis, 0, 2, 'downbeats')
  assert.deepEqual(map.cues.map(cue => cue.time), [0, 1.5])
  assert.ok(map.cues.every(cue => cue.downbeat))
})

test('pulse preserves the travelling path and peaks exactly on each beat', () => {
  const map = buildSceneRhythmMap(analysis, 0, 2)
  const synced = applySceneRhythmToLayer(layer, map, { profile: 'pulse', sceneDuration: 2, intensity: .8 })
  const before = evaluateSceneLayer(synced, .4)
  const peak = evaluateSceneLayer(synced, .5)
  const after = evaluateSceneLayer(synced, .7)

  assert.ok(peak.scale > before.scale)
  assert.ok(peak.scale > after.scale)
  assert.ok(peak.x > before.x)
  assert.ok(after.x > peak.x)
  assert.equal(synced.animation.offset, 0)
  assert.equal(synced.animation.loop, false)
})

test('peek hides a 3D object between beats and reveals it on the beat', () => {
  const map = buildSceneRhythmMap(analysis, 0, 2)
  const synced = applySceneRhythmToLayer(layer, map, { profile: 'peek', sceneDuration: 2, intensity: .7 })

  assert.equal(evaluateSceneLayer(synced, 0).opacity, 1)
  assert.match(synced.animation.keyframes[0].id, /peek-visible-0/)
  assert.equal(evaluateSceneLayer(synced, .25).opacity, 0)
  assert.equal(evaluateSceneLayer(synced, .5).opacity, 1)
  assert.equal(evaluateSceneLayer(synced, .7).opacity, 0)
  assert.ok(evaluateSceneLayer(synced, .25).x < evaluateSceneLayer(synced, .5).x)
})

test('camera punch uses a restrained scale accent', () => {
  const camera = { ...layer, id: 'camera', type: 'camera', source: '' }
  const map = buildSceneRhythmMap(analysis, 0, 2)
  const pulse = applySceneRhythmToLayer(camera, map, { profile: 'pulse', sceneDuration: 2, intensity: 1 })
  const punch = applySceneRhythmToLayer(camera, map, { profile: 'camera-punch', sceneDuration: 2, intensity: 1 })

  assert.ok(evaluateSceneLayer(punch, .5).scale > 1)
  assert.ok(evaluateSceneLayer(punch, .5).scale < evaluateSceneLayer(pulse, .5).scale)
})

test('a synthetic 120 BPM click track bakes beat peaks within one millisecond', () => {
  const clicks = Array.from({ length: 16 }, (_, index) => ({ time: index * .5, strength: 1 }))
  const clickTrack = { ...analysis, duration: 8, beats: clicks, downbeats: [0, 2, 4, 6, 8] }
  const map = buildSceneRhythmMap(clickTrack, 0, 8, 'beats')
  const synced = applySceneRhythmToLayer(layer, map, { profile: 'pulse', sceneDuration: 8, intensity: 1 })
  const peaks = synced.animation.keyframes.filter(frame => frame.id.includes('rhythm-peak-'))
  assert.equal(peaks.length, clicks.length)
  for (const [index, frame] of peaks.entries()) {
    assert.ok(Math.abs(frame.time - clicks[index].time) <= .001, `click ${index} drifted by ${Math.abs(frame.time - clicks[index].time)}s`)
  }
})
