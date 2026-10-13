import * as api from '../api/client'
import type { ModelDef } from '../types'

export const ENABLED_MODELS_KEY = 'maestro_enabled_models'
export const HUNYUAN3D_VISIBILITY_MIGRATION_KEY = 'maestro_hunyuan3d_visibility_v2'
export const MINIMAX_H3_VISIBILITY_MIGRATION_KEY = 'maestro_minimax_h3_visibility_v1'
export let _initializedMatureModels = new Set<string>()
export let _modelVisibilityHydrated = false
export let _modelVisibilityDefaultsVersion = 1
let _modelVisibilitySaveTask: Promise<void> = Promise.resolve()

export function _saveEnabledModels(models: Set<string>) {
  try {
    localStorage.setItem(ENABLED_MODELS_KEY, JSON.stringify([...models]))
  } catch { /* quota exceeded */ }
  const payload = {
    enabled_models: [...models],
    initialized_mature_models: [..._initializedMatureModels],
    defaults_version: _modelVisibilityDefaultsVersion,
  }
  _modelVisibilitySaveTask = _modelVisibilitySaveTask
    .catch(() => { /* a later save should still run */ })
    .then(async () => {
      try {
        await api.updateModelVisibility(payload)
      } catch (error) {
        console.warn('Failed to persist model visibility:', error)
      }
    })
}

export function _enableUninitializedMatureModels(
  models: ModelDef[],
  enabledModels: Set<string>,
): Set<string> | null {
  const next = new Set(enabledModels)
  let changed = false
  for (const model of models) {
    if (
      model.nsfw_only
      && !_initializedMatureModels.has(model.model_type)
    ) {
      _initializedMatureModels.add(model.model_type)
      next.add(model.model_type)
      changed = true
    }
  }
  return changed ? next : null
}

export function replaceInitializedMatureModels(models: Set<string>) {
  _initializedMatureModels = models
}

export function setModelVisibilityDefaultsVersion(version: number) {
  _modelVisibilityDefaultsVersion = version
}

export function markModelVisibilityHydrated() {
  _modelVisibilityHydrated = true
}

const HUNYUAN3D_MODEL_TYPES = [
  'hunyuan3d-2mini-turbo',
  'hunyuan3d-2mini-fast',
  'hunyuan3d-2mini',
  'hunyuan3d-2-turbo',
  'hunyuan3d-2-fast',
  'hunyuan3d-2',
  'hunyuan3d-2mv-turbo',
  'hunyuan3d-2mv-fast',
  'hunyuan3d-2mv',
  'hunyuan3d-2.1',
] as const

// Default enabled models (shown by default in selectors)
export const DEFAULT_ENABLED_MODELS = new Set([
  'viggle_animate',
  'h3_advanced_fl2va_pruned',
  'h3_advanced_ref2va_pruned',
  'h3_advanced_vdn_pruned',
  'sensenova_u1_5_8b_mot',

  // Image
  // Keep the general-purpose Flux default plus the complete Krea 2 family:
  // base RAW/Turbo generation and their identity-preserving Edit variants.
  // Other image models remain opt-in through Model Visibility.
  'flux2_klein_9b',
  'krea2_raw',
  'krea2_turbo',
  'krea2_raw_edit',
  'krea2_turbo_edit',
  'qwen_image_21',
  'qwen_image_21_viggle_turbo',
  'qwen_image_21_turbo',
  'qwen_image_21_bf16',
  'qwen_image_21_gguf_q8_0',
  'qwen_image_21_gguf_q5_0',
  'qwen_image_21_gguf_q4_k',
  'qwen_image_21_uncensored_gguf_q4_k_m',
  'qwen_image_21_uncensored_gguf_q5_k_m',
  'qwen_image_21_uncensored_gguf_q6_k',
  // Video
  // Default to just the LTX-2.3 Distilled 1.1 22B checkpoint (newer /
  // better quality). The FP8 build and every other video model
  // (Wan 2.2 t2v/i2v, GGUF quants, dev variants) stay available via
  // Settings → System → Model Visibility but off by default so the
  // first-launch picker isn't overwhelming.
  'ltx2_22B_distilled_1_1',
  // SCAIL-2 character animation (Animate a character with a control
  // video). Fast = lightx2v distill bundled (6 steps, no CFG, ~13x).
  'scail2_14B',
  'scail2_14B_fast',
  'scail2_14B_recast_fast',
  // MiniMax H3 Base: text, first/last-frame video, and native stereo audio.
  'minimax_h3',
  'minimax_h3_full',
  'minimax_h3_legacy',
  // MiniMax H3 Ref2VA: ordered image, video, and audio references.
  'minimax_h3_ref2va',
  'minimax_h3_ref2va_full',
  'minimax_h3_fused_turbo',
  'minimax_h3_ref2va_fused_turbo',
  'yue2',
  'auk',
  'auk_flash',
  // Audio — Speech
  'kugelaudio_0_open',
  'qwen3_tts_base',
  'qwen3_tts_customvoice',
  'qwen3_tts_voicedesign',
  'voxcpm2_base',
  'voxcpm2_voicedesign',
  // Audio — Music
  'ace_step_v1_5_turbo_lm_4b',
  'ace_step_v1_5_xl',
  'ace_step_v1_5_xl_turbo_lm_4b',
  'ace_step_v1_5_xl_sft',
  'ace_step_v1_5_xl_sft_lm_4b',
  // Audio — SFX
  'mmaudio_v2',
  'mmaudio_nsfw',
  // Avatar
  'animate',
])

/* Version of the curated defaults list above. enabledModels is a stored
 * whitelist, so existing installs never re-read DEFAULT_ENABLED_MODELS —
 * without this, entries added to the curated list in an update stay
 * invisible for everyone who ever opened the app before. Bump the
 * version when adding entries and list them under that version below:
 * they get merged into existing installs' whitelists exactly ONCE, so
 * a user who then disables them stays disabled forever. (This is
 * deliberately narrower than auto-enabling every unknown model — only
 * the curated list's own additions are pushed.) */
export const DEFAULTS_VERSION = 17
export const DEFAULTS_ADDED_IN: Record<number, string[]> = {
  17: ['voxcpm2_base', 'voxcpm2_voicedesign'],
  16: ['qwen_image_21_turbo'],
  15: ['qwen_image_21_viggle_turbo'],
  14: ['qwen_image_21_uncensored_gguf_q4_k_m', 'qwen_image_21_uncensored_gguf_q5_k_m', 'qwen_image_21_uncensored_gguf_q6_k'],
  13: ['qwen_image_21', 'qwen_image_21_bf16', 'qwen_image_21_gguf_q8_0', 'qwen_image_21_gguf_q5_0', 'qwen_image_21_gguf_q4_k'],
  12: ['yue2', 'auk', 'auk_flash'],
  11: ["viggle_animate", "h3_advanced_fl2va_pruned", "h3_advanced_ref2va_pruned", "h3_advanced_vdn_pruned", "sensenova_u1_5_8b_mot"],
  // v1.2.0: the ACE-Step XL SFT pair; LM_4B becomes the music default.
  2: ['ace_step_v1_5_xl_sft', 'ace_step_v1_5_xl_sft_lm_4b'],
  // v1.3.0: SCAIL-2 character animation, base + lightx2v-distilled Fast.
  3: ['scail2_14B', 'scail2_14B_fast'],
  // Dedicated Recast recipe: native replacement + official I2V LightX point.
  4: ['scail2_14B_recast_fast'],
  // Krea 2 image generation + identity-preserving image editing.
  5: ['krea2_raw', 'krea2_turbo', 'krea2_raw_edit', 'krea2_turbo_edit'],
  // MiniMax H3 Base native audio-video generation.
  6: ['minimax_h3'],
  // MiniMax H3 Base Omni Reference (Ref2VA).
  7: ['minimax_h3_ref2va'],
  // Full 33B H3 variants alongside the recommended Pruned 20B entries.
  8: ['minimax_h3_full', 'minimax_h3_ref2va_full'],
  // Proven previous-Maestro INT8 ConvRot quality route.
  9: ['minimax_h3_legacy'],
  10: ['minimax_h3_fused_turbo', 'minimax_h3_ref2va_fused_turbo'],
}
export const DEFAULTS_VERSION_KEY = 'maestro_defaults_version'

export function _loadEnabledModels(): Set<string> | null {
  try {
    const raw = localStorage.getItem(ENABLED_MODELS_KEY)
    if (raw) {
      const models = new Set<string>(JSON.parse(raw))
      if (localStorage.getItem(HUNYUAN3D_VISIBILITY_MIGRATION_KEY) !== '1') {
        // Hunyuan3D weights are downloaded on first use. Keep the optional
        // models hidden until the user enables one, rather than presenting
        // every variant as already chosen on an existing installation.
        HUNYUAN3D_MODEL_TYPES.forEach(modelType => models.delete(modelType))
        _saveEnabledModels(models)
        localStorage.setItem(HUNYUAN3D_VISIBILITY_MIGRATION_KEY, '1')
      }
      if (localStorage.getItem(MINIMAX_H3_VISIBILITY_MIGRATION_KEY) !== '1') {
        // H3 did not exist when this persisted set was written, so enable the
        // new model once for existing users. They can still hide it normally.
        models.add('minimax_h3')
        _saveEnabledModels(models)
        localStorage.setItem(MINIMAX_H3_VISIBILITY_MIGRATION_KEY, '1')
      }
      return models
    }
  } catch { /* ignore */ }
  return null
}

export function _markMatureModelsInitialized(
  models: ModelDef[],
  modelTypes?: Iterable<string>,
) {
  const requested = modelTypes ? new Set(modelTypes) : null
  for (const model of models) {
    if (
      model.nsfw_only
      && (requested == null || requested.has(model.model_type))
    ) {
      _initializedMatureModels.add(model.model_type)
    }
  }
}
