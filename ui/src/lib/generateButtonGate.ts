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
  needsPrompt?: boolean
  needsScheduledPrompts?: boolean
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
  if (input.needsScheduledPrompts) return { label: input.t('generate.addPrompts') }
  if (input.needsPrompt) {
    return { label: input.t('generate.addPrompt'), title: input.t('generate.addPromptHint') }
  }
  return { label: input.t('generate.addPrompt') }
}
