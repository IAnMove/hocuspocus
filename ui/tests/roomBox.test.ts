import assert from 'node:assert/strict'
import { test } from 'node:test'
import { readFileSync } from 'node:fs'
import { createDefaultScene3DDocument, parseScene3DDocument } from '../src/features/scene3d/document.ts'
import { stageDioramaSet } from '../src/features/scene3d/dioramaSet.ts'
import { stageRoomSet, type RoomMold } from '../src/features/scene3d/roomSet.ts'
import { roomBoxCamera, stageRoomBox } from '../src/features/scene3d/roomBox.ts'
import { applyLensShift, validLensShift } from '../src/features/scene3d/lensShift.ts'
import { PerspectiveCamera, Vector3 } from 'three'
import { hashSoftwareFrame, renderScene3DSoftware } from '../src/features/scene3d/softwareRender.ts'
import { measureProof } from '../scripts/room-box-proof.mjs'

const FLOOR = new Set(['196,164,112', '148,108,68'])

test('a document without a box room keeps the software-frame hash', () => {
  assert.equal(hashSoftwareFrame(renderScene3DSoftware(createDefaultScene3DDocument(), 0)), '308718ed')
})

test('diorama and mold staging stay identical across two calls', () => {
  const houses = [{ source: '/house.glb', width: 4, height: 6 }]
  assert.deepEqual(
    stageDioramaSet(createDefaultScene3DDocument(), { houses }),
    stageDioramaSet(createDefaultScene3DDocument(), { houses }),
  )
  const loaded = JSON.parse(readFileSync(new URL('../../app/shared/set_molds/despacho.json', import.meta.url), 'utf8')) as RoomMold & { sizes: { medium: RoomMold['dimensions'] } }
  loaded.dimensions = loaded.sizes.medium
  loaded.size = 'medium'
  const mold = loaded
  assert.deepEqual(
    stageRoomSet(createDefaultScene3DDocument(), { mold }),
    stageRoomSet(createDefaultScene3DDocument(), { mold }),
  )
})

test('the wide camera matches the shared frame and an adult measures the door', () => {
  assert.deepEqual(roomBoxCamera(5), { eye: [0, 1.6, -3.35], look: [0, 1.15, 0.75], fov: 48 })
  const measured = measureProof()
  const ratio = measured.adult.height / measured.door.height
  assert.ok(measured.adult.count > 100 && measured.door.count > 100 && measured.near.count > 100)
  assert.ok(Math.abs(ratio - 0.875) <= 0.03, `adult/door ${ratio}`)
  assert.ok(measured.near.height > measured.adult.height, 'the nearer figure is taller on screen')
  assert.ok(measured.adult.maxY < measured.near.maxY, 'the farther figure stands higher on screen')
  assert.ok(measured.adult.centerX < measured.width / 2, 'world +x is on the left of a camera looking +z')
  assert.ok(FLOOR.has(measured.below.join(',')), `the row under the feet is floor, saw ${measured.below}`)
  const staged = stageRoomBox(createDefaultScene3DDocument(), {
    size: { w: 4, d: 5, h: 2.6 }, door: { wall: 'back', x: 0, w: 0.9, h: 2 },
    characters: [{ x: 1.2, z: 2.48, heightM: 1.75, color: [40, 110, 190] }],
  })
  assert.equal(parseScene3DDocument(JSON.parse(JSON.stringify(staged)))?.roomBox?.characters.length, 1)
  assert.equal(staged.slots.some(slot => slot.id === 'subject_1'), true)
  assert.equal(staged.environment?.floorStyle, 'none')
})

test('a document with no environment still gets floorStyle none, like a mold room', () => {
  const staged = stageRoomBox(createDefaultScene3DDocument(), {
    size: { w: 4, d: 5, h: 2.6 }, door: { wall: 'back', x: 0, w: 0.9, h: 2 },
  })
  assert.equal(createDefaultScene3DDocument().environment, undefined)
  assert.equal(staged.environment?.floorStyle, 'none')
  assert.equal(staged.environment?.reflectiveFloor, false)
})

test('a staged box room with a file keeps the GLB on the ungrounded room-box slot', () => {
  const staged = stageRoomBox(createDefaultScene3DDocument(), {
    size: { w: 4, d: 5, h: 2.6 }, door: { wall: 'back', x: 0, w: 0.9, h: 2 },
    file: '/api/v1/file/set-batch-kitchen.glb?workspace=w',
  })
  const room = staged.slots.find(slot => slot.id === 'room-box')
  assert.equal(room?.sourceUrl, '/api/v1/file/set-batch-kitchen.glb?workspace=w')
  assert.equal(room?.grounded, false)
  assert.equal(room?.media, 'model3d')
  assert.equal(room?.scale, 2.6 / 1.7)
  assert.deepEqual(room?.position, [0, 0, 0])
})

const PLATE_CAMERA = { eye: [0, 1.6129, -1.8113], look: [0, 1.6129, 1.8113], fov: 48, lensShift: 0.28 } as const

test('a plate room takes its camera from the plate, with the lens shift, and draws no door of its own', () => {
  const staged = stageRoomBox(createDefaultScene3DDocument(), {
    size: { w: 5.69, d: 3.62, h: 2.32 }, door: null, plate: { camera: { ...PLATE_CAMERA, eye: [...PLATE_CAMERA.eye], look: [...PLATE_CAMERA.look] } },
    file: '/api/v1/file/rooms/office.glb?workspace=w',
  })
  assert.deepEqual(staged.camera.eye, [0, 1.6129, -1.8113])
  assert.equal(staged.camera.lensShift, 0.28)
  assert.deepEqual(staged.look, { toneMapping: 'none', exposure: 0 }, 'the plate carries its own light')
  assert.equal(staged.camera.family, 'fixed')
  assert.equal(staged.roomBox?.door, undefined)
  assert.equal(staged.slots.find(slot => slot.id === 'room-box')?.scale, 2.32 / 1.7)
  const round = parseScene3DDocument(JSON.parse(JSON.stringify(staged)))
  assert.equal(round?.camera.lensShift, 0.28)
  const ordinary = stageRoomBox(createDefaultScene3DDocument(), { size: { w: 4, d: 5, h: 2.6 }, door: { wall: 'back', x: 0, w: 0.9, h: 2 } })
  assert.equal('lensShift' in ordinary.camera, false, 'an ordinary room keeps the camera it had')
  assert.notEqual(ordinary.look?.toneMapping, 'none', 'and the look it had')
})

test('a lens shift moves the horizon without moving the verticals, and no shift leaves the camera alone', () => {
  const camera = new PerspectiveCamera(48, 1920 / 1088, 0.05, 200)
  camera.position.set(0, 1.6, -2)
  camera.lookAt(0, 1.6, 2)
  camera.updateMatrixWorld()
  const before = camera.projectionMatrix.clone()
  applyLensShift(camera, undefined)
  assert.deepEqual(camera.projectionMatrix.elements, before.elements)
  assert.equal(camera.view, null)
  applyLensShift(camera, 0.28)
  camera.updateProjectionMatrix()
  const row = (point: [number, number, number]) => 0.5 - new Vector3(...point).project(camera).y / 2
  assert.ok(Math.abs(row([0, 1.6, 4]) - 0.22) < 1e-4, 'the horizon is at 0.22 from the top')
  assert.ok(Math.abs(camera.projectionMatrix.elements[0] - before.elements[0]) < 1e-6, "the horizontal scale is the lens's own")
  applyLensShift(camera, 0)
  assert.equal(camera.view?.enabled ?? false, false)
  assert.ok(Math.abs(camera.projectionMatrix.elements[9]) < 1e-9, 'shift 0 gives the symmetric frustum back')
  assert.equal(validLensShift(0.28) && validLensShift(undefined) && !validLensShift(Number.NaN) && !validLensShift(0.8), true)
})
