import type { Scene3DDocument, Scene3DSlot } from './types'

const bounded = (n: unknown, fallback: number, min: number, max: number) =>
  typeof n === 'number' && Number.isFinite(n) ? Math.max(min, Math.min(max, n)) : fallback

export function parseEnvironment(raw: unknown): Scene3DDocument['environment'] {
  if (!raw || typeof raw !== 'object') return undefined
  const v = raw as NonNullable<Scene3DDocument['environment']>
  return { reflectiveFloor: v.reflectiveFloor === true, platform: v.platform === true, bloom: bounded(v.bloom, .48, 0, 1.5) }
}

export function parseAppearance(raw: unknown): Scene3DSlot['appearance'] {
  if (!raw || typeof raw !== 'object') return undefined
  const v = raw as NonNullable<Scene3DSlot['appearance']>
  return { start: bounded(v.start, 2, 0, 600), duration: bounded(v.duration, .9, .1, 30),
    color: typeof v.color === 'string' && /^#[a-f\d]{6}$/i.test(v.color) ? v.color : '#83e8ff' }
}
