import type { AspectRatio, ModelOptions, ProductionProfile, ResolutionPreset } from '../types'

export const DEFAULT_PRODUCTION_PROFILE: ProductionProfile = {
  version: 1,
  text: { provider: 'minimax', model: 'MiniMax-M3', base_url: 'https://api.minimax.io' },
  image: { provider: 'local', model: 'qwen_image_21' },
  music: { provider: 'local', model: 'ace_step_v1_5_xl_sft_lm_4b' },
  model3d: { provider: 'local', model: 'hunyuan3d-2mini-turbo' },
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

export function writingProviderFromText(
  provider: ProductionProfile['text']['provider'],
): 'maestro' | 'deepseek' | 'minimax' | 'openai' | 'openai-compatible' | 'ollama' | 'grok' {
  if (provider === 'local' || provider === 'anthropic') return 'maestro'
  if (provider === 'remote') return 'openai-compatible'
  return provider
}

export function seriesProviderFieldsFromProfile(profile: ProductionProfile) {
  const portrait = profile.video.settings.aspectRatio === '9:16'
    || profile.video.settings.aspectRatio === '3:4'
  return {
    writingProvider: writingProviderFromText(profile.text.provider),
    writingModel: profile.text.model,
    writingBaseUrl: writingBaseUrlFromProfile(profile),
    imageProvider: (profile.image.provider === 'minimax' ? 'minimax' : 'maestro') as 'minimax' | 'maestro',
    imageModel: profile.image.model,
    videoModel: profile.video.model,
    videoSettings: {
      resolution: profile.video.settings.resolution,
      orientation: (portrait ? 'portrait' : 'landscape') as 'landscape' | 'portrait',
      numInferenceSteps: profile.video.settings.steps,
      flowShift: profile.video.settings.flowShift,
      audioShift: profile.video.settings.audioShift,
      modelProfile: profile.video.settings.profile,
    },
  }
}

export function seriesProviderMatchesGlobal(
  provider: {
    writingProvider?: string
    writingModel?: string
    writingBaseUrl?: string
    imageProvider?: string
    imageModel?: string
    videoModel?: string
    videoSettings?: Record<string, unknown>
  },
  fields: ReturnType<typeof seriesProviderFieldsFromProfile>,
): boolean {
  const settings = provider.videoSettings || {}
  return provider.writingProvider === fields.writingProvider
    && provider.writingModel === fields.writingModel
    && (provider.writingBaseUrl || '') === (fields.writingBaseUrl || '')
    && provider.imageProvider === fields.imageProvider
    && provider.imageModel === fields.imageModel
    && provider.videoModel === fields.videoModel
    && settings.resolution === fields.videoSettings.resolution
    && settings.orientation === fields.videoSettings.orientation
    && settings.numInferenceSteps === fields.videoSettings.numInferenceSteps
    && settings.flowShift === fields.videoSettings.flowShift
    && settings.audioShift === fields.videoSettings.audioShift
    && settings.modelProfile === fields.videoSettings.modelProfile
}

export function applySeriesGlobalProvider<T extends {
  useGlobalProfile?: boolean
  writingProvider?: string
  writingModel?: string
  writingBaseUrl?: string
  imageProvider?: string
  imageModel?: string
  videoModel?: string
  videoSettings?: Record<string, unknown>
}>(provider: T, fields: ReturnType<typeof seriesProviderFieldsFromProfile>): T {
  return {
    ...provider,
    useGlobalProfile: true,
    writingProvider: fields.writingProvider,
    writingModel: fields.writingModel,
    writingBaseUrl: fields.writingBaseUrl,
    imageProvider: fields.imageProvider,
    imageModel: fields.imageModel,
    videoModel: fields.videoModel,
    videoSettings: {
      ...(provider.videoSettings || {}),
      ...fields.videoSettings,
    },
  }
}

export function writingBaseUrlFromProfile(profile: ProductionProfile): string {
  if (profile.text.base_url) return profile.text.base_url
  if (profile.text.provider === 'minimax') return 'https://api.minimax.io/v1'
  if (profile.text.provider === 'grok') return 'https://api.x.ai/v1'
  if (profile.text.provider === 'ollama') return 'http://127.0.0.1:11434'
  if (profile.text.provider === 'openai') return 'https://api.openai.com'
  if (profile.text.provider === 'deepseek') return 'https://api.deepseek.com'
  return ''
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
