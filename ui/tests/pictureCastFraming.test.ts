import assert from 'node:assert/strict'
import test from 'node:test'
import { Bone, BoxGeometry, Group, Mesh, MeshBasicMaterial, type Object3D } from 'three'
import { applyScene3DTemplate } from '../src/features/scene3d/templates.ts'
import { cameraEyeAtTime, projectPoint } from '../src/features/scene3d/camera.ts'
import { framingFov, framingPose } from '../src/features/scene3d/framing.ts'
import { framingAnchor, HEAD_BELOW_CROWN, markRestPose } from '../src/features/scene3d/framingAnchor.ts'
import { imageCutoutMesh, poseImageCutout } from '../src/features/scene3d/imageCutout.ts'
import { slotPoseAtTime } from '../src/features/scene3d/performance.ts'
import { MODEL_HEIGHT, pictureInModelSlot, turnPicturesToCamera } from '../src/features/scene3d/pictureStandIn.ts'
import { templateTraitsOf } from '../src/features/scene3d/templateFilters.ts'
import { SCENE3D_TEMPLATE_IDS, type Scene3DDocument, type Scene3DSlot, type Vec3 } from '../src/features/scene3d/types.ts'

const PACKS = ['transition-', 'speed-', 'title-', 'dialogue-', 'reaction-', 'group-']
const PACK_IDS = SCENE3D_TEMPLATE_IDS.filter(id => PACKS.some(prefix => id.startsWith(prefix)))
const PEOPLE = /^(subject_\d|person_\d|crowd_\d)$/
const length = (v: Vec3) => Math.hypot(v[0], v[1], v[2])

const model = (patch: Partial<Scene3DSlot> = {}): Scene3DSlot => ({
  id: 'hero', slot: 'subject_1', media: 'model3d', sourceUrl: '/api/v1/file/hero.png?workspace=w', clip: null,
  position: [0, 0, 0], rotationY: 0.4, scale: 1, ...patch,
})

test('a picture in a model slot stands as a grounded cutout as tall as the model', () => {
  const picture = pictureInModelSlot(model())
  assert.equal(picture.media, 'image')
  assert.equal(picture.surface, 'cutout')
  assert.deepEqual(picture.imageLook, { grounded: true })
  assert.equal(picture.scale, 0.85)
  assert.ok(Math.abs(2 * picture.scale - MODEL_HEIGHT) < 1e-9, 'the cutout plane is as tall as the model would be')
  assert.equal(picture.rotationY, 0.4, 'a figure that stands keeps its staging')
  assert.equal(pictureInModelSlot(model({ scale: 0.98 })).scale, 0.833)
  const told = pictureInModelSlot(model(), { scale: 1.2, imageLook: { unlit: true } })
  assert.equal(told.scale, 1.2, 'the cast scale wins')
  assert.deepEqual(told.imageLook, { grounded: true, unlit: true }, 'the cast look joins the grounding')
  assert.deepEqual(pictureInModelSlot(model(), { grounded: false }).imageLook, {}, 'grounded: false floats it')
  assert.equal(pictureInModelSlot(model({ scale: 0.85, surface: 'cutout' })).scale, 0.85, 'a marker sized as a cutout keeps its size')
})

test('a picture never travels edge-on: it faces the camera and mirrors to run left', () => {
  const runner = model({ rotationY: Math.PI / 2, position: [-5, 0, 0], motion: { to: [5, 0, 0], faceTravel: true, headingOffset: 0.3, easing: 'linear' } })
  const right = pictureInModelSlot(runner)
  assert.equal(right.rotationY, 0)
  assert.deepEqual(right.motion, { to: [5, 0, 0], easing: 'linear' })
  assert.equal(slotPoseAtTime(right, 1, 2).rotationY, 0, 'it holds its face to the camera along the path')
  const left = pictureInModelSlot({ ...runner, position: [5, 0, 0], motion: { ...runner.motion!, to: [-5, 0, 0] } })
  assert.equal(left.rotationY, Math.PI)
  assert.equal(runner.motion?.faceTravel, true, 'the template slot is not changed')
})

const body = () => new Mesh(new BoxGeometry(0.5, MODEL_HEIGHT, 0.3).translate(0, MODEL_HEIGHT / 2, 0), new MeshBasicMaterial())

function rig(headShare: number, withCrown = true) {
  const root = new Group()
  root.add(body())
  const head = new Bone(); head.name = 'Head'; head.position.y = headShare * MODEL_HEIGHT; root.add(head)
  if (withCrown) {
    const crown = new Bone(); crown.name = 'HeadTop_End'; crown.position.y = (1 - headShare) * MODEL_HEIGHT; head.add(crown)
  }
  return root
}

test('a head bone far under the rig crown mark is raised to the head; a realistic rig keeps its bone', () => {
  const near = (actual: number, expected: number) => assert.ok(Math.abs(actual - expected) < 1e-6, `${actual} is not ${expected}`)
  // The pilot's auto-rigged doll: Head at 66 % of its height, the crown mark on top. It framed the chest.
  near(framingAnchor(rig(0.66), 'head')[1], MODEL_HEIGHT * (1 - HEAD_BELOW_CROWN))
  near(framingAnchor(rig(0.9), 'head')[1], MODEL_HEIGHT * 0.9)
  near(framingAnchor(rig(0.66, false), 'head')[1], MODEL_HEIGHT * 0.66)
  const scaled = rig(0.66); scaled.scale.setScalar(2); scaled.position.set(1, 0.5, -2)
  const [x, y, z] = framingAnchor(scaled, 'head')
  near(x, 1); near(z, -2); near(y, 0.5 + 2 * MODEL_HEIGHT * (1 - HEAD_BELOW_CROWN))
})

/** A figure standing in the target slot, the points that must land in frame, and how to place it at a time. */
type Figure = { name: string; slot: Scene3DSlot; root: Object3D; eyes: number; crown: number; place: (slot: Scene3DSlot) => void }

function figures(slot: Scene3DSlot): Figure[] {
  const glb = slot.media === 'image' ? { ...slot, media: 'model3d' as const } : slot
  const placeModel = (root: Object3D) => (posed: Scene3DSlot) => {
    root.position.set(...posed.position); root.rotation.y = posed.rotationY; root.scale.setScalar(posed.scale)
  }
  const height = MODEL_HEIGHT * glb.scale
  // Eyes as a share of the figure: a realistic body, an unrigged one framed on its box, the pilot's big-headed doll.
  const models = [['rig', rig(0.9), 0.935], ['box', body(), 0.935], ['doll', rig(0.66), 0.88]] as const
  const out: Figure[] = models.map(([name, root, eyes]) => ({ name, slot: glb, root, eyes: eyes * height, crown: height, place: placeModel(root) }))
  const picture = slot.media === 'model3d' ? pictureInModelSlot(slot) : slot
  const cutout = imageCutoutMesh(picture, null)
  const plane = 2 * picture.scale
  // A full-body picture with a little air above the hair.
  out.push({ name: 'picture', slot: picture, root: cutout, eyes: 0.888 * plane, crown: 0.95 * plane, place: posed => poseImageCutout(cutout, posed) })
  return out
}

function closeAtTheEnd(id: string) {
  const doc = applyScene3DTemplate(id)
  const framing = doc.camera.framing
  if (!framing || framing.anchor !== 'head') return false
  const target = doc.slots.find(slot => slot.id === framing.targetSlot)!
  return templateTraitsOf(id).shot === 'close' || length(framing.to) * target.scale <= 1.5
}

test('every close pack card ends with the eyes near the upper third and air above the head', () => {
  const close = PACK_IDS.filter(closeAtTheEnd)
  for (const id of ['reaction-push-face', 'dialogue-ots-a', 'dialogue-ots-b', 'dialogue-embrace', 'speed-rush-lines', 'transition-iris-in', 'transition-smash-in']) {
    assert.ok(close.includes(id), id)
  }
  for (const id of close) {
    for (const orientation of ['horizontal', 'vertical'] as const) {
      const doc = applyScene3DTemplate(id, { orientation }) as Scene3DDocument
      const framing = doc.camera.framing!
      const end = doc.duration
      for (const figure of figures(doc.slots.find(slot => slot.id === framing.targetSlot)!)) {
        figure.place(figure.slot)
        markRestPose(figure.root)
        const posed = { ...figure.slot, ...slotPoseAtTime(figure.slot, end, doc.duration) }
        figure.place(posed)
        const pose = framingPose(framing, framingAnchor(figure.root, framing.anchor, framing.track), posed, end, doc.duration)
        const fov = framingFov(framing, doc.camera.fov, end, doc.duration)
        const at = (height: number) => projectPoint([posed.position[0], posed.position[1] + height, posed.position[2]], pose.eye, pose.look, fov, doc.width / doc.height)!
        const eyes = at(figure.eyes), crown = at(figure.crown)
        const where = `${id} ${orientation} ${figure.name}: eyes ${(eyes.y * 100).toFixed(1)} %, crown ${(crown.y * 100).toFixed(1)} %`
        assert.ok(eyes.y >= 0.25 && eyes.y <= 0.45, where)
        assert.ok(eyes.x > 0.05 && eyes.x < 0.95, where)
        assert.ok(crown.y >= 0.05, `${where}: the head needs air above it`)
      }
    }
  }
})

test('pictures cast into every pack card are cutouts the camera never sees edge-on', () => {
  for (const id of PACK_IDS) {
    const doc = applyScene3DTemplate(id)
    const people = doc.slots.filter(slot => PEOPLE.test(slot.id) && slot.media !== 'screen')
    const standIns = new Set(people.filter(slot => slot.media === 'model3d').map(slot => slot.id))
    doc.slots = doc.slots.map(slot => standIns.has(slot.id) ? pictureInModelSlot(slot) : slot)
    turnPicturesToCamera(doc, standIns)
    const framing = doc.camera.family === 'fixed' ? undefined : doc.camera.framing
    for (const seconds of [0, doc.duration / 2, doc.duration]) {
      const slots = doc.slots.map(slot => ({ ...slot, ...slotPoseAtTime(slot, seconds, doc.duration) }))
      const target = framing && slots.find(slot => slot.id === framing.targetSlot)
      const height = target && (target.media === 'image' ? 2 : MODEL_HEIGHT) * target.scale
      const eye = framing && target && height
        ? framingPose(framing, [target.position[0], target.position[1] + 0.86 * height, target.position[2]], target, seconds, doc.duration).eye
        : cameraEyeAtTime(doc.camera, seconds, doc.duration, slots)
      for (const picture of slots.filter(slot => people.some(person => person.id === slot.id))) {
        assert.equal(picture.media, 'image', `${id} ${picture.id}`)
        assert.equal(picture.surface, 'cutout', `${id} ${picture.id}`)
        const plane = 2 * picture.scale
        assert.ok(plane >= 1.6 && plane <= 2, `${id} ${picture.id}: a ${plane.toFixed(2)} m picture`)
        const toCamera = [eye[0] - picture.position[0], eye[2] - picture.position[2]]
        const facing = Math.abs(Math.sin(picture.rotationY) * toCamera[0] + Math.cos(picture.rotationY) * toCamera[1]) / (Math.hypot(toCamera[0], toCamera[1]) || 1)
        assert.ok(facing >= 0.2, `${id} ${picture.id} at ${seconds.toFixed(2)} s: the camera sees ${facing.toFixed(2)} of its width`)
      }
    }
  }
})

test('a picture keeps the side it was turned to, at most sixty degrees from the camera; a back stays a back', () => {
  const doc = applyScene3DTemplate('dialogue-table')
  const ids = new Set(['subject_1', 'subject_2'])
  doc.slots = doc.slots.map(slot => ids.has(slot.id) ? pictureInModelSlot(slot) : slot)
  turnPicturesToCamera(doc, ids)
  const [left, right] = ['subject_1', 'subject_2'].map(id => doc.slots.find(slot => slot.id === id)!)
  assert.ok(left.rotationY > 0.5 && left.rotationY < 1.25, `${left.rotationY}: turned toward the camera, still toward the other seat`)
  assert.ok(right.rotationY < -0.5 && right.rotationY >= -1.25, `${right.rotationY}`)
  const ots = applyScene3DTemplate('dialogue-ots-a')
  ots.slots = ots.slots.map(slot => ids.has(slot.id) ? pictureInModelSlot(slot) : slot)
  turnPicturesToCamera(ots, ids)
  const [near, far] = ['subject_1', 'subject_2'].map(id => ots.slots.find(slot => slot.id === id)!)
  assert.ok(Math.abs(near.rotationY - Math.PI / 2) < 0.1, `${near.rotationY}: the near shoulder keeps its back to the camera`)
  assert.equal(far.rotationY, -Math.PI / 2, 'the far face keeps its front')
})
