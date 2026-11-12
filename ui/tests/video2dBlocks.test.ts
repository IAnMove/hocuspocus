import assert from 'node:assert/strict'
import test from 'node:test'
import { FINISH_PRESETS, gradeFilter, grainSeed, parseFinish } from '../src/lib/scene2d/finish.ts'
import { beatEnvelope, parseSequence, pathPoint, sequenceFrame } from '../src/lib/scene2d/motion.ts'
import { normalizeScene2D } from '../src/lib/scene2d/normalize.ts'

test('finish presets stay inside the grade limits and grain follows the frame', () => {
  const finish = parseFinish({ grade: { exposure: 4, contrast: 0, saturation: 0, temperature: 0, tint: 0, fade: 0 }, texture: { kind: 'nope', amount: 1 } })
  assert.equal(finish?.grade?.exposure, 1)
  assert.equal(finish?.texture, undefined)
  assert.equal(parseFinish(FINISH_PRESETS.oldDoc)?.grain?.amount, FINISH_PRESETS.oldDoc.grain?.amount)
  assert.match(gradeFilter(FINISH_PRESETS.warmCinema.grade!), /brightness\(/)
  assert.equal(grainSeed(0), 0)
  assert.equal(grainSeed(1), 30)
})

test('paths, frame sequences and beat envelopes are deterministic', () => {
  const straight = pathPoint({ points: [{ x: 0, y: 0 }, { x: 100, y: 0 }], orient: true }, 0.5)
  assert.ok(Math.abs(straight.x - 50) < 8)
  assert.ok(Math.abs(straight.rotation) < 20)
  const uneven = pathPoint({ points: [{ x: 0, y: 0 }, { x: 10, y: 0 }, { x: 110, y: 0 }], orient: false }, 0.5)
  assert.ok(uneven.x > 30)
  const frames = parseSequence({ kind: 'frames', sources: ['a', 'b', 'c'], fps: 1, loop: 'pingpong' })
  assert.equal(frames && sequenceFrame(frames, 3), 1)
  assert.equal(sequenceFrame({ kind: 'frames', sources: ['a', 'b', 'c'], fps: 1, loop: 'once' }, 9), 2)
  assert.equal(beatEnvelope({ bpm: 120, beats: [1] }, 1), 1)
  assert.equal(beatEnvelope(undefined, 1), 0)
  assert.equal(beatEnvelope({ bpm: 120, beats: [1] }, 1.2), 0)
})

test('a sheet sequence can start late and play mirrored; the rest keep their clock', () => {
  const sheet = { kind: 'sheet', source: 's.png', columns: 4, rows: 1, count: 4, fps: 2 } as const
  const late = parseSequence({ ...sheet, loop: 'once', start: 3, mirror: true })
  assert.deepEqual(late, { ...sheet, loop: 'once', start: 3, mirror: true })
  assert.equal(late && sequenceFrame(late, 2), 0, 'before its start it shows the first cell')
  assert.deepEqual([3, 3.5, 4, 5, 9].map(time => late && sequenceFrame(late, time)), [0, 1, 2, 3, 3], 'a once sheet counts from its start')
  const pingpong = parseSequence({ ...sheet, loop: 'pingpong', start: 1 })!
  assert.deepEqual([1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5].map(time => sequenceFrame(pingpong, time)), [0, 1, 2, 3, 2, 1, 0, 1])
  assert.deepEqual(parseSequence({ ...sheet, loop: 'loop', start: -2, mirror: false }), { ...sheet, loop: 'loop' }, 'a bad start and a false mirror are dropped')
  assert.equal(sequenceFrame({ ...sheet, loop: 'loop' }, 1.5), 3, 'without a start the clock is the scene\'s, as before')
})

test('anchored emitters break cycles instead of following each other', () => {
  const cycled = normalizeScene2D({
    version: 1, name: 'cycle', width: 320, height: 180, fps: 24, duration: 1,
    layers: ['a', 'b'].map(id => ({
      id, name: id, type: 'effect', source: '', visible: true, z: 0,
      transform: { x: 50, y: 50, scale: 1, opacity: 1 },
      animation: { start: { x: 50, y: 50, scale: 1 }, end: { x: 50, y: 50, scale: 1 }, duration: 1, curve: 'linear' },
      atmosphere: { kind: 'smoke', density: 8, speed: 0.2, size: 1, wind: 0, color: '#cccccc', emitter: { mode: 'layer', targetLayerId: id === 'a' ? 'b' : 'a', direction: 0, spread: 20, rate: 4, lifetime: 1, speed: 12, gravity: 0 } },
    })),
  })
  assert.ok(cycled.layers.every(layer => layer.atmosphere?.emitter?.mode === 'frame'))
})
