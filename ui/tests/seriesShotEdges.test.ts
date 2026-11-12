import assert from 'node:assert/strict'
import test from 'node:test'
import { createCharacterKit, type CharacterKit, type CharacterKitAsset } from '../src/lib/characterKit'
import { normalizeScene2D } from '../src/lib/scene2d/normalize'
import { sceneTimeToLayerTime, sceneVideoTime } from '../src/lib/sceneTimeline'
import type { Scene, SceneLayer } from '../src/types'
import {
  castTransform, compileSeriesShot, EDGE_BLEED, floorLine, groundedY, MAX_EDGE_ZOOM, personTransform, setLayer,
  type CutEdges, type PropSpec, type ShotSpec,
} from '../scripts/seriesShot.ts'

const STATES = ['closed', 'small', 'wide', 'round', 'pressed', 'medium', 'pucker', 'bite', 'tongue'] as const
const LANDSCAPE = 16 / 9
const asset = (id: string, kind: 'image' | 'overlay' = 'overlay', extra: Partial<CharacterKitAsset> = {}): CharacterKitAsset => ({
  id, name: id, source: `/api/v1/file/${id}.png?workspace=cast`, kind, alphaStatus: 'transparent', reviewState: 'approved', ...extra })

/** A bust drawn 896x1152 with its eyes at 0.28 of its height, cut by its image border as ``cut`` says. */
function bust(id: string, cut?: CutEdges): CharacterKit {
  const value = createCharacterKit(id)
  value.id = id
  value.base = { ...asset(`${id}-base`, 'image', { width: 896, height: 1152 }), ...(cut ? { cut } : {}) } as CharacterKitAsset
  value.poses = {}
  value.mouth = Object.fromEntries(STATES.map(state => [state, asset(`${id}-mouth-${state}`)]))
  value.mouthMapping = { rest: 'closed', M: 'pressed', A: 'wide', E: 'medium', I: 'small', O: 'round', U: 'pucker', F: 'bite', L: 'tongue' }
  value.eyes = { blink: asset(`${id}-blink`) }
  const anchors = { mouth: { offsetX: 0, offsetY: -8, scale: 0.1, rotation: 0 }, eyes: { offsetX: 0, offsetY: -22, scale: 0.18, rotation: 0 } }
  value.anchors = { base: anchors }
  return value
}

/** Frame box of a placed 896x1152 pose (% of the frame): its edges and its eye line. */
function box(pose: { x: number; y: number; scale: number }, aspect = LANDSCAPE) {
  const ratio = 896 / 1152
  const height = ratio < aspect ? pose.scale * 100 : pose.scale * 100 * aspect / ratio
  const width = height * ratio / aspect
  return { left: pose.x - width / 2, right: pose.x + width / 2, top: pose.y - height / 2, bottom: pose.y + height / 2,
    eyes: pose.y - height / 2 + 0.28 * height, width, height }
}

const near = (actual: number, expected: number, message?: string) =>
  assert.ok(Math.abs(actual - expected) < 0.01, `${message ?? ''} ${actual} != ${expected}`)
/** Past the frame bottom by the bleed, and not much more. */
const pastBottom = (bottom: number) => assert.ok(bottom >= 100 + EDGE_BLEED - 0.005 && bottom < 100 + EDGE_BLEED + 0.2, `bottom ${bottom}`)
const LEFT_AND_BOTTOM: CutEdges = { left: [[0.4, 1]], bottom: [[0, 1]] }

test('a bust cut on the left slides to the left frame edge, its size and eye line kept', () => {
  const kit = bust('bolivar', LEFT_AND_BOTTOM)
  const before = personTransform(kit, 'base', 'medium', 46, LANDSCAPE)
  const after = castTransform(kit, { kitId: kit.id, x: 46 }, 'medium', LANDSCAPE)
  assert.equal(after.scale, before.scale)
  assert.equal(after.y, before.y)
  near(box(after).left, -EDGE_BLEED, 'the cut edge sits just past the frame edge')
  assert.ok(box(before).left > 10, 'it showed at about a sixth of the frame before')
})

test('the cut side decides the direction, and a cut already out of the frame moves nothing', () => {
  const right = bust('monk', { right: [[0.4, 1]], bottom: [[0, 1]] })
  near(box(castTransform(right, { kitId: right.id, x: 46 }, 'medium', LANDSCAPE)).right, 100 + EDGE_BLEED)
  const left = bust('bolivar', LEFT_AND_BOTTOM)
  assert.equal(castTransform(left, { kitId: left.id, x: 10 }, 'medium', LANDSCAPE).x, 10, 'already past the left edge')
  const close = personTransform(left, 'base', 'close', 90, LANDSCAPE)
  near(castTransform(left, { kitId: left.id, x: 90 }, 'close', LANDSCAPE).x, close.x - (box(close).left + EDGE_BLEED), 'slides by what shows')
})

test('a side cut that lies below the frame bottom is not seen and does not move the cutout', () => {
  const kit = bust('telmo', { left: [[0.9, 1]], bottom: [[0, 1]] })
  assert.deepEqual(castTransform(kit, { kitId: kit.id, x: 48 }, 'medium', LANDSCAPE), personTransform(kit, 'base', 'medium', 48, LANDSCAPE))
})

test('a bust cut at the bottom slides down onto the frame bottom in a wide shot and is enlarged on the eye line in a two-shot', () => {
  const kit = bust('ines', { bottom: [[0.1, 0.9]] })
  const wide = castTransform(kit, { kitId: kit.id, x: 50 }, 'wide', LANDSCAPE)
  assert.equal(wide.scale, personTransform(kit, 'base', 'wide', 50, LANDSCAPE).scale)
  pastBottom(box(wide).bottom)
  const twoBefore = personTransform(kit, 'base', 'two', 34, LANDSCAPE)
  assert.ok(box(twoBefore).bottom < 95, 'the chest cut showed at the bottom of a two-shot')
  const two = castTransform(kit, { kitId: kit.id, x: 34 }, 'two', LANDSCAPE)
  pastBottom(box(two).bottom)
  near(box(two).eyes, 33, 'eyes stay on the two-shot eye line')
  assert.equal(two.x, 34)
})

test('cut on both sides, a cutout is enlarged proportionally until both cuts leave the frame', () => {
  const kit = bust('madre', { left: [[0.3, 1]], right: [[0.3, 1]], bottom: [[0, 1]] })
  const base = personTransform(kit, 'base', 'medium', 46, LANDSCAPE)
  const after = castTransform(kit, { kitId: kit.id, x: 46 }, 'medium', LANDSCAPE)
  const placed = box(after)
  assert.ok(placed.left <= -EDGE_BLEED + 0.01 && placed.right >= 100 + EDGE_BLEED - 0.01, `${placed.left}..${placed.right}`)
  near(placed.eyes, 33, 'enlarged around the eyes')
  assert.ok(after.scale / base.scale < 2 && after.scale / base.scale <= MAX_EDGE_ZOOM)
  // A side cut that only reaches low on the body is hidden by a smaller enlargement: the bottom goes further down.
  const low = bust('low', { left: [[0.75, 1]], right: [[0.3, 1]], bottom: [[0, 1]] })
  const two = castTransform(low, { kitId: low.id, x: 34 }, 'two', LANDSCAPE)
  assert.ok(two.scale < after.scale && box(two).right >= 100 + EDGE_BLEED - 0.01, 'slides right once the left cut is below the frame')
  assert.ok(box(two).top + 0.75 * box(two).height >= 99)
})

test('past the largest enlargement the longer cut is hidden, and edgeSnap false keeps the pose where x puts it', () => {
  const kit = bust('wide-bust', { left: [[0.3, 1]], right: [[0.5, 1]], bottom: [[0, 1]] })
  const narrow = castTransform(kit, { kitId: kit.id, x: 50 }, 'two', LANDSCAPE)
  assert.ok(narrow.scale <= 0.8 * MAX_EDGE_ZOOM + 1e-9)
  near(box(narrow).left, -EDGE_BLEED, 'the left cut, the longer one, is hidden')
  assert.deepEqual(castTransform(kit, { kitId: kit.id, x: 50, edgeSnap: false }, 'two', LANDSCAPE), personTransform(kit, 'base', 'two', 50, LANDSCAPE))
  const uncut = bust('gary')
  assert.deepEqual(castTransform(uncut, { kitId: uncut.id, x: 50 }, 'medium', LANDSCAPE), personTransform(uncut, 'base', 'medium', 50, LANDSCAPE))
})

test('a vertical frame snaps the same way against its narrower width', () => {
  const kit = bust('bolivar', LEFT_AND_BOTTOM)
  const placed = box(castTransform(kit, { kitId: kit.id, x: 50 }, 'two', 9 / 16), 9 / 16)
  near(placed.left, -EDGE_BLEED)
  pastBottom(placed.bottom)
  // A vertical medium shot already draws a bust wider than the frame: nothing to move.
  assert.deepEqual(castTransform(kit, { kitId: kit.id, x: 50 }, 'medium', 9 / 16), personTransform(kit, 'base', 'medium', 50, 9 / 16))
})

function shot(overrides: Partial<ShotSpec> = {}): ShotSpec {
  return {
    name: 'Pilot · s02', workspace: 'cast', width: 1920, height: 1080, fps: 24, duration: 3, framing: 'medium',
    background: { source: '/api/v1/file/room.png?workspace=cast', kind: 'image', focusX: 46 },
    cast: [{ kitId: 'bolivar', x: 46 }], lines: [], camera: 'static', ...overrides,
  }
}

test('a compiled shot places the cut pose and its face together, and edgeSnap false compiles the old document', () => {
  const kits = { bolivar: bust('bolivar', LEFT_AND_BOTTOM) }
  const scene = compileSeriesShot(kits, shot())
  const pose = scene.layers.find(layer => layer.id === 'kit-bolivar-pose-base')!
  near(box(pose.transform).left, -EDGE_BLEED)
  assert.ok(pose.animation.keyframes!.every(frame => Math.abs(frame.x - pose.transform.x) < 1), 'the motion breathes around the new spot')
  const mouth = scene.layers.find(layer => layer.faceBinding?.role === 'mouth')!
  assert.ok(Math.abs(mouth.transform.x - pose.transform.x) < 5, 'the mouth is mounted on the moved pose')
  const kept = compileSeriesShot(kits, shot({ cast: [{ kitId: 'bolivar', x: 46, edgeSnap: false }] }))
  const uncut = compileSeriesShot({ bolivar: bust('bolivar') }, shot())
  assert.deepEqual(kept, uncut, 'without the cut the document is exactly what it was')
})

test('grounded props stand their lowest opaque row on the floor the cast stands on, or on their anchor', () => {
  assert.equal(floorLine('wide', LANDSCAPE), 94)
  assert.equal(floorLine('insert', LANDSCAPE), 94)
  assert.equal(floorLine('two', LANDSCAPE), 99.28)
  assert.equal(floorLine('medium', LANDSCAPE), 106.32)
  assert.equal(floorLine('two', 9 / 16), 94, 'a vertical two-shot stands people on their feet')
  const alien: PropSpec = { id: 'prop-1', name: 'Prop 1', source: '/api/v1/file/gris.png?workspace=cast', x: 30, y: 50, scale: 0.7,
    ground: { width: 896, height: 1152, bottom: 0.96 } }
  const y = groundedY(alien, 'wide', LANDSCAPE)
  near(y + (0.96 - 0.5) * 70, 94, 'feet on the wide floor line')
  near(groundedY({ ...alien, ground: { ...alien.ground, floor: 80 } }, 'wide', LANDSCAPE) + 0.46 * 70, 80)
  assert.equal(groundedY({ ...alien, ground: {} }, 'wide', LANDSCAPE), 50, 'unmeasured: it keeps its y')
  assert.equal(groundedY({ ...alien, ground: undefined }, 'wide', LANDSCAPE), 50)
  const scene = compileSeriesShot({}, shot({ framing: 'wide', cast: [], props: [alien] }))
  assert.equal(scene.layers.find(layer => layer.id === 'prop-1')!.transform.y, y)
})

const video = { id: 'plague', name: 'Back layer 1', source: '/api/v1/file/plague.mp4?workspace=cast', kind: 'video' as const,
  x: 50, y: 50, scale: 1, depth: 0 }

test('a video layer gets its own clock only when the shot asks for one', () => {
  const plain = setLayer(video, 1, 4, 1920, 0.6)
  assert.equal(plain.playback, undefined)
  assert.equal(plain.animation.loop, true)
  assert.deepEqual(setLayer({ ...video, loop: 'pingpong' }, 1, 4, 1920, 0.6).playback, { start: 0, loop: 'pingpong', speed: 1 })
  assert.deepEqual(setLayer({ ...video, start: 2, speed: 0.5 }, 1, 4, 1920, 0.6).playback, { start: 2, loop: 'loop', speed: 0.5 })
  assert.equal(setLayer({ ...video, kind: 'image', start: 2 }, 1, 4, 1920, 0.6).playback, undefined, 'an image has no clock')
})

const layer = (playback?: SceneLayer['playback']): SceneLayer => ({
  id: 'plague', name: 'Plague', type: 'video', source: 'plague.mp4', visible: true, z: 1, transform: { x: 50, y: 50, scale: 1, opacity: 1 },
  animation: { start: { x: 50, y: 50, scale: 1 }, end: { x: 50, y: 50, scale: 1 }, duration: 12, curve: 'linear', loop: true, offset: 0, speed: 1 },
  ...(playback ? { playback } : {}),
})

test('a video clip second is a pure function of the scene time: loop, hold or back and forth, from a start, at a speed', () => {
  const clip = 5, fps = 24, last = clip - 1 / fps
  const legacy = layer()
  for (const time of [0, 1, 4.99, 6.125, 11]) assert.equal(sceneVideoTime(legacy, time, clip, fps), sceneTimeToLayerTime(legacy, time) % clip)
  const looped = layer({ start: 1.5, loop: 'loop', speed: 0.5 })
  near(sceneVideoTime(looped, 2, clip, fps), 2.5)
  near(sceneVideoTime(looped, 8, clip, fps), 0.5, 'past the end it starts again')
  const held = layer({ start: 1, loop: 'hold', speed: 2 })
  near(sceneVideoTime(held, 1, clip, fps), 3)
  assert.equal(sceneVideoTime(held, 9, clip, fps), last, 'keeps the last frame')
  const bounce = layer({ start: 0, loop: 'pingpong', speed: 1 })
  near(sceneVideoTime(bounce, 2, clip, fps), 2)
  near(sceneVideoTime(bounce, 2 * last - 2, clip, fps), 2, 'on the way back it shows the same frame')
  near(sceneVideoTime(bounce, 2 * last + 0.5, clip, fps), 0.5)
  assert.ok(Array.from({ length: 300 }, (_, frame) => sceneVideoTime(bounce, frame / fps, clip, fps)).every(time => time >= 0 && time <= last))
  assert.equal(sceneVideoTime(bounce, 3.3, 0, fps), 0, 'a clip without a duration shows its start')
})

test('playback survives the export normalization on a video layer, bounded, and is dropped from an image', () => {
  const scene = {
    version: 1, name: 'Plague', width: 1920, height: 1080, fps: 24, duration: 4,
    layers: [
      { ...layer({ start: -3, loop: 'bounce' as never, speed: 9 }) },
      { ...layer({ start: 2, loop: 'hold', speed: 0.5 }), id: 'kept' },
      { ...layer({ start: 2, loop: 'hold', speed: 0.5 }), id: 'still', type: 'image' as const, source: 'still.png' },
    ],
  } as Scene
  const normalized = normalizeScene2D(scene)
  assert.deepEqual(normalized.layers.find(item => item.id === 'plague')!.playback, { start: 0, loop: 'loop', speed: 4 })
  assert.deepEqual(normalized.layers.find(item => item.id === 'kept')!.playback, { start: 2, loop: 'hold', speed: 0.5 })
  assert.equal(normalized.layers.find(item => item.id === 'still')!.playback, undefined)
})
