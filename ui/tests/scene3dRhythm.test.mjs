import assert from 'node:assert/strict'
import test from 'node:test'
import { BoxGeometry, DirectionalLight, Mesh, MeshStandardMaterial, PerspectiveCamera, Scene } from 'three'
import { createDefaultScene3DDocument, parseScene3DDocument } from '../src/features/scene3d/document.ts'
import { paintWorld } from '../src/features/scene3d/gpu.ts'
import { remountScene3DTemplate } from '../src/features/scene3d/templates.ts'
import { slotPoseAtTime } from '../src/features/scene3d/performance.ts'
import { parseRhythm, parseSlotRhythm, rhythmicSlotPose } from '../src/features/scene3d/rhythm.ts'

const near = (a, b) => assert.ok(Math.abs(a - b) < 1e-8, `${a} != ${b}`)

test('song offsets keep two differently cut shots on the same beat while travel continues', () => {
  const slot = { ...createDefaultScene3DDocument().slots[0], position: [0, 0, 0], rotationY: 0, scale: 1,
    motion: { to: [8, 0, 0] }, rhythm: parseSlotRhythm({ bounce: .2, sway: .1, yaw: .2, pulse: .1 }) }
  const before = structuredClone(slot), first = parseRhythm({ bpm: 120, offset: 0 }), second = parseRhythm({ bpm: 120, offset: .17 })
  const a = rhythmicSlotPose(slot, slotPoseAtTime(slot, .25, 4), .25, first)
  const b = rhythmicSlotPose(slot, slotPoseAtTime(slot, .25, 4), .08, second)
  a.position.forEach((value, index) => near(value, b.position[index])); near(a.scale, b.scale)
  near(a.position[0], .5); near(a.position[1], .2)
  rhythmicSlotPose(slot, slotPoseAtTime(slot, 4, 4), 4, first)
  assert.deepEqual(rhythmicSlotPose(slot, slotPoseAtTime(slot, .25, 4), .25, first), a)
  assert.deepEqual(slot, before)
})

test('the actual renderer poses a grounded model and pulses camera/light without accumulating or drifting', () => {
  const doc = createDefaultScene3DDocument(); doc.slots = [doc.slots[0]]; doc.dressing = undefined
  doc.camera = { family: 'fixed', eye: [0, 2, 6], look: [0, 1, 0], fov: 50 }
  doc.rhythm = parseRhythm({ bpm: 120, cameraPulse: .1, lightPulse: .5 })
  doc.slots[0] = { ...doc.slots[0], position: [0, 0, 0], rotationY: 0, scale: 1, grounded: true,
    rhythm: parseSlotRhythm({ bounce: .2, pulse: .1 }) }
  const root = new Mesh(new BoxGeometry(1, 1, 1), new MeshStandardMaterial()), scene = new Scene(); scene.add(root)
  const world = { scene, dir: new DirectionalLight(), camera: new PerspectiveCamera(), slots: new Map(), dressing: null,
    driveSpeed: 0, renderer: { domElement: { width: 1280, height: 720 }, shadowMap: { enabled: false }, render() {} } }
  world.slots.set(doc.slots[0].id, { root, baseScale: 1, animations: [], kind: 'model', loaded: true, mixer: null })
  paintWorld(world, doc, 0); near(root.scale.x, 1.1); near(world.camera.position.z, 5.4); near(world.dir.intensity, doc.light.intensity * 1.5)
  paintWorld(world, doc, 0); near(world.dir.intensity, doc.light.intensity * 1.5)
  paintWorld(world, doc, .25); near(root.position.y - root.scale.y / 2, .2)
  paintWorld(world, doc, 0); near(world.camera.position.z, 5.4)
  doc.rhythm = undefined
  paintWorld(world, doc, 0); near(root.scale.x, 1); near(world.camera.position.z, 6); near(world.dir.intensity, doc.light.intensity)
  root.geometry.dispose(); root.material.dispose()
})

test('rhythm survives persistence; malformed imported timing fails before rendering', () => {
  const doc = createDefaultScene3DDocument(); doc.rhythm = parseRhythm({ bpm: 123, offset: -0.17 })
  doc.slots[0].rhythm = parseSlotRhythm({ beats: 2, phase: .25, bounce: .15 })
  const reopened = parseScene3DDocument(JSON.parse(JSON.stringify(doc)))
  assert.deepEqual(reopened.rhythm, doc.rhythm); assert.deepEqual(reopened.slots[0].rhythm, doc.slots[0].rhythm)
  doc.slots[0].sourceUrl = '/api/v1/file/bolt.glb?workspace=musical'
  const remounted = remountScene3DTemplate('hero-push', doc)
  assert.deepEqual(remounted.rhythm, doc.rhythm); assert.deepEqual(remounted.slots[0].rhythm, doc.slots[0].rhythm)
  remounted.rhythm.offset = 9; assert.equal(doc.rhythm.offset, -0.17)
  for (const rhythm of [{ bpm: 0 }, { bpm: NaN }, { bpm: '120' }, { cameraPulse: 1 }, { lightPulse: -1 }, [], null, { unknown: 1 }]) {
    assert.equal(parseScene3DDocument({ ...doc, rhythm }), null)
  }
  for (const rhythm of [{ beats: 0 }, { bounce: Infinity }, { yaw: 'oops' }, { pulse: 2 }, { sway: -1 }]) {
    assert.equal(parseScene3DDocument({ ...doc, slots: [{ ...doc.slots[0], rhythm }] }), null)
  }
})

test('phase and half-time performers share the same clock without forcing a rig', () => {
  const base = { ...createDefaultScene3DDocument().slots[0], position: [0, 0, 0], scale: 1 }, pose = { position: [0, 0, 0], rotationY: 0 }
  const clock = parseRhythm({ bpm: 120 }), half = { ...base, rhythm: parseSlotRhythm({ beats: 2, bounce: .2 }) }
  near(rhythmicSlotPose(half, pose, .5, clock).position[1], .2)
  near(rhythmicSlotPose(half, pose, 1, clock).position[1], 0)
  const offbeat = { ...base, rhythm: parseSlotRhythm({ phase: .5, bounce: .2 }) }
  near(rhythmicSlotPose(offbeat, pose, 0, clock).position[1], .2)
  assert.deepEqual(rhythmicSlotPose(base, pose, .25, clock), { ...pose, scale: 1 })
})
