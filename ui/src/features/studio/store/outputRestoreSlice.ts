import * as api from '../../../api/client'
import { restoredH3ExtendedDuration } from '../../../lib/h3ExtendedDuration'
import { restoreSemanticBridgeSettings } from '../../../lib/h3OptionalSettings'
import { restoreWan1300AudioRecipe } from '../../../lib/wan1300Audio'
import { restoredEditingTrim, restoreWangpSettings } from '../../../lib/wangpUi'
import { beginWangpRestore, legacyEditingPath, restoredGenericImageRefs } from '../../../lib/wangpRestore'
import type { GenerateParams, H3WindowPlan, MultiClip, RecastCharacterMapping, RepaintRegionMapping } from '../../../types'
import { getModelMode, sfxModelTypes } from '../../../stores/modelCatalog'
import { advanceModelOptionsSeq } from '../../../stores/modelOptionsSlice'
import { findResolutionSelection } from '../../../stores/resolution'
import type { SliceCreator } from '../../../stores/storeApi'
import { restoredStudioMusicForm } from '../../../stores/studioMusicSlice'
import type { AppState } from '../../../stores/useStore'
import { audioReferenceParams, stashAudioReferences } from '../audioReferenceState'
import { imageSettingsMode, restoreStudioImageSettings } from '../imageSettingsRestore'
import { beginOutputSettingsRestore, type OutputSettingsSource } from '../outputSettingsRestore'
import {
  extractSingleClipStudioParams,
  isJoinedSequenceOutput,
  restoredSfxSettings,
  splitStudioClipPrompts,
} from '../studioRestore'
import { DEFAULT_RECAST_MAPPING } from './studioEditSlice'
import { audioSubModeForModel, captureVideoSubModeStash } from './studioFormHelpers'

type OutpaintAspect = 'source' | '16:9' | '9:16' | '1:1' | '4:3' | '3:4'

/**
 * Video/H3 form keys the restore always writes, even for a Speech, Music or SFX sidecar. The
 * second row comes from the server's full settings dump in a real sidecar (model_switch_phase 1,
 * denoising_strength 0.5, stg_scale 1...); none of them is in the speech, music or sfx catalog.
 */
const AUDIO_RESTORE_VIDEO_RESIDUE = [
  'minimax_h3_extended_duration', 'minimax_h3_planning_style', 'minimax_h3_audio_policy',
  'minimax_h3_semantic_bridge_alpha', 'minimax_h3_semantic_bridge_magnitude',
  'frames_positions', 'image_start', 'image_end',
  'model_switch_phase', 'denoising_strength', 'video_guide_outpainting', 'input_video_strength',
  'override_attention', 'remove_background_images_ref', 'stg_scale', 'modality_scale', 'ge_gamma',
  'keyframe_conditioning_mode', 'keyframe_inject_mode',
] as const

const _OUTPAINT_ASPECT_RATIOS: Array<[Exclude<OutpaintAspect, 'source'>, number]> = [
  ['16:9', 16 / 9],
  ['9:16', 9 / 16],
  ['1:1', 1],
  ['4:3', 4 / 3],
  ['3:4', 3 / 4],
]

function _inferOutpaintAspect(width: number, height: number): OutpaintAspect | null {
  if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) return null
  const ratio = width / height
  let nearest: Exclude<OutpaintAspect, 'source'> | null = null
  let nearestError = Number.POSITIVE_INFINITY
  for (const [aspect, target] of _OUTPAINT_ASPECT_RATIOS) {
    const relativeError = Math.abs(ratio - target) / target
    if (relativeError < nearestError) {
      nearest = aspect
      nearestError = relativeError
    }
  }
  // Grid alignment can move either dimension by several pixels. Four percent
  // safely recognizes those canvases without pretending an arbitrary ratio
  // is one of the six choices supported by the composer.
  return nearestError <= 0.04 ? nearest : null
}

export type OutputRestoreSlice = {
  loadSettingsFromOutput: (source?: OutputSettingsSource) => Promise<boolean | void>
  wangpRestoreError: string
}

/** loadSettingsFromOutput passes get and set into beginWangpRestore, which is typed as AppState. */
export type OutputRestoreSliceHost = AppState

export const createOutputRestoreSlice: SliceCreator<OutputRestoreSlice, OutputRestoreSliceHost> = (set, get) => ({
  loadSettingsFromOutput: async (source) => {
    const restore = await beginOutputSettingsRestore(get, api.fetchOutputMetadata, source)
    if (!restore) return false
    const selectedOutputMeta = restore.metadata
    const { models } = get()
    const p = selectedOutputMeta.params as Record<string, unknown>
    if (get().generationMode === 'audio') {
      set({ audioReferenceStash: stashAudioReferences(get()) })
    }
    const finishWangpRestore = beginWangpRestore(p, get, set)
    const uploadFilenames = selectedOutputMeta.upload_filenames as Record<string, string> | undefined
    console.log('[LoadSettings] applying settings — model_type:', p.model_type, '| param keys:', Object.keys(p).length)

    let modelType = (p.model_type as string) || ''
    if (!modelType) return false

    // Migrate Recast sidecars made before the dedicated model existed. Those
    // jobs used the general I2V Fast accelerator with replacement conditioning;
    // loading them now should reproduce the corrected native-replacement recipe.
    const migratedLegacyRecast = p.edit_sub_mode === 'recast'
      && modelType === 'scail2_14B_fast'
      && models.some(m => m.model_type === 'scail2_14B_recast_fast')
    if (migratedLegacyRecast) modelType = 'scail2_14B_recast_fast'

    // SFX generations swap the virtual MMAudio model for a video carrier
    // at submit, so the sidecar records the carrier. Restore the virtual
    // id — resubmitting re-swaps it, and mode/sub-tab detection below
    // classifies it as audio/sfx instead of video.
    const sfxVirtual = p._sfx_virtual_model as string | undefined
    if ((p._audio_sub_mode === 'sfx' || p.sfx_mode) && sfxVirtual && models.some(m => m.model_type === sfxVirtual)) {
      modelType = sfxVirtual
    }

    // Per-sub-mode isolation: pencil-load may jump the sidebar to another
    // video sub-mode (or clobber the current one) by writing params
    // wholesale. Stash the active sub-mode's working set first so
    // in-progress work (e.g. a Frames setup) survives loading an Extend
    // clip's settings — switching back restores it.
    {
      const cur = get()
      if (cur.generationMode === 'video') {
        set({
          videoSubModeStash: {
            ...cur.videoSubModeStash,
            [(cur.params.image_mode as number) ?? 0]: captureVideoSubModeStash(cur),
          },
        })
      }
    }

    // Determine generation mode from model (respects per-model avatar overrides)
    if (imageSettingsMode(p, get())) {
      advanceModelOptionsSeq()
      set({ modelOptionsLoading: false })
      return restoreStudioImageSettings(p, source?.workspace || get().activeWorkspace, get, set, restore.isCurrent)
    }
    const model = models.find(m => m.model_type === modelType)
    if (model) {
      const mode = getModelMode(modelType, model.family)
      set({ generationMode: mode })
      // Audio outputs restore the SUB-TAB too (Speech / Music / SFX) —
      // previously the pencil landed on the Audio tab but left whatever
      // sub-tab was last open. Newer sidecars record _audio_sub_mode;
      // older ones fall back to classifying the model. Direct set, NOT
      // setAudioSubMode — that would call selectModel and clobber the
      // params restored below.
      if (mode === 'audio') {
        const recordedSub = p._audio_sub_mode as import('../../../types').AudioSubMode | undefined
        const inferredSub = p.sfx_mode ? 'sfx' : audioSubModeForModel(modelType)
        const subMode = (recordedSub === 'speech' || recordedSub === 'music' || recordedSub === 'sfx')
          ? recordedSub : inferredSub
        const restoredLyrics = (p._tts_original_prompt as string) || (p.prompt as string) || ''
        set(s => ({
          audioSubMode: subMode,
          selectedModelPerAudioSubMode: { ...s.selectedModelPerAudioSubMode, [subMode]: modelType },
          ...(subMode === 'music' ? restoredStudioMusicForm(p, restoredLyrics) : {}),
        }))
      }
    }

    // Load model capabilities BEFORE applying the restored params.
    // loadModelOptions merges model-default steps/guidance into params when
    // its fetch resolves; it used to be fired at the END of this restore,
    // so the defaults landed after the sidecar values and silently reverted
    // num_inference_steps / guidance_scale on every pencil click. Awaiting
    // it here means defaults land first and the restored values win — and
    // modelOptions matches the restored model before rerollGeneration
    // submits (stale capabilities used to strip stg_scale/perturbation_*
    // from the request, which then poisoned the next sidecar with zeros).
    // Virtual SFX clears stale options locally without fetching an endpoint.
    if (!sfxModelTypes.has(modelType)) get().loadLoras(modelType)
    await get().loadModelOptions(modelType)
    if (!restore.isCurrent()) return false

    // Detect I2V: if image_start was used or image_prompt_type contains "S"
    const hadStartImage = !!(p.image_start || (p.image_prompt_type as string || '').includes('S'))
    const hadEndImage = !!(p.image_end || (p.image_prompt_type as string || '').includes('E'))

    // TTS restores names before Speaker 1/2 substitution. Edit workflows
    // restore the user's text rather than internal conditioning guidance.
    const originalPrompt = (p._tts_original_prompt as string) || (
      p.edit_sub_mode === 'recast' && typeof p.edit_recast_raw_prompt === 'string'
        ? p.edit_recast_raw_prompt as string
        : p.edit_sub_mode === 'outpaint' && typeof p.edit_outpaint_raw_prompt === 'string'
          ? p.edit_outpaint_raw_prompt as string
          : p.prompt as string
    ) || ''

    // Build params from metadata
    // For image_mode: use 1 (I2V UI toggle) if start image was used, else 0
    const newParams: Partial<GenerateParams> = {
      prompt: originalPrompt,
      model_type: modelType,
      resolution: (p.resolution as string) || '1280x720',
      video_length: (p.video_length as number) || 81,
      num_inference_steps: migratedLegacyRecast ? 8 : (p.num_inference_steps as number) || 20,
      guidance_scale: migratedLegacyRecast ? 1 : (p.guidance_scale as number) || 5.0,
      seed: (p.seed as number) ?? -1,
      // Restore the ACTUAL saved output mode (0 = video, 1 = image). The old
      // `hadStartImage ? 1 : 0` was wrong: an I2V *video* clip has a start image
      // but image_mode 0 — inferring 1 from the start image put the UI in image-
      // output mode, so a later T2V (after clearing the start image) emitted a PNG.
      image_mode: (p.image_mode as number) ?? 0,
      negative_prompt: (p.negative_prompt as string) || '',
      repeat_generation: 1,
      activated_loras: (p.activated_loras as string[]) || [],
      loras_multipliers: (p.loras_multipliers as string) || '',
      settings_version: p.settings_version as number,
    }

    Object.assign(newParams, restoreWangpSettings(p))
    if (get().generationMode === 'audio') Object.assign(newParams, audioReferenceParams(p))
    if (get().generationMode === 'audio' && get().audioSubMode === 'sfx') {
      Object.assign(newParams, restoredSfxSettings(p))
    }
    // Copy optional fields — explicitly clear when absent to prevent stale values leaking
    newParams.sliding_window_size = (p.sliding_window_size as number) ?? undefined
    newParams.sliding_window_overlap = (p.sliding_window_overlap as number) ?? undefined
    newParams.guidance_phases = (p.guidance_phases as number) ?? undefined
    newParams.video_prompt_type = (p.video_prompt_type as string) || ''
    newParams.audio_prompt_type = (p.audio_prompt_type as string) || ''
    newParams.image_prompt_type = (p.image_prompt_type as string) || ''
    newParams.input_video_strength = (p.input_video_strength as number) ?? undefined
    newParams.flow_shift = migratedLegacyRecast ? 1 : (p.flow_shift as number) ?? undefined
    newParams.h3_audio_shift = (p.h3_audio_shift as number) ?? undefined
    newParams.h3_audio_prompt = (p.h3_audio_prompt as string) || undefined
    newParams.h3_ref_image_size = (p.h3_ref_image_size as 'match' | 'max') ?? undefined
    newParams.h3_reference_mode = (p.h3_reference_mode as 'first_frame' | 'references') ?? undefined
    newParams.h3_model_profile = (
      p.h3_model_profile as GenerateParams['h3_model_profile']
    ) ?? undefined
    newParams.minimax_h3_references = Array.isArray(p.minimax_h3_references)
      ? p.minimax_h3_references as GenerateParams['minimax_h3_references']
      : []
    newParams.minimax_h3_reference_detail = (
      p.minimax_h3_reference_detail as GenerateParams['minimax_h3_reference_detail']
    ) ?? undefined
    newParams.minimax_h3_text_encoder = (
      p.minimax_h3_text_encoder as GenerateParams['minimax_h3_text_encoder']
    ) ?? undefined
    newParams.minimax_h3_turbo_mode = Boolean(p.minimax_h3_turbo_mode)
    newParams.override_attention = typeof p.override_attention === 'string' ? p.override_attention : undefined
    newParams.minimax_h3_turbo_preset = typeof p.minimax_h3_turbo_preset === 'string' ? p.minimax_h3_turbo_preset : undefined
    newParams.minimax_h3_planning_style = p.minimax_h3_planning_style === 'creative' ? 'creative' : 'faithful'
    newParams.minimax_h3_audio_policy = p.minimax_h3_audio_policy === 'legacy' ? 'legacy' : 'native'
    newParams.minimax_h3_reference_sequence = p.minimax_h3_reference_sequence === true
    newParams.minimax_h3_extended_duration = restoredH3ExtendedDuration(p, get().modelOptions)
    Object.assign(newParams, restoreSemanticBridgeSettings(p, modelType))
    newParams.h3_reference_context = typeof p.h3_reference_context === 'string' ? p.h3_reference_context : undefined
    newParams.self_refiner_setting = (p.self_refiner_setting as number) ?? undefined
    newParams.audio_guide = (p.audio_guide as string) || ''
    newParams.audio_guide2 = (p.audio_guide2 as string) || ''
    // Style / Music Caption (ACE-Step). Was never copied here, so the
    // pencil restored only the lyrics — clear when absent so a stale
    // caption can't leak into an unrelated restore.
    newParams.alt_prompt = (p.alt_prompt as string) || ''
    // Audio tabs own video_guide via audioReferenceParams. Forcing '' here
    // after a Music/Speech restore makes generation.music treat the empty
    // residual as active. Video/Edit still clear an absent guide.
    if (get().generationMode !== 'audio') {
      newParams.video_guide = (p.video_guide as string) || ''
    }
    newParams.image_refs = Array.isArray(p.image_refs) ? (p.image_refs as string[]) : []
    newParams.h3_ref_videos = Array.isArray(p.h3_ref_videos) ? (p.h3_ref_videos as string[]) : []
    newParams.h3_ref_audios = Array.isArray(p.h3_ref_audios) ? (p.h3_ref_audios as string[]) : []
    newParams.frames_positions = (p.frames_positions as string) || ''
    newParams.injection_strength = (p.injection_strength as number) ?? undefined
    newParams.remove_background_images_ref = (p.remove_background_images_ref as number) ?? 0

    // Progressive 3-stage pipeline settings
    if (p.progressive_pipeline) {
      (newParams as Record<string, unknown>).progressive_pipeline = true;
      (newParams as Record<string, unknown>).progressive_stage1_image_weight = (p.progressive_stage1_image_weight as number) ?? 0.7;
      (newParams as Record<string, unknown>).progressive_stage2_steps = (p.progressive_stage2_steps as number) ?? 8;
      (newParams as Record<string, unknown>).progressive_stage3_steps = (p.progressive_stage3_steps as number) ?? 3;
      (newParams as Record<string, unknown>).progressive_stage2_sigma = (p.progressive_stage2_sigma as number) ?? 1.0;
      (newParams as Record<string, unknown>).progressive_stage3_sigma = (p.progressive_stage3_sigma as number) ?? 0.85;
      (newParams as Record<string, unknown>).progressive_stage3_image_weight = (p.progressive_stage3_image_weight as number) ?? 0.7
    }
    // Single-stage distilled mode — mutually exclusive with progressive above
    if (p.single_stage_pipeline) {
      (newParams as Record<string, unknown>).single_stage_pipeline = true;
      (newParams as Record<string, unknown>).progressive_pipeline = false;
    }
    // Reference two-stage pipeline (10Eros) — restore so re-generating an
    // STG-era sidecar reproduces the pipeline that made it.
    (newParams as Record<string, unknown>).reference_pipeline = (p.reference_pipeline as boolean) ?? undefined;

    // Advanced pipeline settings
    (newParams as Record<string, unknown>).stage2_steps = (p.stage2_steps as number) ?? undefined;
    (newParams as Record<string, unknown>).stg_scale = (p.stg_scale as number) ?? undefined;
    // Perturbation config rides along with stg_scale so re-generating an STG
    // run is faithful. Old sidecars (pre-STG-wiring) simply lack these keys.
    (newParams as Record<string, unknown>).perturbation_switch = (p.perturbation_switch as number) ?? undefined;
    (newParams as Record<string, unknown>).perturbation_layers = Array.isArray(p.perturbation_layers) ? (p.perturbation_layers as number[]) : undefined;
    (newParams as Record<string, unknown>).perturbation_start_perc = (p.perturbation_start_perc as number) ?? undefined;
    (newParams as Record<string, unknown>).perturbation_end_perc = (p.perturbation_end_perc as number) ?? undefined;
    (newParams as Record<string, unknown>).cfg_rescale = (p.cfg_rescale as number) ?? undefined;
    (newParams as Record<string, unknown>).modality_scale = (p.modality_scale as number) ?? undefined;
    (newParams as Record<string, unknown>).use_gradient_estimation = (p.use_gradient_estimation as boolean) ?? undefined;
    (newParams as Record<string, unknown>).ge_gamma = (p.ge_gamma as number) ?? undefined;
    (newParams as Record<string, unknown>).keyframe_conditioning_mode = (p.keyframe_conditioning_mode as string) ?? undefined;
    (newParams as Record<string, unknown>).keyframe_inject_mode = (p.keyframe_inject_mode as string) ?? undefined;
    (newParams as Record<string, unknown>).temperature = (p.temperature as number) ?? undefined;
    Object.assign(newParams, restoreWan1300AudioRecipe(modelType, p));
    (newParams as Record<string, unknown>).audio_guidance_scale = (p.audio_guidance_scale as number) ?? undefined
    newParams.minimax_h3_window_storyboard = (p.minimax_h3_window_storyboard as boolean) ?? undefined
    const restoredH3WindowPlan = (
      p.h3_window_plan
      && typeof p.h3_window_plan === 'object'
      && Array.isArray((p.h3_window_plan as Record<string, unknown>).windows)
    ) ? p.h3_window_plan as unknown as H3WindowPlan : null

    // Detect multi-clip output and reconstruct clips
    const selectedName = restore.name
    const loadFullSequence = isJoinedSequenceOutput(selectedName)
    if (p.multi_prompts_gen_type === 3 && Array.isArray(p.image_start) && loadFullSequence) {
      // Director Mode joins per-clip prompts with `\n---CLIP_BOUNDARY---\n`.
      // Structured H3 prompts contain their own newlines, so never split those
      // on `\n` or Studio reconstructs dozens of fake clips.
      const promptLines = splitStudioClipPrompts((p.prompt as string) || '')
      const imagePaths = p.image_start as string[]
      const perClipFrames = Array.isArray(p.per_clip_frames) ? (p.per_clip_frames as number[]) : []
      const perClipKeyframes = Array.isArray(p.per_clip_keyframes) ? (p.per_clip_keyframes as string[][]) : []
      const clipCount = Math.max(promptLines.length, imagePaths.length, perClipFrames.length)
      const clips: MultiClip[] = []
      for (let i = 0; i < clipCount; i++) {
        clips.push({
          prompt: promptLines[i] || '',
          startImage: null,
          startImagePath: imagePaths[i] || null,
          endImage: null,
          endImagePath: null,
          durationFrames: perClipFrames[i] || undefined,
          keyframes: (perClipKeyframes[i] || [])
            .filter(path => typeof path === 'string' && path.length > 0)
            .map(path => ({ file: null, path })),
        })
      }
      set({ clips, singlePromptMode: false, studioFocusedClipIndex: 0 })
      newParams.image_mode = 2
      newParams.multi_prompts_gen_type = 3

      const uploadNames = Array.isArray(uploadFilenames?.image_start)
        ? uploadFilenames.image_start as string[]
        : imagePaths.map(path => (path || '').replace(/\\/g, '/').split('/').pop() || '')
      for (let i = 0; i < clipCount; i++) {
        const fname = uploadNames[i]
        if (fname) {
          const idx = i
          const storedPath = imagePaths[i] || fname
          api.fetchStoredAsset(storedPath)
            .then(r => r.ok ? r.blob() : null)
            .then(blob => {
              if (!blob) return
              const file = new File([blob], fname, { type: blob.type })
              get().setClipStartImage(idx, file)
            })
            .catch(() => {})
        }
      }
    } else {
      const extracted = (
        p.multi_prompts_gen_type === 3 || Array.isArray(p.image_start)
      ) ? extractSingleClipStudioParams(p) : null
      if (extracted) {
        newParams.prompt = extracted.prompt
        newParams.image_start = extracted.imageStart
        newParams.image_end = extracted.imageEnd
        if (extracted.videoLength) newParams.video_length = extracted.videoLength
        newParams.image_prompt_type = extracted.imagePromptType
      } else {
        newParams.image_start = p.image_start ? (p.image_start as string) : ''
      }
      newParams.multi_prompts_gen_type = 2
      set({ clips: [], singlePromptMode: false, studioFocusedClipIndex: 0 })
    }
    if (newParams.image_end === undefined) {
      newParams.image_end = p.image_end ? (p.image_end as string) : ''
    }
    // An audio restore must not leave the video/H3 "inactive" sentinels written
    // above ('' / false / 'faithful' / 'native' / 'per_token'). The closed
    // generation.speech and generation.music builders refuse them, so every
    // Speech/Music reroll and pencil + Generate failed before posting anything.
    // `undefined` is how the form itself clears these keys.
    if (get().generationMode === 'audio') {
      for (const key of AUDIO_RESTORE_VIDEO_RESIDUE) (newParams as Record<string, unknown>)[key] = undefined
      // A Speech field (in its catalog); generation.music and generation.sfx refuse it.
      if (get().audioSubMode !== 'speech') (newParams as Record<string, unknown>).audio_guidance_scale = undefined
    }

    // Rebuild lora weights from multipliers string
    const loraWeights: Record<string, number[]> = {}
    const loras = newParams.activated_loras || []
    const multParts = (newParams.loras_multipliers || '').split(' ').filter(Boolean)
    for (let i = 0; i < loras.length; i++) {
      const parts = (multParts[i] || '1.00').split(';').map(Number)
      loraWeights[loras[i]] = parts
    }

    // Restore duration from metadata
    const restoredDuration = (p.duration_seconds as number) || 0
    // Restore post-processing settings from metadata
    const restoredSpatialUpsampling = (p.spatial_upsampling as string) || ''
    const restoredFilmGrainIntensity = (p.film_grain_intensity as number) || 0
    const restoredFilmGrainSaturation = (p.film_grain_saturation as number) || 0.5

    // Restore audio guide filename from upload_filenames. Fall back to
    // deriving basename from params.audio_guide for sidecars that pre-date
    // the upload_filenames extraction code.
    const _deriveBase = (val: unknown): string | null => {
      if (typeof val !== 'string' || !val) return null
      const bn = val.replace(/\\/g, '/').split('/').pop()
      return bn || null
    }
    const restoredAudioGuideFilename =
      (typeof uploadFilenames?.audio_guide === 'string' ? uploadFilenames.audio_guide : null)
      || _deriveBase(p.audio_guide)
    const restoredAudioGuide2Filename =
      (typeof uploadFilenames?.audio_guide2 === 'string' ? uploadFilenames.audio_guide2 : null)
      || _deriveBase(p.audio_guide2)
    // Restore TTS speaker names (1-6)
    const restoredSpeakerName1 = (p._tts_speaker_name1 as string) || ''
    const restoredSpeakerName2 = (p._tts_speaker_name2 as string) || ''
    const restoredVoiceCount = (p._tts_voice_count as number) || 0
    const restoredVoices: { name: string; filename: string | null; path: string | null }[] = []
    for (let i = 0; i < Math.max(restoredVoiceCount, 2); i++) {
      const name = (p[`_tts_speaker_name${i + 1}`] as string) || ''
      if (name || i < restoredVoiceCount) {
        restoredVoices.push({ name, filename: null, path: null })
      }
    }

    set(s => ({
      params: { ...s.params, ...newParams },
      ...(s.generationMode === 'image' ? {
        imageStudioIntent: newParams.image_guide ? 'edit' as const
          : newParams.image_refs?.length ? 'character' as const : 'new' as const,
        imageSourceSize: null,
      } : {}),
      h3WindowPlan: restoredH3WindowPlan,
      loraWeights,
      startImage: null,
      endImage: null,
      imageRefs: [],  // Clear — will repopulate below if image_refs exist
      outputCount: 1,
      ...(restoredDuration > 0 ? { durationSeconds: restoredDuration } : {}),
      spatialUpsampling: restoredSpatialUpsampling,
      filmGrainIntensity: restoredFilmGrainIntensity,
      filmGrainSaturation: restoredFilmGrainSaturation,
      audioGuideFilename: restoredAudioGuideFilename,
      audioGuide2Filename: restoredAudioGuide2Filename,
      // TTS state
      ...(restoredSpeakerName1 || restoredSpeakerName2 || restoredVoiceCount > 0 ? {
        ttsSpeakerName1: restoredSpeakerName1,
        ttsSpeakerName2: restoredSpeakerName2,
        ttsSpeakerNamesManual: true,
        ttsVoiceCount: restoredVoiceCount,
        ttsVoices: restoredVoices,
      } : {}),
    }))

    // Restore image refs as File objects (for image mode reference images)
    // Skip if this is a KFI (frames injection) output — those refs are handled by ControlVideoSection
    const imageRefPaths = restoredGenericImageRefs(p, newParams.image_refs)
    const isKFI = (newParams.video_prompt_type || '').includes('KFI')
    if (imageRefPaths.length > 0 && !isKFI) {
      // Set the ref type from saved params
      const vpt = newParams.video_prompt_type || ''
      const refType = vpt.includes('K') && vpt.includes('I') ? 'KI' : vpt.includes('I') ? 'I' : 'KI'
      set({ imageRefType: refType })

      // Fetch all ref images in parallel, then set in original order
      const refPromises = imageRefPaths.map(refPath => {
        const fname = refPath.replace(/\\/g, '/').split('/').pop() || ''
        if (!fname) return Promise.resolve(null)
        return api.fetchStoredAsset(refPath)
          .then(r => r.ok ? r.blob() : null)
          .then(blob => blob ? new File([blob], fname, { type: blob.type || 'image/png' }) : null)
          .catch(() => null)
      })
      Promise.all(refPromises).then(files => {
        const ordered = files.filter((f): f is File => f !== null)
        set({ imageRefs: ordered })
      })
    }

    // Derive duration and sliding window from video_length and fps
    const fps = model?.fps || 16
    const frames = newParams.video_length || 81
    set({ durationSeconds: get().generationMode === 'audio' && restoredDuration > 0
      ? restoredDuration : Math.round((frames / fps) * 10) / 10 })
    if (newParams.sliding_window_size) {
      set({ slidingWindowSeconds: Math.round((newParams.sliding_window_size / fps) * 10) / 10 })
    }
    if (newParams.sliding_window_overlap != null) {
      set({ slidingWindowOverlap: newParams.sliding_window_overlap })
    }

    // Derive resolution preset and aspect ratio
    const res = newParams.resolution || '1280x720'
    const resolutionSelection = findResolutionSelection(res, get().modelOptions)
    if (resolutionSelection) {
      set({
        resolutionPreset: resolutionSelection.preset,
        aspectRatio: resolutionSelection.ratio,
      })
    }

    // Restore start/end images from upload URLs as File objects. Prefer
    // upload_filenames.image_{start,end} (basename); fall back to deriving
    // from the full path in params for sidecars missing upload_filenames.
    const startFile = (typeof uploadFilenames?.image_start === 'string'
      ? uploadFilenames.image_start
      : null) || _deriveBase(newParams.image_start)
    const endFile = (typeof uploadFilenames?.image_end === 'string'
      ? uploadFilenames.image_end
      : null) || _deriveBase(newParams.image_end)
    if (hadStartImage && startFile) {
      api.fetchStoredAsset(typeof newParams.image_start === 'string' && newParams.image_start
        ? newParams.image_start
        : startFile)
        .then(r => r.ok ? r.blob() : null)
        .then(blob => {
          if (!blob) return
          const file = new File([blob], startFile, { type: blob.type })
          set({ startImage: file })
        })
        .catch(() => {})
    }
    if (hadEndImage && endFile) {
      api.fetchStoredAsset(typeof newParams.image_end === 'string' && newParams.image_end
        ? newParams.image_end
        : endFile)
        .then(r => r.ok ? r.blob() : null)
        .then(blob => {
          if (!blob) return
          const file = new File([blob], endFile, { type: blob.type })
          set({ endImage: file })
        })
        .catch(() => {})
    }

    // ── Edit Mode restore ───────────────────────────────────────────────
    // If the sidecar carries edit_sub_mode, this output was made by the
    // Retake / Inpaint / Outpaint / Restyle / Edit Anything sub-modes.
    // Switch the sidebar into the matching mode and re-populate the
    // sub-mode-specific controls. The standard restore above already set
    // generationMode from the model family, so we override here when the
    // sidecar tag is authoritative.
    const editSubMode = (p.edit_sub_mode as string) || ''
    if (editSubMode) {
      set({
        generationMode: 'avatar',
        editSubMode: editSubMode as 'retake' | 'inpaint' | 'restyle' | 'outpaint' | 'edit_anything' | 'recast',
      })

      // Re-link the source video. The sidecar stores either edit_video_path
      // (preferred — set by the new endpoints) or falls back to retake_video.
      // We fetch the file by URL so the EditVideoUpload UI shows the same
      // clip the user originally edited.
      const editVideoPath = legacyEditingPath(p, 'edit_video_path', String(p.retake_video || ''))
      if (editVideoPath) {
        const fname = editVideoPath.replace(/\\/g, '/').split('/').pop() || ''
        if (fname) {
          // Fetch first so basename-only legacy sidecars can fall back between
          // outputs and uploads before probing browser video metadata.
          api.fetchStoredAsset(editVideoPath)
            .then(r => r.ok ? r.blob() : null)
            .then(blob => {
              if (!blob) return
              const file = new File([blob], fname, { type: blob.type || 'video/mp4' })
              const url = URL.createObjectURL(file)
              const video = document.createElement('video')
              video.src = url
              video.muted = true
              video.onloadedmetadata = () => {
                const duration = video.duration && isFinite(video.duration) ? video.duration : 0
                const resolution = `${video.videoWidth}x${video.videoHeight}`
                get().setEditVideo(file, editVideoPath, url, duration, resolution)
                set(restoredEditingTrim(p, duration))
              }
              set({ editVideoPath, editVideoUrl: url })
            })
            .catch(() => {})
        }
      }

      // Trim range — applies to retake, inpaint, edit_anything, outpaint.
      const trimStart = (p.edit_start_time as number) ?? (p.outpaint_trim_start as number)
      const trimEnd = (p.edit_end_time as number) ?? (p.outpaint_trim_end as number)
      if (trimStart != null && trimStart >= 0) {
        set({ editStartTime: trimStart })
        if (editSubMode === 'outpaint') set({ outpaintTrimStart: trimStart })
      }
      if (trimEnd != null && trimEnd > 0) {
        set({ editEndTime: trimEnd })
        if (editSubMode === 'outpaint') set({ outpaintTrimEnd: trimEnd })
      }

      // Sub-mode-specific knobs
      if (editSubMode === 'retake' || editSubMode === 'inpaint' || editSubMode === 'edit_anything') {
        if (p.retake_strength != null) set({ editRetakeStrength: p.retake_strength as number })
        if (p.retake_engine) set({ editRetakeEngine: p.retake_engine as 'native' | 'legacy' })
        if (p.regenerate_audio != null) set({ editRegenerateAudio: !!p.regenerate_audio })
      }
      if (editSubMode === 'inpaint') {
        if (p.edit_target) set({ editDetectedTarget: p.edit_target as string })
        if (p.retake_masks_path) set({ editMasksPath: p.retake_masks_path as string })
      }
      if (editSubMode === 'edit_anything') {
        if (p.edit_anything_lora_strength != null) {
          set({ editAnythingLoraStrength: p.edit_anything_lora_strength as number })
        }
      }
      if (editSubMode === 'restyle') {
        const savedRepaintMappings = Array.isArray(p.edit_repaint_region_mappings)
          ? p.edit_repaint_region_mappings
            .slice(0, 5)
            .map((raw, index): RepaintRegionMapping | null => {
              if (!raw || typeof raw !== 'object') return null
              const mapping = raw as Record<string, unknown>
              const source = String(mapping.source || '').trim()
              const target = String(mapping.target || '').trim()
              if (!source || !target) return null
              return {
                id: String(mapping.id || `repaint-${index + 1}`),
                source,
                target,
              }
            })
            .filter((mapping): mapping is RepaintRegionMapping => mapping !== null)
          : []
        const repaintFrame = String(p.edit_repaint_target_frame || p.image_start || '')
        const repaintFrameName = repaintFrame.replace(/\\/g, '/').split('/').pop() || ''
        set({
          editRepaintMappings: savedRepaintMappings,
          editRepaintResolutionProfile: p.edit_repaint_resolution_profile === '704p'
            ? '704p'
            : p.edit_repaint_resolution_profile === '512p'
              ? '512p'
              : '480p',
          editRepaintFrameFile: null,
          editRepaintFramePath: repaintFrame,
          editRepaintFrameUrl: repaintFrameName ? api.getFileUrl(repaintFrameName) : '',
        })
        if (repaintFrame && repaintFrameName) {
          const repaintUrl = api.getFileUrl(repaintFrameName)
          fetch(repaintUrl)
            .then(r => r.ok ? r.blob() : null)
            .then(blob => {
              if (!blob) return
              get().setEditRepaintFrame(
                new File([blob], repaintFrameName, { type: blob.type || 'image/png' }),
                repaintFrame,
                URL.createObjectURL(blob),
              )
            })
            .catch(() => {})
        }
      }
      if (editSubMode === 'recast') {
        const savedMappings = p.edit_recast_character_mappings
        if (Array.isArray(savedMappings)) {
          const restoredMappings = savedMappings
            .slice(0, 5)
            .map((raw, index): RecastCharacterMapping | null => {
              if (!raw || typeof raw !== 'object') return null
              const mapping = raw as Record<string, unknown>
              const refPath = String(mapping.ref_image_path || '')
              const target = String(mapping.target || '').trim()
              if (!refPath || !target) return null
              const refName = refPath.replace(/\\/g, '/').split('/').pop() || ''
              const additionalPaths = Array.isArray(mapping.additional_ref_image_paths)
                ? mapping.additional_ref_image_paths.map(path => String(path || '')).filter(Boolean)
                : []
              return {
                id: String(mapping.id || `recast-${index + 1}`),
                target,
                refFile: null,
                refPath,
                refUrl: api.getFileUrl(refName),
                additionalRefs: additionalPaths.map(path => {
                  const name = path.replace(/\\/g, '/').split('/').pop() || ''
                  return { file: null, path, url: api.getFileUrl(name) }
                }),
                referenceAlignedToSource: mapping.reference_aligned_to_source === true,
              }
            })
            .filter((mapping): mapping is RecastCharacterMapping => mapping !== null)
          if (restoredMappings.length > 0) {
            set({
              editRecastMappings: restoredMappings,
              editRecastTarget: restoredMappings[0].target,
              editRecastPersonCount: restoredMappings.length,
              editRecastRefFile: null,
              editRecastRefPath: restoredMappings[0].refPath,
              editRecastRefUrl: restoredMappings[0].refUrl,
              editRecastRefAligned: restoredMappings[0].referenceAlignedToSource,
            })
          }
        }
        if (!Array.isArray(savedMappings) || savedMappings.length === 0) {
          set(s => ({
            editRecastMappings: [{
              ...(s.editRecastMappings[0] || DEFAULT_RECAST_MAPPING),
              target: String(p.edit_recast_target || 'person'),
              referenceAlignedToSource: p.edit_recast_ref_aligned === true,
            }],
          }))
        }
        if (p.edit_recast_target) set({ editRecastTarget: p.edit_recast_target as string })
        if (p.edit_recast_person_count != null) {
          const count = Number(p.edit_recast_person_count)
          set({ editRecastPersonCount: Math.min(5, Math.max(1, Number.isFinite(count) ? Math.round(count) : 1)) })
        }
        set({
          editRecastIsolateReference: p.edit_recast_isolate_reference !== false,
          editRecastAutoFaceDetail: p.edit_recast_auto_face_detail !== false,
          editRecastEnhancePrompt: p.edit_recast_enhance_prompt === true,
          editRecastProtectBystanders: p.edit_recast_protect_bystanders === true,
          editRecastPreserveBystanders: p.edit_recast_preserve_bystanders !== undefined
            ? p.edit_recast_preserve_bystanders === true
            : p.edit_recast_preserve_scene_reference !== undefined
              ? p.edit_recast_preserve_scene_reference === true
              : true,
          editRecastUseRelighting: p.edit_recast_use_relighting === true,
          editRecastResolutionProfile: p.edit_recast_resolution_profile === '704p'
            ? '704p'
            : p.edit_recast_resolution_profile === '512p'
              ? '512p'
              : '480p',
        })
        const recastRef = legacyEditingPath(p, 'edit_recast_ref_path')
        if (recastRef) {
          const refName = recastRef.replace(/\\/g, '/').split('/').pop() || ''
          // Recast references can be either uploads or Image-mode outputs.
          const refUrl = api.getFileUrl(refName)
          fetch(refUrl)
            .then(r => r.ok ? r.blob() : null)
            .then(blob => {
              if (!blob) return
              const file = new File([blob], refName, { type: blob.type || 'image/png' })
              get().setEditRecastRef(
                file,
                recastRef,
                URL.createObjectURL(file),
                p.edit_recast_ref_aligned === true,
              )
            })
            .catch(() => {})
        }
      }
      if (editSubMode === 'outpaint') {
        // Padding (pixels) — preserved as-is; the OutpaintCanvas reads
        // outpaintAspect + outpaintVideoBox to compose, but we also mirror
        // the pixel pads to outpaintPadding so legacy code paths line up.
        const padTop = (p.outpaint_pad_top as number) ?? 0
        const padBottom = (p.outpaint_pad_bottom as number) ?? 0
        const padLeft = (p.outpaint_pad_left as number) ?? 0
        const padRight = (p.outpaint_pad_right as number) ?? 0
        set({ outpaintPadding: { top: padTop, bottom: padBottom, left: padLeft, right: padRight } })

        const canvasW = (p._outpaint_canvas_w as number) || 0
        const canvasH = (p._outpaint_canvas_h as number) || 0
        const savedAspect = String(p.outpaint_aspect || '') as OutpaintAspect
        const validSavedAspect = (
          savedAspect === 'source'
          || _OUTPAINT_ASPECT_RATIOS.some(([aspect]) => aspect === savedAspect)
        )
        let restoredAspect: OutpaintAspect | null = validSavedAspect ? savedAspect : null
        if (!restoredAspect) {
          let aspectW = canvasW
          let aspectH = canvasH
          if (aspectW <= 0 || aspectH <= 0) {
            const resolutionMatch = /^(\d+)x(\d+)$/i.exec(String(p.resolution || '').trim())
            if (resolutionMatch) {
              aspectW = Number(resolutionMatch[1])
              aspectH = Number(resolutionMatch[2])
            }
          }
          restoredAspect = _inferOutpaintAspect(aspectW, aspectH)
        }
        if (restoredAspect) set({ outpaintAspect: restoredAspect })
        if (p.outpaint_resolution_preset) {
          set({ outpaintResolutionPreset: p.outpaint_resolution_preset as 'auto' | '480p' | '540p' | '720p' | '1080p' })
        }
        if (p.outpaint_source_preservation != null) {
          set({ outpaintSourcePreservation: p.outpaint_source_preservation as number })
        }
        if (p.outpaint_lora_strength_ui != null) {
          set({ outpaintLoraStrength: p.outpaint_lora_strength_ui as number })
        }
        if (p.outpaint_mask_preserving != null) {
          set({ outpaintMaskPreserving: !!p.outpaint_mask_preserving })
        }

        // Recompute the canvas-relative video box from saved pad pixels +
        // saved canvas dimensions, so the OutpaintCanvas reproduces the
        // exact composition. Falls back to centered-fit if anything is
        // missing.
        if (canvasW > 0 && canvasH > 0) {
          const savedX = (p._outpaint_overlay_x as number) ?? padLeft
          const savedY = (p._outpaint_overlay_y as number) ?? padTop
          const srcW = (p._outpaint_overlay_w as number)
            || (canvasW - padLeft - padRight)
          const srcH = (p._outpaint_overlay_h as number)
            || (canvasH - padTop - padBottom)
          if (srcW > 0 && srcH > 0) {
            set({
              outpaintVideoBox: {
                x: savedX / canvasW,
                y: savedY / canvasH,
                w: srcW / canvasW,
                h: srcH / canvasH,
              },
            })
          }
        }

        // Audio/sync toggles
        if (p._outpaint_preserve_audio != null) {
          set({ outpaintPreserveSourceAudio: !!p._outpaint_preserve_audio })
        }
        if (p._outpaint_lock_source_pixels != null) {
          set({ outpaintLockSourcePixels: !!p._outpaint_lock_source_pixels })
        }
        if (p._outpaint_trim_smear != null) {
          set({ outpaintTrimSmear: !!p._outpaint_trim_smear })
        }
      }
    }
    const restored = await finishWangpRestore()
    return restore.isCurrent() && restored
  },

  wangpRestoreError: '',
})
