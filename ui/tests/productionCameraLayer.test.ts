import assert from 'node:assert/strict'
import test from 'node:test'
import { createSceneEvaluator } from '../src/lib/scene2d/evaluate.ts'
import { normalizeScene2D } from '../src/lib/scene2d/normalize.ts'
import type { AnimatorScene } from '../src/lib/scene2d/types.ts'

// The shape app/services/production_camera.py writes for a production shot: a still picture layer enlarged to cover
// the frame, and a camera layer that plays the named preset over the whole shot.
type Pose = { x: number; y: number; scale: number; rotation: number }
const still = (scale: number): Pose => ({ x: 50, y: 50, scale, rotation: 0 })

function shot(start: Pose, end: Pose, scale: number, shake?: { amount: number; frequency: number; seed: number }): AnimatorScene {
  return normalizeScene2D({
    version: 1, name: 'shot', width: 1920, height: 1080, fps: 24, duration: 8, texts: [],
    layers: [
      { id: 'bg', name: 'bg', type: 'image', source: '/examples/hero.png', visible: true, z: 0, fill: true, focus: { x: 50, y: 50 },
        transform: { ...still(scale), opacity: 1 }, animation: { start: still(scale), end: still(scale), duration: 8, curve: 'linear' } },
      { id: 'camera', name: 'camera', type: 'camera', source: '', visible: true, z: 10,
        transform: { ...start, opacity: 1 }, animation: { start, end, duration: 8, curve: 'ease', ...(shake ? { shake } : {}) } },
    ],
  })
}

function picture(scene: AnimatorScene, progress: number) {
  const evaluator = createSceneEvaluator(scene)
  return evaluator.renderedLayerStates(scene.layers.find(layer => layer.id === 'bg')!, progress)[0]
}

test('a camera layer pans and cranes the view the way its preset is named', () => {
  const pan = shot({ x: 35, y: 50, scale: 1, rotation: 0 }, { x: 65, y: 50, scale: 1, rotation: 0 }, 1.3)
  assert.ok(picture(pan, 0).x > 50 && picture(pan, 1).x < 50, 'pan right: the picture slides left under the frame')
  assert.ok(picture(pan, .9).x > picture(pan, 1).x, 'still moving just before the cut')
  for (let step = 0; step <= 20; step += 1) {
    const state = picture(pan, step / 20)
    assert.ok(Math.abs(state.x - 50) <= 50 * (state.scale - 1) + 1e-6, 'the enlarged picture never shows its edge')
  }
  const crane = shot({ x: 50, y: 68, scale: 1.15, rotation: 0 }, { x: 50, y: 34, scale: 1, rotation: 0 }, 1.32)
  assert.ok(picture(crane, 1).y > picture(crane, 0).y, 'crane up: the picture sinks, the view rises')
  const push = shot(still(1), still(1.55), 1)
  assert.ok(picture(push, 1).scale > picture(push, 0).scale * 1.5)
})

test('a camera layer shake reaches the picture', () => {
  const shake = { amount: .75, frequency: 3.2, seed: 1.7 }
  const steady = shot(still(1.08), still(1.12), 1)
  const handheld = shot(still(1.08), still(1.12), 1, shake)
  const moved = [.13, .41, .77].map(progress => Math.abs(picture(handheld, progress).x - picture(steady, progress).x))
  assert.ok(Math.max(...moved) > .1)
})
