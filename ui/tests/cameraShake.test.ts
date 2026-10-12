import assert from 'node:assert/strict'
import test from 'node:test'
import { Group, PerspectiveCamera, Scene } from 'three'
import { cameraShakeAt, shakeCamera, validCameraShake, type Scene3DCameraShake } from '../src/features/scene3d/cameraShake.ts'
import { unitProgress, vecDot, vecNormalize, vecSub } from '../src/features/scene3d/camera.ts'
import { createDefaultScene3DDocument, parseScene3DDocument } from '../src/features/scene3d/document.ts'
import { framingProgress, validFraming } from '../src/features/scene3d/framing.ts'
import { paintWorld } from '../src/features/scene3d/gpu.ts'
import { hashSoftwareFrame, renderScene3DSoftware } from '../src/features/scene3d/softwareRender.ts'
import type { Scene3DFraming, Vec3 } from '../src/features/scene3d/types.ts'

const HIT: Scene3DCameraShake = { start: 1, end: 2, amplitude: 0.1, frequency: 18, seed: 7, decay: 3 }

test('camera shake is a pure function of time and zero outside its windows', () => {
  for (const seconds of [0, 0.999, 2, 2.5]) assert.deepEqual(cameraShakeAt([HIT], seconds), { right: 0, up: 0, roll: 0 })
  assert.deepEqual(cameraShakeAt(undefined, 1.5), { right: 0, up: 0, roll: 0 })
  const samples = [1.05, 1.2, 1.37, 1.6, 1.9].map(seconds => cameraShakeAt([HIT], seconds))
  assert.deepEqual([1.05, 1.2, 1.37, 1.6, 1.9].map(seconds => cameraShakeAt([HIT], seconds)), samples)
  assert.ok(samples.some(sample => Math.abs(sample.right) > 0.01), 'it actually moves')
  for (const sample of samples) assert.ok(Math.abs(sample.right) <= HIT.amplitude + 1e-9 && Math.abs(sample.up) <= HIT.amplitude)
  const other = cameraShakeAt([{ ...HIT, seed: 8 }], 1.2)
  assert.notDeepEqual(other, samples[1], 'the seed picks the noise')
  // Decay: the late part of the window is quieter than the hit.
  const peak = (from: number, to: number) => Math.max(...Array.from({ length: 50 }, (_, i) => Math.abs(cameraShakeAt([HIT], from + (to - from) * i / 50).right)))
  assert.ok(peak(1.6, 1.9) < peak(1.0, 1.3) * 0.6)
  const steady = { start: 0, end: 4, amplitude: 0.05, frequency: 3 }
  assert.ok(Math.abs(cameraShakeAt([steady], 3).right) > 0 || Math.abs(cameraShakeAt([steady], 3).up) > 0)
})

test('shake moves eye and look together across the view, so the target does not swing', () => {
  const eye: Vec3 = [0, 1.5, 4], look: Vec3 = [0, 1.2, 0]
  const shaken = shakeCamera([HIT], 1.2, eye, look)
  const moveEye = vecSub(shaken.eye, eye), moveLook = vecSub(shaken.look, look)
  moveEye.forEach((value, i) => assert.ok(Math.abs(value - moveLook[i]) < 1e-12))
  assert.ok(Math.hypot(...moveEye) > 0.001)
  assert.ok(Math.abs(vecDot(vecNormalize(moveEye), vecNormalize(vecSub(look, eye)))) < 1e-9, 'perpendicular to the view')
  assert.notEqual(shaken.roll, 0)
  assert.deepEqual(shakeCamera([HIT], 3, eye, look), { eye, look, roll: 0 })
})

test('documents accept bounded shake windows and reject bad ones', () => {
  assert.equal(validCameraShake([HIT, { start: 0, end: 600, amplitude: 2, frequency: 60, seed: 0, decay: 0 }]), true)
  assert.equal(validCameraShake([]), true)
  const bad: unknown[] = [
    'shake', [null], [{ ...HIT, end: 1 }], [{ ...HIT, end: 601 }], [{ ...HIT, start: -1 }], [{ ...HIT, amplitude: 0 }],
    [{ ...HIT, amplitude: 2.5 }], [{ ...HIT, frequency: 0 }], [{ ...HIT, frequency: 61 }], [{ ...HIT, seed: 1.5 }],
    [{ ...HIT, decay: -1 }], [{ ...HIT, amplitude: Number.NaN }], [{ ...HIT, roll: 3 }], [{ start: 0, end: 1, amplitude: 0.1 }],
    Array.from({ length: 17 }, () => HIT),
  ]
  for (const value of bad) assert.equal(validCameraShake(value), false, JSON.stringify(value))
  const doc = createDefaultScene3DDocument()
  doc.camera.shake = [HIT]
  assert.deepEqual(parseScene3DDocument(JSON.parse(JSON.stringify(doc)))?.camera.shake, [HIT])
  assert.equal(parseScene3DDocument({ ...doc, camera: { ...doc.camera, shake: [{ ...HIT, amplitude: 9 }] } }), null)
})

test('the editor/export camera and the software preview both shake', () => {
  const doc = createDefaultScene3DDocument()
  doc.camera = { family: 'fixed', eye: [0, 1.5, 4], look: [0, 1, 0], fov: 40, shake: [HIT] }
  delete doc.lighting; delete doc.look
  const world = { slots: new Map([[doc.slots[0].id, { root: new Group(), baseScale: 1, kind: 'model', animations: [], clipKey: '', mixer: null }]]),
    scene: new Scene(), camera: new PerspectiveCamera(), dressing: null, driveWheels: [], driveRoad: null, driveMovers: [], driveSpeed: 0, renderer: { render() {} } }
  const pose = (seconds: number) => {
    paintWorld(world as never, doc, seconds)
    return { position: world.camera.position.toArray(), quaternion: world.camera.quaternion.toArray() }
  }
  const still = pose(0.5)
  assert.deepEqual(still.position, [0, 1.5, 4])
  const shaken = pose(1.2)
  assert.notDeepEqual(shaken.position, still.position)
  assert.deepEqual(pose(1.2), shaken, 'seeking back paints the same frame')
  assert.deepEqual(pose(2.5).position, still.position)
  const soft = (seconds: number) => hashSoftwareFrame(renderScene3DSoftware(doc, seconds))
  const calm = { ...doc, camera: { ...doc.camera, shake: undefined } }
  assert.equal(soft(0.5), hashSoftwareFrame(renderScene3DSoftware(calm, 0.5)))
  assert.notEqual(soft(1.2), hashSoftwareFrame(renderScene3DSoftware(calm, 1.2)))
})

test('a framing move can hold, snap and settle inside part of the shot', () => {
  const base: Scene3DFraming = { targetSlot: 'a', anchor: 'head', from: [0, 0, 3], to: [0, 0, 1] }
  for (const seconds of [0, 0.7, 2, 3.3, 4]) assert.equal(framingProgress(base, seconds, 4), unitProgress(seconds, 4), 'unchanged without a window')
  const snap: Scene3DFraming = { ...base, moveStart: 0.25, moveEnd: 0.5, ease: 'snap' }
  assert.equal(framingProgress(snap, 0.9, 4), 0)
  assert.equal(framingProgress(snap, 2, 4), 1)
  assert.equal(framingProgress(snap, 3.5, 4), 1)
  assert.ok(framingProgress(snap, 1.25, 4) > framingProgress({ ...snap, ease: 'smooth' }, 1.25, 4), 'a snap leaves at full speed')
  assert.equal(validFraming(snap), true)
  for (const bad of [{ moveStart: 0.6, moveEnd: 0.5 }, { moveStart: -0.1 }, { moveEnd: 1.2 }, { ease: 'bounce' }, { moveStart: 1 }]) {
    assert.equal(validFraming({ ...base, ...bad }), false, JSON.stringify(bad))
  }
})
