import type { TFunction } from 'i18next'
import type { ModelDef } from '../../types'

export type ComicMovieQuality =
  | '480p' | '540p' | '720p' | '768p' | '1080p'
  | 'h3-fast' | 'h3-default' | 'h3-balanced' | 'h3-native'
export type ComicMovieAspect = 'landscape' | 'portrait' | 'square'

export type ComicMovieResolution = {
  quality: ComicMovieQuality
  value: string
  label: string
  recommended?: boolean
  preset?: string
  aspectRatio?: string
}

type H3Tier = {
  quality: ComicMovieQuality
  preset: string
  landscape: string
  portrait: string
  square: string
  label: 'p480' | 'rtxDefault' | 'p720' | 'nativeRes' | 'p1080'
  recommended?: boolean
}

const H3_TIERS: H3Tier[] = [
  { quality: '480p', preset: '480p', landscape: '864x480', portrait: '480x864', square: '640x640', label: 'p480' },
  { quality: '540p', preset: '540p', landscape: '960x544', portrait: '544x960', square: '736x736', label: 'rtxDefault' },
  { quality: '720p', preset: '720p', landscape: '1280x704', portrait: '704x1280', square: '704x704', label: 'p720', recommended: true },
  { quality: '768p', preset: '768p', landscape: '1344x768', portrait: '768x1344', square: '768x768', label: 'nativeRes' },
  { quality: '1080p', preset: '1080p', landscape: '1920x1088', portrait: '1088x1920', square: '1088x1088', label: 'p1080' },
]

export const resolutionMegapixels = (value: string): number => {
  const [width, height] = value.split('x').map(Number)
  return (width * height) / 1_000_000
}

export const isH3Family = (modelId: string, architecture = ''): boolean => (
  modelId.toLowerCase().startsWith('minimax_h3')
  || architecture.toLowerCase().startsWith('minimax_h3')
)

const aspectKey = (aspect: ComicMovieAspect): string => (
  aspect === 'portrait' ? '9:16' : aspect === 'square' ? '1:1' : '16:9'
)

const h3Size = (tier: H3Tier, aspect: ComicMovieAspect): string => (
  aspect === 'portrait' ? tier.portrait : aspect === 'square' ? tier.square : tier.landscape
)

const h3Label = (t: TFunction<'comics'>, tier: H3Tier, size: string): string => {
  const pretty = size.replace('x', '×')
  const mp = resolutionMegapixels(size).toFixed(2)
  if (tier.label === 'rtxDefault') return t('video.rtxDefault', { size: pretty, mp })
  if (tier.label === 'nativeRes') return t('video.nativeRes', { size: pretty, mp })
  if (tier.label === 'p480') return t('video.p480', { size: pretty })
  if (tier.label === 'p1080') return t('video.p1080', { size: pretty })
  return t('video.p720', { size: pretty })
}

export const comicMovieResolutions = (
  t: TFunction<'comics'>,
  modelId: string,
  aspect: ComicMovieAspect,
  architecture = '',
): ComicMovieResolution[] => {
  if (isH3Family(modelId, architecture)) {
    const ratio = aspectKey(aspect)
    return H3_TIERS.map(tier => {
      const value = h3Size(tier, aspect)
      return {
        quality: tier.quality,
        value,
        label: h3Label(t, tier, value),
        recommended: tier.recommended,
        preset: tier.preset,
        aspectRatio: ratio,
      }
    })
  }
  return [
    {
      quality: '480p',
      value: aspect === 'portrait' ? '448x832' : aspect === 'square' ? '640x640' : '832x448',
      label: t('video.p480', { size: aspect === 'portrait' ? '448×832' : aspect === 'square' ? '640×640' : '832×448' }),
    },
    {
      quality: '720p',
      value: aspect === 'portrait' ? '704x1280' : aspect === 'square' ? '1024x1024' : '1280x704',
      label: t('video.p720', { size: aspect === 'portrait' ? '704×1280' : aspect === 'square' ? '1024×1024' : '1280×704' }),
      recommended: true,
    },
    {
      quality: '1080p',
      value: aspect === 'portrait' ? '1088x1920' : aspect === 'square' ? '1408x1408' : '1920x1088',
      label: t('video.p1080', { size: aspect === 'portrait' ? '1088×1920' : aspect === 'square' ? '1408×1408' : '1920×1088' }),
    },
  ]
}

export const comicDirectorResolutionFields = (
  option: ComicMovieResolution,
): { director_resolution_preset?: string; director_aspect_ratio?: string } => {
  if (!option.preset || !option.aspectRatio) return {}
  return {
    director_resolution_preset: option.preset,
    director_aspect_ratio: option.aspectRatio,
  }
}

export const comicMovieEngineCompatible = (model: ModelDef): boolean => {
  const comic = model.director?.video?.comic_movie
  if (comic) return comic.compatible
  return model.is_i2v
}

export const selectableComicMovieEngines = (
  models: ModelDef[],
  enabled: { has(modelType: string): boolean },
): ModelDef[] => models
  .filter(model => enabled.has(model.model_type) && comicMovieEngineCompatible(model))
  .sort((left, right) => left.name.localeCompare(right.name))

export const installedComicMovieEngine = (
  models: ModelDef[],
  enabled: { has(modelType: string): boolean },
  selected: string,
): string => {
  const installed = selectableComicMovieEngines(models, enabled)
    .filter(model => model.is_downloaded !== false)
  if (selected && installed.some(model => model.model_type === selected)) return selected
  return installed[0]?.model_type || selected || 'ltx2_22B_distilled_1_1'
}
