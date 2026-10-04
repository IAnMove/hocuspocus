import assert from 'node:assert/strict'
import test from 'node:test'
import { Bone, DirectionalLight, Object3D, PerspectiveCamera, Quaternion, Scene, Vector3 } from 'three'
import { createDefaultScene3DDocument } from '../src/features/scene3d/document.ts'
import { normalizeScene3DSlot } from '../src/features/scene3d/documentSlot.ts'
import { paintWorld } from '../src/features/scene3d/gpu.ts'
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

test('a cm-scale carrier still copies this frame\'s hand rotation and a metre offset', () => {
  const scene = new Scene()
  const carrier = new Object3D()
  const hand = new Bone()
  hand.name = 'RightHand'
  carrier.add(hand)
  const prop = new Object3D()
  scene.add(carrier, prop)
  carrier.scale.setScalar(0.01)
  hand.position.set(100, 0, 0)
  hand.rotation.y = Math.PI / 2
  followHand(prop, hand, [0.1, 0, 0], 0)
  const handQuat = new Quaternion()
  hand.getWorldQuaternion(handQuat)
  assert.ok(prop.getWorldQuaternion(new Quaternion()).angleTo(handQuat) < 1e-6, 'decompose, not a scaled rotation matrix')
  const world = prop.getWorldPosition(new Vector3())
  assert.ok(world.distanceTo(new Vector3(1, 0, -0.1)) < 1e-6, 'offset is metres after fitGltf, not model units')
})

test('paintWorld orients a held prop to a scaled carrier hand', () => {
  const doc = createDefaultScene3DDocument()
  doc.dressing = undefined
  const hero = { ...doc.slots[0], id: 'hero', position: [0, 0, 0] as [number, number, number], rotationY: 0, scale: 1, sourceUrl: 'hero.glb' }
  const cup = { ...doc.slots[1], id: 'cup', position: [3, 0, 0] as [number, number, number], rotationY: 0, scale: 1, sourceUrl: 'cup.glb', hold: { carrier: 'hero', hand: 'right' as const, offset: [0.1, 0, 0] as [number, number, number] } }
  doc.slots = [hero, cup]
  const scene = new Scene()
  const carrier = new Object3D()
  const hand = new Bone()
  hand.name = 'mixamorigRightHand'
  carrier.add(hand)
  carrier.scale.setScalar(0.01)
  hand.position.set(80, 120, 0)
  hand.rotation.y = Math.PI / 2
  const prop = new Object3D()
  scene.add(carrier, prop)
  const world = {
    scene, dir: new DirectionalLight(), camera: new PerspectiveCamera(), slots: new Map(),
    dressing: null, driveSpeed: 0,
    renderer: { domElement: { width: 1280, height: 720 }, shadowMap: { enabled: false }, render() {} },
  }
  world.slots.set('hero', { root: carrier, baseScale: 0.01, animations: [], kind: 'model', loaded: true, mixer: null })
  world.slots.set('cup', { root: prop, baseScale: 1, animations: [], kind: 'model', loaded: true, mixer: null })
  paintWorld(world as never, doc, 0)
  const handQuat = new Quaternion()
  hand.getWorldQuaternion(handQuat)
  assert.ok(prop.getWorldQuaternion(new Quaternion()).angleTo(handQuat) < 1e-5)
  assert.ok(prop.getWorldPosition(new Vector3()).distanceTo(new Vector3(0.8, 1.2, -0.1)) < 1e-5)
})
