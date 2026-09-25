import type { ModelOptions } from '../../types'

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
  'seed', 'num_inference_steps', 'guidance_scale', 'sample_solver', 'model_mode', 'batch_size',
  'activated_loras', 'loras_multipliers', 'flow_shift', 'guidance_phases', 'image_fit_mode',
] as const

export type ImageStudioDraft = {
  imageBatch?: import('./imageBatch').ImageBatchSettings
  params: Record<string, unknown>
  imageRefs: File[]
  imageRefType: string
  removeBackgroundRefs: boolean
  startImage: File | null
  endImage: File | null
  resolutionPreset: import('../../types').ResolutionPreset
  aspectRatio: import('../../types').AspectRatio
  imageSourceSize: { source: string; width: number; height: number } | null
  loraWeights: Record<string, number[]>
  outputCount: number
}

export function emptyImageStudioDraft(options?: Partial<ModelOptions> | null): ImageStudioDraft {
  return {
    params: {
      ...imageSamplingDefaults(options),
      sample_solver: options?.sample_solvers?.[0]?.[1] ?? '', model_mode: options?.image_edit_modes?.default ?? 0,
      batch_size: options?.image_layer_count?.default ?? 1, activated_loras: [], loras_multipliers: '', guidance_phases: 1,
    }, imageRefs: [], imageRefType: '', removeBackgroundRefs: false,
    startImage: null, endImage: null, imageSourceSize: null,
    resolutionPreset: 'auto', aspectRatio: 'auto', loraWeights: {}, outputCount: 1, imageBatch: undefined,
  }
}

function imageSamplingDefaults(options?: Partial<ModelOptions> | null) {
  return { seed: -1, num_inference_steps: options?.default_num_inference_steps ?? 20,
    guidance_scale: options?.default_guidance_scale ?? 5, flow_shift: options?.default_flow_shift }
}

export function imageStudioInputRequirement(intent: ImageStudioIntent, source: unknown, referenceCount: number): 'source' | 'reference' | null {
  if (intent === 'edit' && !source) return 'source'
  if (intent === 'character' && !referenceCount) return 'reference'
  return null
}

export function imageStudioDraft(state: Omit<ImageStudioDraft, 'params'> & { params: object }): ImageStudioDraft {
  return {
    imageBatch: state.imageBatch ? { ...state.imageBatch, sources: state.imageBatch.sources.map(item => ({ ...item })) } : undefined,
    params: Object.fromEntries(IMAGE_INTENT_PARAMS.map(key => [key, (state.params as Record<string, unknown>)[key]])),
    imageRefs: [...state.imageRefs], imageRefType: state.imageRefType,
    removeBackgroundRefs: state.removeBackgroundRefs,
    startImage: state.startImage, endImage: state.endImage,
    resolutionPreset: state.resolutionPreset, aspectRatio: state.aspectRatio,
    imageSourceSize: state.imageSourceSize,
    loraWeights: structuredClone(state.loraWeights), outputCount: state.outputCount,
  }
}

type ImageCapabilities = Pick<ModelOptions, 'image_ref_choices' | 'inpaint_support' | 'image_source_support'
  | 'image_source_required' | 'image_conditioning_required'>

export function supportsImageIntent(intent: ImageStudioIntent, options?: Partial<ImageCapabilities> | null): boolean {
  if (!options || intent === 'chooser') return true
  if (intent === 'edit') return Boolean(options.image_source_support || options.inpaint_support)
  if (intent === 'character') return Boolean(options.image_ref_choices) && !options.image_source_required
  return !options.image_source_required && !options.image_conditioning_required
}
