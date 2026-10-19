import assert from 'node:assert/strict'
import { test } from 'node:test'
import { readFileSync } from 'node:fs'
import { DUST_ID, keyLightBreath, OPENING_DEPTH, OPENING_MARGIN, roomPanels, roomSky, stageRoomSet, type RoomMold } from '../src/features/scene3d/roomSet.ts'
import { createDefaultScene3DDocument, parseScene3DDocument } from '../src/features/scene3d/document.ts'
import { templateTraits } from '../src/features/scene3d/templateTraits.ts'
import { AmbientLight, Color, Mesh, MeshBasicMaterial, PointLight } from 'three'
import { RoomSetRuntime, SKY_DOME } from '../src/features/scene3d/roomSetRuntime.ts'
type AuthoredMold = RoomMold & { sizes: { medium: RoomMold['dimensions'] } }
function authored(name: string): AuthoredMold {
  const loaded = JSON.parse(readFileSync(new URL(`../../app/shared/set_molds/${name}.json`, import.meta.url), 'utf8')) as AuthoredMold
  loaded.dimensions = loaded.sizes.medium; loaded.size = 'medium'
  return loaded
}
const mold = authored('despacho'), street = authored('calle')
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
test('an exterior has no ceiling panel, keeps only the walls it lists and is lit by its sun preset', () => {
  const panels = roomPanels({ mold: street })
  assert(!panels.some(p => p.surface === 'ceiling'))
  assert.deepEqual([...new Set(panels.map(p => p.surface).filter(s => s.startsWith('wall_')))].sort(), ['wall_back', 'wall_left', 'wall_right'])
  assert.equal(panels.filter(p => p.surface === 'floor').length, 1)
  const doc = stageRoomSet(createDefaultScene3DDocument(), { mold: street })
  assert.deepEqual(doc.light, { kind: 'directional', color: '#fff4dc', intensity: 1.25, direction: [-0.55, -1, -0.35] })
  assert.equal(doc.room?.mold.kind, 'exterior')
})

test('a staged room carries low dust for the whole shot unless the mold turns its ambient life off', () => {
  const doc = stageRoomSet(createDefaultScene3DDocument(), { mold })
  const dust = doc.worldSfx?.find(cue => cue.id === DUST_ID)
  assert(dust && dust.kind === 'dust' && dust.start === 0 && dust.end === doc.duration && dust.intensity < 0.5 && dust.scale === 2)
  assert.equal(templateTraits(doc).still, false)
  assert.deepEqual(templateTraits(doc).moving, ['effects'])
  assert(parseScene3DDocument(doc)?.worldSfx?.some(cue => cue.id === DUST_ID))
  const twice = stageRoomSet(stageRoomSet(createDefaultScene3DDocument(), { mold }), { mold })
  assert.equal(twice.worldSfx?.filter(cue => cue.id === DUST_ID).length, 1)
  const quiet = stageRoomSet(createDefaultScene3DDocument(), { mold: { ...mold, ambient: false } })
  assert.equal(quiet.worldSfx, undefined)
  assert.equal(templateTraits(quiet).still, true)
})

test('the key light breathes 8 % over 6 s as a pure function of scene time, so an export replays a frame', async () => {
  assert.equal(keyLightBreath(0), 1)
  assert(Math.abs(keyLightBreath(1.5) - 1.08) < 1e-9 && Math.abs(keyLightBreath(4.5) - 0.92) < 1e-9 && Math.abs(keyLightBreath(6) - 1) < 1e-9)
  const room = new RoomSetRuntime({ mold })
  await Promise.resolve()
  const base = room.key!.intensity
  await room.seek(1.5)
  const lit = room.key!.intensity
  assert(Math.abs(lit / base - 1.08) < 1e-9)
  await room.seek(4.5)
  assert(Math.abs(room.key!.intensity / base - 0.92) < 1e-9)
  await room.seek(1.5)
  assert.equal(room.key!.intensity, lit)
  assert.equal(room.sunBreath(1.5), 1)
  room.dispose()
  const outside = new RoomSetRuntime({ mold: street })
  await Promise.resolve()
  assert.equal(outside.key, undefined)
  assert(!outside.root.children.some(child => child instanceof PointLight))
  assert(outside.root.children.some(child => child instanceof AmbientLight))
  assert.equal(outside.sunBreath(1.5), keyLightBreath(1.5))
  outside.dispose()
  const still = new RoomSetRuntime({ mold: { ...mold, ambient: false } })
  await Promise.resolve()
  await still.seek(1.5)
  assert.equal(still.key!.intensity, base)
  still.dispose()
})

test('a stage-* template id survives parsing like a personal one', () => {
  assert.equal(parseScene3DDocument({ ...createDefaultScene3DDocument(), templateId: 'stage-sala' })?.templateId, 'stage-sala')
  assert.equal(parseScene3DDocument({ ...createDefaultScene3DDocument(), templateId: 'nowhere' })?.templateId, 'two-shot')
})

test('a painted furniture front leaves its ends in the mold colour', () => {
  const panels = roomPanels({ mold, skin: { shelf_front: { image: { asset: '/shelf.png' } }, desk_front: { color: '#112233' } } })
  const shelf = panels.filter(p => p.surface === 'shelf_front'), desk = panels.filter(p => p.surface === 'desk_front')
  assert.equal(shelf.filter(p => p.material.image).length, 1)
  assert(shelf.filter(p => !p.material.image).every(p => p.material.color === mold.defaultSkin.shelf_front.color))
  assert(desk.every(p => p.material.color === '#112233'))
})

test('an exterior closes its view with a sky dome in its preset colours; an interior has none', () => {
  const plaza = authored('plaza'), roof = authored('azotea')
  assert.equal(roomSky({ mold: mold }), undefined)
  assert.deepEqual(roomSky({ mold: plaza }), { zenith: '#79aedf', horizon: '#dfe9f1' })
  assert.deepEqual(roomSky({ mold: roof }), { zenith: '#050a1a', horizon: '#1d2b50' })
  const outside = new RoomSetRuntime({ mold: plaza }), inside = new RoomSetRuntime({ mold })
  const dome = outside.root.getObjectByName(SKY_DOME) as Mesh
  assert.ok(dome, 'the exterior has a dome')
  assert.equal(inside.root.getObjectByName(SKY_DOME), undefined)
  const [w, d, h] = plaza.dimensions
  const radius = Math.min(150, 6 * Math.max(w, d, h))
  assert.ok((dome.geometry as unknown as { parameters: { radius: number } }).parameters.radius === radius && radius < 200, 'inside the camera far plane')
  assert.ok(dome.material instanceof MeshBasicMaterial && !(dome.material as MeshBasicMaterial).depthWrite)
  const colours = dome.geometry.getAttribute('color'), positions = dome.geometry.getAttribute('position')
  let top = 0, bottom = 0
  for (let i = 1; i < positions.count; i++) {
    if (positions.getY(i) > positions.getY(top)) top = i
    if (positions.getY(i) < positions.getY(bottom)) bottom = i
  }
  const near = (i: number, hex: string) => { const c = new Color(hex); return Math.abs(colours.getX(i) - c.r) < 0.02 && Math.abs(colours.getY(i) - c.g) < 0.02 && Math.abs(colours.getZ(i) - c.b) < 0.02 }
  assert.ok(near(top, '#79aedf'), 'zenith overhead')
  assert.ok(near(bottom, '#dfe9f1'), 'horizon colour below eye level, never black')
  outside.dispose(); inside.dispose()
})

test('night and dusk exteriors default to a view that matches their light', () => {
  assert.equal(authored('azotea').defaultSkin.wall_back.color, '#1c2946')
  assert.equal(authored('orilla').defaultSkin.wall_back.color, '#d6a58f')
})
