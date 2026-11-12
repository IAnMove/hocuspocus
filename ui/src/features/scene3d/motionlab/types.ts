import type { Group } from 'three'

export const MOTION_LAB_IDS = [
  'motion-bouncing-ball', 'motion-music-machine', 'motion-sunset-flight', 'motion-seasonal-carriage',
  'motion-data-assembly', 'motion-lighthouse-story', 'motion-poster-breakout', 'motion-particle-morph',
] as const
export type MotionLabId = typeof MOTION_LAB_IDS[number]
export function isMotionLab(value: unknown): value is MotionLabId {
  return typeof value === 'string' && (MOTION_LAB_IDS as readonly string[]).includes(value)
}
export type MotionLabSettings = {
  bpm: number; seed: number; title: string; color: string; secondaryColor: string
  density: number; amplitude: number; speed: number; sound: boolean; volume: number
}
export type MotionLabHandle = { root: Group; update: (seconds: number) => void; dispose: () => void }
export const DEFAULT_MOTION_LAB: Readonly<MotionLabSettings> = {
  bpm: 120, seed: 7, title: 'HOCUS', color: '#54ddff', secondaryColor: '#ffb86b',
  density: 900, amplitude: 1, speed: 1, sound: true, volume: .35,
}

/** Reject malformed controls at the common editor/MCP boundary rather than silently changing a render. */
export function parseMotionLab(raw: unknown): MotionLabSettings | undefined {
  if (raw === undefined) return undefined
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) throw new Error('Invalid motionLab settings.')
  const value = raw as Record<string, unknown>
  if (Object.keys(value).some(key => !Object.hasOwn(DEFAULT_MOTION_LAB, key))) throw new Error('Unknown motionLab setting.')
  const settings = { ...DEFAULT_MOTION_LAB, ...value } as MotionLabSettings
  for (const [key, min, max, integer] of [
    ['bpm', 40, 240, false], ['seed', 0, 2147483647, true], ['density', 200, 3000, true],
    ['amplitude', .1, 3, false], ['speed', .1, 3, false], ['volume', 0, 1, false],
  ] as const) {
    const number = settings[key]
    if (typeof number !== 'number' || !Number.isFinite(number) || number < min || number > max || (integer && !Number.isInteger(number))) throw new Error(`Invalid motionLab.${key}.`)
  }
  if (typeof settings.title !== 'string' || settings.title.trim().length > 24) throw new Error('Invalid motionLab.title.')
  settings.title = settings.title.trim()
  for (const key of ['color', 'secondaryColor'] as const) {
    if (typeof settings[key] !== 'string' || !/^#[\da-f]{6}$/i.test(settings[key])) throw new Error(`Invalid motionLab.${key}.`)
  }
  if (typeof settings.sound !== 'boolean') throw new Error('Invalid motionLab.sound.')
  return settings
}
