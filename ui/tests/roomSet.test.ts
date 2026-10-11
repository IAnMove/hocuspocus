import assert from 'node:assert/strict'
import { test } from 'node:test'
import { readFileSync } from 'node:fs'
import { OPENING_DEPTH, OPENING_MARGIN, roomPanels, stageRoomSet, type RoomMold } from '../src/features/scene3d/roomSet.ts'
import { createDefaultScene3DDocument, parseScene3DDocument } from '../src/features/scene3d/document.ts'
import { AmbientLight, PointLight } from 'three'
import { RoomSetRuntime } from '../src/features/scene3d/roomSetRuntime.ts'
const mold = JSON.parse(readFileSync(new URL('../../app/shared/set_molds/despacho.json', import.meta.url), 'utf8')) as RoomMold & { sizes: { medium: RoomMold['dimensions'] } }
mold.dimensions = mold.sizes.medium; mold.size = 'medium'
test('room panels leave holes in walls and put views behind them', () => {
  const panels = roomPanels({ mold })
  assert.equal(panels.length, 31)
  const hole = mold.openings[0], view = panels.find(p => p.surface === 'window_view')!
  assert.deepEqual(view.size, [hole.width + 2 * OPENING_MARGIN, hole.height + 2 * OPENING_MARGIN])
  assert.equal(view.position[0], -3 - OPENING_DEPTH)
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

test('image strips on the front and left walls keep their order as seen from inside', () => {
  const twoDoors = { ...mold, walls: ['back', 'left', 'right', 'front'], openings: [{ wall: 'front', kind: 'door', x: 0.2, width: 1, height: 2.1 }, { wall: 'back', kind: 'door', x: 0.2, width: 1, height: 2.1 }] }
  const panels = roomPanels({ mold: twoDoors })
  const strips = (wall: string) => panels.filter(p => p.surface === `wall_${wall}` && p.position[1] < 1.5).sort((a, b) => a.position[0] - b.position[0])
  const [frontLow, frontHigh] = strips('front'), [backLow, backHigh] = strips('back')
  // The back wall maps world x directly; the front wall faces the other way, so its first strip holds the image's right end.
  assert.deepEqual([backLow.uv[0], backLow.uv[2], backHigh.uv[0], backHigh.uv[2]].map(n => Math.round(n * 60)), [0, 7, 17, 60])
  assert.deepEqual([frontLow.uv[0], frontLow.uv[2], frontHigh.uv[0], frontHigh.uv[2]].map(n => Math.round(n * 60)), [53, 60, 0, 43])
  const left = roomPanels({ mold }).filter(p => p.surface === 'wall_left' && p.position[1] > .9 && p.position[1] < 2.3).sort((a, b) => a.position[2] - b.position[2])
  assert(left[0].uv[0] > left[left.length - 1].uv[0])
})
test('a painted furniture front leaves its ends in the mold colour', () => {
  const panels = roomPanels({ mold, skin: { shelf_front: { image: { asset: '/shelf.png' } }, desk_front: { color: '#112233' } } })
  const shelf = panels.filter(p => p.surface === 'shelf_front'), desk = panels.filter(p => p.surface === 'desk_front')
  assert.equal(shelf.filter(p => p.material.image).length, 1)
  assert(shelf.filter(p => !p.material.image).every(p => p.material.color === mold.defaultSkin.shelf_front.color))
  assert(desk.every(p => p.material.color === '#112233'))
})
