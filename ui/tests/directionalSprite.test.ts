import assert from 'node:assert/strict'
import { test } from 'node:test'
import { parseMediaScreen, mediaScreenMountKey } from '../src/features/scene3d/mediaScreen.ts'
import { facingSlot, isDirectional, walkedSlot } from '../src/features/scene3d/directionalPaint.ts'
import { spriteFoot, spriteFrame } from '../src/features/scene3d/directionalSprite.ts'
import { parseDirectional } from '../src/features/scene3d/directionalParse.ts'
import { imageCutoutMesh } from '../src/features/scene3d/imageCutout.ts'
import { ALPHA_CUT } from '../src/features/scene3d/directionalSprite.ts'
import type { Material } from 'three'
import type { Scene3DSlot } from '../src/features/scene3d/types.ts'
import {
  CROSSFADE_SECONDS, DirectionMemory, directionalPosition, directionalView, faceAngle, headingDegrees, headingFacing, normalizeDegrees,
  lightTint, pickSheet, sectorOf, strideFrame, travelFacing, walkState, type DirectionalSheet, type DirectionalSprite, type V2,
} from '../src/features/scene3d/directionalSprite.ts'

const sheet = (motion: DirectionalSheet['motion'], dir: DirectionalSheet['dir'], count = 12, extra: Partial<DirectionalSheet> = {}): DirectionalSheet =>
  ({ motion, dir, source: `/api/v1/file/${motion}-${dir}.png`, columns: 4, rows: Math.ceil(count / 4), count, cell: { width: 400, height: 640 }, fps: 8, loop: 'loop', ...extra })

const FIVE = (['front', 'front34', 'side', 'back34', 'back'] as const)
const ALL = [...FIVE.map(dir => sheet('walk', dir)), ...FIVE.map(dir => sheet('idle', dir, 2, { loop: 'pingpong', fps: 2 }))]

function expected(theta: number) {
  const a = Math.abs(normalizeDegrees(theta))
  const dir = a <= 22.5 ? 'front' : a <= 67.5 ? 'front34' : a <= 112.5 ? 'side' : a <= 157.5 ? 'back34' : 'back'
  return { dir, negative: normalizeDegrees(theta) < 0 }
}

test('every angle from 0 to 360 degrees maps to the sector of the table, and a left turn is the mirror of a right one', () => {
  for (let theta = 0; theta <= 360; theta += 0.25) {
    const sector = sectorOf(theta)
    const want = expected(theta)
    assert.equal(sector.dir, want.dir, `theta ${theta}`)
    assert.equal(sector.negative, want.negative, `sign at ${theta}`)
  }
  for (let theta = 0.25; theta < 180; theta += 0.25) {
    const right = sectorOf(theta), left = sectorOf(-theta)
    assert.equal(left.dir, right.dir, `mirror of ${theta}`)
    assert.equal(left.negative, !right.negative)
  }
  assert.equal(sectorOf(0).dir, 'front'); assert.equal(sectorOf(180).dir, 'back'); assert.equal(sectorOf(-180).dir, 'back')
  assert.equal(sectorOf(360).dir, 'front'); assert.equal(sectorOf(-90).dir, 'side'); assert.equal(sectorOf(270).negative, true)
  assert.equal(sectorOf(22.5).dir, 'front'); assert.equal(sectorOf(22.51).dir, 'front34')
})

test('a sector holds ten degrees past its edge and then moves on to the nearest one', () => {
  let held = sectorOf(0)
  const up: Record<string, number> = {}
  for (let theta = 0; theta <= 180; theta += 0.5) {
    const next = sectorOf(theta, held)
    if (next.dir !== held.dir) up[`${held.dir}>${next.dir}`] = theta
    held = next
  }
  assert.deepEqual(up, { 'front>front34': 33, 'front34>side': 78, 'side>back34': 123, 'back34>back': 168 })
  const down: Record<string, number> = {}
  for (let theta = 180; theta >= 0; theta -= 0.5) {
    const next = sectorOf(theta, held)
    if (next.dir !== held.dir) down[`${held.dir}>${next.dir}`] = theta
    held = next
  }
  assert.deepEqual(down, { 'back>back34': 147, 'back34>side': 102, 'side>front34': 57, 'front34>front': 12 })
})

test('a figure that jitters across a boundary does not flicker', () => {
  const memory = new DirectionMemory()
  const seen = new Set<string>()
  for (let step = 0; step < 60; step += 1) seen.add(memory.choose('a', step / 24, 22.5 + (step % 2 ? 8 : -8)).dir)
  assert.deepEqual([...seen], ['front'])
})

test('memory forgets after a jump in time, so a seek always lands on the plain sector', () => {
  const memory = new DirectionMemory()
  memory.choose('a', 0, 45)
  assert.equal(memory.choose('a', 0.04, 25).dir, 'front34')
  assert.equal(memory.choose('a', 5, 20).dir, 'front')
  assert.equal(new DirectionMemory().choose('a', 9, 20).dir, 'front')
})

test('the angle is measured against the line to the camera, in the camera own right and left', () => {
  // A camera on +z looks toward -z, so +x is screen right.
  const eye: V2 = [0, 5], at: V2 = [0, 0]
  assert.ok(Math.abs(faceAngle([0, 1], at, eye)!) < 1e-9)
  assert.ok(Math.abs(faceAngle([1, 0], at, eye)! - 90) < 1e-9)
  assert.ok(Math.abs(faceAngle([-1, 0], at, eye)! + 90) < 1e-9)
  assert.ok(Math.abs(Math.abs(faceAngle([0, -1], at, eye)!) - 180) < 1e-9)
  // A box-room camera at -z looks toward +z, where +x is screen left.
  const room: V2 = [0, -3.35]
  assert.ok(Math.abs(faceAngle([-1, 0], at, room)! - 90) < 1e-9)
  assert.ok(Math.abs(faceAngle([1, 0], at, room)! + 90) < 1e-9)
  assert.equal(faceAngle([0, 1], [0, 0], [0, 0]), null)
})

test('a heading is read from the camera of the start of the shot', () => {
  const eye: V2 = [0, -3.35], at: V2 = [1, 0.5]
  for (const [name, degrees] of [['toward', 0], ['right', 90], ['away', 180], ['left', -90]] as const) {
    assert.ok(Math.abs(normalizeDegrees(faceAngle(headingFacing(headingDegrees(name)!, at, eye), at, eye)! - degrees)) < 1e-9, name)
  }
  assert.equal(headingDegrees('sideways'), undefined)
  assert.equal(headingDegrees(45), 45)
  assert.equal(headingDegrees(Number.NaN), undefined)
})

test('a still figure changes drawing as the camera orbits around it (the Doom effect)', () => {
  const at: V2 = [0, 0]
  const first: V2 = [0, 5]
  const facing = headingFacing(0, at, first)
  const memory = new DirectionMemory()
  const seen: string[] = []
  for (let degrees = 0; degrees <= 360; degrees += 5) {
    const radians = degrees * Math.PI / 180
    const eye: V2 = [5 * Math.sin(radians), 5 * Math.cos(radians)]
    const sector = memory.choose('a', degrees / 100, faceAngle(facing, at, eye)!)
    const label = `${sector.dir}${sector.negative && sector.dir !== 'front' && sector.dir !== 'back' ? '*' : ''}`
    if (seen[seen.length - 1] !== label) seen.push(label)
  }
  assert.deepEqual(seen, ['front', 'front34*', 'side*', 'back34*', 'back', 'back34', 'side', 'front34', 'front'])
})

test('a walk takes as long as its distance at its speed, and stands where it stopped', () => {
  const walk = { to: [3, 4] as V2, speed: 1, start: 1 }
  const at = (t: number, speech: [number, number][] = []) => walkState([0, 0], walk, speech, t)
  assert.equal(at(0.5).phase, 'before'); assert.deepEqual([at(0.5).x, at(0.5).z], [0, 0])
  assert.equal(at(3).phase, 'walking')
  assert.ok(Math.abs(at(3).x - 1.2) < 1e-9 && Math.abs(at(3).z - 1.6) < 1e-9 && Math.abs(at(3).distance - 2) < 1e-9)
  assert.equal(at(6).phase, 'arrived'); assert.deepEqual([at(60).x, at(60).z], [3, 4])
  assert.deepEqual(travelFacing([0, 0], [3, 4]), [0.6, 0.8])
  const talk: [number, number][] = [[2, 3]]
  assert.equal(at(2.5, talk).phase, 'paused')
  assert.ok(Math.abs(at(2.5, talk).distance - 1) < 1e-9)
  assert.ok(Math.abs(at(4, talk).distance - 2) < 1e-9)
  assert.equal(at(6.5, talk).phase, 'walking'); assert.equal(at(7, talk).phase, 'arrived')
})

test('the walk cycle advances one cycle every two steps of 0.75 m, with no slide', () => {
  assert.equal(strideFrame(0, 12, 'loop'), 0)
  assert.equal(strideFrame(0.124, 12, 'loop'), 0)
  assert.equal(strideFrame(0.126, 12, 'loop'), 1)
  assert.equal(strideFrame(1.499, 12, 'loop'), 11)
  assert.equal(strideFrame(1.5, 12, 'loop'), 0)
  assert.equal(strideFrame(3.0 + 0.2, 12, 'loop'), strideFrame(0.2, 12, 'loop'))
  // Whatever the cycle length in cells, a cycle is 1.5 m.
  for (const count of [4, 8, 12]) assert.equal(strideFrame(1.5 * 7 + 0.001, count, 'loop'), 0)
  // The feet move the same distance of ground for every cell: no frame is held longer than the others.
  const held = new Array(12).fill(0)
  for (let d = 0; d < 1.5; d += 0.001) held[strideFrame(d, 12, 'loop')] += 1
  assert.ok(Math.max(...held) - Math.min(...held) <= 2)
  assert.deepEqual([0, 0.4, 0.8, 1.1, 1.4].map(d => strideFrame(d, 4, 'pingpong')), [0, 1, 3, 2, 1])
  assert.equal(strideFrame(100, 4, 'once'), 3)
})

test('a missing direction takes the nearest one the kit has, a missing walk glides on an idle sheet, and nothing falls back to the pose', () => {
  const pick = (sheets: DirectionalSheet[], motion: 'walk' | 'idle', theta: number) => {
    const found = pickSheet(sheets, motion, sectorOf(theta))
    return { dir: found.index >= 0 ? sheets[found.index].dir : null, motion: found.index >= 0 ? sheets[found.index].motion : null, mirror: found.mirror, exact: found.exact }
  }
  assert.deepEqual(pick(ALL, 'walk', 45), { dir: 'front34', motion: 'walk', mirror: false, exact: true })
  assert.deepEqual(pick(ALL, 'walk', -120), { dir: 'back34', motion: 'walk', mirror: true, exact: true })
  assert.deepEqual(pick(ALL, 'walk', 10), { dir: 'front', motion: 'walk', mirror: false, exact: true })
  const sideOnly = [sheet('walk', 'side', 12)]
  assert.deepEqual(pick(sideOnly, 'walk', 0), { dir: 'side', motion: 'walk', mirror: false, exact: false })
  assert.deepEqual(pick(sideOnly, 'walk', -170), { dir: 'side', motion: 'walk', mirror: true, exact: false })
  assert.deepEqual(pick(sideOnly, 'walk', -50), { dir: 'side', motion: 'walk', mirror: true, exact: false })
  // A tie between two neighbours takes the one nearer the front.
  const wide = [sheet('walk', 'front34'), sheet('walk', 'back34')]
  assert.equal(pick(wide, 'walk', 90).dir, 'front34')
  // No walk sheet: it glides on the idle sheet of the direction; no idle sheet either: the pose.
  const idleOnly = [sheet('idle', 'front', 2, { loop: 'pingpong' })]
  assert.deepEqual(pick(idleOnly, 'walk', 90), { dir: 'front', motion: 'idle', mirror: false, exact: false })
  assert.equal(pick([], 'walk', 90).dir, null)
  assert.equal(pick(sideOnly, 'idle', 90).dir, null)
  // Of two sheets for one direction the one with more cells wins, so walk-12 beats the four-pose walk.
  const both = [sheet('walk', 'side', 4), sheet('walk', 'side', 12)]
  assert.equal(both[pickSheet(both, 'walk', sectorOf(90)).index].count, 12)
  // A sheet drawn looking left is mirrored for the right and kept for the left.
  const lefty = [sheet('walk', 'side', 12, { facing: 'left' })]
  assert.equal(pickSheet(lefty, 'walk', sectorOf(90)).mirror, true)
  assert.equal(pickSheet(lefty, 'walk', sectorOf(-90)).mirror, false)
})

const sprite = (extra: Partial<DirectionalSprite> = {}): DirectionalSprite => ({ sheets: ALL, ...extra })

test('a figure that crosses the room shows the walk sheets of its path, the idle sheet when it stops and the pose while it speaks', () => {
  // A camera at -z looking toward +z (a box room): +x is screen left. The figure goes from x=1.5 to x=-1.5: screen right.
  const eye: V2 = [0, -3.35], start: V2 = [1.5, 0.5]
  const walk = { to: [-1.5, 0.5] as V2, speed: 1.2, start: 0.5 }
  const memory = new DirectionMemory()
  const at = (t: number, speech: [number, number][] = []) =>
    directionalView(sprite({ walk, speech, heading: 0 }), { start, eye0: eye, eye, t, memory, id: 'ana' })
  const standing = at(0)
  assert.equal(standing.view.kind, 'sheet')
  if (standing.view.kind === 'sheet') assert.equal(ALL[standing.view.sheet].motion, 'idle')
  const walking = at(1.5)
  assert.ok(walking.view.kind === 'sheet' && ALL[walking.view.sheet].motion === 'walk' && ALL[walking.view.sheet].dir === 'side' && !walking.view.mirror)
  assert.equal(walking.theta! > 80 && walking.theta! < 100, true)
  // Distance 1.2 m at 1.5 m per cycle: cell 9 of 12.
  assert.equal(walking.view.kind === 'sheet' && walking.view.frame, 9)
  const arrived = at(6)
  assert.ok(arrived.view.kind === 'sheet' && ALL[arrived.view.sheet].motion === 'idle')
  const speaking = at(1.5, [[1, 2]])
  assert.deepEqual(speaking.view, { kind: 'pose', talking: true })
  // The same walk to the other side is the mirror.
  const left = directionalView(sprite({ walk: { to: [1.5, 0.5], speed: 1.2, start: 0.5 } }), { start: [-1.5, 0.5], eye0: eye, eye, t: 1.5, memory: new DirectionMemory(), id: 'b' })
  assert.ok(left.view.kind === 'sheet' && left.view.mirror && ALL[left.view.sheet].dir === 'side')
  // Walking out to the side of the room it is seen from behind: the three-quarter back sheet, mirrored.
  const out = directionalView(sprite({ walk: { to: [3, 0.5], speed: 1.2, start: 0.5 } }), { start, eye0: eye, eye, t: 1.5, memory: new DirectionMemory(), id: 'c' })
  assert.ok(out.view.kind === 'sheet' && out.view.mirror && ALL[out.view.sheet].dir === 'back34')
})

test('a figure with no sheets, or with no walk, falls back to the pose without an error', () => {
  const eye: V2 = [0, 5]
  const view = (value: DirectionalSprite, t = 1) => directionalView(value, { start: [0, 0], eye0: eye, eye, t, memory: new DirectionMemory(), id: 'x' }).view
  assert.deepEqual(view({ sheets: [], heading: 0 }), { kind: 'pose', talking: false })
  assert.deepEqual(view({ sheets: [sheet('walk', 'side')], heading: 0 }), { kind: 'pose', talking: false })
  assert.equal(view({ sheets: [sheet('idle', 'front', 2)], heading: 0 }).kind, 'sheet')
})

test('the position of a figure that does not walk is the one it was placed at', () => {
  assert.deepEqual(directionalPosition(sprite({ heading: 90 }), [1, 0, 2], 3), [1, 0, 2])
  const moved = directionalPosition(sprite({ walk: { to: [1, 6], speed: 2, start: 0 } }), [1, 0.1, 2], 1)
  assert.deepEqual(moved, [1, 0.1, 4])
})

test('a directional block is read strictly and everything else is dropped', () => {
  const good = { sheets: [sheet('walk', 'side', 12)], heading: 'left', walk: { to: [1, 2], speed: 1.2, start: 0 }, speech: [[3, 4], [0, 1], [0.5, 2]], extra: 1 }
  const parsed = parseDirectional(good)!
  assert.equal(parsed.heading, 270 - 360)
  assert.deepEqual(parsed.speech, [[0, 2], [3, 4]])
  assert.equal('extra' in parsed, false)
  assert.deepEqual(parsed.walk, { to: [1, 2], speed: 1.2, start: 0 })
  assert.equal(parseDirectional(null), undefined)
  assert.equal(parseDirectional({ sheets: [] }), undefined)
  assert.equal(parseDirectional({ sheets: [{ ...sheet('walk', 'side'), dir: 'up' }] }), undefined)
  assert.equal(parseDirectional({ sheets: [{ ...sheet('walk', 'side'), source: '' }] }), undefined)
  assert.equal(parseDirectional({ sheets: [{ ...sheet('walk', 'side'), count: 0 }] }), undefined)
  assert.equal(parseDirectional({ sheets: [sheet('walk', 'side')], walk: { to: [1, 'x'], speed: 1, start: 0 } })!.walk, undefined)
  assert.equal(parseDirectional({ sheets: [sheet('walk', 'side')], walk: { to: [1, 2], speed: 0, start: 0 } })!.walk!.speed, 0.05)
  assert.deepEqual(parseDirectional(JSON.parse(JSON.stringify(parsed))), parsed)
})

const slotOf = (directional: Partial<DirectionalSprite>, extra: Record<string, unknown> = {}): Scene3DSlot => ({
  id: 'ana', slot: 'subject_1', position: [1, 0, 2], rotationY: 0, scale: 1, sourceUrl: '/pose.png', media: 'image', surface: 'cutout', clip: null,
  screen: parseMediaScreen({ media: 'image', sourceUrl: '/pose.png', directional: { sheets: ALL, ...directional }, ...extra }),
} as unknown as Scene3DSlot)

test('a screen with a directional block keeps it, with the talk block beside it, and a screen without one is read as before', () => {
  const screen = parseMediaScreen({ media: 'image', sourceUrl: '/pose.png', directional: { sheets: ALL, heading: 90 }, talk: { base: '/pose.png', mouths: { closed: '/m.png' }, mouth: { offsetX: 0, offsetY: -18, scale: 0.05, rotation: 0 }, rest: 'closed', cues: [] } })!
  assert.equal(screen.directional?.heading, 90)
  assert.equal(screen.talk?.base, '/pose.png')
  assert.equal(screen.transparent, true)
  assert.equal(screen.sourceUrl, '/pose.png')
  const plain = parseMediaScreen({ media: 'image', sourceUrl: '/a.png' })!
  assert.equal('directional' in plain, false)
  // Every screen that does not say it stays as it was read before directional figures existed.
  const talking = { base: '/pose.png', mouths: { closed: '/m.png' }, mouth: { offsetX: 0, offsetY: -18, scale: 0.05, rotation: 0 }, rest: 'closed', cues: [] }
  for (const raw of [{ media: 'image', sourceUrl: '/a.png' }, { media: 'image', sourceUrl: '/p.png', talk: talking }, { media: 'image', poseSequence: [{ sourceUrl: '/p.png', duration: 1 }] }, { media: 'video', sourceUrl: '/v.mp4' }]) {
    const read = parseMediaScreen(raw)!
    assert.equal('directional' in read, false, JSON.stringify(raw))
    assert.deepEqual(parseMediaScreen(JSON.parse(JSON.stringify(read))), read)
  }
  assert.equal(mediaScreenMountKey(plain), mediaScreenMountKey(parseMediaScreen({ media: 'image', sourceUrl: '/a.png', directional: { sheets: [] } })))
  // The sheets mount with it, the heading and the walk do not: editing them repaints without loading again.
  const key = mediaScreenMountKey(screen)
  assert.notEqual(key, mediaScreenMountKey(parseMediaScreen({ media: 'image', sourceUrl: '/pose.png', directional: { sheets: ALL.slice(1) } })))
  const moved = parseMediaScreen({ media: 'image', sourceUrl: '/pose.png', directional: { sheets: ALL, heading: 0, walk: { to: [1, 1], speed: 1, start: 0 } }, talk: screen.talk })!
  assert.equal(mediaScreenMountKey(moved), key)
})

test('the painter pass turns the figure to the camera and hands the painter the drawing, without touching the document', () => {
  const slot = slotOf({ heading: 0 })
  assert.equal(isDirectional(slot), true)
  assert.equal(isDirectional({ ...slot, screen: undefined }), false)
  const painted = facingSlot(walkedSlot(slot, slot.position, 0), slot.position, { memory: new DirectionMemory(), eye: [4, 1.6, 2], eye0: [1, 8], t: 0 })
  assert.ok(Math.abs(painted.rotationY - Math.PI / 2) < 1e-9)
  assert.ok(Math.abs(painted.scale - 1 / 0.86) < 1e-9)
  assert.equal(painted.screen?.directional?.view?.kind, 'sheet')
  assert.equal(slot.screen?.directional?.view, undefined)
})

test('a walking figure is placed along its path by the time, and every other slot is returned as it came', () => {
  const walker = slotOf({ walk: { to: [1, 8], speed: 2, start: 1 } })
  assert.deepEqual(walkedSlot(walker, walker.position, 2).position, [1, 0, 4])
  assert.deepEqual(walkedSlot(walker, walker.position, 0).position, [1, 0, 2])
  const still = slotOf({ heading: 0 })
  assert.deepEqual(walkedSlot(still, still.position, 5).position, still.position)
  assert.ok(Math.abs(walkedSlot(still, still.position, 5).scale - 1 / 0.86) < 1e-9, 'the plane of the sheets is the cell: taller than the figure by the share it fills')
  const bare = slotOf({ sheets: [], heading: 0 })
  assert.equal(walkedSlot(bare, bare.position, 5), bare, 'no sheet, no cell: the pose keeps its own size')
  const model = { ...still, media: 'model3d', screen: undefined } as unknown as Scene3DSlot
  assert.equal(walkedSlot(model, model.position, 5), model)
})

test('the plane of a figure is as wide as its widest cell and its feet stand on the line of the catalog', () => {
  const frame = spriteFrame({ sheets: [sheet('walk', 'side', 12, { cell: { width: 300, height: 600 } }), sheet('idle', 'front', 2, { cell: { width: 420, height: 600 } })] })
  assert.ok(Math.abs(frame.aspect - 0.7) < 1e-9)
  assert.equal(frame.feet, 0.96); assert.equal(frame.figure, 0.86)
  const foot = spriteFoot({ sheets: ALL })
  assert.ok(Math.abs(foot.bottom - 0.04) < 1e-9 && foot.center === 0.5)
})

test('a figure whose kit has no sheet still turns and walks in its pose', () => {
  const screen = parseMediaScreen({ directional: { sheets: [], heading: 'away', walk: { to: [2, 3], speed: 1.2, start: 0.5 } } })!
  assert.deepEqual(screen.directional, { sheets: [], heading: 180, walk: { to: [2, 3], speed: 1.2, start: 0.5 } })
  assert.equal(screen.sourceUrl, '')
  const talking = parseMediaScreen({ media: 'image', sourceUrl: '/pose.png', directional: { sheets: [], heading: 0 }, talk: { base: '/pose.png', mouths: { closed: '/m.png' }, mouth: { offsetX: 0, offsetY: -18, scale: 0.05, rotation: 0 }, rest: 'closed', cues: [] } })!
  assert.equal(talking.talk?.base, '/pose.png'); assert.equal(talking.directional?.heading, 0)
  assert.equal(parseMediaScreen({ directional: { sheets: [] } })!.directional, undefined)
  const slot = { id: 'a', slot: 'prop', position: [0, 0, 0], rotationY: 0, scale: 1, sourceUrl: '/pose.png', media: 'image', clip: null, screen } as unknown as Scene3DSlot
  const painted = facingSlot(walkedSlot(slot, [0, 0, 0], 0), [0, 0, 0], { memory: new DirectionMemory(), eye: [0, 1.6, 5], eye0: [0, 5], t: 0 })
  assert.deepEqual(painted.screen?.directional?.view, { kind: 'pose', talking: false })
  assert.equal(painted.scale, 1, 'no sheet, no cell: the pose keeps its own size')
  const moved = walkedSlot(slot, [0, 0, 0], 2).position, length = Math.hypot(2, 3)
  assert.ok(Math.abs(moved[0] - 1.8 * 2 / length) < 1e-9 && Math.abs(moved[2] - 1.8 * 3 / length) < 1e-9)
})

const MOUTH = { offsetX: 4, offsetY: -30, scale: 0.05, rotation: 0 }

test('a change of drawing fades in over 0.12 s, a frame at a time, and never the first one or one after a jump in time', () => {
  assert.equal(CROSSFADE_SECONDS, 0.12)
  const eye: V2 = [0, 5], start: V2 = [0, 0]
  const memory = new DirectionMemory()
  const at = (t: number, theta: number) => {
    // A figure whose facing turns with the camera: the camera sits at the angle that makes the figure look theta degrees off.
    const radians = theta * Math.PI / 180
    return directionalView(sprite({ heading: 0 }), { start, eye0: eye, eye: [5 * Math.sin(radians), 5 * Math.cos(radians)], t, memory, id: 'ana' })
  }
  assert.equal('blend' in at(0, 0).view, false, 'the first picture has nothing to fade from')
  assert.equal(at(1 / 30, 0).view.blend, undefined)
  // 1.0 s of sequential frames: front turns to front34 (past 32.5 degrees) at t = 0.1.
  const frames: { t: number; kind: string; mix?: number }[] = []
  for (let step = 3; step <= 14; step += 1) {
    const t = step / 30
    const view = at(t, t < 0.1 ? 0 : 40).view
    frames.push({ t, kind: view.kind, mix: view.blend?.mix })
  }
  const faded = frames.filter(frame => frame.mix !== undefined)
  assert.equal(faded.length, 4, 'the fade lasts 0.12 s: four frames at 30 fps')
  assert.equal(faded[0].mix, 0, 'it starts on the frame of the change, still the old picture')
  assert.ok(faded.every((frame, index) => index === 0 || frame.mix! > faded[index - 1].mix!), 'it rises')
  assert.ok(faded.every(frame => frame.mix! >= 0 && frame.mix! < 1))
  const last = frames[frames.length - 1]
  assert.equal(last.mix, undefined, 'and ends')
  // A jump in time forgets the figure: no fade out of a picture that was seen a long time ago.
  assert.equal(at(30, 80).view.blend, undefined)
})

test('the picture a fade comes from is the one that was drawn, and it keeps walking while it fades out', () => {
  const eye: V2 = [0, -3.35], start: V2 = [1.5, 0.5]
  const walker = sprite({ walk: { to: [-1.5, 0.5], speed: 1.2, start: 0 } })
  const memory = new DirectionMemory()
  let changed: ReturnType<typeof directionalView> | undefined
  let previous: ReturnType<typeof directionalView> | undefined
  for (let step = 0; step <= 90 && !changed; step += 1) {
    const now = directionalView(walker, { start, eye0: eye, eye, t: step / 30, memory, id: 'luis' })
    if (now.view.blend) changed = now
    previous = now
  }
  assert.ok(changed && previous, 'the walker turns from front34 to side on its way')
  const blend = changed!.view.blend!
  assert.equal(blend.from.kind, 'sheet')
  if (blend.from.kind === 'sheet' && previous!.view.kind === 'sheet') {
    assert.equal(ALL[blend.from.sheet].dir, ALL[previous!.view.sheet].dir)
    assert.equal(blend.from.mirror, previous!.view.mirror)
    assert.equal(ALL[blend.from.sheet].motion, 'walk')
  }
  if (changed!.view.kind === 'sheet') assert.equal(ALL[changed!.view.sheet].dir, 'side')
  assert.ok(blend.mix >= 0 && blend.mix < 0.5)
})

test('a figure that is drawn by the same sheet in the same way when its sector changes does not fade (a front sheet has no mirror)', () => {
  const only = sprite({ heading: 0 })
  only.sheets = [sheet('idle', 'front', 2, { loop: 'pingpong' })]
  const eye: V2 = [0, 5]
  const memory = new DirectionMemory()
  const at = (t: number, theta: number) => {
    const radians = theta * Math.PI / 180
    return directionalView(only, { start: [0, 0], eye0: eye, eye: [5 * Math.sin(radians), 5 * Math.cos(radians)], t, memory, id: 'ana' })
  }
  at(0, 0)
  for (let step = 1; step <= 10; step += 1) assert.equal(at(step / 30, step * 8).view.blend, undefined, `step ${step}`)
})

test('the kit can give the opposite side as its own sheet, which beats the mirror', () => {
  const right = sheet('walk', 'side', 12), left = sheet('walk', 'side', 12, { facing: 'left', source: '/api/v1/file/walk-side_r.png' })
  const both = [right, left]
  const pick = (sheets: DirectionalSheet[], theta: number) => {
    const found = pickSheet(sheets, 'walk', sectorOf(theta))
    return { source: found.index >= 0 ? sheets[found.index].source : null, mirror: found.mirror }
  }
  assert.deepEqual(pick(both, 90), { source: right.source, mirror: false })
  assert.deepEqual(pick(both, -90), { source: left.source, mirror: false })
  assert.deepEqual(pick([right], -90), { source: right.source, mirror: true })
  assert.deepEqual(pick([left], 90), { source: left.source, mirror: true })
  // A front34 asked for with only a left-looking side sheet takes the nearest direction and its mirror as before.
  assert.equal(pick([left], 45).mirror, true)
  const parsed = parseDirectional({ sheets: [{ ...sheet('walk', 'front34'), dir: 'front34_r' }, { ...sheet('idle', 'side', 2), dir: 'side_r' }] })!
  assert.deepEqual(parsed.sheets.map(item => [item.dir, item.facing]), [['front34', 'left'], ['side', 'left']])
  assert.equal(parseDirectional({ sheets: [{ ...sheet('walk', 'front'), dir: 'front_r' }] }), undefined, 'a front or a back has no other side')
})

test('while it speaks a figure shows its sheet with a mouth when the sheet has one, else its talking pose', () => {
  const eye: V2 = [0, 5]
  const talker = (mouth: boolean) => sprite({ heading: 90, speech: [[1, 2]], sheets: [...ALL.filter(item => item.motion === 'walk'),
    ...ALL.filter(item => item.motion === 'idle').map(item => mouth ? { ...item, mouth: MOUTH } : item)] })
  const view = (value: DirectionalSprite, t: number) => directionalView(value, { start: [0, 0], eye0: eye, eye, t, memory: new DirectionMemory(), id: 'ana' }).view
  const withMouth = view(talker(true), 1.5)
  assert.ok(withMouth.kind === 'sheet' && withMouth.speaking && ALL[withMouth.sheet].motion === 'idle' && ALL[withMouth.sheet].dir === 'side' && !withMouth.mirror)
  assert.deepEqual(view(talker(false), 1.5), { kind: 'pose', talking: true })
  const quiet = view(talker(true), 0.5)
  assert.ok(quiet.kind === 'sheet' && !quiet.speaking)
  const parsed = parseDirectional({ sheets: [{ ...sheet('idle', 'side', 2), mouth: MOUTH, eyes: { offsetX: 0, offsetY: -40, scale: 0.12 } }] })!
  assert.deepEqual(parsed.sheets[0].mouth, MOUTH)
  assert.deepEqual(parsed.sheets[0].eyes, { offsetX: 0, offsetY: -40, scale: 0.12, rotation: 0 })
  assert.equal(parseDirectional({ sheets: [{ ...sheet('idle', 'side', 2), mouth: { offsetX: 999, offsetY: 0, scale: 1 } }] })!.sheets[0].mouth, undefined)
})

test('the sprite takes the colour and strength of the key light by a soft multiply that can be turned off', () => {
  assert.deepEqual(lightTint('#ffffff', 1.2, 0), [1, 1, 1], '0 turns it off')
  assert.deepEqual(lightTint('#ffffff', 1.2, 1), [1, 1, 1], 'a white light at full strength leaves the picture as drawn')
  const warm = lightTint('#ffcc88', 1.0, 1)
  assert.ok(warm[0] > warm[1] && warm[1] > warm[2] && warm.every(value => value <= 1))
  const half = lightTint('#ffcc88', 1.0, 0.5)
  assert.ok(half[2] > warm[2] && half[2] < 1, 'half the amount is half way to white')
  assert.ok(lightTint('#ffffff', 0.3, 1)[0] < 0.7, 'a dim light darkens it')
  assert.deepEqual(lightTint('not a colour', 1, 1), [1, 1, 1])
  assert.equal(parseDirectional({ sheets: [sheet('idle', 'side', 2)], lightTint: 0.25 })!.lightTint, 0.25)
  assert.equal(parseDirectional({ sheets: [sheet('idle', 'side', 2)], lightTint: 4 })!.lightTint, undefined)
})

test('a directional figure writes colour and depth only where it is at least half opaque; any other cutout keeps its old cut', () => {
  const material = (slot: Scene3DSlot) => imageCutoutMesh(slot, null).material as Material & { alphaTest: number; alphaToCoverage: boolean; depthWrite: boolean }
  const sprite = material(slotOf({ heading: 0 }))
  assert.equal(ALPHA_CUT, 0.5)
  assert.equal(sprite.alphaTest, ALPHA_CUT); assert.equal(sprite.alphaToCoverage, true); assert.equal(sprite.depthWrite, true)
  const bare = material(slotOf({ sheets: [], heading: 0 }))
  assert.equal(bare.alphaTest, ALPHA_CUT, 'a figure that has no sheet is a sprite too')
  const plain = material({ ...slotOf({ heading: 0 }), screen: undefined } as unknown as Scene3DSlot)
  assert.equal(plain.alphaTest, 0.05); assert.equal(plain.alphaToCoverage, false)
})
