import type { Vec3 } from '../types.ts'

export type TimeOfDay = 'dawn' | 'morning' | 'golden'
export type ClearingPalette = 'green' | 'autumn' | 'blue'
export type AtmosQuality = 'low' | 'high'

export type AtmosSettings = {
  timeOfDay: TimeOfDay
  fogDensity: number
  wind: number
  motes: number
  palette: ClearingPalette
  previewFigure?: boolean
}

export type ResolvedAtmos = AtmosSettings & {
  seed: number
  sun: Vec3
  sunColor: string
  fogColor: string
  grass: string
  stone: string
  shaftSteps: number
  grassBlades: number
  moteCount: number
  dof: boolean
}

const DAYS: Record<TimeOfDay, { sun: Vec3; sunColor: string }> = {
  dawn: { sun: [0.7, -0.28, 0.22], sunColor: '#ffb4c0' },
  morning: { sun: [0.4, -0.82, 0.16], sunColor: '#fff4dc' },
  golden: { sun: [0.82, -0.55, 0.16], sunColor: '#ffd39a' },
}

const PALETTES: Record<ClearingPalette, { fog: string; grass: string; stone: string }> = {
  green: { fog: '#d5e6c6', grass: '#7cbc46', stone: '#b7bba6' },
  autumn: { fog: '#ead4b2', grass: '#c4a04a', stone: '#c6b49c' },
  blue: { fog: '#d4e4f0', grass: '#6aadc4', stone: '#b7c2c8' },
}

const DAYS_SET = new Set<string>(['dawn', 'morning', 'golden'])
const PALETTE_SET = new Set<string>(['green', 'autumn', 'blue'])

function unit(value: unknown, fallback: number): number {
  return typeof value === 'number' && Number.isFinite(value) ? Math.min(1, Math.max(0, value)) : fallback
}

function normalize(v: Vec3): Vec3 {
  const len = Math.hypot(v[0], v[1], v[2]) || 1
  return [v[0] / len, v[1] / len, v[2] / len]
}

export function parseAtmosSettings(raw: unknown): AtmosSettings | undefined {
  if (!raw || typeof raw !== 'object') return undefined
  const value = raw as Partial<AtmosSettings>
  const timeOfDay = DAYS_SET.has(String(value.timeOfDay)) ? value.timeOfDay as TimeOfDay : 'golden'
  const palette = PALETTE_SET.has(String(value.palette)) ? value.palette as ClearingPalette : 'green'
  return {
    timeOfDay,
    fogDensity: unit(value.fogDensity, 0.58),
    wind: unit(value.wind, 0.46),
    motes: unit(value.motes, 0.72),
    palette,
    ...(value.previewFigure === true ? { previewFigure: true } : {}),
  }
}

export function resolveAtmos(settings: AtmosSettings | undefined, quality: AtmosQuality): ResolvedAtmos {
  const base = settings ?? parseAtmosSettings({})!
  const look = PALETTES[base.palette]
  const day = DAYS[base.timeOfDay]
  const high = quality === 'high'
  return {
    ...base,
    seed: 17041,
    sun: normalize(day.sun),
    sunColor: day.sunColor,
    fogColor: look.fog,
    grass: look.grass,
    stone: look.stone,
    shaftSteps: high ? 24 : 8,
    grassBlades: high ? 24000 : 4000,
    moteCount: high ? 700 : 220,
    dof: high,
  }
}

export function atmosFingerprint(resolved: ResolvedAtmos, seconds: number): string {
  const sun = resolved.sun.map(n => n.toFixed(4)).join(',')
  return [
    resolved.timeOfDay, resolved.palette, resolved.fogDensity.toFixed(3),
    resolved.wind.toFixed(3), resolved.motes.toFixed(3), resolved.seed,
    sun, seconds.toFixed(3), resolved.shaftSteps, resolved.grassBlades,
  ].join('|')
}
