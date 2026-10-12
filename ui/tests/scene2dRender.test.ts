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

test('a depth layer (parallaxZoom) takes its parallax share of the camera zoom; others take all of it', () => {
  const camera = layer('cam', { type: 'camera', source: '', z: 100, animation: { start: { x: 50, y: 50, scale: 2 }, end: { x: 50, y: 50, scale: 2 }, duration: 4, curve: 'linear' } })
  const still = { transform: { x: 60, y: 50, scale: 1, opacity: 1 }, animation: { start: { x: 60, y: 50, scale: 1 }, end: { x: 60, y: 50, scale: 1 }, duration: 4, curve: 'linear' as const } }
  const far = layer('far', { ...still, parallax: 0.25, parallaxZoom: true })
  const flat = layer('flat', { ...still, parallax: 0.25 })
  const evaluator = createSceneEvaluator(scene([far, flat, camera]))
  const [depth] = evaluator.renderedLayerStates(far, 0)
  assert.equal(depth.scale, 1.25)
  assert.equal(depth.x, 62.5, 'positions spread from the centre by the same share')
  assert.equal(evaluator.renderedLayerStates(flat, 0)[0].scale, 2)
  const normalized = normalizeScene2D(scene([far, layer('odd', { parallaxZoom: 'yes' as unknown as boolean }), { ...camera, parallaxZoom: true }]))
  assert.deepEqual(normalized.layers.map(item => [item.id, item.parallaxZoom]), [['far', true], ['odd', undefined], ['cam', undefined]])
})

test('dependency cycles are broken before evaluation', () => {
  const a = layer('a', { relationship: { type: 'follow', targetLayerId: 'b' } })
  const b = layer('b', { relationship: { type: 'follow', targetLayerId: 'a' } })
  const [first, second] = breakDependencyCycles([a, b])
  assert.equal(first.relationship, undefined)
  assert.equal(second.relationship?.targetLayerId, 'a')
})

test('focus keeps an image point on the anchor while scale changes', () => {
  const zoomed = layer('hero', {
    transform: { x: 50, y: 50, scale: 3, opacity: 1 },
    animation: { start: { x: 50, y: 50, scale: 3 }, end: { x: 50, y: 50, scale: 3 }, duration: 4, curve: 'linear' },
    focus: { x: 0, y: 50 },
  })
  const [state] = createSceneEvaluator(scene([zoomed], 4)).renderedLayerStates(zoomed, 0)
  assert.equal(state.x, 200)
  assert.equal(state.y, 50)
  const centered = layer('still', {
    transform: { x: 50, y: 50, scale: 3, opacity: 1 },
    animation: { start: { x: 50, y: 50, scale: 3 }, end: { x: 50, y: 50, scale: 3 }, duration: 4, curve: 'linear' },
  })
  const [plain] = createSceneEvaluator(scene([centered], 4)).renderedLayerStates(centered, 0)
  assert.equal(plain.x, 50)
  const normalized = normalizeScene2D(scene([zoomed]))
  assert.deepEqual(normalized.layers[0].focus, { x: 0, y: 50 })
  assert.equal(normalizeScene2D(scene([layer('plain')])).layers[0].focus, undefined)
})

test('strip offsets wrap copies around the frame', () => {
  const offsets = stripOffsets(layer('strip', { strip: { enabled: true, count: 3, spacing: 30, direction: 'left', speed: 10 } }), 0)
  assert.deepEqual(offsets.map(item => item.x), [-30, 0, 30])
})

test('headless normalization gives screen effects their catalog colour and drops unknown kinds', async () => {
  const { FX_CATALOG } = await import('../src/features/sceneFx/types.ts')
  const { readFileSync } = await import('node:fs')
  const normalized = normalizeScene2D({ ...scene([layer('bg')]), sfx: [
    { id: 'smoke', kind: 'smoke', start: 0, end: 2 },
    { id: 'dust', kind: 'dust', start: 0, end: 2, color: 'not-a-colour' },
    { id: 'ghost', kind: 'not-an-effect', start: 0, end: 1 },
  ] })
  const catalogColor = (kind: string) => FX_CATALOG.find(item => item.id === kind)!.color
  assert.deepEqual(normalized.sfx?.map(cue => [cue.id, cue.color]), [['smoke', catalogColor('smoke')], ['dust', catalogColor('dust')]])
  assert.equal(normalizeScene2D(scene([layer('bg')])).sfx, undefined)
  // The render page has no app stylesheet; it must load the lettering faces itself.
  assert.match(readFileSync(new URL('../src/features/scene2d/ownedRenderer.ts', import.meta.url), 'utf8'), /kineticText\/fonts\.css/)
  assert.match(readFileSync(new URL('../src/lib/kineticText/fonts.css', import.meta.url), 'utf8'), /Hocus Marker[\s\S]*Hocus Hand|Hocus Hand[\s\S]*Hocus Marker/)
})
