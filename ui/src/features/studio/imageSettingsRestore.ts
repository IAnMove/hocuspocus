import * as api from '../../api/client'
import { findResolutionSelection, getModelMode, invalidateModelOptionsLoad, type AppState } from '../../stores/useStore'
import type { GenerateParams, ModelOptions } from '../../types'
import { restoreImageFile } from '../../lib/storedImageFiles'
import { concreteImageResolution } from '../../lib/imageResolution'
import { STUDIO_IMAGE_PARAM_KEYS } from './generationSpec'
import { emptyImageStudioDraft, imageStudioDraft, type ImageStudioIntent } from './imageStudioIntent'
import { fetchCanonicalImageReferences } from './prepareGeneration'
import { mergeVideoPromptLetters } from '../../lib/studioImageEdit'

type Get = () => AppState
type Set = (patch: Partial<AppState>) => void
let revision = 0
let pending: AbortController | undefined
const FORM_FIELDS = ['params', 'generationMode', 'imageStudioIntent', 'activeWorkspace', 'browsingUploads',
  'imageRefs', 'imageRefType', 'removeBackgroundRefs', 'loraWeights', 'outputCount', 'resolutionPreset', 'aspectRatio',
  'spatialUpsampling', 'filmGrainIntensity', 'filmGrainSaturation'] as const

export function imageSettingsMode(params: Record<string, unknown>, state: AppState): boolean {
  const model = state.models.find(item => item.model_type === params.model_type)
  if (model) return getModelMode(model.model_type, model.family) === 'image'
  // Video sub-modes also use image_mode 1/2/3. When the catalog has not loaded
  // or the model was removed, trust the sidecar mode — never treat a video
  // job as an image restore just because image_mode is nonzero.
  if (params.generation_mode) return params.generation_mode === 'image'
  if (String(params.model_type).startsWith('qwen_image_')) return true
  if (Number(params.video_length) > 1) return false
  return Number(params.image_mode) === 1
}

/** Covers recipes, gallery actions and saved settings; editing the form wins over pending IO. */
export function beginImageSettingsChange(get: Get, stillCurrent: () => boolean = () => true) {
  pending?.abort()
  const controller = new AbortController(), ticket = ++revision, before = get()
  pending = controller
  return {
    signal: controller.signal,
    current: () => ticket === revision && stillCurrent() && FORM_FIELDS.every(field => get()[field] === before[field]),
  }
}

function imageParameters(saved: Record<string, unknown>, options: ModelOptions): GenerateParams {
  const defaults = emptyImageStudioDraft(options).params
  const params = Object.fromEntries(STUDIO_IMAGE_PARAM_KEYS.map(key => [key, saved[key]]))
  for (const [key, value] of Object.entries(defaults)) if (params[key] == null) params[key] = value
  return {
    ...params, model_type: String(saved.model_type), prompt: String(saved.prompt ?? ''),
    negative_prompt: String(saved.negative_prompt ?? ''),
    resolution: concreteImageResolution(saved.resolution ?? options.resolution_presets?.auto?.values?.auto, saved.model_type),
    image_mode: 1, video_length: 1, repeat_generation: 1,
    ...savedImageConditioning(saved),
  } as GenerateParams
}

function savedImageConditioning(saved: Record<string, unknown>) {
  return {
    image_guide: saved.image_guide || saved.video_guide || undefined,
    image_mask: saved.image_mask || saved.video_mask || undefined,
    video_guide_outpainting: saved.video_guide_outpainting || undefined,
    video_guide: undefined, video_mask: undefined,
    denoising_strength: saved.denoising_strength ?? 1, masking_strength: saved.masking_strength ?? 1,
    image_refs: Array.isArray(saved.image_refs) ? saved.image_refs : [],
  }
}

async function restoreMediaField(value: string | string[], workspace: string, signal: AbortSignal) {
  const list = Array.isArray(value) ? value : [value]
  const media = await Promise.all(list.map(path => path ? restoreImageFile(path, workspace, signal) : null))
  return { media, paths: Array.isArray(value) ? media.map(item => item?.url || '') : media[0]?.url }
}

async function restoreMedia(params: GenerateParams, workspace: string, signal: AbortSignal) {
  await restoreMediaIdentity(params)
  signal.throwIfAborted()
  const refs = await Promise.all((params.image_refs || []).map(path => restoreImageFile(path, workspace, signal)))
  params.image_refs = refs.map(item => item.url)
  const frames: Partial<Pick<AppState, 'startImage' | 'endImage'>> = { startImage: null, endImage: null }
  let imageSourceSize: AppState['imageSourceSize'] = null
  for (const field of ['image_guide', 'image_mask', 'image_start', 'image_end'] as const) {
    const value = params[field]
    if (!value) continue
    const { media, paths } = await restoreMediaField(value, workspace, signal)
    Object.assign(params, { [field]: paths })
    if (field === 'image_guide' && media[0] && typeof createImageBitmap === 'function') {
      const bitmap = await createImageBitmap(media[0].file)
      imageSourceSize = { source: media[0].url, width: bitmap.width, height: bitmap.height }
      bitmap.close()
    }
    if (field === 'image_start') frames.startImage = media[0]?.file || null
    if (field === 'image_end') frames.endImage = media[0]?.file || null
  }
  return { imageRefs: refs.map(item => item.file), imageSourceSize, ...frames }
}

async function restoreMediaIdentity(params: GenerateParams): Promise<void> {
  const fields = ['image_guide', 'image_mask', 'image_refs', 'image_start', 'image_end'] as const
  for (const field of fields) {
    const value = params[field]
    const values = Array.isArray(value) ? value : value ? [value] : []
    if (!values.some(path => path && (!path.startsWith('/api/v1/') || path.startsWith('/api/v1/assets/')))) continue
    const resolved = await fetchCanonicalImageReferences(values.filter(Boolean))
    let index = 0
    Object.assign(params, { [field]: Array.isArray(value) ? values.map(path => path ? resolved[index++] : '') : resolved[0] })
  }
  if (params.image_guide) params.video_prompt_type = mergeVideoPromptLetters(String(params.video_prompt_type || ''), params.image_mask ? 'VAG' : 'V')
}

function imageIntent(params: GenerateParams, options: ModelOptions): ImageStudioIntent {
  if (params.image_guide || options.image_source_required) return 'edit'
  if (params.image_refs?.length || options.image_conditioning_required) return 'character'
  return 'new'
}

function imageWeights(params: GenerateParams): Record<string, number[]> {
  const parts = String(params.loras_multipliers || '').split(' ').filter(Boolean)
  return Object.fromEntries((params.activated_loras || []).map((name, i) => [name, (parts[i] || '1').split(';').map(Number)]))
}

function savedImageFinish(saved: Record<string, unknown>) {
  return { spatialUpsampling: String(saved.spatial_upsampling || ''),
    filmGrainIntensity: Number(saved.film_grain_intensity ?? 0), filmGrainSaturation: Number(saved.film_grain_saturation ?? .5) }
}

function savedReferenceType(params: GenerateParams) {
  if (String(params.video_prompt_type || '').includes('K')) return 'KI'
  return params.image_refs?.length ? 'I' : ''
}

/** Commit a complete image form once. Missing inputs fail without reusing the previous draft. */
export async function restoreStudioImageSettings(saved: Record<string, unknown>, workspace: string, get: Get, set: Set,
  stillCurrent: () => boolean = () => true): Promise<boolean> {
  const change = beginImageSettingsChange(get, stillCurrent)
  invalidateModelOptionsLoad()
  set({ modelOptionsLoading: false })
  try {
    const options = await api.fetchModelOptions(String(saved.model_type))
    if (!change.current()) return false
    const params = imageParameters(saved, options)
    const media = await restoreMedia(params, workspace, change.signal)
    if (!change.current()) return false
    const state = get(), intent = imageIntent(params, options), drafts = { ...state.imageStudioDrafts }
    if (state.generationMode === 'image' && state.imageStudioIntent !== 'chooser') drafts[state.imageStudioIntent] = imageStudioDraft(state)
    const selection = findResolutionSelection(params.resolution, options)
    const draft = { ...emptyImageStudioDraft(options), ...media, params: { ...params }, loraWeights: imageWeights(params),
      ...(selection ? { resolutionPreset: selection.preset, aspectRatio: selection.ratio } : {}),
      removeBackgroundRefs: Boolean(params.remove_background_images_ref),
      imageRefType: savedReferenceType(params),
    }
    drafts[intent] = draft
    set({ ...draft, generationMode: 'image', imageStudioIntent: intent, imageStudioDrafts: drafts,
      modelOptions: options, modelOptionsLoading: false, selectedModelPerMode: { ...state.selectedModelPerMode, image: params.model_type },
      availableLoras: [], ...savedImageFinish(saved),
    })
    void get().loadLoras(params.model_type)
    return true
  } catch (error) {
    if (!change.current() || change.signal.aborted) return false
    throw error
  }
}
