import { bindAtmosExtra } from './registryIds.ts'
import type { AtmosQuality, AtmosSettings, ResolvedAtmos } from './params.ts'
import type { AtmosSetDefinition, AtmosVec3 } from './definition.ts'
import { clearingSet } from './sets/clearing.ts'
import { waterfallSet } from './sets/waterfall.ts'

export const ATMOS_SETS: readonly AtmosSetDefinition[] = [clearingSet, waterfallSet]

const extra: AtmosSetDefinition[] = []

export function atmosSets(): readonly AtmosSetDefinition[] {
  return extra.length ? [...ATMOS_SETS, ...extra] : ATMOS_SETS
}

export function atmosSet(id: string | undefined): AtmosSetDefinition | undefined {
  return atmosSets().find(set => set.id === id)
}

export function isAtmosDressing(kind: string | undefined): boolean {
  return Boolean(kind && atmosSet(kind))
}

/** Test hook. A set installed here is visible without editing another module. */
export function installAtmosSet(set: AtmosSetDefinition): () => void {
  extra.push(set)
  bindAtmosExtra(set.id, true)
  return () => {
    const index = extra.indexOf(set)
    if (index >= 0) extra.splice(index, 1)
    bindAtmosExtra(set.id, false)
  }
}

export function atmosTemplate(id: string): { set: AtmosSetDefinition; template: AtmosSetDefinition['templates'][number] } | undefined {
  for (const set of atmosSets()) {
    const template = set.templates.find(item => item.id === id)
    if (template) return { set, template }
  }
  return undefined
}

function unit(value: unknown, fallback: number): number {
  return typeof value === 'number' && Number.isFinite(value) ? Math.min(1, Math.max(0, value)) : fallback
}

function normalize(v: AtmosVec3): AtmosVec3 {
  const len = Math.hypot(v[0], v[1], v[2]) || 1
  return [v[0] / len, v[1] / len, v[2] / len]
}

export function parseAtmosSettings(raw: unknown, setId?: string): AtmosSettings | undefined {
  if (!raw || typeof raw !== 'object') return undefined
  const set = atmosSet(setId) ?? clearingSet
  const value = raw as Partial<AtmosSettings>
  const timeOfDay = set.times[String(value.timeOfDay)] ? String(value.timeOfDay) : set.defaults.timeOfDay
  const palette = set.palettes[String(value.palette)] ? String(value.palette) : set.defaults.palette
  const settings: AtmosSettings = {
    timeOfDay,
    fogDensity: unit(value.fogDensity, set.defaults.fogDensity),
    wind: unit(value.wind, set.defaults.wind),
    motes: unit(value.motes, set.defaults.motes),
    palette,
    ...(value.previewFigure === true ? { previewFigure: true } : {}),
  }
  if (set.variant && typeof value.variant === 'number' && Number.isFinite(value.variant)) {
    settings.variant = Math.min(set.variant.max, Math.max(set.variant.min, value.variant))
  }
  return settings
}

export function resolveAtmos(settings: AtmosSettings | undefined, quality: AtmosQuality, setId?: string): ResolvedAtmos {
  const set = atmosSet(setId) ?? clearingSet
  const base = settings ?? set.defaults
  const look = set.palettes[base.palette] ?? set.palettes[set.defaults.palette]
  const day = set.times[base.timeOfDay] ?? set.times[set.defaults.timeOfDay]
  const high = quality === 'high'
  const count = high ? set.high : set.low
  return {
    ...base,
    seed: set.seed,
    sun: normalize(day.sun),
    sunColor: day.sunColor,
    fogColor: look.fog,
    grass: look.accent,
    stone: look.ground,
    shaftSteps: count.shaftSteps,
    grassBlades: count.grassBlades,
    moteCount: count.moteCount,
    dof: high,
  }
}
