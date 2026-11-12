export const MINIMAX_IMAGE_API_MODEL = 'minimax:image-01'
export const MINIMAX_IMAGE_API_LABEL = 'MiniMax Image-01 · external API'
export const MINIMAX_H3_IMAGE_MODEL = 'minimax:h3-image'
export const MINIMAX_H3_IMAGE_FAST_MODEL = 'minimax:h3-image-highspeed'

/** Hardcoded so a picker can offer them even when the catalog copy is hidden. */
export const EXTERNAL_IMAGE_MODELS = [
  { model_type: MINIMAX_IMAGE_API_MODEL, label: MINIMAX_IMAGE_API_LABEL },
  { model_type: MINIMAX_H3_IMAGE_MODEL, label: 'MiniMax H3-Image · external API' },
  { model_type: MINIMAX_H3_IMAGE_FAST_MODEL, label: 'MiniMax H3-Image Highspeed · external API' },
] as const

export function isExternalImageModel(modelType: string): boolean {
  return EXTERNAL_IMAGE_MODELS.some(model => model.model_type === modelType)
}

/** The picker already lists these under «external API»; the catalog entry must not appear a second time. */
export function withoutExternalImageModel<T extends { model_type: string }>(models: T[]): T[] {
  return models.filter(model => !isExternalImageModel(model.model_type))
}
