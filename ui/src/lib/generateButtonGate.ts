import type { TFunction } from 'i18next'

export function isRemoteMiniMaxImage(
  generationMode: string,
  modelType: string | undefined,
  imageProvider: string | undefined,
): boolean {
  return generationMode === 'image' && (
    String(modelType || '').startsWith('minimax:')
    || imageProvider === 'minimax'
  )
}

export function generateBlockedCopy(input: {
  localUnavailable?: boolean
  needsImage?: boolean
  needsReference?: boolean
  needsOutpaintSource?: boolean
  needsOutpaintArea?: boolean
  t: TFunction<'studio'>
}): { label: string; title?: string } {
  if (input.localUnavailable) {
    return { label: input.t('generate.localUnavailable'), title: input.t('generate.localUnavailableHint') }
  }
  if (input.needsImage) return { label: input.t('generate.needImage') }
  if (input.needsReference) {
    return { label: input.t('generate.needReference'), title: input.t('generate.referenceHint') }
  }
  if (input.needsOutpaintSource) return { label: input.t('generate.needSource') }
  if (input.needsOutpaintArea) {
    return { label: input.t('generate.chooseCanvas'), title: input.t('generate.outpaintAreaHint') }
  }
  return { label: input.t('generate.addPrompt') }
}
