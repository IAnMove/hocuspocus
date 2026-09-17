import { parseEndlessRoad } from './endlessRoad'
import type { Scene3DDocument, Scene3DSlot } from './types'

type Environment = NonNullable<Scene3DDocument['environment']>
type FloorStyle = NonNullable<Environment['floorStyle']>

const FLOOR_STYLES = new Set<FloorStyle>(['mirror', 'none', 'tiles', 'backdrop', 'road'])
const bounded = (n: unknown, fallback: number, min: number, max: number) =>
  typeof n === 'number' && Number.isFinite(n) ? Math.max(min, Math.min(max, n)) : fallback

function parseFloorStyle(value: unknown): FloorStyle | undefined {
  return typeof value === 'string' && FLOOR_STYLES.has(value as FloorStyle) ? value as FloorStyle : undefined
}

function parseHexColor(value: unknown) {
  return typeof value === 'string' && /^#[a-f\d]{6}$/i.test(value) ? value : undefined
}

function optionalField<K extends string, T>(key: K, value: T | undefined): Partial<Record<K, T>> {
  return value === undefined ? {} : { [key]: value } as Partial<Record<K, T>>
}

/** Seamless/tiles reflectors stay hidden when the floor is off or replaced by the road. */
export function cinematicReflectorVisible(environment: Scene3DDocument['environment']) {
  return environment?.reflectiveFloor === true && environment.floorStyle !== 'none' && environment.floorStyle !== 'road'
}

export function parseEnvironment(raw: unknown): Scene3DDocument['environment'] {
  if (!raw || typeof raw !== 'object') return undefined
  const v = raw as Environment
  const floorSourceHeight = typeof v.floorSourceHeight === 'number' && Number.isFinite(v.floorSourceHeight)
    ? bounded(v.floorSourceHeight, 1, .1, 1) : undefined
  return {
    reflectiveFloor: v.reflectiveFloor === true,
    platform: v.platform === true,
    bloom: bounded(v.bloom, .48, 0, 1.5),
    ...optionalField('road', parseEndlessRoad(v.road)),
    ...optionalField('floorStyle', parseFloorStyle(v.floorStyle)),
    ...optionalField('floorColor', parseHexColor(v.floorColor)),
    ...optionalField('floorSourceHeight', floorSourceHeight),
  }
}

export function parseAppearance(raw: unknown): Scene3DSlot['appearance'] {
  if (!raw || typeof raw !== 'object') return undefined
  const v = raw as NonNullable<Scene3DSlot['appearance']>
  return { start: bounded(v.start, 2, 0, 600), duration: bounded(v.duration, .9, .1, 30),
    color: typeof v.color === 'string' && /^#[a-f\d]{6}$/i.test(v.color) ? v.color : '#83e8ff' }
}
