import assert from 'node:assert/strict'
import test from 'node:test'
import { applySceneCurve, evaluateSceneLayer } from '../src/lib/sceneTimeline.ts'

test('hold keeps the preceding keyframe until the next keyframe', () => {
  assert.equal(applySceneCurve(.01, 'hold'), 0)
  assert.equal(applySceneCurve(.5, 'hold'), 0)
  assert.equal(applySceneCurve(.999, 'hold'), 0)
  assert.equal(applySceneCurve(1, 'hold'), 1)
})

test('held opacity makes a dialogue mouth remain visible for its authored beat', () => {
  const layer = {
    id: 'mouth-open',
    transform: { x: 50, y: 50, scale: 1, opacity: 0, rotation: 0 },
    animation: {
      start: { x: 50, y: 50, scale: 1, opacity: 0, rotation: 0 },
      end: { x: 50, y: 50, scale: 1, opacity: 0, rotation: 0 },
      duration: 2,
      curve: 'hold',
      keyframes: [
        { id: 'closed', time: 0, x: 50, y: 50, scale: 1, opacity: 0, rotation: 0, curve: 'hold' },
        { id: 'open', time: .3, x: 50, y: 50, scale: 1, opacity: 1, rotation: 0, curve: 'hold' },
        { id: 'closed-again', time: .6, x: 50, y: 50, scale: 1, opacity: 0, rotation: 0, curve: 'hold' },
      ],
    },
  }

  assert.equal(evaluateSceneLayer(layer, .45).opacity, 1)
  assert.equal(evaluateSceneLayer(layer, .6).opacity, 0)
})
