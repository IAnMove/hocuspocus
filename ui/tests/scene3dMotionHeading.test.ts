import assert from 'node:assert/strict'
import test from 'node:test'
import { createDefaultScene3DDocument, parseScene3DDocument } from '../src/features/scene3d/document.ts'
import { parseMotion, slotPoseAtTime } from '../src/features/scene3d/performance.ts'
import type { Scene3DSlot } from '../src/features/scene3d/types.ts'

function ship(motion: Scene3DSlot['motion']): Scene3DSlot {
  const slot = createDefaultScene3DDocument().slots[0]
  return { ...slot, position: [0, 0, 0], rotationY: 0, motion }
}

test('a heading offset turns a model whose nose is not +Z along its path', () => {
  const plain = slotPoseAtTime(ship({ to: [10, 0, 0], faceTravel: true, easing: 'linear' }), 1, 2)
  assert.ok(Math.abs(plain.rotationY - Math.PI / 2) < 1e-9, '+Z faces +X travel')
  const nose = slotPoseAtTime(ship({ to: [10, 0, 0], faceTravel: true, headingOffset: Math.PI / 2, easing: 'linear' }), 1, 2)
  assert.ok(Math.abs(nose.rotationY - Math.PI) < 1e-9, 'a nose at -X turned by PI faces +X')
  const curve = ship({ to: [0, 0, -20], points: [[-8, 0, 0], [-4, 0, -4]], faceTravel: true, headingOffset: Math.PI / 2, easing: 'linear' })
  const along = slotPoseAtTime(curve, 1.9, 2)
  const without = slotPoseAtTime({ ...curve, motion: { ...curve.motion!, headingOffset: undefined } }, 1.9, 2)
  assert.ok(Math.abs(along.rotationY - without.rotationY - Math.PI / 2) < 1e-9, 'waypoint paths add the offset too')
})

test('the offset is parsed, kept in documents and dropped when unusable', () => {
  assert.equal(parseMotion({ to: [1, 0, 0], faceTravel: true, headingOffset: 1.5708 })?.headingOffset, 1.5708)
  for (const bad of [Number.NaN, 9, '1.5', 0]) assert.equal(parseMotion({ to: [1, 0, 0], headingOffset: bad })?.headingOffset, undefined)
  const doc = createDefaultScene3DDocument()
  doc.slots[0] = ship({ to: [3, 0, 0], faceTravel: true, headingOffset: -1.5708, easing: 'smooth' })
  const reread = parseScene3DDocument(JSON.parse(JSON.stringify(doc)))
  assert.equal(reread?.slots[0].motion?.headingOffset, -1.5708)
})
