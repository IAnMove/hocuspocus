// The defects the real-asset review renders showed (2026-10-12), measured on the compiled documents with the real
// evaluator and real picture shapes: a 1:3 full-body cutout, a 1:1.9 bottle, a 3:1 ship, 16:9 plates.
import assert from 'node:assert/strict'
import test from 'node:test'
import { compileCandidateScene, type TemplateControlInput } from '../src/features/sceneTemplates/compile.ts'
import { createSceneEvaluator } from '../src/lib/scene2d/evaluate.ts'
import { normalizeScene2D } from '../src/lib/scene2d/normalize.ts'
import { normalizedStrip, stripFlipCss, stripOffsets } from '../src/lib/scene2d/layerStyle.ts'
import { applyStripFlip } from '../src/lib/scene2d/paint.ts'
import type { AnimatorLayer } from '../src/lib/scene2d/types.ts'
import type { Scene } from '../src/types/index.ts'
import { drawnRects, overlaps, textRect, worstOverflow } from './sceneTemplateFrame.ts'

const FIGURE = 1 / 3
const BOTTLE = 1 / 1.9
const SHIP = 3
const picture = (name: string) => ({ type: 'image' as const, source: `/api/v1/file/${name}.png` })
const pictures = (...slots: string[]) => Object.fromEntries(slots.map(slot => [slot, picture(slot)]))
const SAMPLES = 48

test('scroll strips mirror every other copy and the copies touch, so a plate that is not seamless meets itself', () => {
  for (const [id, axis] of [['music-speed-flight', 'x'], ['music-infinite-fall', 'y'], ['music-conveyor', 'x']] as const) {
    const scene = normalizeScene2D(compileCandidateScene(id, pictures('subject_1', 'background')))
    const strip = scene.layers.find(layer => layer.id === 'background-scroll')!
    assert.equal(strip.strip?.mirror, true, id)
    const evaluator = createSceneEvaluator(scene)
    for (let index = 0; index <= SAMPLES; index += 1) {
      // A filled copy is drawn as its whole box: the frame times the copy's scale (camera zoom included).
      const copies = evaluator.renderedLayerStates(strip, index / SAMPLES)
        .map(state => ({ ...state, px: scene.width * state.x / 100, py: scene.height * state.y / 100, size: (axis === 'x' ? scene.width : scene.height) * state.scale }))
        .sort((a, b) => axis === 'x' ? a.px - b.px : a.py - b.py)
      for (let at = 1; at < copies.length; at += 1) {
        const [before, after] = [copies[at - 1], copies[at]]
        // Measured centre to centre in pixels, so the camera's slight roll does not count as a gap.
        const gap = Math.hypot(after.px - before.px, after.py - before.py) - (before.size + after.size) / 2
        assert.ok(Math.abs(gap) < 1e-6, `${id} copies touch (gap ${gap} px)`)
        assert.notEqual(Boolean(before.flip), Boolean(after.flip), `${id} neighbours alternate plain and mirrored`)
        assert.equal(after.flip ?? before.flip, axis, `${id} mirrors along its scroll axis`)
      }
      const rects = drawnRects(scene, strip.id, 16 / 9, index / SAMPLES)
      assert.ok(axis === 'x' ? Math.min(...rects.map(r => r.left)) <= 0 && Math.max(...rects.map(r => r.right)) >= 100
        : Math.min(...rects.map(r => r.top)) <= 0 && Math.max(...rects.map(r => r.bottom)) >= 100, `${id} copies cover the frame`)
    }
  }
})

test('the painter and the editor flip a mirrored copy the same way, and a mirrored loop has an even count', () => {
  const calls: number[][] = []
  applyStripFlip({ scale: (x: number, y: number) => void calls.push([x, y]) }, { flip: 'x' })
  applyStripFlip({ scale: (x: number, y: number) => void calls.push([x, y]) }, { flip: 'y' })
  applyStripFlip({ scale: (x: number, y: number) => void calls.push([x, y]) }, {})
  assert.deepEqual(calls, [[-1, 1], [1, -1]])
  assert.deepEqual([stripFlipCss({ flip: 'x' }), stripFlipCss({ flip: 'y' }), stripFlipCss({})], [' scaleX(-1)', ' scaleY(-1)', ''])
  assert.equal(normalizedStrip({ enabled: true, count: 5, spacing: 50, direction: 'left', speed: 1, mirror: true }).count, 6)
  assert.equal(normalizedStrip({ enabled: true, count: 5, spacing: 50, direction: 'left', speed: 1 }).count, 5)
  const layer = { strip: { enabled: true, count: 4, spacing: 100, direction: 'up', speed: 10, mirror: true } } as unknown as AnimatorLayer
  assert.deepEqual(stripOffsets(layer, 0).map(offset => offset.flip), [undefined, 'y', undefined, 'y'])
  assert.deepEqual(stripOffsets({ strip: { ...layer.strip, mirror: false } } as unknown as AnimatorLayer, 0).map(offset => offset.flip), [undefined, undefined, undefined, undefined])
})

const durations: TemplateControlInput[] = [{}, { duration: 3 }, { duration: 12 }]
const drifts: TemplateControlInput[] = [{ drift: 0 }, { drift: 1 }, { drift: 1, duration: 12 }]

test('a product or a detail object stays whole in frame with a margin, whatever its shape', () => {
  for (const id of ['cinema-detail', 'music-product']) {
    for (const controls of [...durations, ...(id === 'music-product' ? drifts : [])]) {
      const scene = compileCandidateScene(id, pictures('subject_1', 'background'), controls)
      for (const aspect of [BOTTLE, SHIP, 1, 16 / 9]) {
        const overflow = worstOverflow(scene, 'subject_1', aspect)
        assert.ok(overflow <= -1, `${id} ${JSON.stringify(controls)} aspect ${aspect.toFixed(2)}: cut by ${overflow.toFixed(1)} %`)
      }
    }
  }
})

test('music-staircase-pop keeps the whole figure in frame on every step, the camera following it up', () => {
  for (const controls of [...durations, { drift: 0 }]) {
    const scene = compileCandidateScene('music-staircase-pop', pictures('subject_1', 'background'), controls)
    for (const aspect of [FIGURE, BOTTLE]) assert.ok(worstOverflow(scene, 'subject_1', aspect) <= -2, `${JSON.stringify(controls)} aspect ${aspect.toFixed(2)}`)
  }
  for (const controls of drifts.slice(1)) {
    const scene = compileCandidateScene('music-staircase-pop', pictures('subject_1', 'background'), controls)
    assert.ok(worstOverflow(scene, 'subject_1', FIGURE) <= 0, `${JSON.stringify(controls)} with the strongest drift`)
  }
})

const SPACE: Array<[string, string[]]> = [
  ['space-cruise', ['subject_1']], ['space-orbit', ['subject_1', 'prop_1']], ['space-docking', ['subject_1', 'prop_1']],
  ['space-chase', ['subject_1', 'prop_1']], ['space-broadside', ['subject_1', 'prop_1']], ['space-warp', ['subject_1']],
]

test('3:1 picture ships (and a ringed planet or a station) stay inside the frame on every space card', () => {
  for (const [id, ships] of SPACE) {
    for (const controls of [...durations, ...(id === 'space-broadside' ? [{ outcome: 'shield' }, { outcome: 'explode' }, { outcome: 'shield', duration: 12 }] : [])]) {
      const scene = compileCandidateScene(id, pictures('background', ...ships), controls)
      for (const slot of ships) {
        for (const aspect of [SHIP, 2, 1]) {
          const overflow = worstOverflow(scene, slot, aspect)
          assert.ok(overflow <= -2, `${id} ${JSON.stringify(controls)} ${slot} aspect ${aspect}: ${overflow.toFixed(1)} %`)
        }
      }
    }
  }
  const glb = compileCandidateScene('space-broadside', { background: picture('space'), subject_1: { type: 'model3d', source: '/api/v1/file/a.glb' }, prop_1: { type: 'model3d', source: '/api/v1/file/b.glb' } })
  assert.equal(glb.layers.find(layer => layer.id === 'subject_1')!.transform.scale, .64, 'a GLB ship keeps its viewer scale')
})

const at = (scene: Scene, id: string, time: number) => drawnRects(scene, id, SHIP, time)[0]

test('space-broadside: each picture ship keeps to its half, both ships bob, the first recoils and the beams read', () => {
  for (const outcome of ['miss', 'shield', 'explode']) {
    const scene = compileCandidateScene('space-broadside', pictures('background', 'subject_1', 'prop_1'), { outcome })
    for (let index = 0; index <= SAMPLES; index += 1) {
      assert.ok(at(scene, 'subject_1', index / SAMPLES).right < 50, `${outcome}: the first ship stays in the left half`)
      assert.ok(at(scene, 'prop_1', index / SAMPLES).left > 50, `${outcome}: the rival stays in the right half`)
    }
    for (const id of ['subject_1', 'prop_1']) {
      const frames = scene.layers.find(layer => layer.id === id)!.animation.keyframes!
      assert.ok(new Set(frames.map(frame => frame.y.toFixed(2))).size > 10, `${outcome}: ${id} bobs`)
    }
    const hero = scene.layers.find(layer => layer.id === 'subject_1')!.animation.keyframes!
    assert.ok(Math.min(...hero.map(frame => frame.x)) < 27.2, `${outcome}: the first ship recoils when it fires`)
    // The bolt: an 8:1 picture, long and thick enough to read, flying from the first ship across the gap into the rival.
    const beam = scene.layers.find(layer => layer.id === 'beam-0')!
    const shape = decodeURIComponent(beam.source).match(/width="(\d+)" height="(\d+)"/)!
    const aspect = Number(shape[1]) / Number(shape[2])
    assert.equal(aspect, 8)
    const flight = [.21, .25, .28].map(time => drawnRects(scene, 'beam-0', aspect, time)[0])
    const evaluator = createSceneEvaluator(normalizeScene2D(scene))
    assert.ok([.21, .25, .28].every(time => evaluator.renderedLayerStates(normalizeScene2D(scene).layers.find(layer => layer.id === 'beam-0')!, time)[0].opacity > .9), `${outcome}: the bolt is fully lit in flight`)
    for (const rect of flight) {
      assert.ok(rect.right - rect.left >= 20, `${outcome}: the bolt is long (${(rect.right - rect.left).toFixed(1)} % of the width)`)
      assert.ok(rect.bottom - rect.top >= 7, `${outcome}: the bolt is thick (${(rect.bottom - rect.top).toFixed(1)} % of the height, rotated)`)
    }
    assert.ok(flight[0].left <= at(scene, 'subject_1', .21).right, `${outcome}: the bolt leaves the first ship`)
    assert.ok(flight[2].right >= at(scene, 'prop_1', .28).left + 5, `${outcome}: the bolt reaches into the rival`)
  }
  const shielded = normalizeScene2D(compileCandidateScene('space-broadside', pictures('background', 'subject_1', 'prop_1'), { outcome: 'shield' }))
  const shield = createSceneEvaluator(shielded).renderedLayerStates(shielded.layers.find(layer => layer.id === 'impact-shield')!, .32)[0]
  const rival = at(shielded as unknown as Scene, 'prop_1', .32)
  assert.ok(shield.opacity > .9 && shield.x > rival.left && shield.x < rival.right, 'the shield lights up over the rival')
  const exploded = normalizeScene2D(compileCandidateScene('space-broadside', pictures('background', 'subject_1', 'prop_1'), { outcome: 'explode' }))
  const evaluate = createSceneEvaluator(exploded)
  const flash = evaluate.renderedLayerStates(exploded.layers.find(layer => layer.id === 'explosion-flash')!, .53)[0]
  assert.ok(flash.opacity > .9 && flash.scale >= .5, 'the rival explodes in a flash')
  assert.equal(evaluate.renderedLayerStates(exploded.layers.find(layer => layer.id === 'prop_1')!, .6)[0].opacity, 0, 'and is gone')
})

/** Every sample in which the cue is on screen, its rect against the subject's drawn rect. */
function titleOverSubject(scene: Scene, aspect: number): string[] {
  const hits: string[] = []
  for (let index = 0; index <= SAMPLES; index += 1) {
    const seconds = index / SAMPLES * scene.duration
    const subject = drawnRects(scene, 'subject_1', aspect, index / SAMPLES)[0]
    for (const cue of scene.texts ?? []) {
      if (seconds < cue.start || seconds > cue.end) continue
      if (overlaps(textRect(cue, scene), subject)) hits.push(`${cue.id} at ${seconds.toFixed(1)} s`)
    }
  }
  return [...new Set(hits)]
}

test('documentary-history keeps the counter, the date and the caption clear of a centred subject', () => {
  const fields = { caption: 'The harbour keeps the light through the long winter', yearFrom: '1961', yearTo: '1968', yearLabel: 'Year' }
  for (const frame of [{}, { width: 1080, height: 1920 }]) {
    for (const controls of [{}, { duration: 12 }]) {
      const scene = compileCandidateScene('documentary-history', pictures('subject_1', 'background'), { ...fields, ...controls }, frame)
      assert.deepEqual(scene.texts?.map(cue => cue.id), ['date', 'caption', 'count', 'label'])
      for (const aspect of [FIGURE, BOTTLE]) assert.deepEqual(titleOverSubject(scene, aspect), [], `${JSON.stringify(frame)} ${JSON.stringify(controls)} aspect ${aspect.toFixed(2)}`)
      for (const cue of scene.texts ?? []) assert.ok(cue.y >= 12 && cue.y <= 88, `${cue.id} stays in the title-safe band`)
    }
  }
})

test('city-postcard keeps the banner above the figure, never across its head', () => {
  for (const frame of [{}, { width: 1080, height: 1920 }]) {
    for (const controls of [{}, { duration: 12 }]) {
      const scene = compileCandidateScene('city-postcard', pictures('subject_1', 'background'), { banner: 'Salt on the windows', ...controls }, frame)
      for (const aspect of [FIGURE, BOTTLE]) assert.deepEqual(titleOverSubject(scene, aspect), [], `${JSON.stringify(frame)} ${JSON.stringify(controls)} aspect ${aspect.toFixed(2)}`)
    }
  }
})
