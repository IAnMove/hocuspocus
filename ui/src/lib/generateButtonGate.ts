import type { TFunction } from 'i18next'

export function hasOutpaintArea(box: { x: number; y: number; w: number; h: number }): boolean {
  return box.x > .0005 || box.y > .0005 || box.x + box.w < .9995 || box.y + box.h < .9995
}

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
  incompatibleImage?: boolean
  localUnavailable?: boolean
  needsImage?: boolean
  needsReference?: boolean
  needsOutpaintSource?: boolean
  needsOutpaintArea?: boolean
  needsPrompt?: boolean
  needsScheduledPrompts?: boolean
  t: TFunction<'studio'>
}): { label: string; title?: string } {
  if (input.incompatibleImage) return { label: input.t('imageIntent.changeModel'), title: input.t('imageIntent.incompatible') }
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
