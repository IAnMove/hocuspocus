import assert from 'node:assert/strict'
import test from 'node:test'
import { FX_CATALOG, AIMED_FX_KINDS, SCENE_FX_SCHEMA, parseSceneFx } from '../src/features/sceneFx/types.ts'
import { fxOrigin, paintSceneFx } from '../src/features/sceneFx/paint.ts'
import { aimedPainters } from '../src/features/sceneFx/stormPaint.ts'
import { createSceneEvaluator } from '../src/lib/scene2d/evaluate.ts'
import { normalizeScene2D } from '../src/lib/scene2d/normalize.ts'
import { layerPicturePoint, type SceneMedia } from '../src/lib/scene2d/paint.ts'
import type { AnimatorLayer, AnimatorScene } from '../src/lib/scene2d/types.ts'

type Move = [string, number[]]

/** A 2D context that keeps its translate, rotate and scale calls in order. */
function recorder(width: number, height: number) {
  const moves: Move[] = []
  const state: Record<string, unknown> = { canvas: { width, height }, fillStyle: '#000', strokeStyle: '#000', globalAlpha: 1,
    globalCompositeOperation: 'source-over', lineWidth: 1, lineCap: 'butt' }
  const gradient = { addColorStop() {} }
  const context = new Proxy(state, {
    get(target, prop, receiver) {
      if (prop === 'createRadialGradient' || prop === 'createLinearGradient') return () => gradient
      if (prop === 'translate' || prop === 'rotate' || prop === 'scale') return (...args: number[]) => { moves.push([prop, args]) }
      if (prop === 'getTransform') return () => ({ a: 1, b: 0, c: 0, d: 1, e: 0, f: 0 })
      if (typeof prop === 'string' && !(prop in target)) return () => {}
      return Reflect.get(target, prop, receiver)
    },
  })
  return { context: context as unknown as CanvasRenderingContext2D, moves }
}

const near = (actual: number, expected: number, tolerance = 1e-6) => assert.ok(Math.abs(actual - expected) <= tolerance, `${actual} is not ${expected}`)

test('a laser or lightning cue keeps its origin; other kinds, bad points and the catalog agree', () => {
  assert.deepEqual([...AIMED_FX_KINDS].sort(), ['laser', 'lightning'])
  assert.deepEqual(Object.keys(aimedPainters).sort(), FX_CATALOG.filter(item => item.aim).map(item => item.id).sort(), 'every aim kind has a painter')
  const [laser, bolt, sparks, broken, far] = parseSceneFx([
    { id: 'a', kind: 'laser', start: 0, end: 1, x: 80, y: 20, from: { layerId: 'kit-guard-pose-base', x: 95, y: 46 } },
    { id: 'b', kind: 'lightning', start: 0, end: 1, from: { x: 10, y: -20 } },
    { id: 'c', kind: 'sparks', start: 0, end: 1, from: { x: 10, y: 20 } },
    { id: 'd', kind: 'laser', start: 0, end: 1, from: { x: 10 } },
    { id: 'e', kind: 'laser', start: 0, end: 1, from: { x: 900, y: -900, layerId: '' } },
  ])
  assert.deepEqual(laser.from, { x: 95, y: 46, layerId: 'kit-guard-pose-base' })
  assert.deepEqual(bolt.from, { x: 10, y: -20 })
  assert.equal(sparks.from, undefined, 'only a beam aims')
  assert.equal(broken.from, undefined)
  assert.deepEqual(far.from, { x: 150, y: -50 }, 'clamped to half a picture outside it')
  const schema = SCENE_FX_SCHEMA.items.properties.from
  assert.deepEqual(schema.required, ['x', 'y'])
  assert.equal(schema.properties.layerId.maxLength, 160)
})

test('a beam starts at its origin and runs to the cue x/y; a layer origin goes through the frame resolver', () => {
  const [laser] = parseSceneFx([{ id: 'a', kind: 'laser', start: 0, end: 1, x: 80, y: 20, size: 50, from: { x: 20, y: 80 } }])
  assert.deepEqual(fxOrigin(laser), { x: 20, y: 80 })
  const { context, moves } = recorder(1000, 500)
  paintSceneFx(context, 1000, 500, .5, [laser])
  assert.deepEqual(moves[0], ['translate', [200, 400]], 'from the origin')
  near(moves[1][1][0], Math.atan2(100 - 400, 800 - 200))
  assert.deepEqual(moves[2], ['scale', [250, 250]], 'size still sets the width')
  const onLayer = { ...laser, from: { layerId: 'guard', x: 95, y: 46 } }
  const asked: unknown[] = []
  assert.deepEqual(fxOrigin(onLayer, (...args) => { asked.push(args); return { x: 30, y: 40 } }), { x: 30, y: 40 })
  assert.deepEqual(asked, [['guard', 95, 46]])
  assert.equal(fxOrigin(onLayer), undefined, 'no resolver (a 3D frame): drawn as a placed cue')
  assert.equal(fxOrigin(onLayer, () => null), undefined, 'the layer is not in the frame')
  const placed = recorder(1000, 500)
  paintSceneFx(placed.context, 1000, 500, .5, [onLayer], undefined, () => null)
  assert.deepEqual(placed.moves[0], ['translate', [800, 100]], 'as before: across the cue point')
})

function sceneWithGuard(camera: boolean): AnimatorScene {
  const still = (x: number, y: number, scale: number) => ({ x, y, scale, opacity: 1, rotation: 0 })
  const guard = { id: 'guard', name: 'Guard', type: 'image', source: '/api/v1/file/guard.png', visible: true, locked: false, z: 20, fill: false,
    parallax: 1, transform: still(30, 60, .8), animation: { start: still(30, 60, .8), end: still(30, 60, .8), duration: 4, curve: 'linear' } }
  const push = { id: 'camera', name: 'Camera', type: 'camera', source: '', visible: true, locked: false, z: 1000, transform: still(50, 50, 1),
    animation: { start: still(50, 50, 1), end: still(50, 50, 1.1), duration: 4, curve: 'linear' } }
  return normalizeScene2D({ version: 1, name: 'shot', width: 1920, height: 1080, fps: 24, duration: 4,
    layers: [guard, ...(camera ? [push] : [])] as unknown as AnimatorLayer[] })
}

test('a point on a layer picture follows its placement, its contained fit and the camera push', () => {
  // A 896 × 1152 pose contained in a 1536 × 864 box (scale 0.8 of a 1920 × 1080 frame) is 672 px wide.
  const picture = { width: 896, height: 1152 } as unknown as SceneMedia
  const canvas = { width: 1920, height: 1080 }
  const still = sceneWithGuard(false)
  const point = layerPicturePoint(canvas, still, createSceneEvaluator(still), () => picture, 0, 0)
  assert.deepEqual(point('guard', 50, 50), { x: 30, y: 60 })
  const edge = point('guard', 100, 0)!
  near(edge.x, 30 + 336 / 1920 * 100); near(edge.y, 60 - 432 / 1080 * 100)
  assert.equal(point('nobody', 50, 50), null)
  const pushed = sceneWithGuard(true)
  const late = layerPicturePoint(canvas, pushed, createSceneEvaluator(pushed), () => picture, 1, 4)
  const centre = late('guard', 50, 50)!, muzzle = late('guard', 100, 0)!
  near(centre.x, 50 + (30 - 50) * 1.1); near(centre.y, 50 + (60 - 50) * 1.1)
  near(muzzle.x, 50 + (edge.x - 50) * 1.1); near(muzzle.y, 50 + (edge.y - 50) * 1.1)
  const unloaded = layerPicturePoint(canvas, still, createSceneEvaluator(still), () => null, 0, 0)('guard', 100, 50)!
  near(unloaded.x, 30 + .8 * 50, 1e-6)
})
