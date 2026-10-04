import type { Vec3 } from '../types.ts'

export type AtmosQuality = 'low' | 'high'

export type AtmosSettings = {
  timeOfDay: string
  fogDensity: number
  wind: number
  motes: number
  palette: string
  variant?: number
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

export { parseAtmosSettings, resolveAtmos } from './registry.ts'

export function atmosFingerprint(resolved: ResolvedAtmos, seconds: number): string {
  const sun = resolved.sun.map(n => n.toFixed(4)).join(',')
  return [
    resolved.timeOfDay, resolved.palette, resolved.fogDensity.toFixed(3),
    resolved.wind.toFixed(3), resolved.motes.toFixed(3), resolved.seed,
    sun, seconds.toFixed(3), resolved.shaftSteps, resolved.grassBlades,
  ].join('|')
}
