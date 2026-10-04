import type { Group } from 'three'
import type { AtmosSettings, ResolvedAtmos } from './params.ts'

export type AtmosVec3 = readonly [number, number, number]
export type AtmosPalette = { fog: string; ground: string; accent: string; sky: readonly [string, string] }
export type AtmosTime = { sun: AtmosVec3; sunColor: string; sky?: readonly [string, string] }
export type AtmosCounts = { shaftSteps: number; grassBlades: number; moteCount: number }
export type AtmosTemplateSpec = {
  id: string
  camera: 'establishment'
  eye: AtmosVec3
  look: AtmosVec3
  fov: number
  duration: number
}
export type AtmosFallback = { sky: [number, number, number]; ground: [number, number, number] }

/** One procedural set. Ship it from registry.ts; keep its ids in registryIds.ts. */
export type AtmosSetDefinition = {
  id: string
  titleKey: string
  setting?: string
  seed: number
  subject: AtmosVec3
  subjectYaw: number
  palettes: Record<string, AtmosPalette>
  times: Record<string, AtmosTime>
  defaults: AtmosSettings
  variant?: { labelKey: string; min: number; max: number }
  low: AtmosCounts
  high: AtmosCounts
  templates: readonly AtmosTemplateSpec[]
  build: (resolved: ResolvedAtmos, webgl2: boolean) => { root: Group; handle: { dispose: () => void } }
  fallback: (resolved: ResolvedAtmos) => AtmosFallback
}
