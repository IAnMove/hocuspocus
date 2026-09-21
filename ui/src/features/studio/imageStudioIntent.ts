export type ImageStudioIntent = 'chooser' | 'new' | 'edit' | 'loop' | 'character'

export const IMAGE_STUDIO_INTENTS: Array<{
  id: Exclude<ImageStudioIntent, 'chooser'>
  icon: string
}> = [
  { id: 'new', icon: '✦' },
  { id: 'edit', icon: '✎' },
  { id: 'character', icon: '☺' },
  { id: 'loop', icon: '∞' },
]


// Keep each image workflow's inputs in its own draft. The model remains shared.
export const IMAGE_INTENT_PARAMS = [
  'prompt', 'negative_prompt', 'resolution', 'image_guide', 'image_mask', 'image_refs',
  'image_start', 'image_end', 'video_guide', 'video_mask', 'video_guide_outpainting',
  'video_prompt_type', 'image_prompt_type', 'remove_background_images_ref',
  'denoising_strength', 'masking_strength',
] as const

export type ImageStudioDraft = {
  params: Record<string, unknown>
  imageRefs: File[]
  imageRefType: string
  removeBackgroundRefs: boolean
  startImage: File | null
  endImage: File | null
  resolutionPreset: import('../../types').ResolutionPreset
  aspectRatio: import('../../types').AspectRatio
  imageSourceSize: { source: string; width: number; height: number } | null
}

export function imageStudioDraft(state: Omit<ImageStudioDraft, 'params'> & { params: object }): ImageStudioDraft {
  return {
    params: Object.fromEntries(IMAGE_INTENT_PARAMS.map(key => [key, (state.params as Record<string, unknown>)[key]])),
    imageRefs: [...state.imageRefs], imageRefType: state.imageRefType,
    removeBackgroundRefs: state.removeBackgroundRefs,
    startImage: state.startImage, endImage: state.endImage,
    resolutionPreset: state.resolutionPreset, aspectRatio: state.aspectRatio,
    imageSourceSize: state.imageSourceSize,
  }
}
