import { atmosSet } from './registry.ts'
import { resolveAtmos, type AtmosSettings } from './params.ts'

export type AtmosFallback = { sky: [number, number, number]; ground: [number, number, number] }

/** Flat look when WebGL2 is missing. Colors come from the set's fallback. */
export function atmosFallbackLook(settings?: AtmosSettings, setId?: string): AtmosFallback {
  const set = atmosSet(setId) ?? atmosSet('atmos-clearing')
  if (!set) return { sky: [213, 230, 198], ground: [109, 125, 88] }
  return set.fallback(resolveAtmos(settings, 'low', set.id))
}

export function hasWebGL2(gl: unknown): boolean {
  return typeof WebGL2RenderingContext !== 'undefined' && gl instanceof WebGL2RenderingContext
}
