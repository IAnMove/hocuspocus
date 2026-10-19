import { durableScene3DSourceUrl } from './slotSource.ts'
import { parseAnchor } from './talkingCutout.ts'
import {
  DIRECTIONS, LATERAL, SECONDS, clamp, finite, headingDegrees,
  type Direction, type DirectionalSheet, type DirectionalSprite, type DirectionalWalk, type Motion, type Window,
} from './directionalSprite.ts'
import spec from '../../../../app/shared/directional_sprites.json' with { type: 'json' }

/** Reads a stored `screen.directional`: what the editor keeps of it. The bounds are the server's (`services/directional_sprite.py`). */
const MAX_SHEETS = 24
const MAX_WINDOWS = 64
const MIN_SPEED = 0.05
const MAX_SPEED = 20
const REACH = 1000

const integer = (value: unknown, low: number, high: number): value is number => Number.isInteger(value) && (value as number) >= low && (value as number) <= high

/** A kit's `side_r`, `front34_r` and `back34_r` are the lateral directions drawn looking left; the rest of the names are the five. */
function directionOf(raw: unknown): { dir: Direction; reversed: boolean } | undefined {
  const text = typeof raw === 'string' ? raw : ''
  const reversed = text.endsWith('_r')
  const base = reversed ? text.slice(0, -2) : text
  if (!(DIRECTIONS as readonly string[]).includes(base) || (reversed && !LATERAL.has(base))) return undefined
  return { dir: base as Direction, reversed }
}

/** The cells of a sheet: how many, in how many columns and rows, and how big each one is. */
function sheetGrid(value: Record<string, unknown>): Pick<DirectionalSheet, 'columns' | 'rows' | 'count' | 'cell'> | undefined {
  const cell = (value.cell ?? {}) as Record<string, unknown>
  const { count, columns, rows } = value, { width, height } = cell
  if (!integer(count, 1, 64) || !integer(columns, 1, 64) || !integer(rows, 1, 64) || !integer(width, 1, 16384) || !integer(height, 1, 16384)) return undefined
  return { columns, rows, count, cell: { width, height } }
}

function sheetCore(value: Record<string, unknown>): DirectionalSheet | undefined {
  const source = durableScene3DSourceUrl(typeof value.source === 'string' ? value.source : '')
  const direction = directionOf(value.dir), grid = sheetGrid(value)
  if (!source || source.length > 2000 || !direction || !grid || !(spec.motions as unknown[]).includes(value.motion)) return undefined
  return { motion: value.motion as Motion, dir: direction.dir, source, ...grid,
    fps: finite(value.fps) ? clamp(value.fps, 1, 60) : 8, loop: value.loop === 'pingpong' || value.loop === 'once' ? value.loop : 'loop',
    ...(direction.reversed ? { facing: 'left' as const } : {}) }
}

function sheetExtras(value: Record<string, unknown>, sheet: DirectionalSheet): DirectionalSheet {
  if (typeof value.id === 'string' && value.id.length <= 80) sheet.id = value.id
  if (!sheet.facing && (value.facing === 'left' || value.facing === 'right' || value.facing === 'front')) sheet.facing = value.facing
  for (const key of ['feet', 'figure'] as const) {
    const share = value[key]
    if (finite(share) && share > 0 && share <= 1) sheet[key] = share
  }
  for (const key of ['mouth', 'eyes'] as const) {
    const anchor = parseAnchor(value[key])
    if (anchor) sheet[key] = anchor
  }
  return sheet
}

function parseSheet(raw: unknown): DirectionalSheet | undefined {
  if (!raw || typeof raw !== 'object') return undefined
  const value = raw as Record<string, unknown>
  const sheet = sheetCore(value)
  return sheet ? sheetExtras(value, sheet) : undefined
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

/** A stored `screen.directional`: the sheets that are well formed, and the heading, walk, speech windows and light tint that are. A
 * figure with no sheet still turns and walks, in its pose; a block that says none of it is nothing. */
export function parseDirectional(raw: unknown): DirectionalSprite | undefined {
  if (!raw || typeof raw !== 'object') return undefined
  const value = raw as Record<string, unknown>
  const sheets = (Array.isArray(value.sheets) ? value.sheets.slice(0, MAX_SHEETS) : []).map(parseSheet).filter((sheet): sheet is DirectionalSheet => Boolean(sheet))
  const heading = headingDegrees(value.heading), walk = parseWalk(value.walk), speech = parseSpeech(value.speech)
  if (!sheets.length && heading === undefined && !walk) return undefined
  const tint = finite(value.lightTint) && value.lightTint >= 0 && value.lightTint <= 1 ? value.lightTint : undefined
  return { sheets, ...(heading !== undefined ? { heading } : {}), ...(walk ? { walk } : {}), ...(speech ? { speech } : {}), ...(tint !== undefined ? { lightTint: tint } : {}) }
}
