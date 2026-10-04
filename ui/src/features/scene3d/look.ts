/** Scene lighting from the environment and the colour look (tone mapping, exposure, LUT).

Both document fields are optional. A scene saved without them renders exactly as before;
new scenes get `NEW_SCENE_LIGHTING` and `NEW_SCENE_LOOK`. Phase 2.F2 adds HDRI loading and
2.F3 the LUT texture; this module only fixes the contract and its bounds.
*/
export type EnvironmentSource = 'room' | 'hdri' | 'none'
export type EnvironmentBackground = 'set' | 'hdri' | 'blurred'
export type Scene3DLighting = {
  environment: {
    source: EnvironmentSource
    /** Library or workspace URL of an equirectangular .hdr/.exr when `source` is `hdri`. */
    asset?: string
    intensity: number
    /** Degrees around +Y. */
    rotation: number
    background: EnvironmentBackground
    blur: number
  }
}
export type ToneMappingName = 'aces' | 'agx' | 'neutral'
export type Scene3DLook = {
  toneMapping: ToneMappingName
  /** Exposure in EV: the frame is multiplied by 2^exposure before tone mapping. */
  exposure: number
  lut?: { asset: string; strength: number }
}

/** Tuned on a Hunyuan pet, a box robot, a dark alien and a metallic sphere (2026-10-03): fill and reflections
 * without washing out light albedo; ACES matches the cinematic sets. */
export const NEW_SCENE_LIGHTING: Scene3DLighting = {
  environment: { source: 'room', intensity: 0.3, rotation: 0, background: 'set', blur: 0 },
}
export const NEW_SCENE_LOOK: Scene3DLook = { toneMapping: 'aces', exposure: -0.5 }

const SOURCES: readonly EnvironmentSource[] = ['room', 'hdri', 'none']
const BACKGROUNDS: readonly EnvironmentBackground[] = ['set', 'hdri', 'blurred']
const TONE_MAPPINGS: readonly ToneMappingName[] = ['aces', 'agx', 'neutral']

function bounded(value: unknown, min: number, max: number, fallback: number): number {
  return typeof value === 'number' && Number.isFinite(value) ? Math.min(max, Math.max(min, value)) : fallback
}

function assetUrl(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() && value.length <= 2000 && !/^(blob|file|javascript|filesystem):/i.test(value.trim())
    ? value.trim()
    : undefined
}

/** A stored lighting block, bounded; anything unusable means "no environment lighting" (today's look). */
export function parseLighting(raw: unknown): Scene3DLighting | undefined {
  const environment = (raw as { environment?: Record<string, unknown> } | null | undefined)?.environment
  if (!environment || typeof environment !== 'object') return undefined
  const source = SOURCES.includes(environment.source as EnvironmentSource) ? environment.source as EnvironmentSource : undefined
  if (!source) return undefined
  const asset = assetUrl(environment.asset)
  return {
    environment: {
      source,
      ...(asset ? { asset } : {}),
      intensity: bounded(environment.intensity, 0, 4, NEW_SCENE_LIGHTING.environment.intensity),
      rotation: ((bounded(environment.rotation, -3600, 3600, 0) % 360) + 360) % 360,
      background: BACKGROUNDS.includes(environment.background as EnvironmentBackground) ? environment.background as EnvironmentBackground : 'set',
      blur: bounded(environment.blur, 0, 1, 0),
    },
  }
}

/** A stored look, bounded; an unknown tone mapping drops the block. */
export function parseLook(raw: unknown): Scene3DLook | undefined {
  const value = raw as Record<string, unknown> | null | undefined
  if (!value || typeof value !== 'object' || !TONE_MAPPINGS.includes(value.toneMapping as ToneMappingName)) return undefined
  const lut = value.lut as { asset?: unknown; strength?: unknown } | undefined
  const asset = assetUrl(lut?.asset)
  return {
    toneMapping: value.toneMapping as ToneMappingName,
    exposure: bounded(value.exposure, -4, 4, 0),
    ...(asset ? { lut: { asset, strength: bounded(lut?.strength, 0, 1, 1) } } : {}),
  }
}

export function lightingField(raw: unknown): { lighting?: Scene3DLighting } {
  const lighting = parseLighting(raw)
  return lighting ? { lighting } : {}
}

export function lookField(raw: unknown): { look?: Scene3DLook } {
  const look = parseLook(raw)
  return look ? { look } : {}
}

/** 2^exposure, the renderer's `toneMappingExposure`. */
export function exposureFactor(look: Scene3DLook): number {
  return 2 ** look.exposure
}
