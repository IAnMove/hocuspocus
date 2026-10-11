import assert from 'node:assert/strict'
import { test } from 'node:test'
import { readFileSync } from 'node:fs'
import { roomPanels, stageRoomSet, type RoomMold } from '../src/features/scene3d/roomSet.ts'
import { createDefaultScene3DDocument, parseScene3DDocument } from '../src/features/scene3d/document.ts'
import { AmbientLight, PointLight } from 'three'
import { RoomSetRuntime } from '../src/features/scene3d/roomSetRuntime.ts'
const mold = JSON.parse(readFileSync(new URL('../../app/shared/set_molds/despacho.json', import.meta.url), 'utf8')) as RoomMold & { sizes: { medium: RoomMold['dimensions'] } }
mold.dimensions = mold.sizes.medium; mold.size = 'medium'
test('room panels leave holes in walls and put views behind them', () => {
  const panels = roomPanels({ mold })
  assert.equal(panels.length, 31)
  const hole = mold.openings[0], view = panels.find(p => p.surface === 'window_view')!
  assert.equal(view.size[0], hole.width)
  assert(view.position[0] < -3)
  const walls = panels.filter(p => p.surface === 'wall_left')
  assert(walls.every(p => !(Math.abs(p.position[2]) < .8 && p.position[1] > .9 && p.position[1] < 2.3)))
  assert(Math.abs(walls.reduce((area, p) => area+p.size[0]*p.size[1],0) - (15-1.6*1.4)) < 1e-8)
})
test('an absent room preserves the document snapshot', () => {
  const doc = createDefaultScene3DDocument(), before = JSON.stringify(doc)
  assert.equal(stageRoomSet(doc), doc)
  assert.equal(JSON.stringify(doc), before)
  assert.deepEqual(parseScene3DDocument(doc), parseScene3DDocument(JSON.parse(before)))
})
test('named camera and materials survive editor roundtrip', () => {
  const room = { mold, camera: 'ots_a', skin: { floor: { texture: { asset: '/floor.png' }, tile_m: 1 } } }
  const doc = stageRoomSet(createDefaultScene3DDocument(), room)
  assert.equal(doc.camera.family, 'fixed')
  assert.deepEqual(doc.camera.eye, mold.cameras[1].position)
  assert.deepEqual(parseScene3DDocument(doc)?.room, room)
})

test('a closed room has its own fill and a key below its ceiling without a model or HDRI', async () => {
  const room = new RoomSetRuntime({ mold })
  await Promise.resolve()
  const fill = room.root.children.find(child => child instanceof AmbientLight) as AmbientLight
  const key = room.root.children.find(child => child instanceof PointLight) as PointLight
  assert(fill.intensity > 0)
  assert(key.intensity > 0)
  assert(key.position.y > 0 && key.position.y < mold.dimensions[2])
  assert(Math.abs(key.position.z) < mold.dimensions[1] / 2)
  assert(key.distance > Math.max(...mold.dimensions))
  room.dispose()
})

test('room production images become cutouts while an explicit wall keeps its material', () => {
  const document = createDefaultScene3DDocument()
  document.slots[0] = { ...document.slots[0], media: 'image', sourceUrl: '/person.png' }
  document.slots[1] = { ...document.slots[1], media: 'image', sourceUrl: '/wall.png', surface: 'wall' }
  const parsed = parseScene3DDocument(stageRoomSet(document, { mold }))!
  assert.equal(parsed.slots[0].surface, 'cutout')
  assert.equal(parsed.slots[0].imageLook?.grounded, true)
  assert.equal(parsed.slots[1].surface, 'wall')
})
