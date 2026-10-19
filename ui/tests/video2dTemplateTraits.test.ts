import assert from 'node:assert/strict'
import test from 'node:test'
import { normalizeScene2D } from '../src/lib/scene2d/normalize.ts'
import type { AnimatorScene } from '../src/lib/scene2d/types.ts'
import { slotRole, templateTraits2d, turns, type CardHints, type LayerRole } from '../scripts/video2dTemplateTraits.ts'

// Synthetic one-card scenes: each test builds the smallest document that shows one trait, the way a compiled card
// would carry it, and reads it back through the real evaluator.
type Pose = { x: number; y: number; scale: number; rotation?: number; opacity?: number }
type Key = Pose & { time: number; curve?: 'linear' | 'ease' | 'hold' }
const DURATION = 4

function pose(value: Pose) {
  return { x: value.x, y: value.y, scale: value.scale, rotation: value.rotation ?? 0, opacity: value.opacity ?? 1 }
}

function layer(id: string, type: string, from: Pose, to: Pose = from, extra: Record<string, unknown> = {}) {
  return {
    id, name: id, type, source: type === 'camera' || type === 'effect' ? '' : `/examples/t/${id}.png`, visible: true, z: 0,
    transform: pose(from), animation: { start: pose(from), end: pose(to), duration: DURATION, curve: 'linear' }, ...extra,
  }
}

function keyed(id: string, keys: Key[]) {
  const frames = keys.map((key, index) => ({ id: `${id}-${index}`, ...pose(key), time: key.time, curve: key.curve ?? 'linear' }))
  return layer(id, 'image', keys[0], keys[keys.length - 1], { animation: { start: pose(keys[0]), end: pose(keys[keys.length - 1]), duration: DURATION, curve: 'linear', keyframes: frames } })
}

const PLATE = layer('background', 'image', { x: 50, y: 50, scale: 1.15 }, { x: 50, y: 50, scale: 1.15 }, { fill: true })
const DUST = layer('dust', 'effect', { x: 50, y: 50, scale: 1, opacity: .35 }, { x: 50, y: 50, scale: 1, opacity: .35 }, { atmosphere: { kind: 'dust' } })
const STILL_FIGURE = layer('subject_1', 'image', { x: 50, y: 60, scale: .8 })

function scene(layers: unknown[], extra: Record<string, unknown> = {}): AnimatorScene {
  return normalizeScene2D({ version: 1, name: 'card', width: 1280, height: 720, fps: 30, duration: DURATION, texts: [], layers, ...extra })
}

function hints(doc: AnimatorScene, family = 'music', id = 'music-test'): CardHints {
  const roles = new Map<string, LayerRole>(doc.layers.map(item => [item.id,
    item.type === 'camera' ? 'camera' : item.atmosphere || item.type === 'effect' ? 'particles' : slotRole(item.id.replace(/-copy-\d+$/, ''))]))
  const slots = [...new Set(doc.layers.filter(item => item.type !== 'camera' && !item.atmosphere && item.type !== 'effect').map(item => item.id.replace(/-copy-\d+$/, '')))]
  return { id, family, slots, roles }
}

const traitsOf = (layers: unknown[], family = 'music', id = 'music-test', extra: Record<string, unknown> = {}) => {
  const doc = scene(layers, extra)
  return templateTraits2d(doc, hints(doc, family, id))
}

test('turns counts swings that go back by at least the swing', () => {
  assert.equal(turns([0, 1, 2, 3, 2, 1, 2, 3], 1), 2)
  assert.equal(turns([0, .4, 0, .4, 0], 1), 0, 'a wobble under the swing is not a turn')
  assert.equal(turns([5, 4, 3, 2], 1), 0, 'one way is no turn')
})

test('slot names give the role in the new vocabulary and the old one', () => {
  assert.deepEqual(['subject_1', 'subject_2', 'hero', 'background', 'plate', 'prop_1', 'prop', 'foreground'].map(slotRole),
    ['subject', 'subject', 'subject', 'background', 'background', 'prop', 'prop', 'foreground'])
})

test('a plate with a figure and only particles is a still shot held all the time', () => {
  const traits = traitsOf([PLATE, STILL_FIGURE, DUST])
  assert.equal(traits.holdShare, 1)
  assert.equal(traits.still, true)
  assert.deepEqual(traits.moves, [])
  assert.deepEqual(traits.moving, ['particles'])
  assert.equal(traits.background, 'still')
  assert.equal(traits.travel, 'none')
  assert.equal(traits.format, 'landscape')
})

test('a camera push, a slow drift and a crane are named by what the view does', () => {
  const push = traitsOf([PLATE, STILL_FIGURE, layer('camera', 'camera', { x: 50, y: 50, scale: 1 }, { x: 50, y: 50, scale: 1.12 })])
  assert.deepEqual(push.moves, ['push'])
  assert.deepEqual(push.moving, ['camera'])
  assert.equal(push.holdShare, 0)
  assert.equal(push.background, 'drift', 'the plate moves on screen')
  const drift = traitsOf([PLATE, STILL_FIGURE, layer('camera', 'camera', { x: 48, y: 50, scale: 1.02 }, { x: 52, y: 50, scale: 1.04 })])
  assert.deepEqual(drift.moves, ['drift'])
  const crane = traitsOf([PLATE, STILL_FIGURE, layer('camera', 'camera', { x: 50, y: 62, scale: 1.2 }, { x: 50, y: 47, scale: 1 })])
  assert.deepEqual(crane.moves, ['pull', 'rise'])
  const shake = traitsOf([PLATE, STILL_FIGURE, layer('camera', 'camera', { x: 44, y: 50, scale: 1 }, { x: 60, y: 50, scale: 1 }, { animation: { start: pose({ x: 44, y: 50, scale: 1 }), end: pose({ x: 60, y: 50, scale: 1 }), duration: DURATION, curve: 'linear', shake: { amount: 1, frequency: 8, seed: 1 } } })])
  assert.deepEqual(shake.moves, ['slide', 'shake'])
})

test('a figure that hops on the beat bounces and dances; a held stretch is counted in the hold share', () => {
  const hops = keyed('subject_1', [0, 1, 2, 3, 4].map(time => ({ time, x: 50, y: time % 2 ? 56 : 60, scale: .8 })))
  const traits = traitsOf([PLATE, hops])
  assert.deepEqual(traits.moves, ['bounce'])
  assert.ok(traits.uses.includes('dance') && traits.uses.includes('music'))
  assert.equal(traits.holdShare, 0)
  const pause = keyed('subject_1', [{ time: 0, x: 20, y: 60, scale: .8, curve: 'hold' }, { time: 3, x: 20, y: 60, scale: .8 }, { time: 4, x: 60, y: 60, scale: .8 }])
  const held = traitsOf([PLATE, pause])
  assert.ok(Math.abs(held.holdShare - .75) <= .02, String(held.holdShare))
  assert.equal(held.still, true)
})

test('a figure that crosses from one edge to the other travels across and serves as a transition', () => {
  const flight = keyed('subject_1', [{ time: 0, x: -30, y: 55, scale: .8 }, { time: 4, x: 130, y: 50, scale: .8 }])
  const traits = traitsOf([PLATE, flight])
  assert.equal(traits.travel, 'cross')
  assert.deepEqual(traits.uses, ['music', 'transition', 'entrance', 'exit'])
  const exit = keyed('subject_1', [{ time: 0, x: 50, y: 50, scale: .9 }, { time: 4, x: 50, y: 50, scale: .02, rotation: 720, opacity: 0 }])
  const spiral = traitsOf([PLATE, exit])
  assert.equal(spiral.travel, 'out')
  assert.deepEqual(spiral.moves, ['spin'])
  assert.ok(spiral.uses.includes('exit') && !spiral.uses.includes('entrance'))
})

test('an orbiting object, a scrolling plate and a two-figure conversation are read from the layers', () => {
  const orbit = layer('prop_1', 'image', { x: 50, y: 50, scale: .2 }, { x: 50, y: 50, scale: .2 },
    { animation: { start: pose({ x: 50, y: 50, scale: .2 }), end: pose({ x: 50, y: 50, scale: .2 }), duration: DURATION, curve: 'linear', orbit: { targetLayerId: 'subject_1', radiusX: 20, radiusY: 10, turns: 1, phase: 0, count: 3 } } })
  const orbiting = traitsOf([PLATE, STILL_FIGURE, orbit])
  assert.deepEqual(orbiting.moves, ['orbit'])
  assert.deepEqual(orbiting.moving, ['props'])
  assert.equal(orbiting.props, 1)
  const strip = layer('background', 'image', { x: 50, y: 50, scale: 1.15 }, { x: 50, y: 50, scale: 1.15 }, { fill: true, strip: { enabled: true, count: 3, spacing: 100, direction: 'left', speed: 40 } })
  const scrolling = traitsOf([strip, STILL_FIGURE])
  assert.equal(scrolling.background, 'strip')
  assert.deepEqual(scrolling.moving, ['background'])
  const talk = traitsOf([PLATE, layer('subject_1', 'image', { x: 33, y: 62, scale: .85 }), layer('subject_2', 'image', { x: 67, y: 62, scale: .85 }),
    layer('camera', 'camera', { x: 50, y: 50, scale: 1 }, { x: 50, y: 50, scale: 1.1 })], 'cinema', 'cinema-two')
  assert.equal(talk.subjects, 2)
  assert.deepEqual(talk.uses, ['dialogue'])
})

test('a portrait document says so, and texts count as moving text', () => {
  const traits = traitsOf([PLATE, STILL_FIGURE], 'music', 'music-test', {
    width: 1080, height: 1920,
    texts: [{ id: 'title', text: 'Hola', template: 'title-card', start: 0, duration: 2, x: 50, y: 50 }],
  })
  assert.equal(traits.format, 'portrait')
  assert.ok(traits.moving.includes('text'))
})
