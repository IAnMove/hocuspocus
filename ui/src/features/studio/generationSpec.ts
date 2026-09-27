import { stableSerialize } from '../../lib/commandContract'
import imageCommandCatalog from '../../api/imageCommandCatalog.json'
import { concreteImageResolution } from '../../lib/imageResolution'

/**
 * The v2 Studio image input is deliberately a closed map.  The values are
 * validated again by the server; this catalog only prevents a UI caller from
 * silently adding a transport, authority, or unrelated form field.
 *
 * Keep this list in step with the native image parameter schema.  It includes
 * optional native settings which can be present in a persisted Studio form,
 * even when a particular model does not consume them.
 */
export const STUDIO_IMAGE_SCHEMA_VERSION = 2 as const
export const STUDIO_IMAGE_OPERATION = 'generation.image' as const

export const STUDIO_IMAGE_PARAM_KEYS = [
  'minimax_h3_turbo_mode',
  'prompt',
  'alt_prompt',
  'model_type',
  'resolution',
  'video_length',
  'num_inference_steps',
  'guidance_scale',
  'seed',
  'image_mode',
  'generation_mode',
  'negative_prompt',
  'repeat_generation',
  'batch_size',
  'activated_loras',
  'loras_multipliers',
  'image_start',
  'image_end',
  'image_refs',
  'image_guide',
  'image_mask',
  'video_guide',
  'video_mask',
  'video_source',
  'audio_guide',
  'audio_guide2',
  'audio_guide3',
  'audio_guide4',
  'audio_guide5',
  'audio_guide6',
  'audio_source',
  'MMAudio_setting',
  'MMAudio_prompt',
  'MMAudio_neg_prompt',
  'h3_ref_videos',
  'h3_ref_audios',
  'minimax_h3_references',
  'image_prompt_type',
  'video_prompt_type',
  'frames_positions',
  'canonical_image_refs',
  'multi_prompts_gen_type',
  'image_fit_mode',
  'input_video_strength',
  'denoising_strength',
  'masking_strength',
  'video_guide_outpainting',
  'control_net_weight',
  'control_net_weight2',
  'control_net_weight_alt',
  'motion_amplitude',
  'mask_expand',
  'image_refs_relative_size',
  'remove_background_images_ref',
  'model_mode',
  'temporal_upsampling',
  'audio_prompt_type',
  'sliding_window_size',
  'sliding_window_overlap',
  'sliding_window_memory_override',
  'sliding_window_discard_last_frames',
  'sliding_window_color_correction_strength',
  'sliding_window_overlap_noise',
  'keep_frames_video_source',
  'keep_frames_video_guide',
  'force_fps',
  'flow_shift',
  'sample_solver',
  'embedded_guidance_scale',
  'guidance2_scale',
  'guidance3_scale',
  'switch_threshold',
  'switch_threshold2',
  'guidance_phases',
  'model_switch_phase',
  'alt_guidance_scale',
  'alt_scale',
  'audio_guidance_scale',
  'audio_scale',
  'NAG_scale',
  'NAG_tau',
  'NAG_alpha',
  'RIFLEx_setting',
  'injection_strength',
  'identity_guidance_scale',
  'skip_steps_cache_type',
  'skip_steps_multiplier',
  'skip_steps_start_step_perc',
  'settings_version',
  'prompt_enhancer',
  'spatial_upsampling',
  'film_grain_intensity',
  'film_grain_saturation',
  'progressive_pipeline',
  'single_stage_pipeline',
  'reference_pipeline',
  'progressive_stage1_image_weight',
  'progressive_stage2_steps',
  'progressive_stage2_sigma',
  'progressive_stage3_steps',
  'progressive_stage3_sigma',
  'progressive_stage3_image_weight',
  'override_profile',
  'override_attention',
  'temperature',
  'top_p',
  'top_k',
  'self_refiner_setting',
  'self_refiner_plan',
  'self_refiner_f_uncertainty',
  'self_refiner_certain_percentage',
  'cfg_rescale',
  'modality_scale',
  'use_gradient_estimation',
  'ge_gamma',
  'ge_alpha',
  'outpaint_lora_strength',
  'outpaint_mask_preserve',
  'outpaint_official_stack',
  'custom_settings',
  'wangp_processor_settings',
] as const

const GENERATED_STUDIO_IMAGE_PARAM_KEYS = new Set(
  imageCommandCatalog.studio.supported_input_fields.filter(key => key !== 'workspace' && key !== 'workspace_collection_id'),
)

/* Keep the type-level tuple and the generated runtime catalog synchronized. */
if (STUDIO_IMAGE_PARAM_KEYS.some(key => !GENERATED_STUDIO_IMAGE_PARAM_KEYS.has(key))
  || GENERATED_STUDIO_IMAGE_PARAM_KEYS.size !== STUDIO_IMAGE_PARAM_KEYS.length) {
  throw new Error('The generated Studio image parameter catalog is stale')
}

export type StudioImageParamKey = typeof STUDIO_IMAGE_PARAM_KEYS[number]
export type StudioImageParams = Partial<Record<StudioImageParamKey, unknown>>
export type StudioImageGenerationFullParams = StudioImageParams & {
  workspace: string
}

export interface StudioImageGenerationInput {
  workspace: string
  workspace_collection_id?: string | null
  params: StudioImageParams
  /**
   * Type-only compatibility for code which reads the common v1/v2 input
   * shape.  The property is never emitted and is rejected on a v2 envelope.
   */
  prompt?: never
}

export interface StudioImageGenerationCommand {
  version: typeof STUDIO_IMAGE_SCHEMA_VERSION
  operation: typeof STUDIO_IMAGE_OPERATION
  intent_id: string
  input: StudioImageGenerationInput
}

export const STUDIO_IMAGE_PARAM_CATALOG: ReadonlySet<string> = GENERATED_STUDIO_IMAGE_PARAM_KEYS

const COMMAND_FIELDS = new Set(['version', 'operation', 'intent_id', 'input'])
const INPUT_FIELDS = new Set(['workspace', 'workspace_collection_id', 'params'])
const MAX_INTENT_LENGTH = 160
const MAX_WORKSPACE_LENGTH = 240
const MAX_WORKSPACE_COLLECTION_LENGTH = 200
const MAX_PROMPT_LENGTH = 200_000
const MAX_RESOLUTION_LENGTH = 8192

// These values are declarations supplied by the UI/runtime boundary, not
// generation inputs.  The builder drops them because Studio already has a
// separate typed submissionContext/header for surface attribution.
const DECLARED_METADATA_FIELDS = new Set([
  'provenance',
  'runtime',
  'client',
  'actor',
  'permission',
  'workspace_id',
  'workspaceId',
])

const ENVELOPE_INJECTION_FIELDS = new Set([
  'version',
  'operation',
  'intent_id',
  'input',
  'params',
  'workspace_collection_id',
  'command',
  'command_id',
  'commandId',
])

/*
 * `useStore.params` is a shared native form bag rather than a Studio image
 * object. Load Settings and reroll can therefore leave fields from the
 * video/audio/avatar families (and a few old primary-settings keys) beside
 * the image fields. Keep this projection explicit: a new typo or an
 * unreviewed native field must still fail at this boundary instead of being
 * silently ignored.
 *
 * The generated `excluded` entries are the field-name portion of the server's
 * image contract. The two descriptive entries in that list are filtered out;
 * the additional names are emitted by the existing WangP restore path or
 * primary-settings snapshot but are not part of the image catalog.
 */
const STUDIO_IMAGE_FORM_RESIDUAL_FIELDS = new Set([
  ...imageCommandCatalog.studio.excluded.filter((field: string) => /^[A-Za-z_][A-Za-z0-9_]*$/.test(field)),
  'attention_sparsity',
  'video_guide2',
  'speakers_locations',
  'apg_switch',
  'cfg_star_switch',
  'cfg_zero_step',
  'custom_guide',
  'matanyone_version',
  'min_frames_if_references',
  'multi_images_gen_type',
  'output_filename',
])

const STUDIO_IMAGE_ADVANCED_RESIDUAL_FIELDS = new Set([
  'perturbation_switch',
  'perturbation_layers',
  'perturbation_start_perc',
  'perturbation_end_perc',
  'stg_scale',
  'apg_switch',
  'cfg_star_switch',
  'cfg_zero_step',
])

// These controls are excluded from the v2 image contract, but some native
// video-capable handlers can use them. A stale sidecar may contain their
// disabled defaults; silently dropping an active value would change a user's
// request, so active controls remain fail-closed at this boundary.
function hasResidualValue(value: unknown): boolean {
  return Array.isArray(value) ? value.length > 0 : value !== undefined && value !== null && value !== 0
}

function isActiveAdvancedResidual(
  key: string,
  value: unknown,
  fullParams: Record<string, unknown>,
): boolean {
  if (!STUDIO_IMAGE_ADVANCED_RESIDUAL_FIELDS.has(key)) return false
  if (key === 'perturbation_switch') return hasResidualValue(value)
  if (key === 'cfg_zero_step') return value !== undefined && value !== null && value !== -1
  if (key === 'apg_switch' || key === 'cfg_star_switch') return hasResidualValue(value)
  return fullParams.perturbation_switch !== 0 && hasResidualValue(value)
}

const SINGLE_REFERENCE_FIELDS = new Set([
  'image_start',
  'image_end',
  'image_guide',
  'image_mask',
])

const MULTI_REFERENCE_FIELDS = new Set([
  'image_start',
  'image_end',
  'image_guide',
  'image_mask',
])

const ARRAY_REFERENCE_FIELDS = new Set([
  'image_refs',
])

// These lists belong to the video/audio command families. Studio may leave
// them in a restored image form, but a non-empty value would silently switch
// modes or be ignored by the native image contract, so fail closed here.
const INACTIVE_REFERENCE_LIST_FIELDS = new Set([
  'h3_ref_videos',
  'h3_ref_audios',
  'minimax_h3_references',
])

const INACTIVE_IMAGE_FIELDS = new Set([
  'video_guide',
  'video_mask',
  'video_source',
  'audio_guide',
  'audio_guide2',
  'audio_guide3',
  'audio_guide4',
  'audio_guide5',
  'audio_guide6',
  'audio_source',
  'temporal_upsampling',
  'audio_prompt_type',
  'MMAudio_prompt',
  'MMAudio_neg_prompt',
  'keep_frames_video_source',
  'keep_frames_video_guide',
  'force_fps',
])

const CUSTOM_SETTING_FIELDS = new Set([
  'sensenova_kv_cache',
  'noise_scale_start',
  'noise_scale_end',
  'noise_clip_std',
])

const PROCESSOR_SETTING_FIELDS = new Set([
  'spatial_upsampler_strength',
  'spatial_upsampler_face_count',
  'spatial_upsampler_h3_strength',
  'spatial_upsampler_prompt',
  'spatial_upsampler_reference_images',
  'spatial_upsampler_dlss_strength',
])

function isRecord(value: unknown): value is Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false
  const prototype = Object.getPrototypeOf(value)
  return prototype === Object.prototype || prototype === null
}

function requiredText(value: unknown, field: string, maximum: number): string {
  if (typeof value !== 'string' || !value.trim()) {
    throw new Error(field + ' must be a non-blank string')
  }
  if (value.length > maximum) throw new Error(field + ' is too long')
  return value
}

function strictInteger(value: unknown, field: string, minimum: number, maximum: number): number {
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < minimum || value > maximum) {
    throw new Error(field + ' must be an integer in range')
  }
  return value
}

function strictFiniteNumber(value: unknown, field: string, minimum: number, maximum: number): number {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < minimum || value > maximum) {
    throw new Error(field + ' must be a finite number in range')
  }
  return value
}

function assertCanonicalMediaUrl(value: unknown, field: string): void {
  if (typeof value !== 'string' || !value || value.trim() !== value) {
    throw new Error(field + ' must be a canonical media URL')
  }
  if (/^asset(?:[_:-])[A-Za-z0-9][A-Za-z0-9._:-]{0,238}$/.test(value)) return
  if (!value.startsWith('/api/v1/')) {
    throw new Error(field + ' must be a canonical media URL')
  }
  // URL() normalizes dot segments before exposing pathname. Inspect the raw
  // path first so `/file/a/../b` cannot become an apparently safe `/file/b`
  // in the browser while the server correctly rejects the traversal.
  const rawPathEnd = value.search(/[?#]/)
  const rawPath = rawPathEnd < 0 ? value : value.slice(0, rawPathEnd)
  let decodedRawPath: string
  try {
    decodedRawPath = decodeURIComponent(rawPath)
  } catch {
    throw new Error(field + ' must be a canonical media URL')
  }
  if (!safeReferencePath(decodedRawPath.slice('/api/v1/'.length))) {
    throw new Error(field + ' must be a canonical media URL')
  }
  let parsed: URL
  try {
    parsed = new URL(value, 'http://hocuspocus.invalid')
  } catch {
    throw new Error(field + ' must be a canonical media URL')
  }
  if (parsed.origin !== 'http://hocuspocus.invalid'
    || parsed.hash
    || !(/^\/api\/v1\/(?:uploads|file|assets)\//).test(parsed.pathname)) {
    throw new Error(field + ' must be a canonical media URL')
  }
  let suffix: string
  try {
    suffix = decodeURIComponent(parsed.pathname.slice(parsed.pathname.indexOf('/api/v1/') + '/api/v1/'.length))
  } catch {
    throw new Error(field + ' must be a canonical media URL')
  }
  if (parsed.pathname.startsWith('/api/v1/assets/')) {
    if (parsed.search || !/^assets\/asset(?:[_:-])[A-Za-z0-9][A-Za-z0-9._:-]{0,238}$/.test(suffix)) {
      throw new Error(field + ' must be a canonical media URL')
    }
  } else if (parsed.pathname.startsWith('/api/v1/uploads/')) {
    if (parsed.search || !safeReferencePath(suffix.slice('uploads/'.length))) {
      throw new Error(field + ' must be a canonical media URL')
    }
  } else {
    const query = new URLSearchParams(parsed.search)
    if (query.size !== 1 || query.getAll('workspace').length !== 1
      || !/^(?:default|[A-Za-z0-9][A-Za-z0-9_-]*)$/.test(query.get('workspace') || '')) {
      throw new Error(field + ' must be a canonical media URL')
    }
    if (!safeReferencePath(suffix.slice('file/'.length))) {
      throw new Error(field + ' must be a canonical media URL')
    }
  }
}

function safeReferencePath(value: string): boolean {
  return Boolean(value)
    && !value.includes('\\')
    && !value.includes('\u0000')
    && value.split('/').every(part => Boolean(part) && part !== '.' && part !== '..')
}

function assertReferenceValue(value: unknown, field: string): void {
  if (value == null || value === '') return
  assertCanonicalMediaUrl(value, field)
}

function assertOptionalReferenceItem(value: unknown, field: string): void {
  if (typeof value !== 'string') {
    throw new Error(field + ' must be a canonical media URL')
  }
  // The native optional start/end/guide/mask fields use an empty string as a
  // persisted "no reference" sentinel, including when the UI restored a
  // list-shaped value. It is different from an image_refs entry, which must
  // always identify a real asset.
  if (value === '') return
  assertCanonicalMediaUrl(value, field)
}

function assertReferences(params: Record<string, unknown>): void {
  for (const field of SINGLE_REFERENCE_FIELDS) {
    if (!(field in params)) continue
    const value = params[field]
    if (MULTI_REFERENCE_FIELDS.has(field) && Array.isArray(value)) {
      value.forEach((item, index) => assertOptionalReferenceItem(
        item,
        'input.params.' + field + '[' + index + ']',
      ))
    } else {
      assertReferenceValue(value, 'input.params.' + field)
    }
  }
  for (const field of ARRAY_REFERENCE_FIELDS) {
    if (!(field in params) || params[field] == null) continue
    if (!Array.isArray(params[field])) {
      throw new Error('input.params.' + field + ' must be an ordered URL list')
    }
    params[field].forEach((value, index) => {
      assertCanonicalMediaUrl(value, 'input.params.' + field + '[' + index + ']')
    })
  }
  for (const field of INACTIVE_REFERENCE_LIST_FIELDS) {
    if (!(field in params) || params[field] == null) continue
    if (!Array.isArray(params[field])) {
      throw new Error('input.params.' + field + ' must be an empty image-mode list')
    }
    if (params[field].length > 0) {
      throw new Error('input.params.' + field + ' must be empty in image mode')
    }
  }
  for (const field of INACTIVE_IMAGE_FIELDS) {
    if (field in params && params[field] !== null && params[field] !== '') {
      throw new Error('input.params.' + field + ' must be the inactive image value')
    }
  }
  if ('custom_settings' in params && params.custom_settings != null) {
    assertClosedNestedObject(params.custom_settings, CUSTOM_SETTING_FIELDS, 'custom_settings')
  }
  if ('wangp_processor_settings' in params && params.wangp_processor_settings != null) {
    const settings = assertClosedNestedObject(
      params.wangp_processor_settings,
      PROCESSOR_SETTING_FIELDS,
      'wangp_processor_settings',
    )
    if ('spatial_upsampler_reference_images' in settings
      && settings.spatial_upsampler_reference_images != null) {
      const refs = settings.spatial_upsampler_reference_images
      if (!Array.isArray(refs)) throw new Error('input.params.wangp_processor_settings.spatial_upsampler_reference_images must be a URL list')
      refs.forEach((value, index) => assertCanonicalMediaUrl(
        value,
        'input.params.wangp_processor_settings.spatial_upsampler_reference_images[' + index + ']',
      ))
    }
  }
}

function assertClosedNestedObject(
  value: unknown,
  fields: ReadonlySet<string>,
  name: string,
): Record<string, unknown> {
  if (!isRecord(value)) throw new Error('input.params.' + name + ' must be an object or null')
  for (const key of Object.keys(value)) {
    if (!fields.has(key)) throw new Error('input.params.' + name + '.' + key + ' is not supported')
  }
  return value
}

function assertRequiredImageParams(value: Record<string, unknown>): void {
  requiredText(value.model_type, 'input.params.model_type', MAX_WORKSPACE_LENGTH)
  requiredText(value.prompt, 'input.params.prompt', MAX_PROMPT_LENGTH)
  requiredText(value.resolution, 'input.params.resolution', MAX_RESOLUTION_LENGTH)
  strictInteger(value.num_inference_steps, 'input.params.num_inference_steps', 1, 1000)
  strictInteger(value.seed, 'input.params.seed', -(2 ** 63), 2 ** 63 - 1)
  strictFiniteNumber(value.guidance_scale, 'input.params.guidance_scale', 0, 1000)
  if ('negative_prompt' in value && typeof value.negative_prompt !== 'string') {
    throw new Error('input.params.negative_prompt must be a string')
  }
  if (typeof value.negative_prompt === 'string' && value.negative_prompt.length > MAX_PROMPT_LENGTH) {
    throw new Error('input.params.negative_prompt is too long')
  }
}

function assertImageModeParams(value: Record<string, unknown>): void {
  if ('image_mode' in value && value.image_mode !== 1) {
    throw new Error('input.params.image_mode must be the image value 1')
  }
  if ('video_length' in value && value.video_length !== 1) {
    throw new Error('input.params.video_length must be the image value 1')
  }
  if ('generation_mode' in value && value.generation_mode !== 'image') {
    throw new Error('input.params.generation_mode must be image')
  }
  if ('minimax_h3_turbo_mode' in value
    && value.minimax_h3_turbo_mode !== false
    && value.minimax_h3_turbo_mode !== null) {
    throw new Error('input.params.minimax_h3_turbo_mode must be false or null in image mode')
  }
  if ('MMAudio_setting' in value
    && value.MMAudio_setting !== 0
    && value.MMAudio_setting !== null) {
    throw new Error('input.params.MMAudio_setting must be 0 or null in image mode')
  }
}

function assertImageOptionParams(value: Record<string, unknown>): void {
  if ('image_fit_mode' in value
    && !['', 'contain', 'source', 'crop'].includes(String(value.image_fit_mode))) {
    throw new Error('input.params.image_fit_mode is not supported')
  }
  if ('skip_steps_cache_type' in value
    && !['', 'first_block'].includes(String(value.skip_steps_cache_type))) {
    throw new Error('input.params.skip_steps_cache_type is not supported')
  }
  if ('canonical_image_refs' in value && value.canonical_image_refs !== false
    && value.canonical_image_refs !== true) {
    throw new Error('input.params.canonical_image_refs must be boolean')
  }
  if (value.canonical_image_refs === true
    && (!Array.isArray(value.image_refs) || value.image_refs.length === 0)) {
    throw new Error('input.params.canonical_image_refs requires image_refs')
  }
}

function assertStudioImageParams(value: unknown): asserts value is StudioImageParams {
  if (!isRecord(value)) throw new Error('input.params must be an object')
  for (const key of Object.keys(value)) {
    if (!STUDIO_IMAGE_PARAM_CATALOG.has(key)) {
      throw new Error('input.params.' + key + ' is not supported by generation.image')
    }
  }
  assertRequiredImageParams(value)
  assertImageModeParams(value)
  assertImageOptionParams(value)
  assertReferences(value)
  // This is also the JSON-safety check.  It rejects cycles, BigInt,
  // functions, symbols, class instances, non-finite numbers, and excessive
  // nesting before anything can reach localStorage or fetch.
  stableSerialize(value)
}

export function assertStudioImageGenerationCommand(
  value: unknown,
): asserts value is StudioImageGenerationCommand {
  if (!isRecord(value)) throw new Error('Studio image generation command must be an object')
  for (const key of Object.keys(value)) {
    if (!COMMAND_FIELDS.has(key)) throw new Error('command.' + key + ' is not supported by generation.image')
  }
  if (value.version !== STUDIO_IMAGE_SCHEMA_VERSION) throw new Error('version must be the integer 2')
  if (value.operation !== STUDIO_IMAGE_OPERATION) throw new Error('operation must be generation.image')
  requiredText(value.intent_id, 'intent_id', MAX_INTENT_LENGTH)
  if (!isRecord(value.input)) throw new Error('input must be an object')
  for (const key of Object.keys(value.input)) {
    if (!INPUT_FIELDS.has(key)) throw new Error('input.' + key + ' is not supported by generation.image')
  }
  const workspace = requiredText(value.input.workspace, 'input.workspace', MAX_WORKSPACE_LENGTH)
  if (!/^(?:default|[A-Za-z0-9][A-Za-z0-9_-]*)$/.test(workspace)) {
    throw new Error('input.workspace must be an exact output workspace name')
  }
  if ('workspace_collection_id' in value.input
    && value.input.workspace_collection_id !== null) {
    requiredText(value.input.workspace_collection_id, 'input.workspace_collection_id', MAX_WORKSPACE_COLLECTION_LENGTH)
  }
  assertStudioImageParams(value.input.params)
}

export function detachedStudioImageGenerationCommand(
  value: unknown,
): StudioImageGenerationCommand {
  assertStudioImageGenerationCommand(value)
  return JSON.parse(stableSerialize(value)) as StudioImageGenerationCommand
}

function takeWorkspace(value: Record<string, unknown>): string {
  const workspace = requiredText(value.workspace, 'workspace', MAX_WORKSPACE_LENGTH)
  if (!/^(?:default|[A-Za-z0-9][A-Za-z0-9_-]*)$/.test(workspace)) {
    throw new Error('workspace must be an exact output workspace name')
  }
  return workspace
}

function takeWorkspaceCollectionId(value: unknown): string | undefined {
  if (value === undefined || value === null) return undefined
  if (!isRecord(value)) throw new Error('provenance must be an object when supplied')
  if (value.workspace_id === undefined || value.workspace_id === null) return undefined
  return requiredText(value.workspace_id, 'provenance.workspace_id', MAX_WORKSPACE_COLLECTION_LENGTH)
}

/**
 * Build the detached v2 envelope from the complete flat Studio form.
 *
 * Workspace is moved to input.workspace.  Declared UI metadata is omitted,
 * while every catalogued native parameter is copied at its value level.
 * Shared-form leftovers from Load Settings, reroll sidecars or native
 * primary settings (H3 policy, perturbation, duration_seconds, …) are
 * dropped instead of failing the whole image submission. Envelope
 * injection and invalid catalogued values still fail closed.
 * Legacy filesystem references are intentionally rejected here; callers must
 * resolve them through the read-only references endpoint first.
 */
export function createStudioImageGenerationCommand(
  fullParams: Record<string, unknown>,
  intentId: string,
): StudioImageGenerationCommand {
  if (!isRecord(fullParams)) throw new Error('Studio image parameters must be an object')
  const workspace = takeWorkspace(fullParams)
  const workspaceCollectionId = takeWorkspaceCollectionId(fullParams.provenance)
  const params: Record<string, unknown> = {}
  for (const [key, value] of Object.entries(fullParams)) {
    if (key === 'workspace' || DECLARED_METADATA_FIELDS.has(key)) continue
    if (ENVELOPE_INJECTION_FIELDS.has(key)) {
      throw new Error('workspace parameters cannot contain envelope field ' + key)
    }
    if (!STUDIO_IMAGE_PARAM_CATALOG.has(key) && !STUDIO_IMAGE_FORM_RESIDUAL_FIELDS.has(key)) {
      throw new Error('input.params.' + key + ' is not supported by generation.image')
    }
    if (value === undefined) continue
    if (isActiveAdvancedResidual(key, value, fullParams)) {
      throw new Error('input.params.' + key + ' is active and incompatible with generation.image')
    }
    if (!STUDIO_IMAGE_PARAM_CATALOG.has(key)) continue
    params[key] = value
  }
  params.resolution = concreteImageResolution(params.resolution, params.model_type)
  const command: StudioImageGenerationCommand = {
    version: STUDIO_IMAGE_SCHEMA_VERSION,
    operation: STUDIO_IMAGE_OPERATION,
    intent_id: intentId,
    input: {
      workspace,
      ...(workspaceCollectionId !== undefined ? { workspace_collection_id: workspaceCollectionId } : {}),
      params: params as StudioImageParams,
    },
  }
  return detachedStudioImageGenerationCommand(command)
}

export const buildStudioImageGenerationCommand = createStudioImageGenerationCommand
