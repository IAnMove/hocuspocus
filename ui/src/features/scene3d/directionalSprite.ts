import spec from '../../../../app/shared/directional_sprites.json' with { type: 'json' }
import animationCatalog from '../../../../app/shared/character_animations.json' with { type: 'json' }
import { durableScene3DSourceUrl } from './slotSource.ts'

/** A 2D figure in a 3D shot that shows the drawing facing the camera (the effect of Doom and the 2.5D games): the sheet of
 * the angle between where the figure looks and where the camera is, mirrored for the left, with its walk cycle played by
 * the ground it covers. Everything here is a pure function of the document and the time; `DirectionMemory` is the only
 * state, and it forgets on any jump in time, so a seek always lands on the same drawing. The numbers are
 * `app/shared/directional_sprites.json`, which the server reads too (`services/series_directional.py`). */
export const DIRECTIONS = ['front', 'front34', 'side', 'back34', 'back'] as const
export type Direction = (typeof DIRECTIONS)[number]
export type Motion = 'walk' | 'idle'
export type Loop = 'loop' | 'pingpong' | 'once'
/** Ground point or vector: x and z, in metres. */
export type V2 = readonly [number, number]
export type Window = readonly [number, number]

export const STEP_METERS: number = spec.stepMeters
export const CYCLE_STEPS: number = spec.cycleSteps
export const CYCLE_METERS = STEP_METERS * CYCLE_STEPS
export const DEFAULT_WALK_SPEED: number = spec.walkSpeed
export const HYSTERESIS_DEGREES: number = spec.hysteresisDeg
const RESET_SECONDS: number = spec.resetSeconds
const SECTOR_DEGREES = 45
const HALF_SECTOR = SECTOR_DEGREES / 2
const LATERAL = new Set<string>(spec.lateral)
const MAX_SHEETS = 24
const MAX_WINDOWS = 64
const MIN_SPEED = 0.05
const MAX_SPEED = 20
const SECONDS = 3600
const REACH = 1000
const MIN_ASPECT = 0.1
const MAX_ASPECT = 4
/** The width of a figure's feet in plane units (the plane is two units high): the contact shadow under it. */
const FOOT_METERS = 0.3

export type DirectionalSheet = {
  /** The kit animation it came from. */
  id?: string
  motion: Motion
  dir: Direction
  source: string
  columns: number
  rows: number
  count: number
  cell: { width: number; height: number }
  fps: number
  loop: Loop
  /** Where the sheet looks when it is not to the right (a `side` sheet drawn looking left). */
  facing?: 'left' | 'right' | 'front'
  /** Where the boots are in the cell and how much of it the figure fills; the catalog's when absent. */
  feet?: number
  figure?: number
}

export type DirectionalWalk = { to: V2; speed: number; start: number }
export type DirectionalView = { kind: 'sheet'; sheet: number; mirror: boolean; frame: number } | { kind: 'pose'; talking: boolean }

/** `screen.directional`: what the figure can show, where it looks, where it walks and when it speaks. */
export type DirectionalSprite = {
  sheets: DirectionalSheet[]
  /** Degrees against the camera of the start of the shot: 0 faces it, 90 faces screen right, 180 turns its back. */
  heading?: number
  walk?: DirectionalWalk
  /** Seconds in which the figure speaks: it shows its talking pose and does not walk. */
  speech?: Window[]
  /** Set by the painter pass for one frame; never stored. */
  view?: DirectionalView
}

export type Sector = { index: number; dir: Direction; negative: boolean }

const degrees = (radians: number) => radians * 180 / Math.PI
const radians = (value: number) => value * Math.PI / 180
const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value)
const clamp = (value: number, low: number, high: number) => Math.min(high, Math.max(low, value))

/** An angle in (-180, 180]. */
export function normalizeDegrees(value: number): number {
  const wrapped = (((value + 180) % 360) + 360) % 360 - 180
  return wrapped === -180 ? 180 : wrapped
}

function plainSector(theta: number): Sector {
  const angle = normalizeDegrees(theta)
  const reach = Math.abs(angle)
  const index = reach <= HALF_SECTOR ? 0 : Math.min(4, Math.ceil((reach - HALF_SECTOR) / SECTOR_DEGREES))
  return { index, dir: DIRECTIONS[index], negative: angle < 0 }
}

/** The sector of an angle (0 front, 45 front34, 90 side, 135 back34, 180 back; the negative angles are the same sectors
 * seen from the left). With the sector held before, it stays until the angle is `hysteresisDeg` past its edge. */
export function sectorOf(theta: number, previous?: Sector | null): Sector {
  if (previous) {
    const lateral = previous.index > 0 && previous.index < 4
    const center = previous.index * SECTOR_DEGREES * (lateral && previous.negative ? -1 : 1)
    if (Math.abs(normalizeDegrees(theta - center)) <= HALF_SECTOR + HYSTERESIS_DEGREES) return previous
  }
  return plainSector(theta)
}

/** The sector each figure holds from one frame to the next. It forgets after a jump in time. */
export class DirectionMemory {
  private readonly held = new Map<string, { sector: Sector; t: number }>()

  choose(id: string, t: number, theta: number): Sector {
    const last = this.held.get(id)
    const sector = sectorOf(theta, last && Math.abs(t - last.t) <= RESET_SECONDS ? last.sector : null)
    this.held.set(id, { sector, t })
    return sector
  }
}

/** Degrees of where `facing` looks against the line from the camera `eye` to the figure at `at`: 0 faces the camera,
 * positive faces the camera's right. Null when the camera stands on the figure. */
export function faceAngle(facing: V2, at: V2, eye: V2): number | null {
  const dx = at[0] - eye[0], dz = at[1] - eye[1], length = Math.hypot(dx, dz)
  if (length < 1e-6) return null
  const ax = dx / length, az = dz / length
  const rx = -az, rz = ax
  return degrees(Math.atan2(facing[0] * rx + facing[1] * rz, -(facing[0] * ax + facing[1] * az)))
}

/** Where a figure looks in the ground plane when its heading is read against the camera at the start of the shot. */
export function headingFacing(heading: number, at: V2, eye0: V2): V2 {
  const dx = at[0] - eye0[0], dz = at[1] - eye0[1], length = Math.hypot(dx, dz)
  if (length < 1e-6) return [0, 1]
  const ax = dx / length, az = dz / length
  const turn = radians(heading)
  return [-ax * Math.cos(turn) + -az * Math.sin(turn), -az * Math.cos(turn) + ax * Math.sin(turn)]
}

/** A heading as degrees in (-180, 180]: a number, or `toward`, `right`, `away`, `left`. */
export function headingDegrees(value: unknown): number | undefined {
  const named = typeof value === 'string' ? (spec.headings as Record<string, number>)[value] : undefined
  const raw = named ?? value
  return finite(raw) && Math.abs(raw) <= SECONDS ? normalizeDegrees(raw) : undefined
}

/** The unit vector from one ground point to another, null when they are the same. */
export function travelFacing(from: V2, to: V2): V2 | null {
  const dx = to[0] - from[0], dz = to[1] - from[1], length = Math.hypot(dx, dz)
  return length < 1e-9 ? null : [dx / length, dz / length]
}

export function inWindow(windows: readonly Window[] | undefined, t: number): boolean {
  return Boolean(windows?.some(([start, end]) => t >= start && t < end))
}

function overlap(windows: readonly Window[] | undefined, from: number, to: number): number {
  return (windows ?? []).reduce((sum, [start, end]) => sum + Math.max(0, Math.min(to, end) - Math.max(from, start)), 0)
}

export type WalkState = {
  x: number
  z: number
  /** Metres walked. */
  distance: number
  phase: 'before' | 'walking' | 'paused' | 'arrived'
  /** Unit vector of the path, null for a path of no length. */
  travel: V2 | null
}

/** Where a figure is on its straight walk at `t`. It walks only while it is silent: a figure that speaks stands where it
 * is, so the walk ends later by the time it spoke. */
export function walkState(from: V2, walk: DirectionalWalk, speech: readonly Window[] | undefined, t: number): WalkState {
  const travel = travelFacing(from, walk.to)
  const length = Math.hypot(walk.to[0] - from[0], walk.to[1] - from[1])
  const walked = Math.max(0, t - walk.start - overlap(speech, walk.start, t)) * walk.speed
  const distance = Math.min(length, walked)
  let phase: WalkState['phase'] = 'walking'
  if (!travel) phase = 'arrived'
  else if (t < walk.start) phase = 'before'
  else if (distance >= length) phase = 'arrived'
  else if (inWindow(speech, t)) phase = 'paused'
  const along = length > 0 ? distance / length : 0
  return { x: from[0] + (walk.to[0] - from[0]) * along, z: from[1] + (walk.to[1] - from[1]) * along, distance, phase, travel }
}

/** The cell a running count of steps lands on. */
export function cellAt(raw: number, count: number, loop: Loop): number {
  if (count <= 1) return 0
  if (loop === 'once') return clamp(raw, 0, count - 1)
  if (loop === 'pingpong') {
    const period = count * 2 - 2
    const at = ((raw % period) + period) % period
    return at < count ? at : period - at
  }
  return ((raw % count) + count) % count
}

/** The cell of a walk cycle after `distance` metres: a cycle is `cycleSteps` steps of `stepMeters`, so the feet cover the
 * same ground for every cell and nothing slides. */
export function strideFrame(distance: number, count: number, loop: Loop): number {
  const period = loop === 'pingpong' && count > 1 ? count * 2 - 2 : count
  return cellAt(Math.floor(Math.max(0, distance) / CYCLE_METERS * period), count, loop)
}

function bestPerDirection(sheets: readonly DirectionalSheet[], motion: Motion): Map<number, number> {
  const best = new Map<number, number>()
  sheets.forEach((sheet, index) => {
    if (sheet.motion !== motion) return
    const key = DIRECTIONS.indexOf(sheet.dir)
    const held = best.get(key)
    if (held === undefined || sheet.count > sheets[held].count) best.set(key, index)
  })
  return best
}

function nearestSheet(sheets: readonly DirectionalSheet[], motion: Motion, target: number): number {
  const best = bestPerDirection(sheets, motion)
  const keys = [...best.keys()].sort((a, b) => Math.abs(a - target) - Math.abs(b - target) || a - b)
  return keys.length ? best.get(keys[0])! : -1
}

function mirrored(sheet: DirectionalSheet, sector: Sector): boolean {
  return LATERAL.has(sheet.dir) ? sector.negative !== (sheet.facing === 'left') : false
}

/** The sheet for a sector: the one of its direction, else the nearest direction the kit has (a tie takes the one nearer
 * the front); a walk with no walk sheet glides on an idle one; index -1 is the pose. A left sector mirrors a sheet that
 * looks right. */
export function pickSheet(sheets: readonly DirectionalSheet[], motion: Motion, sector: Sector): { index: number; mirror: boolean; exact: boolean } {
  for (const wanted of motion === 'walk' ? ['walk', 'idle'] as const : ['idle'] as const) {
    const index = nearestSheet(sheets, wanted, sector.index)
    if (index >= 0) return { index, mirror: mirrored(sheets[index], sector), exact: wanted === motion && sheets[index].dir === sector.dir }
  }
  return { index: -1, mirror: false, exact: false }
}

export type ViewContext = { start: V2; eye0: V2; eye: V2; t: number; memory: DirectionMemory; id: string }

/** Where the figure stands at `t`: the point it was placed at, or the point of its walk. */
export function directionalPosition(sprite: DirectionalSprite, start: readonly [number, number, number], t: number): readonly [number, number, number] {
  if (!sprite.walk) return start
  const state = walkState([start[0], start[2]], sprite.walk, sprite.speech, t)
  return [state.x, start[1], state.z]
}

function facingOf(sprite: DirectionalSprite, state: WalkState | null, context: ViewContext): V2 {
  if (state?.travel && (state.phase === 'walking' || state.phase === 'paused')) return state.travel
  if (sprite.heading !== undefined) return headingFacing(sprite.heading, context.start, context.eye0)
  return state?.travel ?? headingFacing(0, context.start, context.eye0)
}

/** What the figure shows at `t` from the camera at `eye`: a cell of a sheet, or its pose (talking while it speaks). */
export function directionalView(sprite: DirectionalSprite, context: ViewContext): { view: DirectionalView; theta: number | null; sector: Sector } {
  const state = sprite.walk ? walkState(context.start, sprite.walk, sprite.speech, context.t) : null
  const at: V2 = state ? [state.x, state.z] : context.start
  const theta = faceAngle(facingOf(sprite, state, context), at, context.eye)
  const sector = context.memory.choose(context.id, context.t, theta ?? 0)
  if (inWindow(sprite.speech, context.t)) return { view: { kind: 'pose', talking: true }, theta, sector }
  const picked = pickSheet(sprite.sheets, state?.phase === 'walking' ? 'walk' : 'idle', sector)
  if (picked.index < 0) return { view: { kind: 'pose', talking: false }, theta, sector }
  const sheet = sprite.sheets[picked.index]
  const frame = sheet.motion === 'walk' ? strideFrame(state?.distance ?? 0, sheet.count, sheet.loop)
    : cellAt(Math.floor(context.t * sheet.fps), sheet.count, sheet.loop)
  return { view: { kind: 'sheet', sheet: picked.index, mirror: picked.mirror, frame }, theta, sector }
}

/** The plane every cell is drawn on: as wide as the widest cell, with the boots on the catalog's line. */
export function spriteFrame(sprite: Pick<DirectionalSprite, 'sheets'>): { aspect: number; feet: number; figure: number } {
  const first = sprite.sheets[0]
  const aspect = Math.max(...sprite.sheets.map(sheet => sheet.cell.width / sheet.cell.height))
  return { aspect: clamp(aspect, MIN_ASPECT, MAX_ASPECT), feet: first?.feet ?? animationCatalog.sheet.feet, figure: first?.figure ?? animationCatalog.sheet.figure }
}

/** Where its boots stand in the plane, as an image footprint: the contact shadow and the grounding read it. */
export function spriteFoot(sprite: Pick<DirectionalSprite, 'sheets'>): { bottom: number; center: number; width: number } {
  const { aspect, feet } = spriteFrame(sprite)
  return { bottom: 1 - feet, center: 0.5, width: Math.min(1, FOOT_METERS / aspect) }
}

// Reading a stored block --------------------------------------------------------------------------------------------

const integer = (value: unknown, low: number, high: number): value is number => Number.isInteger(value) && (value as number) >= low && (value as number) <= high

function parseSheet(raw: unknown): DirectionalSheet | undefined {
  if (!raw || typeof raw !== 'object') return undefined
  const value = raw as Record<string, unknown>
  const cell = (value.cell ?? {}) as Record<string, unknown>
  const source = durableScene3DSourceUrl(typeof value.source === 'string' ? value.source : '')
  const { motion, dir, count, columns, rows } = value, { width, height } = cell
  if (!source || source.length > 2000 || !(spec.motions as unknown[]).includes(motion) || !(DIRECTIONS as readonly unknown[]).includes(dir)
    || !integer(count, 1, 64) || !integer(columns, 1, 64) || !integer(rows, 1, 64) || !integer(width, 1, 16384) || !integer(height, 1, 16384)) return undefined
  const sheet: DirectionalSheet = { motion: motion as Motion, dir: dir as Direction, source, columns, rows, count, cell: { width, height },
    fps: finite(value.fps) ? clamp(value.fps, 1, 60) : 8, loop: value.loop === 'pingpong' || value.loop === 'once' ? value.loop : 'loop' }
  if (typeof value.id === 'string' && value.id.length <= 80) sheet.id = value.id
  if (value.facing === 'left' || value.facing === 'right' || value.facing === 'front') sheet.facing = value.facing
  for (const key of ['feet', 'figure'] as const) {
    const share = value[key]
    if (finite(share) && share > 0 && share <= 1) sheet[key] = share
  }
  return sheet
}

function parseWalk(raw: unknown): DirectionalWalk | undefined {
  if (!raw || typeof raw !== 'object') return undefined
  const { to, speed, start } = raw as Record<string, unknown>
  if (!Array.isArray(to) || to.length !== 2 || !finite(to[0]) || !finite(to[1]) || Math.abs(to[0]) > REACH || Math.abs(to[1]) > REACH || !finite(speed) || !finite(start)) return undefined
  return { to: [to[0], to[1]], speed: clamp(speed, MIN_SPEED, MAX_SPEED), start: clamp(start, 0, SECONDS) }
}

function parseSpeech(raw: unknown): Window[] | undefined {
  if (!Array.isArray(raw)) return undefined
  const windows = raw.slice(0, MAX_WINDOWS).filter((item): item is [number, number] =>
    Array.isArray(item) && item.length === 2 && finite(item[0]) && finite(item[1]) && item[0] >= 0 && item[1] <= SECONDS && item[1] > item[0])
    .sort((a, b) => a[0] - b[0])
  const merged: [number, number][] = []
  for (const [start, end] of windows) {
    const last = merged[merged.length - 1]
    if (last && start <= last[1]) last[1] = Math.max(last[1], end)
    else merged.push([start, end])
  }
  return merged.length ? merged : undefined
}

/** A stored `screen.directional`: the sheets that are well formed, and the heading, walk and speech windows that are. A figure with
 * no sheet still turns and walks, in its pose; a block that says none of it is nothing. */
export function parseDirectional(raw: unknown): DirectionalSprite | undefined {
  if (!raw || typeof raw !== 'object') return undefined
  const value = raw as Record<string, unknown>
  const sheets = (Array.isArray(value.sheets) ? value.sheets.slice(0, MAX_SHEETS) : []).map(parseSheet).filter((sheet): sheet is DirectionalSheet => Boolean(sheet))
  const heading = headingDegrees(value.heading), walk = parseWalk(value.walk), speech = parseSpeech(value.speech)
  if (!sheets.length && heading === undefined && !walk) return undefined
  return { sheets, ...(heading !== undefined ? { heading } : {}), ...(walk ? { walk } : {}), ...(speech ? { speech } : {}) }
}
