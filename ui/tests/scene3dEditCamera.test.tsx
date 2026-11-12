import assert from 'node:assert/strict'
import test from 'node:test'
import { Object3D } from 'three'
import { applyEditCamera, framedView } from '../src/features/scene3d/editCamera'
import { createDefaultScene3DDocument, parseScene3DDocument } from '../src/features/scene3d/document.ts'
import { slotTilt } from '../src/features/scene3d/slotTilt'
import { transformPatch } from '../src/features/scene3d/transformGizmo'
import type { Vec3 } from '../src/features/scene3d/types.ts'

test('orbiting leaves the shot camera and committing writes a fixed camera', () => {
  const document = createDefaultScene3DDocument()
  const shot = { ...document.camera, eye: [...document.camera.eye] as Vec3, look: [...document.camera.look] as Vec3 }
  assert.equal(applyEditCamera(document, null), document)
  const view = { eye: [1, 2, 3] as Vec3, look: [0, 1, 0] as Vec3, fov: 28 }
  const next = applyEditCamera(document, view)
  assert.equal(document.camera.family, shot.family)
  assert.deepEqual(document.camera.eye, shot.eye)
  assert.deepEqual(document.camera.look, shot.look)
  assert.equal(next.camera.family, 'fixed')
  assert.deepEqual(next.camera.eye, [1, 2, 3])
  assert.deepEqual(next.camera.look, [0, 1, 0])
  assert.equal(next.camera.fov, 28)
  assert.equal(next.camera.framing, undefined)
})

test('framing aims the same camera offset at the selection', () => {
  const framed = framedView([0, 1, 5], [0, 1, 0], [3, 1, 0])
  assert.deepEqual(framed.look, [3, 1, 0])
  assert.deepEqual(framed.eye, [3, 1, 5])
})

test('a scene with only a yaw loads unchanged and a tilt round-trips', () => {
  assert.deepEqual(slotTilt({ rotationY: 0.4 }), [0, 0.4, 0])
  assert.deepEqual(slotTilt({ rotationY: 0.4, rotationX: 0.2, rotationZ: -0.1 }), [0.2, 0.4, -0.1])
  const document = createDefaultScene3DDocument()
  const loaded = parseScene3DDocument(JSON.parse(JSON.stringify(document)))
  assert.ok(loaded)
  assert.equal(loaded.slots[0].rotationX, undefined)
  assert.equal(loaded.slots[0].rotationZ, undefined)
  assert.equal(loaded.slots[0].rotationY, document.slots[0].rotationY)
  const raw = JSON.parse(JSON.stringify(document))
  raw.slots[0].rotationX = 0.25
  raw.slots[0].rotationZ = -0.15
  const tilted = parseScene3DDocument(raw)
  assert.equal(tilted?.slots[0].rotationX, 0.25)
  assert.equal(tilted?.slots[0].rotationY, document.slots[0].rotationY)
  assert.equal(tilted?.slots[0].rotationZ, -0.15)
})

test('object rotate writes X, Y and Z and a yaw-only gizmo writes Y', () => {
  const proxy = new Object3D()
  proxy.rotation.set(0.1, 0.2, 0.3)
  const patch = transformPatch(proxy, 'rotate', null, false, true)
  assert.equal(patch.rotationX, 0.1)
  assert.equal(patch.rotationY, 0.2)
  assert.equal(patch.rotationZ, 0.3)
  const yaw = transformPatch(proxy, 'rotate', null, false, false)
  assert.equal(yaw.rotationY, 0.2)
  assert.equal(yaw.rotationX, undefined)
  assert.equal(yaw.rotationZ, undefined)
})
