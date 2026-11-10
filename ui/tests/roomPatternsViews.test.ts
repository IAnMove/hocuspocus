import assert from 'node:assert/strict'
import { test } from 'node:test'
import { readFileSync } from 'node:fs'
import { FACE_PATTERNS, isRoomPattern, patternLevel, ROOM_PATTERNS, TILE_PATTERNS } from '../src/features/scene3d/roomPatterns.ts'
import { HORIZON, isRoomView, ROOM_VIEWS, viewRole, viewSize } from '../src/features/scene3d/roomViews.ts'
import { roomPanels, type RoomMold } from '../src/features/scene3d/roomSet.ts'

type AuthoredMold = RoomMold & { sizes: { medium: RoomMold['dimensions'] } }
function authored(name: string): AuthoredMold {
  const loaded = JSON.parse(readFileSync(new URL(`../../app/shared/set_molds/${name}.json`, import.meta.url), 'utf8')) as AuthoredMold
  loaded.dimensions = loaded.sizes.medium; loaded.size = 'medium'
  return loaded
}

test('every tile pattern paints the same grey for the same pixel, inside 0..1, and repeats at its edge', () => {
  for (const pattern of TILE_PATTERNS) {
    let total = 0
    for (let y = 0; y < 256; y += 7) for (let x = 0; x < 256; x += 5) {
      const level = patternLevel(pattern, x, y, 3)
      assert.equal(level, patternLevel(pattern, x, y, 3))
      assert(level > -0.1 && level < 1.1, `${pattern} ${x},${y}: ${level}`)
      total += level
    }
    assert(total / (37 * 52) > 0.45, `${pattern} is too dark to tint`)
  }
  assert.deepEqual([...ROOM_PATTERNS], [...TILE_PATTERNS, ...FACE_PATTERNS])
  assert(isRoomPattern('leather') && isRoomPattern('dials') && !isRoomPattern('lava'))
})

test('a window view names its wall: the road comes toward the front, leaves through the rear, and the side walls run opposite ways', () => {
  assert.deepEqual(['back', 'front', 'left', 'right'].map(viewRole), ['front', 'rear', 'left', 'right'])
  assert(ROOM_VIEWS.every(isRoomView) && !isRoomView('mars'))
  assert.deepEqual(viewSize(3, 1.45), [1024, 495])
  assert(HORIZON > 0 && HORIZON < 0.5)
})

test('every cabin mold skins its four windows with a moving view and paints each side window from its own part of the wall', () => {
  for (const id of ['cabina', 'coche_interior', 'cabina_nave']) {
    const cabin = authored(id)
    for (const surface of ['windshield', 'window_left', 'window_right', 'window_rear']) assert(isRoomView(cabin.defaultSkin[surface]?.view), `${id} ${surface}`)
    const left = roomPanels({ mold: cabin }).filter(panel => panel.surface === 'window_left')
    assert.equal(left.length, 2, `${id}: two windows on a side`)
    assert(left.every(panel => panel.wall === 'left' && panel.fullSize[0] === cabin.dimensions[1]))
    const [a, b] = left.map(panel => panel.uv)
    assert(a[0] !== b[0] && a[2] !== b[2], 'the two windows show different parts of the roadside')
    assert(Math.max(a[0], b[0]) >= Math.min(a[2], b[2]) - 0.5)
    for (const surface of Object.values(cabin.defaultSkin)) assert(!surface.pattern || isRoomPattern(surface.pattern))
  }
})
