import assert from 'node:assert/strict'
import test from 'node:test'
import { ALL_SCENE_TEMPLATES } from '../src/features/sceneTemplates/catalog.ts'
import { compileCandidateScene, type TemplateControlInput } from '../src/features/sceneTemplates/compile.ts'
import { candidateDemoBindings } from '../src/features/sceneTemplates/demoScenes.ts'
import { createSceneEvaluator } from '../src/lib/scene2d/evaluate.ts'
import { normalizeScene2D } from '../src/lib/scene2d/normalize.ts'
import type { Scene } from '../src/types/index.ts'

const SAMPLES = 120

/** Share of the shot in which nothing but particles moves on screen (the review's held share), from the real
 * evaluator: keyframes, strips, orbits and the camera transform. */
function heldShare(scene: Scene): number {
  const normalized = normalizeScene2D(scene)
  const evaluator = createSceneEvaluator(normalized)
  const visual = normalized.layers.filter(layer => layer.type !== 'effect' && layer.type !== 'camera')
  const frame = (time: number) => visual.flatMap(layer => evaluator.renderedLayerStates(layer, time).flatMap(state => [state.x, state.y, state.scale, state.rotation, state.opacity]))
  let held = 0
  let previous = frame(0)
  for (let index = 1; index <= SAMPLES; index += 1) {
    const current = frame(index / SAMPLES)
    if (current.every((value, at) => Math.abs(value - previous[at]) < 1e-4)) held += 1
    previous = current
  }
  return held / SAMPLES
}

const compile = (id: string, controls: TemplateControlInput = {}) => compileCandidateScene(id, candidateDemoBindings(id), controls)
const camera = (scene: Scene) => scene.layers.find(layer => layer.type === 'camera')

test('the reworked cards move for more than half of the shot, even with the camera drift off', () => {
  for (const id of ['music-staircase-pop', 'music-spotlight-relay', 'cinema-two-shot', 'documentary-history', 'city-postcard']) {
    for (const controls of [{}, { drift: 0 }, { duration: 12, drift: 0 }]) {
      if ('drift' in controls && !id.startsWith('music-')) continue
      const share = heldShare(compile(id, controls))
      assert.ok(share < .5, `${id} ${JSON.stringify(controls)} holds ${Math.round(share * 100)} % of the shot`)
    }
  }
  // Before the rework the review measured 79 % and 70 % held; the subject alone now never stops for long.
  assert.ok(heldShare(compile('music-staircase-pop', { drift: 0 })) < .2)
  assert.ok(heldShare(compile('music-spotlight-relay', { drift: 0 })) < .2)
})

test('every music card and choreography has a camera layer that drifts by default and holds at drift 0', () => {
  for (const template of ALL_SCENE_TEMPLATES.filter(item => item.id.startsWith('music-'))) {
    const drifting = compile(template.id)
    const view = camera(drifting)
    assert.ok(view, `${template.id} has a camera layer`)
    const frames = view.animation.keyframes ?? []
    assert.ok(frames.length >= 9 && new Set(frames.map(frame => frame.x.toFixed(3))).size > 3, `${template.id} camera drifts`)
    assert.equal(heldShare(drifting), 0, `${template.id} never holds a frozen frame`)
    const still = camera(compile(template.id, { drift: 0 }))
    assert.ok(still, `${template.id} keeps an editable camera at drift 0`)
  }
  const choreography = camera(compile('music-pendulum', { drift: 0 }))!
  assert.deepEqual([choreography.animation.start, choreography.animation.keyframes], [choreography.animation.end, undefined], 'drift 0 holds the frame still')
  assert.equal(camera(compile('cinema-establishing'))?.animation.keyframes?.length, 2, 'cinema cards keep their own camera, without drift')
})

test('the drift keeps the card camera move: the push still pushes, the beat still pulses', () => {
  const push = camera(compile('music-pulse'))!.animation.keyframes!
  assert.ok(push.at(-1)!.scale - push[0].scale > .06, 'the push survives the drift')
  const beat = camera(compile('music-pulse', { camera: 'beat' }))!.animation.keyframes!
  const peaks = beat.filter((frame, index) => index && index < beat.length - 1 && frame.scale > beat[index - 1].scale && frame.scale > beat[index + 1].scale)
  assert.ok(peaks.length >= 7, `the camera pulses on the beat (${peaks.length} peaks in 4 s at 120 BPM)`)
})

test('motion keeps its speed on long shots: it repeats or travels further instead of slowing down', () => {
  const xs = (scene: Scene, id: string) => scene.layers.find(layer => layer.id === id)!.animation.keyframes!.map(frame => frame.x)
  const turns = (values: number[]) => values.slice(1, -1).filter((value, index) => (value - values[index]) * (values[index + 2] - value) < 0).length
  assert.equal(turns(xs(compile('music-pendulum', { duration: 12 }), 'subject_1')), 3 * turns(xs(compile('music-pendulum'), 'subject_1')))
  const shortPinball = compile('music-pinball').layers.find(layer => layer.id === 'subject_1')!.animation.keyframes!
  const longPinball = compile('music-pinball', { duration: 12 }).layers.find(layer => layer.id === 'subject_1')!.animation.keyframes!
  assert.equal(shortPinball[1].time, longPinball[1].time, 'each bounce takes the same time')
  const orbit = (duration: number) => compile('music-orbit', { duration }).layers.find(layer => layer.id === 'prop_1')!.animation.orbit!.turns
  assert.equal(orbit(12), 3 * orbit(4))
  const travel = (id: string, duration: number) => {
    const frames = camera(compile(id, { duration }))!.animation.keyframes!
    return { x: frames.at(-1)!.x - frames[0].x, end: frames.at(-1)!.x, scale: frames.at(-1)!.scale - frames[0].scale }
  }
  assert.ok(Math.abs(travel('cinema-detail', 12).x - 2 * travel('cinema-detail', 4).x) < 1e-9, 'a long cinema move travels up to twice as far')
  assert.ok(Math.abs(travel('cinema-detail', 8).scale - 2 * travel('cinema-detail', 4).scale) < 1e-9)
  assert.ok(travel('cinema-tracking', 12).x > travel('cinema-tracking', 4).x && travel('cinema-tracking', 12).end <= 70, 'and stops at the frame bounds')
  const relays = (duration: number) => turns(compile('music-spotlight-relay', { duration }).layers.find(layer => layer.id === 'subject_1')!.animation.keyframes!.map(frame => frame.scale))
  assert.ok(relays(12) >= 2 * relays(6), 'the relay repeats through a longer shot')
  const conveyor = compile('music-conveyor', { duration: 12 }).layers.filter(layer => layer.id.startsWith('subject_1'))
  for (const copy of conveyor) {
    const frames = copy.animation.keyframes!
    for (let index = 1; index < frames.length; index += 1) {
      if (frames[index - 1].curve === 'hold') continue
      const speed = (frames[index - 1].x - frames[index].x) / (frames[index].time - frames[index - 1].time)
      assert.ok(Math.abs(speed - 125 / 4) < 1e-6, `${copy.id} keeps the belt speed`)
    }
  }
})

test('cinema-hero enters, the duet takes turns and the two-shot sways', () => {
  for (const entrance of ['rise', 'left', 'right']) {
    const frames = compile('cinema-hero', { entrance }).layers.find(layer => layer.id === 'subject_1')!.animation.keyframes!
    const start = frames[0]
    assert.ok(start.y > 95 || start.x < 0 || start.x > 100, `${entrance}: the figure starts out of frame`)
  }
  const duet = compile('music-duet', { drift: 0 })
  const lift = (id: string) => duet.layers.find(layer => layer.id === id)!.animation.keyframes!.filter(frame => frame.y < 62).map(frame => Math.round(frame.time * 4))
  const first = lift('subject_1')
  const second = lift('subject_2')
  assert.ok(first.length && second.length)
  assert.equal(first.some(time => second.includes(time)), false, 'the two figures never jump on the same beat')
  const sway = compile('cinema-two-shot').layers.find(layer => layer.id === 'subject_2')!.animation.keyframes!
  assert.ok(Math.max(...sway.map(frame => frame.rotation)) > 1, 'the second figure sways')
})

test('the cards fixed after the real-asset review still move for more than half of the shot', () => {
  const picture = (name: string) => ({ type: 'image' as const, source: `/api/v1/file/${name}.png` })
  const cases: Array<[string, TemplateControlInput]> = [
    ['music-speed-flight', { drift: 0 }], ['music-infinite-fall', { drift: 0 }], ['music-conveyor', { drift: 0 }],
    ['cinema-detail', {}], ['music-product', { drift: 0 }], ['music-staircase-pop', { drift: 0 }],
    ['documentary-history', {}], ['city-postcard', {}],
    ['space-broadside', {}], ['space-broadside', { outcome: 'shield' }], ['space-broadside', { outcome: 'explode' }],
    ['space-cruise', {}], ['space-orbit', {}], ['space-docking', {}], ['space-chase', {}], ['space-warp', {}],
  ]
  for (const [id, controls] of cases) {
    const slots = ALL_SCENE_TEMPLATES.find(template => template.id === id)!.slots.filter(slot => slot.required)
    const scene = compileCandidateScene(id, Object.fromEntries(slots.map(slot => [slot.id, picture(slot.id)])), controls)
    const share = heldShare(scene)
    assert.ok(share < .5, `${id} ${JSON.stringify(controls)} holds ${Math.round(share * 100)} % of the shot`)
  }
})
