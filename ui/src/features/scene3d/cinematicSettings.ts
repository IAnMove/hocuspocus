import type { Scene3DDocument, Scene3DSlot } from './types'

const bounded = (n: unknown, fallback: number, min: number, max: number) =>
  typeof n === 'number' && Number.isFinite(n) ? Math.max(min, Math.min(max, n)) : fallback

export function parseEnvironment(raw: unknown): Scene3DDocument['environment'] {
  if (!raw || typeof raw !== 'object') return undefined
  const v = raw as NonNullable<Scene3DDocument['environment']>
  const floorStyle = v.floorStyle === 'mirror' || v.floorStyle === 'none' || v.floorStyle === 'tiles' || v.floorStyle === 'backdrop' ? v.floorStyle : undefined
  const floorColor = typeof v.floorColor === 'string' && /^#[a-f\d]{6}$/i.test(v.floorColor) ? v.floorColor : undefined
  const floorSourceHeight = typeof v.floorSourceHeight === 'number' && Number.isFinite(v.floorSourceHeight) ? bounded(v.floorSourceHeight, 1, .1, 1) : undefined
  return { reflectiveFloor: v.reflectiveFloor === true, platform: v.platform === true, bloom: bounded(v.bloom, .48, 0, 1.5), ...(floorStyle ? { floorStyle } : {}), ...(floorColor ? { floorColor } : {}), ...(floorSourceHeight !== undefined ? { floorSourceHeight } : {}) }
}

export function parseAppearance(raw: unknown): Scene3DSlot['appearance'] {
  if (!raw || typeof raw !== 'object') return undefined
  const v = raw as NonNullable<Scene3DSlot['appearance']>
  return { start: bounded(v.start, 2, 0, 600), duration: bounded(v.duration, .9, .1, 30),
    color: typeof v.color === 'string' && /^#[a-f\d]{6}$/i.test(v.color) ? v.color : '#83e8ff' }
}
