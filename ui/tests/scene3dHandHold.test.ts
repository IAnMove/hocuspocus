import assert from 'node:assert/strict'
import test from 'node:test'
import { Bone, Euler, Object3D, Quaternion, Scene, Vector3 } from 'three'
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

test('hold.rotation turns the prop in the hand after the bone, and replaces the yaw', () => {
  const scene = new Scene()
  const hand = new Bone()
  hand.name = 'RightHand'
  hand.rotation.y = Math.PI / 2
  scene.add(hand)
  const prop = new Object3D()
  scene.add(prop)
  const tip = () => new Vector3(1, 0, 0).applyQuaternion(prop.getWorldQuaternion(new Quaternion()))
  followHand(prop, hand, [0, 0, 0], 0)
  assert.ok(tip().distanceTo(new Vector3(0, 0, -1)) < 1e-6, 'no turn: the prop takes the bone rotation')
  followHand(prop, hand, [0, 0, 0], Math.PI / 2)
  assert.ok(tip().distanceTo(new Vector3(-1, 0, 0)) < 1e-6, 'an old document keeps the slot yaw')
  followHand(prop, hand, [0, 0, 0], Math.PI / 2, [0, 0, Math.PI / 2])
  assert.ok(tip().distanceTo(new Vector3(0, 1, 0)) < 1e-6, 'the turn is in the bone frame and the yaw no longer applies')
  const expected = hand.quaternion.clone().multiply(new Quaternion().setFromEuler(new Euler(0.3, -1.1, 2.4, 'XYZ')))
  followHand(prop, hand, [0, 0, 0], 0, [0.3, -1.1, 2.4])
  assert.ok(prop.getWorldQuaternion(new Quaternion()).angleTo(expected) < 1e-6, 'Euler XYZ after the bone rotation')
})

test('a scaled carrier turns a held prop exactly and does not rescale it', () => {
  const scene = new Scene()
  const carrier = new Object3D()
  carrier.scale.setScalar(2.4)
  const hand = new Bone()
  hand.name = 'LeftHand'
  hand.rotation.z = Math.PI / 2
  hand.position.set(0.1, 0.2, 0)
  carrier.add(hand)
  const prop = new Object3D()
  prop.scale.setScalar(0.5)
  scene.add(carrier, prop)
  followHand(prop, hand, [0.1, 0, 0], 0)
  const position = new Vector3(), quaternion = new Quaternion(), scale = new Vector3()
  prop.matrixWorld.decompose(position, quaternion, scale)
  assert.ok(quaternion.angleTo(new Quaternion().setFromEuler(new Euler(0, 0, Math.PI / 2))) < 1e-6, 'the rotation, not the scale, of the bone')
  assert.ok(scale.distanceTo(new Vector3(0.5, 0.5, 0.5)) < 1e-6, 'the prop keeps its own size')
  assert.ok(position.distanceTo(new Vector3(0.24, 0.72, 0)) < 1e-6, 'the offset is in the scaled bone frame')
})

test('a hold keeps a bounded rotation and drops a malformed one', () => {
  assert.deepEqual(parseHold({ carrier: 'hero', hand: 'right', rotation: [1, -20, 0.5] }, 'gun')?.rotation, [1, -Math.PI * 2, 0.5])
  assert.equal(parseHold({ carrier: 'hero', hand: 'right', rotation: [1, 'x', 0] }, 'gun')?.rotation, undefined)
  assert.equal(parseHold({ carrier: 'hero', hand: 'right', rotation: [1, 2] }, 'gun')?.rotation, undefined)
  const held = normalizeScene3DSlot(slot({ hold: { carrier: 'hero', hand: 'right', offset: [0, 0.05, 0], rotation: [-1.57, 0, 3.14] } }))
  assert.deepEqual(held.hold, { carrier: 'hero', hand: 'right', offset: [0, 0.05, 0], rotation: [-1.57, 0, 3.14] })
  assert.deepEqual(Object.keys(normalizeScene3DSlot(slot({ hold: { carrier: 'hero', hand: 'left' } })).hold ?? {}), ['carrier', 'hand'])
})

test('a held prop materializes where the hand carries it, not where its slot stands', async () => {
  const { BoxGeometry, Group, Mesh, MeshStandardMaterial, PerspectiveCamera } = await import('three')
  const { createDefaultScene3DDocument } = await import('../src/features/scene3d/document.ts')
  const { paintWorld } = await import('../src/features/scene3d/gpu.ts')
  const doc = createDefaultScene3DDocument()
  delete doc.lighting; delete doc.look
  doc.camera = { family: 'fixed', eye: [0, 1.5, 4], look: [0, 1, 0], fov: 40 }
  doc.slots = [slot({ id: 'hero', slot: 'subject_1', sourceUrl: 'hero.glb' }),
    slot({ id: 'cup', sourceUrl: 'cup.glb', appearance: { start: 0, duration: 1, color: '#83e8ff' }, hold: { carrier: 'hero', hand: 'right' } })]
  const hero = new Group()
  const hand = new Bone()
  hand.name = 'RightHand'
  hand.position.set(0.3, 1.5, 0.2)
  hero.add(hand)
  const cup = new Group()
  cup.add(new Mesh(new BoxGeometry(0.1, 0.2, 0.1), new MeshStandardMaterial()))
  const gpu = (root: Group) => ({ root, baseScale: 1, kind: 'model', animations: [], clipKey: '', mixer: null })
  const world = { slots: new Map([['hero', gpu(hero)], ['cup', gpu(cup)]]), scene: new Scene(), camera: new PerspectiveCamera(), dressing: null,
    driveWheels: [], driveRoad: null, driveMovers: [], driveSpeed: 0, renderer: { render() {}, shadowMap: { enabled: false } } }
  world.scene.add(hero, cup)
  paintWorld(world as never, doc, 2)
  assert.ok(cup.getWorldPosition(new Vector3()).distanceTo(new Vector3(0.3, 1.5, 0.2)) < 1e-6, 'the cup is in the hand')
  const cut = (world.slots.get('cup') as unknown as { appearance: { uniforms: { arrivalCut: { value: number } } } }).appearance.uniforms.arrivalCut.value
  assert.ok(cut > 1.6, `the reveal plane (${cut}) is above the cup in the hand, so the whole cup shows`)
})
