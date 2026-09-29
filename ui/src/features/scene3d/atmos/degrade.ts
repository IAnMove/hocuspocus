import { parseAtmosSettings, type AtmosSettings } from './params.ts'

export type AtmosFallback = { sky: [number, number, number]; ground: [number, number, number] }

function hex(color: string): [number, number, number] {
  const n = Number.parseInt(color.slice(1), 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}

/** Flat look when WebGL2 is missing. No meshes, no passes. */
export function atmosFallbackLook(settings?: AtmosSettings): AtmosFallback {
  const resolved = settings ?? parseAtmosSettings({})!
  const sky = resolved.palette === 'autumn' ? '#ead4b2' : resolved.palette === 'blue' ? '#d4e4f0' : '#d5e6c6'
  const ground = resolved.palette === 'autumn' ? '#8a7a58' : resolved.palette === 'blue' ? '#7d8c86' : '#6d7d58'
  return { sky: hex(sky), ground: hex(ground) }
}

export function hasWebGL2(gl: unknown): boolean {
  return typeof WebGL2RenderingContext !== 'undefined' && gl instanceof WebGL2RenderingContext
}
