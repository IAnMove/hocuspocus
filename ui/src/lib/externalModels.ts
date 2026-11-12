export const MINIMAX_IMAGE_API_MODEL = 'minimax:image-01'
export const MINIMAX_IMAGE_API_LABEL = 'MiniMax Image-01 · external API'

/** The picker already lists MiniMax Image-01 under «external API»; the catalog entry must not appear a second time. */
export function withoutExternalImageModel<T extends { model_type: string }>(models: T[]): T[] {
  return models.filter(model => model.model_type !== MINIMAX_IMAGE_API_MODEL)
}
