import { stableSerialize } from '../../lib/commandContract'
import { createCatalogValidator, type CommandSchema } from '../../lib/generationCommandSchema'
import { assertCanonicalAudioReference } from '../../lib/canonicalAudioReference'
export { assertCanonicalAudioReference } from '../../lib/canonicalAudioReference'
import musicCommandCatalog from '../../api/musicCommandCatalog.json'

export const STUDIO_MUSIC_SCHEMA_VERSION = 2 as const
export const STUDIO_MUSIC_OPERATION = 'generation.music' as const

type CatalogRecord = Record<string, unknown>

const studioCatalog = musicCommandCatalog.studio as unknown as CatalogRecord
const inputSchema = studioCatalog.input as CommandSchema
const paramsSchema = (inputSchema.$defs?.StudioMusicParams || {}) as CommandSchema
const assertCatalogValue = createCatalogValidator(paramsSchema.$defs, STUDIO_MUSIC_OPERATION)

/** The browser key type is generated from the native Pydantic schema. */
export type StudioMusicParamKey = keyof typeof musicCommandCatalog.studio.input.$defs.StudioMusicParams.properties
export type StudioMusicParams = Partial<Record<StudioMusicParamKey, unknown>>
export type StudioMusicGenerationFullParams = StudioMusicParams & {
  workspace: string
  provenance?: unknown
}

export interface StudioMusicGenerationInput {
  workspace: string
  workspace_collection_id?: string | null
  params: StudioMusicParams
}

export interface StudioMusicGenerationCommand {
  version: typeof STUDIO_MUSIC_SCHEMA_VERSION
  operation: typeof STUDIO_MUSIC_OPERATION
  intent_id: string
  input: StudioMusicGenerationInput
}

/*
 * The backend's human-readable supported_input_fields predates
 * lyrics_language. The generated parameter schema is authoritative here, so
 * the field remains available without duplicating a second allowlist.
 */
const generatedParamKeys = Object.keys(paramsSchema.properties || {}) as StudioMusicParamKey[]
export const STUDIO_MUSIC_PARAM_KEYS: readonly StudioMusicParamKey[] = generatedParamKeys
export const STUDIO_MUSIC_PARAM_CATALOG: ReadonlySet<string> = new Set(
  generatedParamKeys as readonly string[],
)

const modelTypes = studioCatalog.music_model_types
export const STUDIO_MUSIC_MODEL_TYPES: readonly string[] = Array.isArray(modelTypes)
  ? modelTypes.filter((value): value is string => typeof value === 'string')
  : []
const STUDIO_MUSIC_MODEL_SET = new Set(STUDIO_MUSIC_MODEL_TYPES)

/**
 * The shared form can carry inactive state from the image/video/speech
 * editors. These names are known UI leftovers and are projected explicitly;
 * an unknown field still fails closed. Catalogued music fields are never
 * dropped, including literal text and inactive sentinels.
 */
export const STUDIO_MUSIC_FORM_RESIDUAL_FIELDS = [
  // Image/video references and selectors restored by Load Settings.
  'image_start', 'image_end', 'image_refs', 'image_guide', 'image_mask',
  'video_guide', 'video_mask', 'video_source', 'video_prompt_type',
  // Both registered music handlers hide flow_shift; the native settings
  // filter drops it, but loadModelOptions still writes its shared default.
  'flow_shift',
  'image_prompt_type', 'input_video_strength', 'denoising_strength',
  'masking_strength', 'video_guide_outpainting', 'frames_positions',
  'canonical_image_refs', 'image_fit_mode', 'image_refs_relative_size',
  'remove_background_images_ref', 'preserve_source_style', 'force_fps',
  'keep_frames_video_source', 'keep_frames_video_guide',
  // H3 and other video-only policy/sidecar settings.
  'h3_ref_videos', 'h3_ref_audios', 'minimax_h3_references',
  'h3_audio_shift', 'h3_audio_prompt', 'h3_ref_image_size',
  'h3_reference_mode', 'h3_model_profile', 'minimax_h3_reference_detail',
  'minimax_h3_text_encoder', 'minimax_h3_turbo_mode', 'minimax_h3_turbo_preset',
  'minimax_h3_planning_style', 'minimax_h3_audio_policy',
  'minimax_h3_reference_sequence', 'minimax_h3_semantic_bridge_alpha',
  'minimax_h3_semantic_bridge_magnitude', 'minimax_h3_multi_window',
  'h3_reference_context', 'minimax_h3_window_storyboard', 'h3_window_prompts',
  'h3_window_plan_signature', 'h3_window_plan', 'sliding_window_size',
  'sliding_window_overlap', 'sliding_window_memory_override',
  'sliding_window_discard_last_frames', 'sliding_window_color_correction_strength',
  'sliding_window_overlap_noise', 'viggle_audio_mode', 'switch_threshold',
  'per_clip_frames', 'per_clip_keyframes',
  // Video cache/advanced controls. The cache selector controls whether the
  // two numeric residuals are active.
  'skip_steps_cache_type', 'skip_steps_multiplier', 'skip_steps_start_step_perc',
  'stage2_steps', 'progressive_pipeline', 'single_stage_pipeline',
  'reference_pipeline', 'progressive_stage1_image_weight',
  'progressive_stage2_steps', 'progressive_stage2_sigma',
  'progressive_stage3_steps', 'progressive_stage3_sigma',
  'progressive_stage3_image_weight', 'stg_scale', 'perturbation_switch',
  'perturbation_layers', 'perturbation_start_perc', 'perturbation_end_perc',
  'cfg_rescale', 'modality_scale', 'use_gradient_estimation', 'ge_gamma',
  'ge_alpha', 'keyframe_conditioning_mode', 'keyframe_inject_mode',
  'override_attention', 'attention_sparsity', 'apg_switch', 'cfg_star_switch',
  'cfg_zero_step', 'custom_guide', 'matanyone_version',
  'min_frames_if_references', 'multi_images_gen_type', 'output_filename',
  'self_refiner_setting', 'self_refiner_plan', 'self_refiner_f_uncertainty',
  'self_refiner_certain_percentage', 'control_net_weight', 'control_net_weight2',
  'control_net_weight_alt', 'motion_amplitude', 'mask_expand',
  // Speech/SFX/post-processing residue. Music voice controls are rejected if
  // active; empty state can safely be projected away.
  'tts_voice_count', 'voice_clone_enabled', 'voice_clone_mode', 'voice_clone_refs',
  'voice_reference', 'sfx_mode', '_sfx_virtual_model', '_mmaudio_variant',
  'MMAudio_setting', 'MMAudio_prompt', 'MMAudio_neg_prompt',
  'spatial_upsampling', 'temporal_upsampling', 'film_grain_intensity',
  'film_grain_saturation', 'speakers_locations', 'edit_sub_mode',
] as const

const STUDIO_MUSIC_FORM_RESIDUAL_SET: ReadonlySet<string> = new Set(
  STUDIO_MUSIC_FORM_RESIDUAL_FIELDS,
)

export interface StudioMusicFormProjection {
  params: Record<string, unknown>
  droppedFields: string[]
}

const COMMAND_FIELDS = new Set(['version', 'operation', 'intent_id', 'input'])
const INPUT_FIELDS = new Set(['workspace', 'workspace_collection_id', 'params'])
const DECLARED_METADATA_FIELDS = new Set([
  'provenance', 'runtime', 'client', 'actor', 'permission', 'workspace_id', 'workspaceId',
])
const ENVELOPE_INJECTION_FIELDS = new Set([
  'version', 'operation', 'intent_id', 'input', 'params', 'workspace_collection_id',
  'command', 'command_id', 'commandId',
])
const AUDIO_REFERENCE_FIELDS = [
  'audio_guide', 'audio_guide2', 'audio_guide3', 'audio_guide4', 'audio_guide5', 'audio_guide6',
] as const
const TTS_SPEAKER_FIELDS = [
  '_tts_speaker_name1', '_tts_speaker_name2', '_tts_speaker_name3',
  '_tts_speaker_name4', '_tts_speaker_name5', '_tts_speaker_name6',
] as const
const WORKSPACE = /^(?:default|[A-Za-z0-9][A-Za-z0-9_-]*)$/
const MAX_INTENT_LENGTH = 160
const MAX_WORKSPACE_LENGTH = 240
const MAX_COLLECTION_LENGTH = 200
const MAX_PROMPT_LENGTH = 200_000

function isRecord(value: unknown): value is CatalogRecord {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false
  const prototype = Object.getPrototypeOf(value)
  return prototype === Object.prototype || prototype === null
}

function requiredText(value: unknown, field: string, maximum: number): string {
  if (typeof value !== 'string' || !value.trim()) throw new Error(`${field} must be a non-blank string`)
  if (value.length > maximum) throw new Error(`${field} is too long`)
  return value
}

function isEmptyList(value: unknown): boolean {
  return Array.isArray(value) && value.every(item => item === null || item === undefined || item === '')
}

const RESIDUAL_TEXT_FIELDS = new Set([
  'viggle_audio_mode', 'video_prompt_type', 'image_prompt_type', 'video_guide',
  'video_guide_outpainting',
  'image_fit_mode', 'force_fps', 'skip_steps_cache_type', 'keyframe_conditioning_mode',
  'keyframe_inject_mode', 'matanyone_version', 'output_filename', 'voice_clone_mode',
  'voice_reference', 'sfx_mode', '_sfx_virtual_model', '_mmaudio_variant',
  'MMAudio_prompt', 'MMAudio_neg_prompt', 'spatial_upsampling', 'temporal_upsampling',
  'speakers_locations', 'edit_sub_mode', 'h3_ref_image_size',
])
const RESIDUAL_LIST_FIELDS = new Set([
  'image_start', 'image_end', 'image_refs', 'h3_ref_videos', 'h3_ref_audios',
  'minimax_h3_references', 'voice_clone_refs', 'per_clip_frames', 'per_clip_keyframes',
  'perturbation_layers', 'frames_positions',
])
const RESIDUAL_BOOLEAN_FIELDS = new Set([
  'sliding_window_memory_override', 'preserve_source_style', 'canonical_image_refs',
  'progressive_pipeline', 'single_stage_pipeline', 'reference_pipeline',
  'use_gradient_estimation', 'override_attention', 'apg_switch', 'cfg_star_switch',
  'voice_clone_enabled', 'sfx_mode', 'minimax_h3_turbo_mode',
  'minimax_h3_reference_sequence', 'minimax_h3_multi_window',
])
const RESIDUAL_ZERO_FIELDS = new Set([
  'switch_threshold', 'denoising_strength', 'input_video_strength', 'masking_strength',
  'image_refs_relative_size', 'remove_background_images_ref', 'h3_audio_shift',
  'h3_ref_image_size', 'minimax_h3_semantic_bridge_alpha',
  'minimax_h3_semantic_bridge_magnitude', 'minimax_h3_multi_window',
  'sliding_window_size', 'sliding_window_overlap', 'sliding_window_discard_last_frames',
  'sliding_window_color_correction_strength', 'sliding_window_overlap_noise', 'stage2_steps',
  'progressive_stage1_image_weight', 'progressive_stage2_steps', 'progressive_stage2_sigma',
  'progressive_stage3_steps', 'progressive_stage3_sigma', 'progressive_stage3_image_weight',
  'stg_scale', 'perturbation_switch', 'perturbation_start_perc', 'perturbation_end_perc',
  'cfg_rescale', 'modality_scale', 'ge_gamma', 'ge_alpha', 'control_net_weight',
  'control_net_weight2', 'control_net_weight_alt', 'motion_amplitude', 'mask_expand',
  'film_grain_intensity', 'film_grain_saturation', 'cfg_zero_step', 'min_frames_if_references',
  'self_refiner_setting', 'self_refiner_f_uncertainty', 'self_refiner_certain_percentage',
  'tts_voice_count', 'MMAudio_setting',
])

function isAlwaysInactiveResidual(key: string, value: unknown): boolean {
  if (value === undefined || value === null) return true
  if (value === '' && RESIDUAL_TEXT_FIELDS.has(key)) return true
  if (value === false && RESIDUAL_BOOLEAN_FIELDS.has(key)) return true
  if (value === 0 && RESIDUAL_ZERO_FIELDS.has(key)) return true
  if (isEmptyList(value) && RESIDUAL_LIST_FIELDS.has(key)) return true
  return false
}

// Native Music disables these video controls even when model-options writes
// shared numeric defaults. Source assets and active processors stay validated.
const INACTIVE_MUSIC_MODEL_CONTROLS = new Set([
  'flow_shift', 'sliding_window_size', 'sliding_window_overlap',
  'sliding_window_discard_last_frames',
])

function isContextInactiveResidual(key: string, value: unknown, fullParams: Record<string, unknown>): boolean {
  if (INACTIVE_MUSIC_MODEL_CONTROLS.has(key)) return typeof value === 'number' && Number.isFinite(value)
  if (key === 'cfg_zero_step') return value === -1
  if (key === 'skip_steps_multiplier' || key === 'skip_steps_start_step_perc') {
    return fullParams.skip_steps_cache_type === undefined || fullParams.skip_steps_cache_type === ''
  }
  if (key === 'perturbation_layers' || key === 'perturbation_start_perc' || key === 'perturbation_end_perc') {
    return fullParams.perturbation_switch === 0
  }
  if (key === 'stg_scale') return value === 0
  return false
}

function isInactiveResidual(key: string, value: unknown, fullParams: Record<string, unknown>): boolean {
  return isAlwaysInactiveResidual(key, value) || isContextInactiveResidual(key, value, fullParams)
}

function assertActiveResidual(key: string, value: unknown, fullParams: Record<string, unknown>): void {
  if (!isInactiveResidual(key, value, fullParams)) {
    throw new Error(`input.params.${key} is active and incompatible with generation.music`)
  }
}

/** Remove only known inactive sidecar values from a complete Studio form. */
export function projectStudioMusicFormParams(
  fullParams: Record<string, unknown>,
): StudioMusicFormProjection {
  if (!isRecord(fullParams)) throw new Error('Studio music parameters must be an object')
  const params: Record<string, unknown> = {}
  const droppedFields: string[] = []
  for (const [key, value] of Object.entries(fullParams)) {
    if (value === undefined) continue
    if (key === 'workspace' || DECLARED_METADATA_FIELDS.has(key)) {
      params[key] = value
    } else if (ENVELOPE_INJECTION_FIELDS.has(key)) {
      throw new Error('workspace parameters cannot contain envelope field ' + key)
    } else if (STUDIO_MUSIC_PARAM_CATALOG.has(key)) {
      params[key] = value
    } else if (STUDIO_MUSIC_FORM_RESIDUAL_SET.has(key)) {
      assertActiveResidual(key, value, fullParams)
      droppedFields.push(key)
    } else {
      throw new Error('input.params.' + key + ' is not supported by generation.music')
    }
  }
  return { params, droppedFields }
}

function assertAudioReferences(value: Record<string, unknown>): void {
  for (const field of AUDIO_REFERENCE_FIELDS) {
    if (field in value) assertCanonicalAudioReference(value[field], `input.params.${field}`)
  }
}

function assertLoraNames(value: Record<string, unknown>): void {
  if (!Array.isArray(value.activated_loras)) return
  value.activated_loras.forEach((item, index) => {
    if (typeof item !== 'string' || !item.trim() || item.includes('/') || item.includes('\\')) {
      throw new Error(`input.params.activated_loras[${index}] must be an exact catalog name`)
    }
  })
}

function assertMusicModeSelectors(value: Record<string, unknown>): void {
  if (value.generation_mode !== undefined && value.generation_mode !== 'audio') {
    throw new Error('input.params.generation_mode must be audio')
  }
  if (value._audio_sub_mode !== undefined && value._audio_sub_mode !== 'music') {
    throw new Error('input.params._audio_sub_mode must be music')
  }
  if (value.model_type !== undefined && !STUDIO_MUSIC_MODEL_SET.has(value.model_type as string)) {
    throw new Error('input.params.model_type is not a registered local music model')
  }
  if (value._tts_voice_count !== undefined && value._tts_voice_count !== 0) {
    throw new Error('input.params._tts_voice_count must be zero in music mode')
  }
  for (const field of TTS_SPEAKER_FIELDS) {
    if (value[field] !== undefined && value[field] !== null && value[field] !== '') {
      throw new Error(`input.params.${field} is inactive in music mode`)
    }
  }
  if (value._tts_original_prompt === null) {
    throw new Error('input.params._tts_original_prompt must be a string when supplied')
  }
}

function assertUnusedMusicAudioGuides(value: Record<string, unknown>): void {
  if (value.audio_guide3 !== undefined && value.audio_guide3 !== null && value.audio_guide3 !== '') {
    throw new Error('input.params.audio_guide3 is not supported by Studio music')
  }
  if (value.audio_guide4 !== undefined && value.audio_guide4 !== null && value.audio_guide4 !== '') {
    throw new Error('input.params.audio_guide4 is not supported by Studio music')
  }
  if (value.audio_guide5 !== undefined && value.audio_guide5 !== null && value.audio_guide5 !== '') {
    throw new Error('input.params.audio_guide5 is not supported by Studio music')
  }
  if (value.audio_guide6 !== undefined && value.audio_guide6 !== null && value.audio_guide6 !== '') {
    throw new Error('input.params.audio_guide6 is not supported by Studio music')
  }
}

function assertMusicAudioGuideSelector(value: Record<string, unknown>): void {
  const mode = typeof value.audio_prompt_type === 'string' ? value.audio_prompt_type : ''
  const first = value.audio_guide
  const second = value.audio_guide2
  if (mode && !['A', 'B', 'AB'].includes(mode as string)) {
    throw new Error('input.params.audio_prompt_type has an invalid music selector')
  }
  if (mode.includes('A') !== Boolean(first)) {
    throw new Error('input.params.audio_guide requires its audio_prompt_type selector')
  }
  if (mode.includes('B') !== Boolean(second)) {
    throw new Error('input.params.audio_guide2 requires its audio_prompt_type selector')
  }
}

function assertMusicSelectors(value: Record<string, unknown>): void {
  assertMusicModeSelectors(value)
  assertUnusedMusicAudioGuides(value)
  assertMusicAudioGuideSelector(value)
}

function assertMusicParams(value: unknown): asserts value is StudioMusicParams {
  if (!isRecord(value)) throw new Error('input.params must be an object')
  for (const key of Object.keys(value)) {
    if (!STUDIO_MUSIC_PARAM_CATALOG.has(key)) {
      throw new Error(`input.params.${key} is not supported by generation.music`)
    }
  }
  assertCatalogValue(value, paramsSchema, 'input.params')
  requiredText(value.prompt, 'input.params.prompt', MAX_PROMPT_LENGTH)
  // ACE-Step's caption is optional; MiniMax requires it before admission.
  if (value.model_type === 'minimax_music3' || value.model_type === 'yue2') {
    requiredText(value.alt_prompt, 'input.params.alt_prompt', MAX_PROMPT_LENGTH)
  }
  requiredText(value.model_type, 'input.params.model_type', MAX_WORKSPACE_LENGTH)
  assertMusicSelectors(value)
  assertAudioReferences(value)
  assertLoraNames(value)
  stableSerialize(value)
}

export function assertStudioMusicGenerationCommand(
  value: unknown,
): asserts value is StudioMusicGenerationCommand {
  if (!isRecord(value)) throw new Error('Studio music generation command must be an object')
  for (const key of Object.keys(value)) {
    if (!COMMAND_FIELDS.has(key)) throw new Error(`command.${key} is not supported by generation.music`)
  }
  if (value.version !== STUDIO_MUSIC_SCHEMA_VERSION) throw new Error('version must be the integer 2')
  if (value.operation !== STUDIO_MUSIC_OPERATION) throw new Error('operation must be generation.music')
  requiredText(value.intent_id, 'intent_id', MAX_INTENT_LENGTH)
  if (!isRecord(value.input)) throw new Error('input must be an object')
  for (const key of Object.keys(value.input)) {
    if (!INPUT_FIELDS.has(key)) throw new Error(`input.${key} is not supported by generation.music`)
  }
  const workspace = requiredText(value.input.workspace, 'input.workspace', MAX_WORKSPACE_LENGTH)
  if (!WORKSPACE.test(workspace)) throw new Error('input.workspace must be an exact output workspace name')
  if ('workspace_collection_id' in value.input && value.input.workspace_collection_id !== null) {
    requiredText(value.input.workspace_collection_id, 'input.workspace_collection_id', MAX_COLLECTION_LENGTH)
  }
  assertMusicParams(value.input.params)
}

export function detachedStudioMusicGenerationCommand(value: unknown): StudioMusicGenerationCommand {
  assertStudioMusicGenerationCommand(value)
  return JSON.parse(stableSerialize(value)) as StudioMusicGenerationCommand
}

function takeWorkspace(value: CatalogRecord): string {
  const workspace = requiredText(value.workspace, 'workspace', MAX_WORKSPACE_LENGTH)
  if (!WORKSPACE.test(workspace)) throw new Error('workspace must be an exact output workspace name')
  return workspace
}

function takeWorkspaceCollectionId(value: unknown): string | undefined {
  if (value === undefined || value === null) return undefined
  if (!isRecord(value)) throw new Error('provenance must be an object when supplied')
  if (value.workspace_id === undefined || value.workspace_id === null) return undefined
  return requiredText(value.workspace_id, 'provenance.workspace_id', MAX_COLLECTION_LENGTH)
}

/** Build a detached v2 envelope from the complete native Studio music form. */
export function createStudioMusicGenerationCommand(
  fullParams: Record<string, unknown>,
  intentId: string,
): StudioMusicGenerationCommand {
  if (!isRecord(fullParams)) throw new Error('Studio music parameters must be an object')
  const workspace = takeWorkspace(fullParams)
  const workspaceCollectionId = takeWorkspaceCollectionId(fullParams.provenance)
  const params: Record<string, unknown> = {}
  for (const [key, value] of Object.entries(fullParams)) {
    if (key === 'workspace' || DECLARED_METADATA_FIELDS.has(key)) continue
    if (ENVELOPE_INJECTION_FIELDS.has(key)) {
      throw new Error('workspace parameters cannot contain envelope field ' + key)
    }
    if (!STUDIO_MUSIC_PARAM_CATALOG.has(key)) {
      throw new Error('input.params.' + key + ' is not supported by generation.music')
    }
    params[key] = value
  }
  return detachedStudioMusicGenerationCommand({
    version: STUDIO_MUSIC_SCHEMA_VERSION,
    operation: STUDIO_MUSIC_OPERATION,
    intent_id: intentId,
    input: {
      workspace,
      ...(workspaceCollectionId !== undefined ? { workspace_collection_id: workspaceCollectionId } : {}),
      params: params as StudioMusicParams,
    },
  })
}

export const buildStudioMusicGenerationCommand = createStudioMusicGenerationCommand
