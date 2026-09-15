import { BASE } from '../../api/http'
import { stableSerialize } from '../../lib/commandContract'
import { viggleEditingParameters } from '../../lib/viggleWorkflow'
import type { GenerationDetails } from '../../types'
import i18n from '../../i18n'
import {
  createStudioImageGenerationCommand,
  type StudioImageGenerationCommand,
} from './generationSpec'
import { generationProvenancePayload, type GenerationSubmissionContext } from './generationProvenance'
import { translateLegacyImageGuides } from './imageCommandSubmission'

const MEDIA_FIELDS = ['image_refs', 'image_start', 'image_end', 'image_guide', 'image_mask'] as const

export type ScheduledPromptSubmission = {
  prompt: string
  position: number
  total: number
}

export type StudioImageClip = {
  prompt?: string
  startImage?: File | null
  startImagePath?: string | null
  endImage?: File | null
  endImagePath?: string | null
  keyframes?: Array<{ file?: File | null; path?: string | null }>
}

export type StudioImageModelFlags = {
  omniReference: boolean
  firstBlockCache: boolean
  skipStepsMultiplierChoices: number[]
  defaultSkipStepsMultiplier: number
  defaultSkipStepsStartStepPerc: number
  perturbation: boolean
  referencePipeline: boolean
  hasH3TextEncoderChoices: boolean
  slidingWindowAutoPromptPacing: boolean
}

export type StudioImageIntent = {
  generationMode: 'image'
  activeWorkspace: string
  params: Record<string, unknown>
  model: StudioImageModelFlags
  models: Array<{ model_type: string; name: string }>
  llmLoaded: boolean
  imageRefs: File[]
  imageRefType: string
  removeBackgroundRefs: boolean
  startImage: File | null
  endImage: File | null
  clips: StudioImageClip[]
  singlePromptMode: boolean
  spatialUpsampling: string
  filmGrainIntensity: number
  filmGrainSaturation: number
  voiceCloneEnabled: boolean
  voiceCloneMode: 'single' | 'two'
  voiceCloneRefs: Array<{ filename: string; path: string }>
  directorVoiceRef: File | null
  directorVoiceRefPath: string | null
  directorIdentityGuidanceScale: number
  resolutionPreset: string
  aspectRatio: string
  editReturnTarget: { modelType?: string; sourceResolution?: string } | null
}

export type StudioImageIntentSource = {
  generationMode: string
  activeWorkspace?: string
  params?: Record<string, unknown>
  modelOptions?: {
    omni_reference?: boolean
    first_block_cache?: boolean
    skip_steps_multiplier_choices?: [string, number][] | null
    default_skip_steps_multiplier?: number
    default_skip_steps_start_step_perc?: number
    perturbation?: boolean
    reference_pipeline?: boolean
    minimax_h3_text_encoder_choices?: unknown[] | null
    sliding_window_auto_prompt_pacing?: boolean
  } | null
  models?: Array<{ model_type: string; name: string }>
  llmStatus?: { loaded?: boolean } | null
  imageRefs?: File[]
  imageRefType?: string
  removeBackgroundRefs?: boolean
  startImage?: File | null
  endImage?: File | null
  clips?: StudioImageClip[]
  singlePromptMode?: boolean
  spatialUpsampling?: string
  filmGrainIntensity?: number
  filmGrainSaturation?: number
  voiceCloneEnabled?: boolean
  voiceCloneMode?: 'single' | 'two'
  voiceCloneRefs?: Array<{ filename: string; path: string }>
  directorVoiceRef?: File | null
  directorVoiceRefPath?: string | null
  directorIdentityGuidanceScale?: number
  resolutionPreset?: string
  aspectRatio?: string
  editReturnTarget?: { modelType?: string; sourceResolution?: string } | null
}

export type StudioImageUpload = { path: string; url: string }

export type StudioImageResolvePorts = {
  uploadImage: (file: File) => Promise<StudioImageUpload>
  uploadAudio: (file: File) => Promise<{ path: string }>
  resolveReferences: (references: unknown[]) => Promise<string[]>
  persistDirectorVoicePath?: (path: string) => void
}

export type StudioImageNormalizeResult = {
  params: Record<string, unknown>
  persistH3FirstFrame: boolean
}

function detachParams(params: Record<string, unknown>): Record<string, unknown> {
  try {
    return structuredClone(params)
  } catch {
    return { ...params }
  }
}

function snapshotModelFlags(
  options: StudioImageIntentSource['modelOptions'],
): StudioImageModelFlags {
  return {
    omniReference: options?.omni_reference === true,
    firstBlockCache: options?.first_block_cache === true,
    skipStepsMultiplierChoices: (options?.skip_steps_multiplier_choices || []).map(choice => choice[1]),
    defaultSkipStepsMultiplier: options?.default_skip_steps_multiplier ?? 0.08,
    defaultSkipStepsStartStepPerc: options?.default_skip_steps_start_step_perc ?? 25,
    perturbation: options?.perturbation === true,
    referencePipeline: Boolean(options?.reference_pipeline),
    hasH3TextEncoderChoices: Boolean(options?.minimax_h3_text_encoder_choices?.length),
    slidingWindowAutoPromptPacing: options?.sliding_window_auto_prompt_pacing === true,
  }
}

function snapshotClips(clips: StudioImageClip[] | undefined): StudioImageClip[] {
  return (clips || []).map(clip => ({
    prompt: clip.prompt,
    startImage: clip.startImage ?? null,
    startImagePath: clip.startImagePath ?? null,
    endImage: clip.endImage ?? null,
    endImagePath: clip.endImagePath ?? null,
    keyframes: (clip.keyframes || []).map(keyframe => ({
      file: keyframe.file ?? null,
      path: keyframe.path ?? null,
    })),
  }))
}

function snapshotMedia(source: StudioImageIntentSource): Pick<
  StudioImageIntent,
  'imageRefs' | 'imageRefType' | 'removeBackgroundRefs' | 'startImage' | 'endImage' | 'clips'
> {
  return {
    imageRefs: [...(source.imageRefs || [])],
    imageRefType: source.imageRefType || '',
    removeBackgroundRefs: Boolean(source.removeBackgroundRefs),
    startImage: source.startImage ?? null,
    endImage: source.endImage ?? null,
    clips: snapshotClips(source.clips),
  }
}

function snapshotVoice(source: StudioImageIntentSource): Pick<
  StudioImageIntent,
  | 'voiceCloneEnabled'
  | 'voiceCloneMode'
  | 'voiceCloneRefs'
  | 'directorVoiceRef'
  | 'directorVoiceRefPath'
  | 'directorIdentityGuidanceScale'
> {
  return {
    voiceCloneEnabled: Boolean(source.voiceCloneEnabled),
    voiceCloneMode: source.voiceCloneMode === 'two' ? 'two' : 'single',
    voiceCloneRefs: [...(source.voiceCloneRefs || [])],
    directorVoiceRef: source.directorVoiceRef ?? null,
    directorVoiceRefPath: source.directorVoiceRefPath ?? null,
    directorIdentityGuidanceScale: source.directorIdentityGuidanceScale ?? 1,
  }
}

function snapshotFinish(source: StudioImageIntentSource): Pick<
  StudioImageIntent,
  | 'spatialUpsampling'
  | 'filmGrainIntensity'
  | 'filmGrainSaturation'
  | 'resolutionPreset'
  | 'aspectRatio'
  | 'editReturnTarget'
  | 'singlePromptMode'
> {
  return {
    spatialUpsampling: source.spatialUpsampling || '',
    filmGrainIntensity: source.filmGrainIntensity ?? 0,
    filmGrainSaturation: source.filmGrainSaturation ?? 0.5,
    resolutionPreset: source.resolutionPreset || '720p',
    aspectRatio: source.aspectRatio || '16:9',
    editReturnTarget: source.editReturnTarget ?? null,
    singlePromptMode: Boolean(source.singlePromptMode),
  }
}

/** Freeze the Studio image form. Later store reads must not mix this request. */
export function snapshotStudioImageIntent(source: StudioImageIntentSource): StudioImageIntent {
  if (source.generationMode !== 'image') {
    throw new Error('Studio image generation requires generationMode image')
  }
  return {
    generationMode: 'image',
    activeWorkspace: source.activeWorkspace || 'default',
    params: detachParams({ ...(source.params as Record<string, unknown> | undefined || {}) }),
    model: snapshotModelFlags(source.modelOptions),
    models: [...(source.models || [])],
    llmLoaded: source.llmStatus?.loaded === true,
    ...snapshotMedia(source),
    ...snapshotVoice(source),
    ...snapshotFinish(source),
  }
}

function applyScheduledPrompt(
  params: Record<string, unknown>,
  scheduledPrompt?: ScheduledPromptSubmission,
): void {
  if (!scheduledPrompt) return
  params.prompt = scheduledPrompt.prompt
  params.repeat_generation = 1
  params.multi_prompts_gen_type = 2
}

function applyOmniReferenceCleanup(params: Record<string, unknown>, intent: StudioImageIntent): void {
  if (intent.model.omniReference) {
    params.image_mode = 0
    params.image_prompt_type = ''
    delete params.image_start
    delete params.image_end
    delete params.video_source
    return
  }
  delete params.minimax_h3_references
  delete params.minimax_h3_reference_detail
}

function applyH3TextEncoder(params: Record<string, unknown>, intent: StudioImageIntent): void {
  if (!intent.model.hasH3TextEncoderChoices) delete params.minimax_h3_text_encoder
}

function applySkipSteps(params: Record<string, unknown>, intent: StudioImageIntent): void {
  if (!intent.model.firstBlockCache) {
    delete params.skip_steps_cache_type
    delete params.skip_steps_multiplier
    delete params.skip_steps_start_step_perc
    return
  }
  const allowed = intent.model.skipStepsMultiplierChoices
  const requested = Number(params.skip_steps_multiplier ?? intent.model.defaultSkipStepsMultiplier)
  params.skip_steps_multiplier = allowed.includes(requested) ? requested : (allowed[0] ?? 0.08)
  params.skip_steps_start_step_perc = Math.max(
    0,
    Math.min(100, Number(params.skip_steps_start_step_perc ?? intent.model.defaultSkipStepsStartStepPerc)),
  )
  if (params.skip_steps_cache_type !== 'first_block') params.skip_steps_cache_type = ''
}

function applyPerturbation(params: Record<string, unknown>, intent: StudioImageIntent): void {
  if (intent.model.perturbation) {
    const stg = params.stg_scale as number | undefined
    if (stg !== undefined) params.perturbation_switch = stg > 0 ? 2 : 0
    return
  }
  delete params.stg_scale
  delete params.perturbation_switch
  delete params.perturbation_layers
  delete params.perturbation_start_perc
  delete params.perturbation_end_perc
}

function applyReferencePipeline(params: Record<string, unknown>, intent: StudioImageIntent): void {
  if (!intent.model.referencePipeline) delete params.reference_pipeline
}

function hasH3References(params: Record<string, unknown>, intent: StudioImageIntent): boolean {
  const filled = (value: unknown) => Array.isArray(value) && value.some(Boolean)
  return intent.imageRefs.length > 0
    || filled(params.image_refs)
    || filled(params.h3_ref_videos)
    || filled(params.h3_ref_audios)
}

function applyH3ReferenceMode(params: Record<string, unknown>, intent: StudioImageIntent): boolean {
  const h3 = params.model_type === 'minimax_h3' || params.model_type === 'minimax_h3_legacy'
  if (!h3 || params.h3_reference_mode !== 'references' || hasH3References(params, intent)) {
    return false
  }
  params.h3_reference_mode = 'first_frame'
  delete params.image_refs
  delete params.h3_ref_videos
  delete params.h3_ref_audios
  return true
}

function applyPostProcessing(params: Record<string, unknown>, intent: StudioImageIntent): void {
  if (intent.spatialUpsampling) params.spatial_upsampling = intent.spatialUpsampling
  if (intent.filmGrainIntensity > 0) {
    params.film_grain_intensity = intent.filmGrainIntensity
    params.film_grain_saturation = intent.filmGrainSaturation
  }
}

function applyVoiceClone(params: Record<string, unknown>, intent: StudioImageIntent): void {
  if (!intent.voiceCloneEnabled || intent.voiceCloneRefs.length === 0) return
  const validRefs = intent.voiceCloneRefs.filter(reference => reference && reference.path)
  if (validRefs.length === 0) return
  params.voice_clone_enabled = true
  params.voice_clone_mode = intent.voiceCloneMode
  params.voice_clone_refs = validRefs.map(reference => reference.path)
}

function applyImageModeFlags(params: Record<string, unknown>): void {
  params.video_length = 1
  params.image_mode = 1
}

function stripStalePromptFlags(params: Record<string, unknown>): void {
  const imagePromptType = (params.image_prompt_type as string) || ''
  if (imagePromptType.includes('V')) params.image_prompt_type = imagePromptType.replace(/V/g, '')
  const videoPromptType = (params.video_prompt_type as string) || ''
  if (videoPromptType.endsWith('T')) params.video_prompt_type = videoPromptType.replace(/T$/, '')
}

function applyH3WindowCleanup(params: Record<string, unknown>, intent: StudioImageIntent): void {
  if (intent.model.slidingWindowAutoPromptPacing || params.minimax_h3_reference_sequence === true) {
    params.minimax_h3_window_storyboard = false
    delete params.h3_window_prompts
    delete params.h3_window_plan_signature
    delete params.h3_window_plan
    return
  }
  delete params.minimax_h3_window_storyboard
  delete params.h3_window_prompts
  delete params.h3_window_plan_signature
  delete params.h3_window_plan
}

/** Pure Studio image request from a frozen intent. Does not read live store state. */
export function normalizeStudioImageParams(
  intent: StudioImageIntent,
  scheduledPrompt?: ScheduledPromptSubmission,
  context?: GenerationSubmissionContext,
): StudioImageNormalizeResult {
  const params: Record<string, unknown> = {
    ...detachParams(intent.params),
    ...viggleEditingParameters({
      generationMode: 'image',
      resolutionPreset: intent.resolutionPreset,
      aspectRatio: intent.aspectRatio,
      editReturnTarget: intent.editReturnTarget,
    }),
    generation_mode: 'image',
    workspace: intent.activeWorkspace,
  }
  const provenance = generationProvenancePayload(context)
  if (provenance) params.provenance = provenance
  applyScheduledPrompt(params, scheduledPrompt)
  applyOmniReferenceCleanup(params, intent)
  applyH3TextEncoder(params, intent)
  applySkipSteps(params, intent)
  applyPerturbation(params, intent)
  applyReferencePipeline(params, intent)
  const persistH3FirstFrame = applyH3ReferenceMode(params, intent)
  applyPostProcessing(params, intent)
  applyVoiceClone(params, intent)
  applyImageModeFlags(params)
  stripStalePromptFlags(params)
  applyH3WindowCleanup(params, intent)
  delete params.preserve_source_style
  return { params, persistH3FirstFrame }
}

function isH3FirstFrameMode(params: Record<string, unknown>): boolean {
  return (params.model_type === 'minimax_h3' || params.model_type === 'minimax_h3_legacy')
    && (params.h3_reference_mode ?? 'first_frame') === 'first_frame'
}

function defaultInputVideoStrength(modelType: unknown): number {
  const name = typeof modelType === 'string' ? modelType : ''
  return name.includes('distilled') ? 0.7 : 1.0
}

async function uploadOptionalImage(
  file: File | null | undefined,
  ports: StudioImageResolvePorts,
): Promise<string> {
  if (!file) return ''
  try {
    const uploaded = await ports.uploadImage(file)
    return uploaded.path
  } catch (error) {
    console.error('Failed to upload clip image:', error)
    return ''
  }
}

async function uploadClipKeyframes(
  clip: StudioImageClip,
  ports: StudioImageResolvePorts,
): Promise<string[]> {
  const paths: string[] = []
  for (const keyframe of clip.keyframes || []) {
    if (keyframe.file) {
      try {
        paths.push((await ports.uploadImage(keyframe.file)).path)
      } catch (error) {
        console.error('Failed to upload clip keyframe:', error)
      }
    } else if (keyframe.path) {
      paths.push(keyframe.path)
    }
  }
  return paths
}

async function resolveClipEnd(
  clip: StudioImageClip,
  ports: StudioImageResolvePorts,
): Promise<{ path: string; present: boolean }> {
  if (clip.endImage) {
    const path = await uploadOptionalImage(clip.endImage, ports)
    return { path, present: Boolean(path) }
  }
  if (clip.endImagePath) return { path: clip.endImagePath, present: true }
  return { path: '', present: false }
}

async function resolveMultiClip(
  intent: StudioImageIntent,
  params: Record<string, unknown>,
  ports: StudioImageResolvePorts,
): Promise<void> {
  const imagePaths: string[] = []
  const endImagePaths: string[] = []
  const perClipKeyframes: string[][] = []
  let hasAnyEndImage = false
  for (const clip of intent.clips) {
    imagePaths.push(clip.startImage
      ? await uploadOptionalImage(clip.startImage, ports)
      : (clip.startImagePath || ''))
    const end = await resolveClipEnd(clip, ports)
    endImagePaths.push(end.path)
    if (end.present) hasAnyEndImage = true
    perClipKeyframes.push(await uploadClipKeyframes(clip, ports))
  }
  const shared = intent.clips[0]?.prompt || (params.prompt as string) || ''
  params.prompt = (intent.singlePromptMode
    ? intent.clips.map(() => shared)
    : intent.clips.map(clip => clip.prompt || '')).join('\n')
  params.image_start = imagePaths
  if (hasAnyEndImage) params.image_end = endImagePaths
  if (perClipKeyframes.some(frames => frames.length > 0)) params.per_clip_keyframes = perClipKeyframes
  else delete params.per_clip_keyframes
  params.multi_prompts_gen_type = 3
  params.image_mode = 0
  params.image_prompt_type = hasAnyEndImage ? 'SE' : 'S'
  if (params.input_video_strength == null) {
    params.input_video_strength = defaultInputVideoStrength(params.model_type)
  }
}

function appendPromptLetter(params: Record<string, unknown>, letter: 'S' | 'E'): void {
  const current = (params.image_prompt_type as string) || ''
  if (!current.includes(letter)) {
    params.image_prompt_type = letter === 'S' ? letter + current : current + letter
  }
}

async function resolveEndImage(
  intent: StudioImageIntent,
  params: Record<string, unknown>,
  ports: StudioImageResolvePorts,
  errors: string[],
): Promise<void> {
  if (intent.model.omniReference) return
  if (intent.endImage) {
    try {
      const uploaded = await ports.uploadImage(intent.endImage)
      params.image_end = uploaded.url
      appendPromptLetter(params, 'E')
    } catch (error) {
      errors.push(String(error))
      console.error('Failed to upload end image:', error)
    }
    return
  }
  if (params.image_end) appendPromptLetter(params, 'E')
}

function mergeRefLetters(params: Record<string, unknown>, letters: string): void {
  let videoPromptType = (params.video_prompt_type as string) || ''
  for (const letter of letters) {
    if (!videoPromptType.includes(letter)) videoPromptType += letter
  }
  params.video_prompt_type = videoPromptType
}

function stripRefLetters(params: Record<string, unknown>, letters: string): void {
  const videoPromptType = (params.video_prompt_type as string) || ''
  if (!videoPromptType) return
  let cleaned = videoPromptType
  for (const letter of letters || 'I') cleaned = cleaned.split(letter).join('')
  if (cleaned !== videoPromptType) params.video_prompt_type = cleaned
}

function deleteH3ReferenceFields(params: Record<string, unknown>): void {
  delete params.image_refs
  delete params.h3_ref_videos
  delete params.h3_ref_audios
}

async function uploadLiveImageRefs(
  intent: StudioImageIntent,
  params: Record<string, unknown>,
  ports: StudioImageResolvePorts,
  errors: string[],
): Promise<void> {
  const refPaths: string[] = []
  for (const file of intent.imageRefs) {
    try {
      refPaths.push((await ports.uploadImage(file)).url)
    } catch (error) {
      errors.push(String(error))
      console.error('Failed to upload reference image:', error)
    }
  }
  if (refPaths.length === 0) return
  params.image_refs = refPaths
  params.remove_background_images_ref = intent.removeBackgroundRefs ? 1 : 0
  mergeRefLetters(params, intent.imageRefType)
}

function applyStoredImageRefs(intent: StudioImageIntent, params: Record<string, unknown>): void {
  if (Array.isArray(params.image_refs) && params.image_refs.length > 0) {
    params.remove_background_images_ref = params.remove_background_images_ref ?? 0
    return
  }
  stripRefLetters(params, intent.imageRefType || 'I')
  const refs = params.image_refs as unknown[] | undefined
  if (params.image_refs !== undefined && (!refs || refs.length === 0)) delete params.image_refs
}

async function resolveImageRefs(
  intent: StudioImageIntent,
  params: Record<string, unknown>,
  ports: StudioImageResolvePorts,
  errors: string[],
): Promise<void> {
  if (isH3FirstFrameMode(params)) {
    deleteH3ReferenceFields(params)
    return
  }
  if (intent.imageRefType && intent.imageRefs.length > 0) {
    await uploadLiveImageRefs(intent, params, ports, errors)
    return
  }
  applyStoredImageRefs(intent, params)
}

async function resolveDirectorVoice(
  intent: StudioImageIntent,
  params: Record<string, unknown>,
  ports: StudioImageResolvePorts,
): Promise<void> {
  if (!intent.directorVoiceRef) return
  let path = intent.directorVoiceRefPath
  if (!path) {
    try {
      path = (await ports.uploadAudio(intent.directorVoiceRef)).path
      if (path) ports.persistDirectorVoicePath?.(path)
    } catch {
      path = null
    }
  }
  if (!path) return
  params.voice_reference = path
  params.identity_guidance_scale = intent.directorIdentityGuidanceScale
}

/** Upload and rewrite media on the detached params copy only. */
export async function resolveStudioImageMedia(
  intent: StudioImageIntent,
  params: Record<string, unknown>,
  ports: StudioImageResolvePorts,
  errors: string[] = [],
): Promise<string[]> {
  if (!intent.model.omniReference && intent.params.image_mode === 2) {
    await resolveMultiClip(intent, params, ports)
  }
  await resolveEndImage(intent, params, ports, errors)
  await resolveImageRefs(intent, params, ports, errors)
  if (isH3FirstFrameMode(params)) deleteH3ReferenceFields(params)
  await resolveDirectorVoice(intent, params, ports)
  return errors
}

function collectMediaReferences(params: Record<string, unknown>): {
  fields: typeof MEDIA_FIELDS[number][]
  references: unknown[]
} {
  const fields = MEDIA_FIELDS.filter(field => params[field])
  const references = fields.flatMap(field => (
    Array.isArray(params[field]) ? params[field] as unknown[] : [params[field]]
  )).filter(value => value !== '')
  return { fields, references }
}

export async function applyCanonicalImageReferences(
  params: Record<string, unknown>,
  resolveReferences: (references: unknown[]) => Promise<string[]>,
): Promise<void> {
  const { fields, references } = collectMediaReferences(params)
  if (!references.length) return
  const resolved = await resolveReferences(references)
  if (resolved.length !== references.length || resolved.some(value => typeof value !== 'string')) {
    throw new Error(i18n.t('studio:commands.referenceFailed'))
  }
  let cursor = 0
  const replace = (value: unknown) => (value === '' ? '' : resolved[cursor++])
  for (const field of fields) {
    const original = params[field]
    params[field] = Array.isArray(original) ? original.map(replace) : replace(original)
  }
}

export async function fetchCanonicalImageReferences(references: unknown[]): Promise<string[]> {
  const response = await fetch(`${BASE}/api/v1/generation/commands/references`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ references }),
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { detail?: { message?: string } }
    throw new Error(body.detail?.message || i18n.t('studio:commands.referenceFailed'))
  }
  const result = await response.json() as { references?: unknown }
  if (!Array.isArray(result.references) || result.references.some(value => typeof value !== 'string')) {
    throw new Error(i18n.t('studio:commands.referenceFailed'))
  }
  return result.references as string[]
}

export async function prepareStudioImageCommand(
  params: Record<string, unknown>,
  intentId: string,
  resolveReferences: (references: unknown[]) => Promise<string[]>,
  referenceErrors: string[] = [],
): Promise<{ command: StudioImageGenerationCommand; params: Record<string, unknown> }> {
  if (referenceErrors.length) throw new Error(i18n.t('studio:commands.referenceFailed'))
  const snapshot = JSON.parse(stableSerialize(params)) as Record<string, unknown>
  translateLegacyImageGuides(snapshot)
  await applyCanonicalImageReferences(snapshot, resolveReferences)
  const command = createStudioImageGenerationCommand(snapshot, intentId)
  return {
    command,
    params: { ...command.input.params, workspace: command.input.workspace },
  }
}

export function generationDetailsFromParams(
  params: Record<string, unknown>,
  models: Array<{ model_type: string; name: string }>,
): GenerationDetails | undefined {
  const modelType = typeof params.model_type === 'string' ? params.model_type.trim() : ''
  if (!modelType) return undefined
  const details: GenerationDetails = {
    model_type: modelType,
    model_name: models.find(model => model.model_type === modelType)?.name || modelType,
  }
  const copy = (source: string, target: keyof GenerationDetails) => {
    const value = params[source]
    if (value !== undefined && value !== null && value !== '') {
      Object.assign(details, { [target]: value })
    }
  }
  copy('generation_mode', 'generation_mode')
  copy('resolution', 'resolution')
  copy('seed', 'seed')
  copy('num_inference_steps', 'steps')
  copy('guidance_scale', 'guidance')
  copy('video_length', 'frames')
  copy('duration_seconds', 'duration_seconds')
  copy('repeat_generation', 'repeat')
  copy('h3_model_profile', 'profile')
  copy('flow_shift', 'flow_shift')
  copy('h3_audio_shift', 'audio_shift')
  copy('minimax_h3_turbo_mode', 'turbo')
  return details
}
