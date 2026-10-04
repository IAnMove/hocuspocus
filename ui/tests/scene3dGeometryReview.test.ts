import assert from 'node:assert/strict'
import test from 'node:test'
import { cutoutFloats } from '../src/features/scene3d/imageGrounding.ts'
import { collectGeometry } from '../src/features/scene3d/geometryReview.ts'
import { geometrySampleTimes, type GeometrySlotSample } from '../src/features/scene3d/geometryChecks.ts'
import type { Scene3DDocument } from '../src/features/scene3d/types.ts'

const body = (patch: Partial<GeometrySlotSample> = {}): GeometrySlotSample => ({
  id: 'hero', character: true, ground: 0, onFloor: true, min: [-0.3, 0, -0.2], max: [0.3, 1.7, 0.2], visible: true, ...patch,
})

test('the editor collects the same geometry report the render uses', () => {
  const document = { duration: 1 } as Scene3DDocument
  const times = geometrySampleTimes(1)
  const report = collectGeometry((_time, doc) => {
    assert.equal(doc, document)
    return { t: _time, camera: [0, 1.6, 4], slots: [body({ min: [-0.3, -0.3, -0.2], max: [0.3, 1.4, 0.2] })] }
  }, document)
  assert.equal(report?.samples, times.length)
  assert.equal(report?.verdict, 'fail')
  assert.equal(report?.warnings[0]?.code, 'below_floor')
  assert.equal(collectGeometry(() => undefined, document), undefined)
})

test('a cutout floats only when the feet sit above the canvas and it is not grounded', () => {
  const foot = { bottom: 0.2, center: 0.5, width: 0.4 }
  assert.equal(cutoutFloats(foot, false), true)
  assert.equal(cutoutFloats(foot, true), false)
  assert.equal(cutoutFloats({ bottom: 0.02, center: 0.5, width: 0.4 }, false), false)
  assert.equal(cutoutFloats(null), false)
})
