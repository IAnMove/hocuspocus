import assert from 'node:assert/strict'
import test from 'node:test'
import { Bone, Object3D, Scene, Vector3 } from 'three'
import { normalizeScene3DSlot } from '../src/features/scene3d/documentSlot.ts'
import { findHandBone, followHand, parseHold } from '../src/features/scene3d/handHold.ts'
import type { Scene3DSlot } from '../src/features/scene3d/types.ts'

function slot(patch: Partial<Scene3DSlot> = {}): Scene3DSlot {
  return { id: 'prop', slot: 'prop', position: [0, 0, 0], rotationY: 0, scale: 1, sourceUrl: 'cup.glb', media: 'model3d', clip: null, ...patch }
}

test('a held object matches the hand bone of this frame, including a yawed offset', () => {
  const scene = new Scene()
  const carrier = new Object3D()
  const hand = new Bone()
  hand.name = 'LeftHand'
  const finger = new Bone()
  finger.name = 'LeftHandIndex1'
  hand.add(finger)
  carrier.add(hand)
  const prop = new Object3D()
  scene.add(carrier, prop)
  hand.position.set(1, 2, 3)
  followHand(prop, hand, [0.1, 0, 0], 0)
  const first = prop.getWorldPosition(new Vector3())
  assert.ok(first.distanceTo(new Vector3(1.1, 2, 3)) < 1e-6)
  hand.position.set(4, 5, 6)
  followHand(prop, hand, [0.1, 0, 0], 0)
  const next = prop.getWorldPosition(new Vector3())
  assert.ok(next.distanceTo(new Vector3(4.1, 5, 6)) < 1e-6, 'the prop uses this frame, not the previous one')
  hand.position.set(0, 0, 0)
  hand.rotation.y = Math.PI / 2
  followHand(prop, hand, [1, 0, 0], 0)
  const turned = prop.getWorldPosition(new Vector3())
  assert.ok(turned.distanceTo(new Vector3(0, 0, -1)) < 1e-6, 'local +X of a +90° yaw lands on world −Z')
  assert.equal(findHandBone(carrier, 'left'), hand)
  assert.equal(findHandBone(carrier, 'right'), undefined)
})

test('a document without hold stays without it, and a finger is not a grip', () => {
  const plain = normalizeScene3DSlot(slot())
  assert.equal(plain.hold, undefined)
  assert.equal(JSON.stringify(plain).includes('"hold"'), false)
  const held = normalizeScene3DSlot(slot({ hold: { carrier: 'hero', hand: 'right', offset: [0, 0.05, 0.02] } }))
  assert.equal(held.hold?.carrier, 'hero')
  assert.equal(parseHold({ carrier: 'prop', hand: 'left' }, 'prop'), undefined)
  const onlyFinger = new Object3D()
  const finger = new Bone()
  finger.name = 'RightHandThumb1'
  onlyFinger.add(finger)
  assert.equal(findHandBone(onlyFinger, 'right'), undefined)
  const prefixed = new Object3D()
  const mixamo = new Bone()
  mixamo.name = 'mixamorigRightHand'
  prefixed.add(mixamo)
  assert.equal(findHandBone(prefixed, 'right'), mixamo)
})
