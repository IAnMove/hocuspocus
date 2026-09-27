import assert from 'node:assert/strict'
import test from 'node:test'
import { createSceneEvaluator } from '../src/lib/scene2d/evaluate.ts'
import { stripOffsets } from '../src/lib/scene2d/layerStyle.ts'
import { breakDependencyCycles, normalizeScene2D } from '../src/lib/scene2d/normalize.ts'
import type { AnimatorLayer, AnimatorScene } from '../src/lib/scene2d/types.ts'

function layer(id: string, overrides: Partial<AnimatorLayer> = {}): AnimatorLayer {
  return {
    id, name: id, type: 'image', source: `/api/v1/file/${id}.png`, visible: true, z: 0,
    transform: { x: 50, y: 50, scale: 1, opacity: 1 },
    animation: { start: { x: 20, y: 50, scale: 1 }, end: { x: 80, y: 50, scale: 1 }, duration: 4, curve: 'linear' },
    ...overrides,
  } as AnimatorLayer
}

function scene(layers: AnimatorLayer[], duration = 4): AnimatorScene {
  return { version: 1, name: 'test', width: 1920, height: 1080, fps: 24, duration, layers }
}

test('normalizeScene2D matches the editor import: bounded size, fps and z-order', () => {
  const normalized = normalizeScene2D({ ...scene([layer('b', { z: 20 }), layer('a', { z: 5 })]), width: 99999, fps: 23 })
  assert.equal(normalized.width, 7680)
  assert.equal(normalized.fps, 30)
  assert.deepEqual(normalized.layers.map(item => [item.id, item.z]), [['a', 0], ['b', 10]])
  assert.throws(() => normalizeScene2D({ version: 1, layers: [layer('x'), layer('x')] }), /unique id/)
  assert.throws(() => normalizeScene2D({ version: 1, layers: [{ ...layer('x'), type: 'hologram' }] }), /Unsupported scene layer type/)
})

test('evaluator interpolates motion and applies the active camera', () => {
  const moving = layer('hero')
  const evaluator = createSceneEvaluator(scene([moving]))
  assert.equal(Math.round(evaluator.layerState(moving, 0.5).x), 50)
  const camera = layer('cam', { type: 'camera', source: '', z: 100, animation: { start: { x: 50, y: 50, scale: 2 }, end: { x: 50, y: 50, scale: 2 }, duration: 4, curve: 'linear' } })
  const zoomed = createSceneEvaluator(scene([moving, camera]))
  const [state] = zoomed.renderedLayerStates(moving, 1)
  assert.equal(Math.round(state.x), 110)
  assert.equal(state.scale, 2)
})

test('dependency cycles are broken before evaluation', () => {
  const a = layer('a', { relationship: { type: 'follow', targetLayerId: 'b' } })
  const b = layer('b', { relationship: { type: 'follow', targetLayerId: 'a' } })
  const [first, second] = breakDependencyCycles([a, b])
  assert.equal(first.relationship, undefined)
  assert.equal(second.relationship?.targetLayerId, 'a')
})

test('strip offsets wrap copies around the frame', () => {
  const offsets = stripOffsets(layer('strip', { strip: { enabled: true, count: 3, spacing: 30, direction: 'left', speed: 10 } }), 0)
  assert.deepEqual(offsets.map(item => item.x), [-30, 0, 30])
})
