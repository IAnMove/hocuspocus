import assert from 'node:assert/strict'
import test from 'node:test'
import { AnimationClip, VectorKeyframeTrack, Bone, Group, Mesh, BoxGeometry, MeshBasicMaterial, PerspectiveCamera, Scene } from 'three'
import { SCENE3D_TEMPLATE_IDS } from '../src/features/scene3d/types.ts'
import { CINEMATIC_TEMPLATE_IDS } from '../src/features/scene3d/cinematicTemplateIds.ts'
import { applyScene3DTemplate, SCENE3D_TEMPLATES } from '../src/features/scene3d/templates.ts'
import { parseScene3DDocument } from '../src/features/scene3d/document.ts'
import { framingPose } from '../src/features/scene3d/framing.ts'
import { framingAnchor } from '../src/features/scene3d/framingAnchor.ts'
import { bindMixer, paintWorld } from '../src/features/scene3d/gpu.ts'
import { documentFromWorld3DRequest } from '../src/features/scene3d/world3dAgent.ts'

test('twenty cinematic shots are registered, saveable and available to the Wizard', () => {
  assert.equal(CINEMATIC_TEMPLATE_IDS.length, 20)
  assert.equal(new Set(SCENE3D_TEMPLATE_IDS).size, SCENE3D_TEMPLATE_IDS.length)
  for (const id of CINEMATIC_TEMPLATE_IDS) {
    assert.ok(SCENE3D_TEMPLATES.some(t => t.id === id))
    const doc = applyScene3DTemplate(id)
    assert.deepEqual(parseScene3DDocument(JSON.parse(JSON.stringify(doc))).camera, doc.camera)
    const wizard = documentFromWorld3DRequest({ type: 'mount_world3d_template', templateId: id, bindings: { subject_1: { media: 'model3d', url: '/hero.glb' } } })
    assert.deepEqual(wizard.camera.framing, doc.camera.framing)
    assert.equal(wizard.slots[0].sourceUrl, '/hero.glb')
  }
})

test('wizard screen bindings land on screen.sourceUrl and keep media=screen', () => {
  const monitor = documentFromWorld3DRequest({
    type: 'mount_world3d_template',
    templateId: 'monitor-detail',
    bindings: { prop: { url: '/api/v1/uploads/show.mp4', media: 'image' } },
  })
  assert.equal(monitor.slots[0].media, 'screen')
  assert.equal(monitor.slots[0].sourceUrl, '')
  assert.equal(monitor.slots[0].screen.sourceUrl, '/api/v1/uploads/show.mp4')
  assert.equal(parseScene3DDocument(JSON.parse(JSON.stringify(monitor)))?.slots[0].media, 'screen')

  const room = documentFromWorld3DRequest({
    type: 'mount_world3d_template',
    templateId: 'control-room',
    bindings: { prop: { url: '/api/v1/uploads/wall.mp4' } },
  })
  const walls = room.slots.filter(slot => slot.media === 'screen')
  assert.equal(walls.length, 6)
  for (const slot of walls) {
    assert.equal(slot.sourceUrl, '')
    assert.equal(slot.screen.sourceUrl, '/api/v1/uploads/wall.mp4')
    assert.equal(slot.media, 'screen')
  }
})

test('explicit camera family replaces cinematic framing; malformed and orphaned anchors are rejected', () => {
  const doc = applyScene3DTemplate('face-closeup')
  for (const patch of [{ anchor: 'nose' }, { from: [0, 1, null] }, { targetSlot: 'missing' }, { orbitTurns: '1' }, { relativeToFacing: 1 }]) {
    const bad = structuredClone(doc); Object.assign(bad.camera.framing, patch)
    assert.equal(parseScene3DDocument(bad), null)
  }
  const wizard = documentFromWorld3DRequest({ type: 'mount_world3d_template', templateId: 'face-closeup', cameraFamily: 'orbit', bindings: {} })
  assert.equal(wizard.camera.framing, undefined)
  assert.equal(wizard.camera.family, 'orbit')
})

test('camera offsets rotate with heading, scale, orbit and independently interpolate the look and roll', () => {
  const slot = { ...applyScene3DTemplate('face-closeup').slots[0], rotationY: Math.PI / 2, scale: 2 }
  const f = { targetSlot: slot.id, anchor: 'head', from: [0, 0, 2], to: [0, 1, 1], lookFrom: [0, 0, 0], lookTo: [0, 1, 0], rollFrom: -10, rollTo: 10 }
  const start = framingPose(f, [10, 2, 0], slot, 0, 4)
  assert.ok(Math.abs(start.eye[0] - 14) < 1e-6)
  const end = framingPose({ ...f, relativeToFacing: false }, [10, 2, 0], slot, 4, 4)
  assert.deepEqual(end.eye, [10, 4, 2]); assert.deepEqual(end.look, [10, 4, 0])
  assert.equal(end.roll, Math.PI / 18)
  const orbit = framingPose({ ...f, orbitTurns: .5 }, [0, 0, 0], slot, 4, 4)
  assert.ok(Math.abs(orbit.eye[0] + 2) < 1e-6)
})

test('head framing reads the current bone pose; unrigged models and empty slots have finite fallbacks', () => {
  const root = new Group(); const head = new Bone(); head.name = 'mixamorigHead'; head.position.y = 1.4; root.add(head)
  root.position.set(3, 1, 2); root.scale.setScalar(2)
  assert.deepEqual(framingAnchor(root, 'head'), [3, 3.8, 2])
  head.position.y = 1.8
  assert.deepEqual(framingAnchor(root, 'head'), [3, 4.6, 2])
  const model = new Mesh(new BoxGeometry(2, 4, 2), new MeshBasicMaterial()); model.position.set(2, 2, 3)
  assert.deepEqual(framingAnchor(model, 'feet'), [2, 0, 3])
  assert.deepEqual(framingAnchor(model, 'center'), [2, 2, 3])
  assert.deepEqual(framingAnchor(model, 'head'), [2, 3.44, 3])
  assert.deepEqual(framingAnchor(new Group(), 'head'), [0, 0, 0])
  model.geometry.dispose(); model.material.dispose()
})

test('camera follows this animation frame with deterministic backward seeking and no accumulated roll', () => {
  const doc = applyScene3DTemplate('face-closeup'); doc.duration = 4
  const root = new Group(); const head = new Bone(); head.name = 'Head'; root.add(head)
  const clip = new AnimationClip('nod', 4, [new VectorKeyframeTrack('Head.position', [0, 4], [0, 1, 0, 0, 2, 0])])
  const slot = { ...doc.slots[0], sourceUrl: '/hero.glb', clip: { index: 0, name: 'nod' } }; doc.slots = [slot]
  doc.camera.framing = { ...doc.camera.framing, from: [0, 0, 2], to: [0, 0, 2], rollFrom: 20, rollTo: -20 }
  const world = { slots: new Map([[slot.id, { root, baseScale: 1, kind: 'model', animations: [clip], clipKey: '0\0nod', mixer: bindMixer(root, [clip], slot) }]]), scene: new Scene(), camera: new PerspectiveCamera(), dressing: null, driveWheels: [], driveRoad: null, driveMovers: [], driveSpeed: 0, renderer: { render() {} } }
  paintWorld(world, doc, 1); const first = world.camera.quaternion.clone()
  assert.equal(world.camera.position.y, 1.25)
  paintWorld(world, doc, 3); assert.equal(world.camera.position.y, 1.75)
  paintWorld(world, doc, 1); assert.ok(first.angleTo(world.camera.quaternion) < 1e-6)
  assert.equal(world.camera.position.y, 1.25)
})
