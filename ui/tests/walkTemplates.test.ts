import assert from 'node:assert/strict'
import test from 'node:test'
import { compileCandidateScene, type TemplateControlInput } from '../src/features/sceneTemplates/compile.ts'
import { candidateDemoBindings } from '../src/features/sceneTemplates/demoScenes.ts'
import { createSceneEvaluator } from '../src/lib/scene2d/evaluate.ts'
import { normalizeScene2D } from '../src/lib/scene2d/normalize.ts'
import type { Scene, SceneLayer } from '../src/types/index.ts'

const compile = (id: string, controls: TemplateControlInput = {}) => compileCandidateScene(id, candidateDemoBindings(id), controls)
const layerOf = (scene: Scene, id: string): SceneLayer => scene.layers.find(layer => layer.id === id)!
const framesOf = (scene: Scene, id: string) => layerOf(scene, id).animation.keyframes!

/** Peaks of a series: the samples lower than both neighbours (y grows downward: mid-step lifts the figure). */
const peaks = (values: number[]) => values.filter((value, index) => index > 0 && index < values.length - 1 && value < values[index - 1] && value <= values[index + 1]).length

test('follow-back and toward-camera hold the figure still on screen while the room travels', () => {
  for (const [id, direction] of [['walk-follow-back', 1], ['walk-toward-camera', -1]] as const) {
    const scene = compile(id)
    const subject = layerOf(scene, 'subject_1')
    assert.equal(subject.parallax, 0, `${id}: the camera does not move the figure`)
    assert.equal(subject.parallaxZoom, true, `${id}: nor does it zoom it`)
    assert.deepEqual([layerOf(scene, 'background').parallax, layerOf(scene, 'background').parallaxZoom], [.5, true])
    const zoom = framesOf(scene, 'camera').map(frame => frame.scale)
    assert.ok((zoom[zoom.length - 1] - zoom[0]) * direction > .3, `${id}: the camera ${direction > 0 ? 'pushes in' : 'backs away'}`)
    const evaluator = createSceneEvaluator(normalizeScene2D(scene))
    const normalized = normalizeScene2D(scene)
    const figure = normalized.layers.find(layer => layer.id === 'subject_1')!
    const drawn = [0, .5, 1].map(time => evaluator.renderedLayerStates(figure, time)[0].scale)
    assert.ok(Math.max(...drawn) - Math.min(...drawn) < .02, `${id}: the figure keeps its size (${drawn.join(', ')})`)
  }
})

test('the waist-up figure has its head near the top and its boots below the frame', () => {
  for (const framing of ['waist', 'chest']) {
    const first = framesOf(compile('walk-follow-back', { framing }), 'subject_1')[0]
    assert.ok(Math.abs((first.y - 50 * first.scale) - 8) < 1e-6, `${framing}: head room 8 %`)
    assert.ok(first.y + 50 * first.scale > 140, `${framing}: the feet are far below the frame`)
  }
  assert.ok(framesOf(compile('walk-follow-back', { framing: 'chest' }), 'subject_1')[0].scale > framesOf(compile('walk-follow-back'), 'subject_1')[0].scale)
})

test('a walk takes a whole number of steps and a longer shot takes more steps, not slower ones', () => {
  for (const [duration, step] of [[6, .55], [12, .55], [6, .4]] as const) {
    const frames = framesOf(compile('walk-follow-back', { duration, step }), 'subject_1')
    const steps = Math.round(duration / step)
    assert.equal(peaks(frames.map(frame => frame.y)), steps, `${duration} s at ${step}: the figure rises once in each of ${steps} steps`)
    assert.ok(Math.abs(frames[frames.length - 1].time - duration) < 1e-6)
    assert.ok(Math.max(...frames.map(frame => Math.abs(frame.rotation))) > 1, 'the figure leans onto the planted foot')
  }
  const first = framesOf(compile('walk-follow-back', { sway: 0 }), 'subject_1')
  assert.equal(Math.max(...first.map(frame => Math.abs(frame.rotation))), 0, 'sway 0 keeps the figure upright')
})

test('behind-foreground needs the covering foreground, keeps it sharp and walks the figure the way it looks', () => {
  assert.throws(() => compileCandidateScene('walk-behind-foreground', { subject_1: candidateDemoBindings('walk-two-pose').subject_1, background: candidateDemoBindings('walk-two-pose').background }), /foreground/)
  for (const [facing, off] of [['right', (x: number) => x < 0], ['left', (x: number) => x > 100]] as const) {
    const scene = compile('walk-behind-foreground', { facing })
    const frames = framesOf(scene, 'subject_1')
    assert.ok(off(frames[0].x), `facing ${facing}: comes in from behind its back`)
    assert.ok(Math.abs(frames[frames.length - 1].x - 50) < 5, `facing ${facing}: stops on its mark`)
    assert.equal(layerOf(scene, 'subject_1').focus?.y, 99, 'the figure turns about its boots')
    const front = layerOf(scene, 'foreground')
    assert.ok(front.z > layerOf(scene, 'subject_1').z, 'the foreground is in front of the figure')
    assert.deepEqual([front.effects?.blur, front.effects?.brightness], [0, 1])
  }
})

test('shadow-first: the shadow crosses an empty wall, then the figure appears on its mark', () => {
  const scene = compile('walk-shadow-first')
  const shadow = layerOf(scene, 'shadow')
  assert.deepEqual([shadow.effects?.brightness, shadow.source], [0, layerOf(scene, 'subject_1').source], 'the shadow is the figure, black')
  const seen = framesOf(scene, 'shadow').filter(frame => frame.opacity > .5).map(frame => frame.time / scene.duration)
  assert.ok(Math.min(...seen) < .1 && Math.max(...seen) < .4, 'the shadow comes first')
  const figure = framesOf(scene, 'subject_1')
  const appears = figure.find(frame => frame.opacity > .5)!
  assert.ok(appears.time / scene.duration > .4 && appears.time / scene.duration < .45, 'the figure is there as the shadow fades')
  assert.equal(figure.filter(frame => frame.time < appears.time).every(frame => frame.opacity === 0), true)
})

test('two-pose: the stride and the legs together take turns, the shadow beats and the figure stops legs together', () => {
  const scene = compile('walk-two-pose', { step: .5 })
  const stride = framesOf(scene, 'subject_1')
  const closed = framesOf(scene, 'subject_2')
  const ground = framesOf(scene, 'contact-shadow')
  assert.deepEqual(stride.map(frame => frame.time), closed.map(frame => frame.time), 'both pictures share their beats')
  assert.ok(stride.every((frame, index) => frame.opacity + closed[index].opacity === 1), 'exactly one of them shows at every beat')
  // Opacity switches within one frame (1/60 s) while the figure's place moves on linearly.
  const swaps = stride.flatMap((frame, index) => index && frame.opacity !== stride[index - 1].opacity ? [frame.time - stride[index - 1].time] : [])
  assert.ok(swaps.length >= 7 && swaps.length % 2 === 1 && swaps.every(gap => gap < 1 / 59), `${swaps.length} swaps (two on every step, one to stop), each inside a frame`)
  const hidden = (frames: typeof stride, time: number) => frames.filter(frame => frame.time <= time + 1e-9).pop()!.opacity
  const step = .5
  const first = stride.find(frame => frame.opacity === 1 && frame.x > 0)!.time
  assert.equal(hidden(stride, first + step * .1), 1, 'legs apart on the footfall')
  assert.equal(hidden(closed, first + step * .5), 1, 'legs together in mid-step')
  const feet = stride.map(frame => frame.x)
  assert.ok(feet[0] < 0 && Math.abs(feet[feet.length - 1] - 50) < 5, 'it comes in and stops on its mark')
  assert.equal(closed[closed.length - 1].opacity, 1, 'it ends with its legs together')
  const pressed = ground.filter(frame => frame.opacity >= .89).length
  assert.ok(pressed >= 5, `the shadow is full on every footfall (${pressed})`)
  assert.ok(ground.some(frame => frame.opacity < .6), 'and lighter when a foot is up')
  assert.ok(layerOf(scene, 'contact-shadow').z < layerOf(scene, 'subject_1').z, 'it lies under the figure')
  for (const id of ['subject_1', 'subject_2']) assert.equal(layerOf(scene, id).focus?.y, 99, 'both turn about their boots')
})

test('two-pose paces the walk by its step: a shorter step is a slower figure that arrives later, and facing left flips the side', () => {
  const arrival = (step: number) => framesOf(compile('walk-two-pose', { step }), 'subject_1').find(frame => frame.x >= 47)!.time
  assert.ok(arrival(.7) > arrival(.4) + .5, `${arrival(.7)} later than ${arrival(.4)}`)
  const left = framesOf(compile('walk-two-pose', { facing: 'left' }), 'subject_1')
  assert.ok(left[0].x > 100 && left[left.length - 1].x < 55 && left[left.length - 1].x > 45)
  assert.throws(() => compileCandidateScene('walk-two-pose', { subject_1: candidateDemoBindings('walk-two-pose').subject_1, background: candidateDemoBindings('walk-two-pose').background }), /subject_2/)
})

test('walk-cycle-sheet plays its sheet at the pace that keeps the boots on the floor', () => {
  const scene = compile('walk-cycle-sheet')
  const figure = layerOf(scene, 'subject_1')
  assert.deepEqual([figure.sequence?.kind, figure.sequence?.source], ['sheet', figure.source])
  assert.deepEqual([(figure.sequence as { count: number }).count, (figure.sequence as { columns: number }).columns, (figure.sequence as { rows: number }).rows], [4, 4, 1])
  assert.equal(figure.focus?.y, 96)
  const frames = framesOf(scene, 'subject_1')
  assert.ok(frames[0].x < -5 && frames[frames.length - 1].x > 105, 'the figure crosses the whole shot')
  const fps = (figure.sequence as { fps: number }).fps
  assert.ok(fps >= 3 && fps <= 24)
  // A longer shot does not slow the feet: the cadence and the speed are the step's, so the crossing takes as long.
  const cadence = (scene: Scene) => (layerOf(scene, 'subject_1').sequence as { fps: number }).fps
  const crossing = (scene: Scene) => {
    const track = framesOf(scene, 'subject_1')
    return track.find(frame => frame.x >= 112 - 1e-6)!.time - track.filter(frame => frame.x <= -12 + 1e-6).pop()!.time
  }
  const long = compile('walk-cycle-sheet', { duration: 12 })
  assert.equal(cadence(long), fps)
  assert.ok(Math.abs(crossing(long) - crossing(scene)) < 1e-6 && crossing(scene) < scene.duration, 'it leaves the shot when its feet have covered the ground')
  assert.ok(cadence(compile('walk-cycle-sheet', { step: .9 })) < fps, 'a longer step is a slower cycle')
  const reverse = framesOf(compile('walk-cycle-sheet', { facing: 'left' }), 'subject_1')
  assert.ok(reverse[0].x > 105 && reverse[reverse.length - 1].x < -5, 'facing left crosses from the right')
  const sheet = compile('walk-cycle-sheet', { frames: 8, columns: 4 }).layers.find(layer => layer.id === 'subject_1')!.sequence as { count: number; columns: number; rows: number }
  assert.deepEqual([sheet.count, sheet.columns, sheet.rows], [8, 4, 2])
})

test('character-reaction: the figure pops in on its mark, plays its sheet once and holds, then breathes', () => {
  const scene = compile('character-reaction')
  const figure = layerOf(scene, 'subject_1')
  const sequence = figure.sequence as { kind: string; count: number; columns: number; rows: number; fps: number; loop: string }
  assert.deepEqual([sequence.kind, sequence.count, sequence.columns, sequence.rows, sequence.fps, sequence.loop], ['sheet', 2, 2, 1, 4, 'once'])
  assert.equal(figure.focus?.y, 96, 'the figure stands on the sheet\'s ground line')
  const frames = framesOf(scene, 'subject_1')
  assert.deepEqual([frames[0].opacity, frames[1].opacity], [0, 1], 'it pops in during the first beat')
  assert.ok(frames[0].scale < frames[1].scale && Math.abs(frames[1].x - 50) < 1e-6)
  assert.ok(frames.length > 6 && frames.every(frame => frame.opacity >= 0 && frame.opacity <= 1), 'then it breathes')
  assert.ok(layerOf(scene, 'contact-shadow').z < figure.z, 'a whole figure has a shadow under it')
})

test('character-reaction: a bust stands on the bottom edge, the mark and the loop are chosen, and every control reaches the sheet', () => {
  const bust = compile('character-reaction', { framing: 'bust', mark: 'left', loop: 'pingpong', frames: 4, columns: 2, fps: 6 })
  const figure = layerOf(bust, 'subject_1')
  assert.deepEqual((figure.sequence as { count: number; columns: number; rows: number; fps: number; loop: string }), { kind: 'sheet', source: figure.source, count: 4, columns: 2, rows: 2, fps: 6, loop: 'pingpong' } as never)
  const frames = framesOf(bust, 'subject_1')
  assert.ok(frames[1].y >= 100 && Math.abs(frames[1].x - 30) < 1e-6, 'the bust stands on the frame\'s bottom, on the left mark')
  assert.equal(bust.layers.some(item => item.id === 'contact-shadow'), false, 'a bust has no floor to cast a shadow on')
  assert.ok(Math.abs(compile('character-reaction', { mark: 'right' }).layers.find(item => item.id === 'subject_1')!.animation.keyframes![1].x - 70) < 1e-6)
  // A sheet that is played once holds its last pose from its own end; a longer shot only breathes for longer.
  const short = framesOf(compile('character-reaction', { duration: 3 }), 'subject_1').length
  assert.ok(framesOf(compile('character-reaction', { duration: 12 }), 'subject_1').length > short)
})
