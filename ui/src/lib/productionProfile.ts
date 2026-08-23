import type { AspectRatio, ModelOptions, ProductionProfile, ResolutionPreset } from '../types'

export const DEFAULT_PRODUCTION_PROFILE: ProductionProfile = {
  version: 1,
  text: { provider: 'minimax', model: 'MiniMax-M3' },
  image: { provider: 'minimax', model: 'image-01' },
  music: { provider: 'local', model: 'ace_step_v1_5_xl_sft_lm_4b' },
  video: {
    provider: 'local',
    model: 'minimax_h3_legacy',
    settings: {
      profile: 'quality',
      steps: 20,
      flowShift: 12,
      audioShift: 3,
      turbo: false,
      cache: false,
      loras: [],
      resolution: '540p',
      aspectRatio: '16:9',
    },
  },
}

export function productionImageModelType(profile: ProductionProfile): string {
  const model = profile.image.model.trim()
  return profile.image.provider === 'minimax' && !model.startsWith('minimax:')
    ? `minimax:${model || 'image-01'}`
    : model
}

const PRESET_HEIGHT: Record<ResolutionPreset, number> = {
  auto: 540,
  '480p': 480,
  '540p': 540,
  '720p': 720,
  '768p': 768,
  '1080p': 1080,
}

function nearestPreset(
  options: ModelOptions | null | undefined,
  requested: ResolutionPreset,
): ResolutionPreset {
  const order = (options?.resolution_preset_order || [])
    .filter((item): item is ResolutionPreset => item in PRESET_HEIGHT && item !== 'auto')
  if (!order.length || order.includes(requested)) return requested
  const wanted = PRESET_HEIGHT[requested] || PRESET_HEIGHT['540p']
  return order.reduce((best, candidate) => (
    Math.abs(Math.log(PRESET_HEIGHT[candidate] / wanted))
      < Math.abs(Math.log(PRESET_HEIGHT[best] / wanted))
      ? candidate
      : best
  ), order[0])
}

function sameOrientation(left: AspectRatio, right: AspectRatio): boolean {
  const orientation = (value: AspectRatio) => {
    if (value === '9:16' || value === '3:4') return 'portrait'
    if (value === '1:1' || value === 'auto') return 'neutral'
    return 'landscape'
  }
  return orientation(left) === orientation(right)
}

/** Resolve a requested profile to a model-advertised preset and aspect.
 *
 * Exact matches win. If the model does not expose that tier, the closest
 * pixel-height tier is selected. Aspect fallback never flips landscape into
 * portrait (or the reverse).
 */
export function resolveSupportedVideoFormat(
  options: ModelOptions | null | undefined,
  requestedPreset: ResolutionPreset,
  requestedAspect: AspectRatio,
): { resolution: ResolutionPreset; aspectRatio: AspectRatio; adjusted: boolean } {
  const resolution = nearestPreset(options, requestedPreset)
  const values = options?.resolution_presets?.[resolution]?.values
  const supportedAspects = Object.keys(values || {}) as AspectRatio[]
  let aspectRatio = requestedAspect
  if (supportedAspects.length && !supportedAspects.includes(requestedAspect)) {
    aspectRatio = supportedAspects.find(candidate => sameOrientation(candidate, requestedAspect))
      || supportedAspects.find(candidate => candidate === '16:9')
      || supportedAspects[0]
  } else if (requestedAspect === 'auto' && options && !options.supports_auto_aspect) {
    aspectRatio = supportedAspects.includes('16:9') ? '16:9' : supportedAspects[0] || '16:9'
  }
  return {
    resolution,
    aspectRatio,
    adjusted: resolution !== requestedPreset || aspectRatio !== requestedAspect,
  }
}
