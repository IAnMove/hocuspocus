import * as api from '../api/client'
import {
  H3_EXPERIMENTAL_MAX_FRAMES,
  h3AlignmentOptions,
  h3MaximumFrames,
  h3WindowMaximumFrames,
  supportsH3ExtendedDuration,
} from '../lib/h3ExtendedDuration'
import { referenceImageResolution } from '../lib/imageResolution'
import { isInstructionSpeechModel } from '../lib/instructionSpeech'
import { resolveSupportedVideoFormat } from '../lib/productionProfile'
import type {
  AspectRatio,
  AudioSubMode,
  GenerateParams,
  GenerationMode,
  ModelOptions,
  ProductionProfile,
  ResolutionPreset,
} from '../types'
import { sfxModelTypes } from './modelCatalog'
import { resolveResolution } from './resolution'
import type { SliceCreator } from './storeApi'
import type { AppState } from './useStore'

// Monotonic sequence for loadModelOptions staleness detection — only the
// most recently requested model's options may touch the store.
export let _modelOptionsSeq = 0

export function advanceModelOptionsSeq(): number {
  return ++_modelOptionsSeq
}

/** Fetch a model's defaults from the backend and merge primary fields
 *  into params. Shared between `selectModel` (explicit model pick) and
 *  `setGenerationMode` (mode switch where the per-mode active model
 *  may change). Without this, switching from LTX-2 (8 steps) to Flux 2
 *  Klein 9B (4 steps) or HiDream Dev (28 steps) would silently keep
 *  the slider at the previous model's value.
 *
 *  Only overrides "primary" model-tuned numeric fields. Leaves
 *  user-intent fields (prompt, seed, negative_prompt, resolution,
 *  repeat_generation, activated_loras) alone — those should survive
 *  model switches.
 *
 *  Race-safe: applies only if the same model is still active when
 *  the fetchDefaults promise resolves. Guards against rapid model
 *  switching from leaving a stale model's defaults applied.
 */
// String list — some of these (sample_solver, embedded_guidance_scale,
// audio_guidance_scale) aren't declared on GenerateParams but the
// params object is loose enough to carry them through to the backend.
export const _PRIMARY_MODEL_DEFAULT_FIELDS: ReadonlyArray<string> = [
  'num_inference_steps',
  'guidance_scale',
  'flow_shift',
  'h3_audio_shift',
  'h3_audio_prompt',
  'h3_ref_image_size',
  'h3_reference_mode',
  'h3_model_profile',
  'sample_solver',
  'embedded_guidance_scale',
  'audio_guidance_scale',
  // Perturbation config for the STG slider. These are inert unless
  // perturbation_switch === 2, which startGeneration derives from the
  // STG slider — the server-side fallback layers ([9]) are wrong for
  // LTX-2 22B (needs [28] from the model's settings file), so the
  // model-correct values must ride along with the request.
  // Deliberately NOT copied: perturbation_switch and stg_scale — older
  // generated settings files carry perturbation_switch: 2 / stg_scale: 1.0
  // from the settings-file era, and copying them would silently re-enable
  // STG on every generation.
  'perturbation_layers',
  'perturbation_start_perc',
  'perturbation_end_perc',
  // Default state of the Reference Pipeline toggle (10Eros defs set it to
  // true). Only copied when the model's settings carry the key, so models
  // without it keep whatever the user last chose — and startGeneration
  // strips it for models that lack the capability anyway. Unchecking the
  // toggle holds until the model is re-selected, same as steps/guidance.
  'reference_pipeline',
  // LM sampling knobs for the ACE-Step 1.5 family (and other LM-staged
  // audio models). Their handlers seed tuned values (temperature 0.85,
  // top_p 0.9, top_k off, LM CFG 2.5); without hydration the UI showed
  // and SENT its generic temperature 1.0. Only models whose defaults
  // carry these keys are affected — video model settings don't include
  // them, so nothing changes there.
  'temperature',
  'top_p',
  'top_k',
  'alt_guidance_scale',
  // Sliding-window geometry. The UI only writes sliding_window_size when
  // the user touches the Advanced slider, so without hydration a request
  // carries NO window size and the backend inherits one from unrelated
  // primary settings — SCAIL-2 (window default 81) then ran a 10s
  // generation as a single 160-frame window and overflowed VRAM at
  // resolutions that fit fine per-window. LTX-2's defaults carry 481
  // (~19s), so typical LTX generations stay single-window as before.
  'sliding_window_size',
  'sliding_window_overlap',
  // Control-video coupling for the SCAIL-2 / Wan-Animate class:
  // force_fps "control" makes the output follow the guide video's frame
  // rate (user-reported: 25fps source came out 16fps without it), and
  // audio_prompt_type "R" remuxes the guide's audio track into the
  // output (user-reported: outputs were silent). Only the scail2 model
  // settings carry force_fps; every other model's audio_prompt_type
  // defaults to "" which matches the UI default, so nothing changes
  // elsewhere.
  'force_fps',
  'audio_prompt_type',
]

let _modelDefaultsSeq = 0
export function invalidateModelOptionsLoad() { advanceModelOptionsSeq(); _modelDefaultsSeq += 1 }

function currentModelDefaults(sequence: number, state: Pick<AppState, 'selectedModelPerMode' | 'generationMode'>, model: string) {
  return sequence === _modelDefaultsSeq && state.selectedModelPerMode[state.generationMode] === model
}

export function _applyModelDefaults(
  storeGet: () => { selectedModelPerMode: Partial<Record<GenerationMode, string>>; generationMode: GenerationMode; params: GenerateParams },
  storeSet: (fn: (s: { params: GenerateParams }) => { params: GenerateParams }) => void,
  modelType: string,
  preservedRecipe?: Partial<GenerateParams>,
): void {
  const sequence = ++_modelDefaultsSeq
  api.fetchDefaults(modelType).then((d) => {
    if (!d || typeof d !== 'object') return
    // Race guard: model may have been switched again while this fetch
    // was in flight. Apply only if still the active model in current mode.
    const state = storeGet()
    if (!currentModelDefaults(sequence, state, modelType)) return
    const overrides: Record<string, unknown> = {}
    for (const field of _PRIMARY_MODEL_DEFAULT_FIELDS) {
      // Audio references belong to the selected tab. A late defaults response
      // must not disable a restored voice/music reference by resetting its selector.
      if (state.generationMode === 'audio' && field === 'audio_prompt_type') continue
      // A tab/mode return already restored the native YuE2/AuK recipe.
      // fetchDefaults would otherwise put planning/sampling back to stock.
      if (preservedRecipe && field in preservedRecipe) continue
      // A one-click Full -> Pruned Turbo recommendation switches models and
      // then restores the managed 6-step preset. Do not let the asynchronous
      // base-model defaults response race in afterward and put it back at
      // 20 steps. loadModelOptions applies the same Turbo contract.
      if (
        field === 'num_inference_steps'
        && modelType.startsWith('minimax_h3')
        && state.params.minimax_h3_turbo_mode === true
      ) {
        continue
      }
      if ((d as Record<string, unknown>)[field] !== undefined) {
        overrides[field] = (d as Record<string, unknown>)[field]
      }
    }
    if (Object.keys(overrides).length > 0) {
      storeSet(s => ({ params: { ...s.params, ...overrides } as GenerateParams }))
    }
  }).catch(() => { /* fetch failure shouldn't break model switch */ })
}

/** Mirror of the backend's align_model_frame_count.
 *
 *  Only models that declare a temporal grid (frame_alignment_modulus > 0) are
 *  aligned here; every other model keeps the plain round(seconds * fps) it has
 *  always used. Without this the slider can promise a duration the model
 *  cannot produce: MiniMax H3 accepts 17n + 5 frames, so a 5s request (120)
 *  becomes 124 and the clip is 5.17s, not 5.00s.
 */
export function alignFrameCount(
  frames: number,
  o: { frame_alignment_modulus?: number; frame_alignment_remainder?: number;
       frame_alignment_mode?: string; frames_minimum?: number | null; frames_maximum?: number | null } | null | undefined,
): number {
  const modulus = o?.frame_alignment_modulus ?? 0
  if (!modulus || modulus <= 0) return frames
  const remainder = (o?.frame_alignment_remainder ?? 1) % modulus
  const minimum = o?.frames_minimum ?? 1
  const maximum = o?.frames_maximum ?? null
  let n = Math.max(minimum, Math.round(frames))
  if (maximum != null) n = Math.min(maximum, n)
  const delta = ((n - remainder) % modulus + modulus) % modulus
  if (delta) {
    const mode = (o?.frame_alignment_mode ?? 'floor').toLowerCase()
    if (mode === 'ceil') n += modulus - delta
    else if (mode === 'nearest') n += delta >= modulus / 2 ? modulus - delta : -delta
    else n -= delta
  }
  if (maximum != null && n > maximum) n -= modulus
  while (n < minimum) n += modulus
  return n
}

export type ModelOptionsSlice = {
  // Model options
  modelOptions: ModelOptions | null
  modelOptionsLoading: boolean
  loadModelOptions: (modelType: string, preservedRecipe?: Partial<GenerateParams>) => Promise<void>
}

/** loadModelOptions reads and writes sibling fields: durationSeconds, slidingWindowSeconds, slidingWindowOverlap, slidingWindowLocked, resolutionPreset, aspectRatio, imageSourceSize, generationMode, productionProfile, audioSubMode, ttsVoiceCount, ttsVoices, params. */
export type ModelOptionsSliceHost = ModelOptionsSlice & {
  durationSeconds: number
  slidingWindowSeconds: number
  slidingWindowOverlap: number
  slidingWindowLocked: boolean
  resolutionPreset: ResolutionPreset
  aspectRatio: AspectRatio
  imageSourceSize: { source: string; width: number; height: number } | null
  generationMode: GenerationMode
  productionProfile: ProductionProfile
  audioSubMode: AudioSubMode
  ttsVoiceCount: number
  ttsVoices: { name: string; filename: string | null; path: string | null }[]
  params: GenerateParams
}

export const createModelOptionsSlice: SliceCreator<ModelOptionsSlice, ModelOptionsSliceHost> = (set, get) => ({
  // Model options
  modelOptions: null,
  modelOptionsLoading: false,

  loadModelOptions: async (modelType, preservedRecipe) => {
    const seq = advanceModelOptionsSeq()
    // Virtual SFX has no options endpoint. Still invalidate pending responses
    // and clear the previous model's constraints and Advanced controls.
    if (sfxModelTypes.has(modelType)) {
      set({ modelOptions: null, modelOptionsLoading: false })
      return
    }
    set({ modelOptionsLoading: true })
    try {
      const options = await api.fetchModelOptions(modelType)
      // Staleness guard: a newer loadModelOptions call was issued while this
      // fetch was in flight (rapid model switching, or a settings restore
      // that jumped models). Applying a superseded response would clobber
      // params (default steps/guidance) and modelOptions with the WRONG
      // model's values — last requested wins.
      if (seq !== _modelOptionsSeq) return
      const activeState = get()
      const { durationSeconds, slidingWindowSeconds } = activeState
      const fps = options.fps || 16
      const isH3 = modelType.startsWith('minimax_h3')
      // Set overlap from model defaults
      const swDefaults = (options as unknown as Record<string, unknown>).sliding_window_defaults as Record<string, number> | undefined
      const overlapDefault = swDefaults?.overlap_default ?? 5
      const discardDefault = swDefaults?.discard_last_frames ?? 0
      const minimumDuration = Math.max(1, (options.frames_minimum || fps) / fps)
      const extendedDuration = activeState.params.minimax_h3_extended_duration === true
      const maximumFrames = h3MaximumFrames(options, extendedDuration)
      const nativeMaximumDuration = maximumFrames != null
        ? maximumFrames / fps
        : null
      const maximumDuration = !options.sliding_window && nativeMaximumDuration
        ? nativeMaximumDuration
        : Number.POSITIVE_INFINITY
      let nextDurationSeconds = Math.min(
        maximumDuration,
        Math.max(minimumDuration, durationSeconds),
      )
      if (
        options.sliding_window
        && nativeMaximumDuration
        && nextDurationSeconds <= Math.round(nativeMaximumDuration * 10) / 10
      ) {
        // H3's native ceiling is 14.375s but the UI displays one decimal.
        // Treat displayed 14.4s as that same one-window endpoint instead of
        // scheduling a second minimum-size pass for one rounded frame.
        nextDurationSeconds = Math.min(
          nextDurationSeconds,
          nativeMaximumDuration,
        )
      }
      let nextWindowFrames = Math.round(slidingWindowSeconds * fps)
      if (extendedDuration && supportsH3ExtendedDuration(options)) {
        nextWindowFrames = H3_EXPERIMENTAL_MAX_FRAMES
      } else if (options.sliding_window && swDefaults?.window_default != null) {
        nextWindowFrames = swDefaults.window_default
      }
      if (options.sliding_window && swDefaults) {
        const windowMaximum = h3WindowMaximumFrames(options, extendedDuration)
          ?? nextWindowFrames
        nextWindowFrames = Math.max(
          swDefaults.window_min ?? 1,
          Math.min(windowMaximum, nextWindowFrames),
        )
      } else if (!options.sliding_window) {
        nextWindowFrames = Math.round(nextDurationSeconds * fps)
      }
      const nextWindowSeconds = nextWindowFrames / fps
      const paramUpdates: Record<string, unknown> = {
        guidance_phases: options.guidance_max_phases,
        video_length: alignFrameCount(
          Math.round(nextDurationSeconds * fps),
          h3AlignmentOptions(options, extendedDuration) ?? options,
        ),
        sliding_window_size: nextWindowFrames,
        sliding_window_overlap: overlapDefault,
        sliding_window_discard_last_frames: discardDefault,
      }
      let nextResolutionPreset = activeState.resolutionPreset
      let nextAspectRatio = activeState.aspectRatio
      const modelPresetOrder = options.resolution_preset_order || []
      if (modelPresetOrder.length > 0) {
        if (!modelPresetOrder.includes(nextResolutionPreset)) {
          // A model-specific list can contain an expensive experimental tier
          // at the end. Select its ordinary 720p tier when the previous
          // model's preset is unavailable instead of silently jumping to the
          // largest canvas.
          nextResolutionPreset = modelPresetOrder.includes('720p')
            ? '720p'
            : modelPresetOrder[0]
        }
        if (nextAspectRatio === 'auto' && !options.supports_auto_aspect) {
          nextAspectRatio = '16:9'
        }
        paramUpdates.resolution = resolveResolution(
          options,
          nextResolutionPreset,
          nextAspectRatio,
        )
        const sourceSize = activeState.imageSourceSize
        if (modelType.startsWith('qwen_image_21') && nextAspectRatio === 'auto'
          && sourceSize && sourceSize.source === activeState.params.image_guide) {
          paramUpdates.resolution = referenceImageResolution(sourceSize.width, sourceSize.height, nextResolutionPreset, modelType)
        }
      } else if (
        nextAspectRatio === 'auto'
        && activeState.generationMode !== 'image'
        && !options.supports_auto_aspect
      ) {
        nextAspectRatio = '16:9'
        paramUpdates.resolution = resolveResolution(
          options,
          nextResolutionPreset,
          nextAspectRatio,
        )
      }
      if (isH3) {
        const requested = activeState.productionProfile.video.model === modelType
          ? activeState.productionProfile.video.settings
          : { resolution: '540p' as ResolutionPreset, aspectRatio: nextAspectRatio }
        const format = resolveSupportedVideoFormat(
          options,
          requested.resolution,
          requested.aspectRatio,
        )
        nextResolutionPreset = format.resolution
        nextAspectRatio = format.aspectRatio
        paramUpdates.resolution = resolveResolution(options, nextResolutionPreset, nextAspectRatio)
        if (modelType === 'minimax_h3_legacy') {
          paramUpdates.num_inference_steps = 20
          paramUpdates.flow_shift = 12
          paramUpdates.h3_audio_shift = 3
          paramUpdates.minimax_h3_turbo_mode = false
          paramUpdates.activated_loras = []
          paramUpdates.loras_multipliers = ''
          paramUpdates.h3_model_profile = 'quality'
        }
      }
      if (modelType === 'yue2' || isInstructionSpeechModel(modelType)) {
        Object.assign(paramUpdates, {
          negative_prompt: '', prompt_enhancer: '', activated_loras: [], loras_multipliers: '',
          custom_settings: undefined, model_mode: modelType === 'yue2' ? 0 : undefined,
          sample_solver: '', audio_scale: undefined, alt_guidance_scale: undefined,
          temperature: modelType === 'yue2' ? 1 : undefined,
          top_k: modelType === 'yue2' ? 100 : undefined,
          top_p: modelType === 'yue2' ? 0.95 : undefined,
          guidance_phases: modelType === 'auk_flash' ? 0 : 1,
        })
      }
      // Apply model defaults for inference steps and guidance scale
      if (options.default_num_inference_steps != null) {
        paramUpdates.num_inference_steps = options.default_num_inference_steps
      }
      if (options.default_guidance_scale != null) {
        paramUpdates.guidance_scale = options.default_guidance_scale
      }
      if (get().generationMode === 'image') {
        paramUpdates.model_mode = options.image_edit_modes?.default ?? 0
        paramUpdates.batch_size = options.image_layer_count?.default ?? 1
      }
      // Flow shift is model-specific but was never applied on model switch,
      // so it carried over from whichever model was selected before.
      if (options.default_flow_shift != null) {
        paramUpdates.flow_shift = options.default_flow_shift
      }
      // Tab/mode return and pencil-adjacent restores pass the native recipe
      // so leftover cleanup cannot silently switch YuE2 planning or AuK CFG.
      if (preservedRecipe) Object.assign(paramUpdates, preservedRecipe)
      if (options.minimax_h3_text_encoder_choices?.length) {
        const currentEncoder = get().params.minimax_h3_text_encoder
        const valid = options.minimax_h3_text_encoder_choices.some(
          choice => choice.value === currentEncoder
        )
        if (!valid) {
          paramUpdates.minimax_h3_text_encoder = (
            options.minimax_h3_text_encoder_default
            || options.minimax_h3_text_encoder_choices[0].value
          )
        }
      }
      if (options.minimax_h3_turbo) {
        // A restored Turbo preset always displays the same step count the
        // backend will enforce. This also closes a race where model defaults
        // (20 steps) arrive after the user checks Turbo (6 steps).
        if (get().params.minimax_h3_turbo_mode === true) {
          paramUpdates.num_inference_steps = options.minimax_h3_turbo.presets?.find(preset => preset.id === get().params.minimax_h3_turbo_preset)?.steps ?? options.minimax_h3_turbo.steps
        }
      } else {
        // Model switches preserve most Studio params. Never carry the Full-H3
        // Turbo flag invisibly into a Pruned H3 or unrelated model.
        paramUpdates.minimax_h3_turbo_mode = false
      }
      // TTS default duration. Prefer the model's declared `default` (DramaBox
      // uses 0 = auto-derive from prompt); fall back to `max` (legacy behavior
      // for older TTS models that didn't declare a default), then 600.
      const ttsDefaults: Record<string, unknown> = {}
      if (options.audio_only && options.duration_slider) {
        const ds = options.duration_slider
        ttsDefaults.durationSeconds = ds.default ?? ds.max ?? 600
      }
      // Clamp current voice count to the new model's max_voice_count (e.g.
      // user had 5 voices on Kugel, switches to Scenema which caps at 2 —
      // trim slots 3-5 so the UI doesn't show ghost voices that the backend
      // would silently ignore).
      const newMaxVoiceCount = ((options as { max_voice_count?: number }).max_voice_count) ?? 6
      const currentVoiceCount = get().ttsVoiceCount
      if (activeState.generationMode === 'audio' && activeState.audioSubMode === 'speech'
          && currentVoiceCount > newMaxVoiceCount) {
        const trimmedVoices = get().ttsVoices.slice(0, newMaxVoiceCount)
        ttsDefaults.ttsVoiceCount = newMaxVoiceCount
        ttsDefaults.ttsVoices = trimmedVoices
        // Re-derive audio_prompt_type from the clamped count using the new
        // model's selection list.
        const selection = (options.audio_prompt_type_sources?.selection as string[] | undefined) || ['', 'A', 'AB']
        const audioType = selection[Math.min(newMaxVoiceCount, selection.length - 1)]
        paramUpdates.audio_prompt_type = audioType
      }
      set(s => ({
        ...ttsDefaults,
        ...(isH3 ? { durationSeconds: 124 / fps } : {}),
        modelOptions: options,
        modelOptionsLoading: false,
        durationSeconds: (
          typeof ttsDefaults.durationSeconds === 'number'
            ? ttsDefaults.durationSeconds
            : nextDurationSeconds
        ),
        slidingWindowSeconds: nextWindowSeconds,
        slidingWindowOverlap: overlapDefault,
        slidingWindowLocked: false,
        resolutionPreset: nextResolutionPreset,
        aspectRatio: nextAspectRatio,
        params: {
          ...s.params,
          ...paramUpdates,
        },
      }))
    } catch {
      // Same staleness rule as the success path — a superseded request's
      // failure must not null out the newer request's options.
      if (seq === _modelOptionsSeq) {
        set({ modelOptions: null, modelOptionsLoading: false })
      }
    }
  },
})
