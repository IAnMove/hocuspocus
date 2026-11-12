import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import spec from '../../app/shared/directional_sprites.json' with { type: 'json' }
import {
  DirectionMemory, WALK_DIAGONAL_DEGREES, directionalView, drawnDirections, sectorEdges, sectorOf, type Direction, type DirectionSet,
  type DirectionalSheet, type DirectionalSprite, type V2,
} from '../src/features/scene3d/directionalSprite.ts'

type Case = { angle: number; walking: Direction; standing: Direction }
const table = JSON.parse(readFileSync(new URL('../../tests/fixtures/directional_walk_sectors.json', import.meta.url), 'utf8')) as { walkDiagonalDeg: number; cases: Case[] }

const sheet = (motion: DirectionalSheet['motion'], dir: Direction, extra: Partial<DirectionalSheet> = {}): DirectionalSheet =>
  ({ motion, dir, source: `/api/v1/file/${motion}-${dir}.png`, columns: 4, rows: 3, count: 12, cell: { width: 400, height: 640 }, fps: 8, loop: 'loop', ...extra })
const FIVE: Direction[] = ['front', 'front34', 'side', 'back34', 'back']
const everything = (dirs: readonly Direction[] = FIVE): DirectionalSheet[] => [...dirs.map(dir => sheet('walk', dir)), ...dirs.map(dir => sheet('idle', dir, { count: 2, loop: 'pingpong' }))]
const set = (...dirs: Direction[]): DirectionSet => new Set(dirs)

test('the table of angles is the one the spec says, and the same one the script check asserts', () => {
  assert.equal(table.walkDiagonalDeg, WALK_DIAGONAL_DEGREES, 'the fixture is for the spec number: change both')
  for (const { angle, walking, standing } of table.cases) {
    for (const sign of [1, -1]) {
      const walks = sectorOf(sign * angle, null, true), stands = sectorOf(sign * angle)
      assert.equal(walks.dir, walking, `walking at ${sign * angle}`)
      assert.equal(stands.dir, standing, `standing at ${sign * angle}`)
      if (sign < 0 && angle > 0 && angle < 180) assert.ok(walks.negative && stands.negative, `the left side at ${-angle}`)
    }
  }
})

test('while it walks, a figure that goes mostly toward or away from the camera is never drawn as a profile or a three-quarter, nor the reverse', () => {
  const edges = sectorEdges(true)
  assert.deepEqual(edges, [45 - WALK_DIAGONAL_DEGREES, 45 + WALK_DIAGONAL_DEGREES, 135 - WALK_DIAGONAL_DEGREES, 135 + WALK_DIAGONAL_DEGREES])
  assert.deepEqual(sectorEdges(false), [22.5, 67.5, 112.5, 157.5], 'a standing figure keeps the equal sectors')
  for (let theta = -180; theta <= 180; theta += 0.5) {
    const along = Math.cos(theta * Math.PI / 180), across = Math.sin(theta * Math.PI / 180)
    const dir = sectorOf(theta, null, true).dir
    // 3:2 is the dominance the default stands for: a movement that large in one direction is never drawn by a sheet of the other axis.
    if (Math.abs(along) >= 1.6 * Math.abs(across)) assert.ok(dir === 'front' || dir === 'back', `${theta}: ${dir}`)
    if (Math.abs(across) >= 1.6 * Math.abs(along)) assert.equal(dir, 'side', `${theta}: ${dir}`)
  }
})

test('a sheet kit with no three-quarter sheet splits that band where the movement changes its larger part, 45 and 135 degrees', () => {
  const plain = set('front', 'side', 'back')
  assert.deepEqual(sectorEdges(true, plain), [45, 45, 135, 135])
  assert.deepEqual(sectorEdges(false, plain), [45, 45, 135, 135])
  const found = (theta: number, walking: boolean) => sectorOf(theta, null, walking, plain).dir
  for (const walking of [true, false]) {
    assert.deepEqual([30, 44, 46, 60, 100, 130, 136, 150].map(theta => found(theta, walking)), ['front', 'front', 'side', 'side', 'side', 'side', 'back', 'back'])
  }
  assert.deepEqual(sectorEdges(true, set('front', 'front34', 'side')), [33, 57, 135, 135], 'each diagonal is judged alone')
  assert.deepEqual(sectorEdges(true, set()), [45, 45, 135, 135])
  assert.deepEqual(sectorEdges(true, set(...FIVE)), sectorEdges(true))
})

test('a band with no width is never held, so a three-quarter sector held before cannot come back', () => {
  const held = { index: 1, dir: 'front34' as const, negative: false }
  const plain = set('front', 'side', 'back')
  for (let theta = 20; theta <= 70; theta += 1) assert.notEqual(sectorOf(theta, held, true, plain).dir, 'front34')
  assert.equal(sectorOf(40, held).dir, 'front34', 'a drawn diagonal is held as before')
})

test('a walking figure keeps its sheet for 4 degrees past an edge, and a straight walk crosses each edge once', () => {
  const across = (from: number, to: number, step: number) => {
    let held = sectorOf(from, null, true)
    const changes: Record<string, number> = {}
    for (let theta = from; step > 0 ? theta <= to : theta >= to; theta += step) {
      const next = sectorOf(theta, held, true)
      if (next.dir !== held.dir) changes[`${held.dir}>${next.dir}`] = theta
      held = next
    }
    return changes
  }
  assert.deepEqual(across(0, 180, 0.5), { 'front>front34': 37.5, 'front34>side': 61.5, 'side>back34': 127.5, 'back34>back': 151.5 })
  assert.deepEqual(across(180, 0, -0.5), { 'back>back34': 142.5, 'back34>side': 118.5, 'side>front34': 52.5, 'front34>front': 28.5 })
})

test('a figure that jitters 3 degrees across an edge of the walk does not flicker', () => {
  const memory = new DirectionMemory()
  const seen = new Set<string>()
  for (let step = 0; step < 90; step += 1) seen.add(memory.choose('a', step / 24, 45 - WALK_DIAGONAL_DEGREES + (step % 2 ? 3 : -3), true).dir)
  assert.equal(seen.size, 1)
})

test('a figure that starts or stops walking takes the sector of its angle afresh', () => {
  const memory = new DirectionMemory()
  assert.equal(memory.choose('a', 0, 30).dir, 'front34', 'a standing figure at 30 degrees is three-quarter')
  assert.equal(memory.choose('a', 0.04, 30, true).dir, 'front', 'the same angle while it walks is front')
  assert.equal(memory.choose('a', 0.08, 30, true).dir, 'front')
  assert.equal(memory.choose('a', 0.12, 30).dir, 'front34', 'and three-quarter again when it stops')
})

// A walk along a straight line far from the camera, so the line to the camera hardly turns while the figure covers 5 metres.
function path(degrees: number, extra: Partial<DirectionalSprite> = {}): { sprite: DirectionalSprite; start: V2; eye: V2 } {
  const turn = degrees * Math.PI / 180, start: V2 = [0, 200]
  return { start, eye: [0, 0], sprite: { sheets: everything(), walk: { to: [start[0] - 5 * Math.sin(turn), start[1] - 5 * Math.cos(turn)], speed: 1, start: 0 }, ...extra } }
}

function pickedAlong(degrees: number, extra: Partial<DirectionalSprite> = {}, sheets?: DirectionalSheet[]): Set<string> {
  const { sprite, start, eye } = path(degrees, extra)
  if (sheets) sprite.sheets = sheets
  const memory = new DirectionMemory()
  const picked = new Set<string>()
  for (let t = 0.1; t < 4.9; t += 0.1) {
    const { view } = directionalView(sprite, { start, eye0: eye, eye, t, memory, id: 'ana' })
    assert.equal(view.kind, 'sheet')
    if (view.kind === 'sheet') picked.add(`${sprite.sheets[view.sheet].motion}-${sprite.sheets[view.sheet].dir}`)
  }
  return picked
}

test('a walk 30 degrees off the line to the camera is drawn by the front walk sheet, not the three-quarter one', () => {
  assert.deepEqual([...pickedAlong(30)], ['walk-front'])
  assert.deepEqual([...pickedAlong(-30)], ['walk-front'])
  assert.deepEqual([...pickedAlong(150)], ['walk-back'])
  assert.deepEqual([...pickedAlong(70)], ['walk-side'])
  assert.deepEqual([...pickedAlong(110)], ['walk-side'])
})

test('a really diagonal walk uses the three-quarter sheets, and a kit without them draws it by its larger part', () => {
  assert.deepEqual([...pickedAlong(45)], ['walk-front34'])
  assert.deepEqual([...pickedAlong(135)], ['walk-back34'])
  const three = everything(['front', 'side', 'back'])
  assert.deepEqual([...pickedAlong(40, {}, three)], ['walk-front'])
  assert.deepEqual([...pickedAlong(50, {}, three)], ['walk-side'])
  assert.deepEqual([...pickedAlong(130, {}, three)], ['walk-side'])
  assert.deepEqual([...pickedAlong(140, {}, three)], ['walk-back'])
  assert.deepEqual([...drawnDirections(three, 'walk')].sort(), ['back', 'front', 'side'])
})

test('a walk that stops to speak keeps the sector it had', () => {
  const { sprite, start, eye } = path(30, { speech: [[1, 2]] })
  const memory = new DirectionMemory()
  const sectors: string[] = []
  for (const t of [0.5, 0.9, 1.1, 1.5, 1.9, 2.1, 2.5]) sectors.push(directionalView(sprite, { start, eye0: eye, eye, t, memory, id: 'ana' }).sector.dir)
  assert.deepEqual(sectors, ['front', 'front', 'front', 'front', 'front', 'front', 'front'])
})

test('a figure with no heading keeps the sectors of its walk before and after it, and one with a heading stands by the plain sectors', () => {
  const sectorAt = (sprite: DirectionalSprite, start: V2, eye: V2, times: number[]) => {
    const memory = new DirectionMemory()
    return times.map(t => directionalView(sprite, { start, eye0: eye, eye, t, memory, id: 'ana' }).sector.dir)
  }
  const free = path(30, { walk: { to: [-2.5, 195.67], speed: 1, start: 1 } })
  assert.deepEqual(sectorAt(free.sprite, free.start, free.eye, [0.2, 0.6, 1.5, 3, 5, 5.4, 5.8]), ['front', 'front', 'front', 'front', 'front', 'front', 'front'])
  const turned = path(30, { heading: 30, walk: { to: [-2.5, 195.67], speed: 1, start: 1 } })
  assert.deepEqual(sectorAt(turned.sprite, turned.start, turned.eye, [0.5, 3, 7]), ['front34', 'front', 'front34'], 'it turns to its heading before and after the walk')
})

test('the walk numbers the spec states are the ones the code reads', () => {
  assert.equal(WALK_DIAGONAL_DEGREES, spec.walkDiagonalDeg)
  assert.ok(spec.walkDiagonalDeg >= 0 && spec.walkDiagonalDeg <= 22.5)
})
