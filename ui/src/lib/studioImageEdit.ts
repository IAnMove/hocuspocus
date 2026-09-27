import type { ModelOptions } from '../types'

export interface StudioImageEditCapabilities {
  refs: boolean
  maxRefs: number | null
  inpaint: boolean
  source: boolean
  outpaint: boolean
  rgba: boolean
  twoK: boolean
}

export function studioImageEditCapabilities(
  options: ModelOptions | null | undefined,
): StudioImageEditCapabilities | null {
  if (!options) return null
  const refs = Boolean(options.image_ref_choices)
  const inpaint = Boolean(options.inpaint_support)
  const source = Boolean(options.image_source_support || inpaint)
  const outpaint = Boolean(options.outpaint_support)
  const rgba = Boolean(options.native_rgba)
  const twoK = Boolean(options.resolution_presets?.['1080p'])
  if (!refs && !source && !outpaint && !rgba && !twoK) return null
  return {
    refs,
    maxRefs: options.max_image_refs ?? null,
    inpaint,
    source,
    outpaint,
    rgba,
    twoK,
  }
}

export function mergeVideoPromptLetters(current: string, add: string, remove = ''): string {
  let next = current
  for (const letter of remove) next = next.split(letter).join('')
  for (const letter of add) {
    if (letter && !next.includes(letter)) next += letter
  }
  return next
}
