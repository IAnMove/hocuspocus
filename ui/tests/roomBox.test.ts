import assert from 'node:assert/strict'
import { test } from 'node:test'
import { readFileSync } from 'node:fs'
import { createDefaultScene3DDocument, parseScene3DDocument } from '../src/features/scene3d/document.ts'
import { stageDioramaSet } from '../src/features/scene3d/dioramaSet.ts'
import { stageRoomSet, type RoomMold } from '../src/features/scene3d/roomSet.ts'
import { roomBoxCamera, stageRoomBox } from '../src/features/scene3d/roomBox.ts'
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
