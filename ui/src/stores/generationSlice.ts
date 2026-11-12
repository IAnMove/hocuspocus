import {
  h3WindowMaximumFrames,
  requestedVideoFrames,
} from '../lib/h3ExtendedDuration'
import { projectStudioH3RequestParams } from '../lib/h3OptionalSettings'
import { viggleEditingParameters } from '../lib/viggleWorkflow'
import * as api from '../api/client'
import type { GenerationReceiptLike } from '../api/generationCommandClient'
import i18n from '../i18n'
import { splitPromptSchedule } from '../lib/promptScheduler'
import { isGenerationJobSettled } from '../lib/generationJobState'
import type { GenerationDetails, GenerationJob, ModelDef } from '../types'
import {
  generationProvenancePayload,
  type GenerationSubmissionContext,
} from '../features/studio/generationProvenance'
import { prepareStudioSubmission, studioUploadReference } from '../features/studio/studioSubmission'
import {
  startStudioImageGenerationFromStore,
  type StudioImageStoreHost,
} from '../features/studio/startGeneration'
import { submitBlendEdit } from '../features/studio/blendSubmission'
import { submitOutpaintEdit } from '../features/studio/outpaintSubmission'
import { submitRecastEdit } from '../features/studio/recastSubmission'
import { submitRestyleEdit } from '../features/studio/restyleSubmission'
import { submitRetakeInpaintEdit } from '../features/studio/retakeInpaintSubmission'
import type { OutputSettingsSource } from '../features/studio/outputSettingsRestore'
import { _jobTimingPatch } from '../features/studio/store/toolsSlice'
import { alignFrameCount } from './modelOptionsSlice'
import { UNLOADED_LLM_STATUS } from './llmSlice'
import { applyStudioAudioSubmitParams } from './studioAudioSubmit'
import { prependJob, updateJob, withJobs } from './jobReducers'
import type { SliceCreator } from './storeApi'
import type { AppState } from './useStore'

export interface ScheduledPromptSubmission {
  prompt: string
  position: number
  total: number
}

function _generationDetailsFromParams(
  params: Record<string, unknown>,
  models: ModelDef[],
): GenerationDetails | undefined {
  const modelType = typeof params.model_type === 'string' ? params.model_type.trim() : ''
  if (!modelType) return undefined
  const details: GenerationDetails = {
    model_type: modelType,
    model_name: models.find(model => model.model_type === modelType)?.name || modelType,
  }
  const copy = (
    source: string,
    target: keyof GenerationDetails,
  ) => {
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

export type GenerationSlice = {
  startGeneration: (
    scheduledPrompt?: ScheduledPromptSubmission,
    submissionContext?: GenerationSubmissionContext,
  ) => Promise<void | GenerationReceiptLike>
  rerollGeneration: (source?: OutputSettingsSource) => Promise<boolean | void>
}

/** startGeneration reads the composed store through get(). The host stays AppState. */
export const createGenerationSlice: SliceCreator<GenerationSlice, AppState> = (set, get) => ({
  startGeneration: async (scheduledPrompt, submissionContext) => {
    if (get().generationMode === 'image') {
      return startStudioImageGenerationFromStore(
        { get, set } as unknown as StudioImageStoreHost,
        scheduledPrompt,
        submissionContext,
      )
    }
    const initialState = get()
    if (initialState.generationMode === 'audio' && initialState.audioSubMode === 'mixer') {
      throw new Error(i18n.t('studio:commands.audioNotGenerative'))
    }

    // Studio Prompt Scheduler: each non-empty line becomes its own normal
    // generation request. Submitting the requests one at a time preserves the
    // prompt order while the backend's existing generation lock keeps them in
    // the shared GPU queue. This client-side split is intentional: WanGP has a
    // native multi-line queue mode, but MiniMax H3 bypasses that parser and
    // would otherwise receive the whole textarea as one prompt.
    if (
      !scheduledPrompt
      && initialState.promptSchedulerEnabled
      && initialState.generationMode === 'video'
      && (initialState.params.image_mode as number) === 0
    ) {
      const scheduledPrompts = splitPromptSchedule(String(initialState.params.prompt || ''))
      for (let index = 0; index < scheduledPrompts.length; index += 1) {
        await get().startGeneration({
          prompt: scheduledPrompts[index],
          position: index + 1,
          total: scheduledPrompts.length,
        }, submissionContext)
      }
      return
    }

    // Auto-unload LLM before GPU-heavy generation to free VRAM
    if (get().llmStatus?.loaded) {
      try {
        await api.unloadLlm()
        set({ llmStatus: UNLOADED_LLM_STATUS })
      } catch { /* best-effort */ }
    }

    const state = get()

    // Validate: i2v-only models require a start image — Video mode only.
    // Edit sub-modes supply their own source media and validate in their
    // own branches (Recast runs the i2v-only SCAIL-2 against a source
    // video + reference image; this guard silently ate its clicks).
    const isI2vOnly = state.modelOptions?.i2v_class && !state.modelOptions?.t2v_class
    const isOmniReference = state.modelOptions?.omni_reference === true
    const hasStartImage = state.startImage || state.params.image_start
    const hasMultiClipImages = state.clips.some(c => c.startImage || c.startImagePath)
    if (state.generationMode === 'video' && isI2vOnly && !isOmniReference && !hasStartImage && !hasMultiClipImages) {
      console.error('This model requires a start image')
      // Could show a toast/notification here in the future
      return
    }
    const omniReferences = state.params.minimax_h3_references ?? []
    if (
      state.generationMode === 'video'
      && isOmniReference
      && !omniReferences.some(reference => reference.type === 'image' || reference.type === 'video')
    ) {
      console.error('MiniMax H3 Omni Reference needs at least one image or video reference')
      return
    }

    // ── Video mode: Blend ──────────────────────────────────────────
    if (state.generationMode === 'video' && (state.params.image_mode as number) === 4) {
      await submitBlendEdit(get, set, state)
      return
    }

    // ── Edit mode: Outpaint ────────────────────────────────────────
    if (state.generationMode === 'avatar' && state.editSubMode === 'outpaint') {
      await submitOutpaintEdit(get, set, state)
      return
    }

    // ── Edit mode: Recast (SCAIL-2 Replace) ─────────────────────
    if (state.generationMode === 'avatar' && state.editSubMode === 'restyle') {
      await submitRestyleEdit(get, set, state)
      return
    }

    if (state.generationMode === 'avatar' && state.editSubMode === 'recast') {
      await submitRecastEdit(get, set, state)
      return
    }

    // ── Edit mode: Retake / Inpaint / Edit Anything ─────────────
    if (state.generationMode === 'avatar' && (state.editSubMode === 'retake' || state.editSubMode === 'inpaint' || state.editSubMode === 'edit_anything')) {
      await submitRetakeInpaintEdit(get, set, state)
      return  // Don't fall through to normal generation
    }

    const params: Record<string, unknown> = projectStudioH3RequestParams({
      ...state.params, ...viggleEditingParameters(state), generation_mode: state.generationMode, workspace: state.activeWorkspace,
    })
    const referenceUploadErrors: string[] = []
    const provenance = generationProvenancePayload(submissionContext)
    if (provenance) params.provenance = provenance
    if (scheduledPrompt) {
      params.prompt = scheduledPrompt.prompt
      params.repeat_generation = 1
      // Every scheduler request contains exactly one prompt. Prevent any
      // persisted sliding-window or multi-clip line policy from reinterpreting
      // it after submission.
      params.multi_prompts_gen_type = 2
    }

    if (state.generationMode === 'video') {
      const fps = state.modelOptions?.fps ?? 16
      const supportsSlidingWindows = state.modelOptions?.sliding_window === true
      params.video_length = requestedVideoFrames(
        state.durationSeconds,
        state.modelOptions,
        state.params.minimax_h3_extended_duration,
        alignFrameCount,
      )
      if (state.modelOptions?.wangp_1272) params.video_length = Math.max(1, Math.round(state.durationSeconds * fps))

      if (supportsSlidingWindows) {
        const swDefaults = state.modelOptions?.sliding_window_defaults
        let windowFrames = Math.round(state.slidingWindowSeconds * fps)
        if (swDefaults) {
          const windowMinimum = swDefaults.window_min ?? 1
          const windowMaximum = h3WindowMaximumFrames(state.modelOptions, state.params.minimax_h3_extended_duration) ?? windowFrames
          const windowStep = Math.max(1, swDefaults.window_step ?? 1)
          windowFrames = windowMinimum
            + Math.round((windowFrames - windowMinimum) / windowStep) * windowStep
          windowFrames = Math.max(
            windowMinimum,
            Math.min(windowMaximum, windowFrames),
          )
        }
        params.sliding_window_size = windowFrames
        params.sliding_window_overlap = swDefaults?.overlap_default
          ?? state.slidingWindowOverlap
        params.sliding_window_discard_last_frames = swDefaults?.discard_last_frames ?? 0
        if (state.params.minimax_h3_extended_duration) {
          params.sliding_window_memory_override = true
        } else if (state.modelOptions?.sliding_window_memory_policy?.manual_override) {
          params.sliding_window_memory_override = state.slidingWindowLocked
        } else {
          delete params.sliding_window_memory_override
        }
      } else {
        delete params.sliding_window_size
        delete params.sliding_window_overlap
        delete params.sliding_window_discard_last_frames
        delete params.sliding_window_memory_override
      }
    }

    if (isOmniReference) {
      // Ref2VA has its own ordered media manifest. Do not let a saved Frames,
      // Multi-Shot, Extend, or Blend state silently enter those pipelines.
      params.image_mode = 0
      params.image_prompt_type = ''
      delete params.image_start
      delete params.image_end
      delete params.video_source
    } else {
      // Keep Omni references in the model's in-memory working set, but do not
      // leak them into unrelated model requests or their saved sidecars.
      delete params.minimax_h3_references
      delete params.minimax_h3_reference_detail
    }
    if (!state.modelOptions?.minimax_h3_text_encoder_choices?.length) {
      delete params.minimax_h3_text_encoder
    }
    if (state.modelOptions?.first_block_cache) {
      const allowedThresholds = (
        state.modelOptions.skip_steps_multiplier_choices || []
      ).map(choice => choice[1])
      const requestedThreshold = Number(
        params.skip_steps_multiplier
        ?? state.modelOptions.default_skip_steps_multiplier
        ?? 0.08
      )
      params.skip_steps_multiplier = allowedThresholds.includes(requestedThreshold)
        ? requestedThreshold
        : (allowedThresholds[0] ?? 0.08)
      params.skip_steps_start_step_perc = Math.max(
        0,
        Math.min(
          100,
          Number(
            params.skip_steps_start_step_perc
            ?? state.modelOptions.default_skip_steps_start_step_perc
            ?? 25
          ),
        ),
      )
      if (params.skip_steps_cache_type !== 'first_block') {
        params.skip_steps_cache_type = ''
      }
    } else {
      delete params.skip_steps_cache_type
      delete params.skip_steps_multiplier
      delete params.skip_steps_start_step_perc
    }

    // STG (Spatio-Temporal Guidance) wiring. The backend only runs STG when
    // perturbation_switch === 2 (skip-self-attention) — stg_scale alone is
    // inert. Derive the switch from the slider so an untouched slider keeps
    // the exact request shape from before this feature existed, and strip
    // all perturbation params for models without the capability so a stale
    // value can't leak across a model switch.
    if (state.modelOptions?.perturbation) {
      const stg = params.stg_scale as number | undefined
      if (stg !== undefined) {
        params.perturbation_switch = stg > 0 ? 2 : 0
      }
    } else {
      delete params.stg_scale
      delete params.perturbation_switch
      delete params.perturbation_layers
      delete params.perturbation_start_perc
      delete params.perturbation_end_perc
    }
    // Reference pipeline is a per-model capability — strip a stale toggle
    // value if the user switched to a model that doesn't support it.
    if (!(state.modelOptions as Record<string, unknown> | null)?.reference_pipeline) {
      delete params.reference_pipeline
    }

    // MiniMax H3 has two mutually exclusive conditioning contracts. After a
    // Ref2VA run, selecting a new Start image can leave the persisted mode set
    // to "references" even when all reference tiles have been removed. In
    // that case the backend rejects the request before generation because
    // Ref2VA has no reference input. Treat an unaccompanied Start image as an
    // explicit FL2VA request and discard stale reference paths from the
    // previous run. If live reference tiles are still present, keep Ref2VA so
    // users can intentionally combine them.
    const hasH3References = (
      state.imageRefs.length > 0
      || (Array.isArray(params.image_refs) && params.image_refs.some(Boolean))
      || (Array.isArray(params.h3_ref_videos) && params.h3_ref_videos.some(Boolean))
      || (Array.isArray(params.h3_ref_audios) && params.h3_ref_audios.some(Boolean))
    )
    if (
      (
        params.model_type === 'minimax_h3'
        || params.model_type === 'minimax_h3_legacy'
      )
      && params.h3_reference_mode === 'references'
      && !hasH3References
    ) {
      params.h3_reference_mode = 'first_frame'
      delete params.image_refs
      delete params.h3_ref_videos
      delete params.h3_ref_audios
      set(s => ({
        params: { ...s.params, h3_reference_mode: 'first_frame' },
        savedParamsPerMode: {
          ...s.savedParamsPerMode,
          video: {
            ...(s.savedParamsPerMode.video || {}),
            h3_reference_mode: 'first_frame',
            image_refs: undefined,
            h3_ref_videos: undefined,
            h3_ref_audios: undefined,
          },
        },
      }))
    }

    // Tag avatar/edit-mode generations with their sub-mode so the gallery's
    // Edits filter and the loadSettingsFromOutput restore path can identify
    // them. Dedicated edit endpoints tag their jobs on the server; this is
    // retained for compatible generic edit submissions.
    if (state.generationMode === 'avatar' && state.editSubMode) {
      params.edit_sub_mode = state.editSubMode
    }

    // Default I2V / video-source strength. Distilled LTX-2 pipelines produce
    // noticeably better motion when the input anchor is at 0.7 instead of
    // tight-locked 1.0 — matches ComfyUI's reference distilled workflows
    // (stage 1 / single-stage both use 0.7). Dev and other families keep 1.0.
    // User can override via the slider; this only fires when the param isn't
    // already set.
    const _defaultIVS = (() => {
      const mt = (params.model_type as string) || ''
      return mt.includes('distilled') ? 0.7 : 1.0
    })()

    // force_fps="control" models (SCAIL-2 class) generate at the control
    // video's frame rate, but durationSeconds→video_length math uses the
    // model's nominal fps (16). Against a 25fps guide that under-counts
    // frames by a third: a "10s" request would cover only 6.4s of the
    // source performance. When the guide's real fps is known (probed at
    // upload), recompute the frame count at the rate the output will
    // actually play at.
    if (
      state.generationMode === 'video' &&
      params.video_guide &&
      params.force_fps === 'control' &&
      state.guideVideoFps && state.guideVideoFps > 0
    ) {
      // Cap at 30fps to match the server's follow-rate cap — a 60fps
      // guide would double the frame count (and sliding windows) for
      // no visible gain.
      const fpsUsed = Math.min(state.guideVideoFps, 30)
      params.video_length = Math.max(5, Math.round(state.durationSeconds * fpsUsed))
    }
    // Always tell the server what duration the user actually asked for.
    // For control-fps models the server recomputes video_length from
    // this at the guide's REAL frame rate — the durable fix for stale
    // restores (Load Settings from old sidecars carries frame counts
    // computed under the wrong fps) and for sessions where the guide's
    // fps never got probed. Underscore keys ride through harmlessly.
    if (state.generationMode === 'video' && params.video_guide) {
      ;(params as Record<string, unknown>)._duration_seconds = state.durationSeconds
    }

    // Smart multi-line prompt handling for video Frames mode:
    // When there's no sliding window (single window), send all lines as ONE prompt
    // with newlines preserved (LTX uses newlines as temporal markers within the clip).
    // When there IS sliding window, each line becomes a window prompt (mode 1).
    if (state.generationMode === 'video' && (isOmniReference || state.params.image_mode !== 2)) {
      const prompt = (params.prompt as string) || ''
      const hasSlidingWindow = state.modelOptions?.sliding_window === true
        && state.durationSeconds > state.slidingWindowSeconds
      if (
        hasSlidingWindow
        && (state.modelOptions?.sliding_window_auto_prompt_pacing === true || state.modelOptions?.wangp_1272 === true || params.minimax_h3_reference_sequence === true)
      ) {
        // H3's structured Context-IR prompt contains semantic line breaks;
        // they are not one prompt per continuation window. Keep the complete
        // shot plan intact so the backend can assign its timeline and tagged
        // dialogue across the automatically sized VRAM-safe passes.
        params.multi_prompts_gen_type = 2
      } else if (hasSlidingWindow && prompt.includes('\n')) {
        // Sliding window: each line = one window prompt (rolling generation)
        params.multi_prompts_gen_type = 1
      } else if (!hasSlidingWindow && prompt.includes('\n')) {
        // No sliding window — send entire prompt as one (multi_prompts_gen_type=2 preserves newlines)
        params.multi_prompts_gen_type = 2
      }
    }

    // Post-processing settings
    if (state.spatialUpsampling) params.spatial_upsampling = state.spatialUpsampling
    if (state.filmGrainIntensity > 0) {
      params.film_grain_intensity = state.filmGrainIntensity
      params.film_grain_saturation = state.filmGrainSaturation
    }
    // Voice clone (SeedVC) — only send if the user explicitly enabled
    // it AND provided at least one reference. Backend defaults all three
    // params to falsy if absent (postprocessing step is a no-op).
    if (!(state.generationMode === 'audio' && state.audioSubMode !== 'speech')
        && state.voiceCloneEnabled && state.voiceCloneRefs.length > 0) {
      const validRefs = state.voiceCloneRefs.filter(r => r && r.path)
      if (validRefs.length > 0) {
        params.voice_clone_enabled = true
        params.voice_clone_mode = state.voiceCloneMode
        // Pass server-side paths (already uploaded via /api/v1/upload-audio).
        params.voice_clone_refs = validRefs.map(r => r.path)
      }
    }

    // Image mode: force single frame + image output format
    // Backend uses image_mode > 0 to determine output as image (.jpg) vs video (.mp4)
    if (state.generationMode === 'image') {
      const { concreteImageResolution } = await import('../lib/imageResolution')
      const { materializeLocalEditImage } = await import('../lib/localEditImages')
      params.video_length = 1
      params.image_mode = 1
      params.repeat_generation = Math.max(1, Number(state.outputCount) || 1)
      params.resolution = concreteImageResolution(params.resolution, params.model_type)
      params.image_guide = await materializeLocalEditImage(params.image_guide)
      params.image_mask = await materializeLocalEditImage(params.image_mask)
    }

    // Audio mode: branch by sub-mode (Speech/Music vs SFX)
    if (state.generationMode === 'audio') {
      // Record the active sub-tab in the request so it lands in the
      // .meta.json sidecar — Load Settings uses it to restore Speech /
      // Music / SFX, not just the Audio tab. Underscore keys ride
      // through generation untouched, same as _tts_*. Music also saves
      // its song-writer inputs (UI-only, not consumed by generation).
      applyStudioAudioSubmitParams(params, state)
    }

    // Defensive cleanup: strip stale "V" (Source Video / extend) flag from
    // image_prompt_type when we're NOT entering the extend/continue path.
    //
    // The leak: when the user does a video extend (image_mode=3 +
    // continueVideoPath) and submits, the continue-mode branch below sets
    // params.image_prompt_type = "V". That mutation is on the local params
    // copy and shouldn't persist, BUT load-settings (loadSettingsFromOutput
    // at line 5284) DOES restore image_prompt_type from sidecar metadata
    // into state.params.image_prompt_type. So after extending a video and
    // then switching back to Frames mode via ModeToggle (which only flips
    // image_mode 3 -> 0, leaving image_prompt_type untouched), the next
    // generation carries forward image_prompt_type="V" from state.
    //
    // The single-clip and end-image handlers below only APPEND flags
    // (e.g. "S" + "V" -> "SV"), they never strip stale ones. So the "V"
    // survives, the backend (wgp.py:941-943) sees it and demands
    // video_source — but the user is in Frames mode with no source video.
    //
    // Symptom user reported: "I did a video extend and it worked. then I
    // switched to normal video mode and it keeps telling me to load a
    // source video. even after I refresh the page and try a new generation."
    //
    // Fix: strip "V" up-front unless we're going to re-add it in the
    // continue/extend branch below. The continue branch (image_mode === 3
    // + continueVideoPath) re-sets image_prompt_type = "V" wholesale, so
    // stripping here is safe — that branch puts it back.
    const willEnterContinueBranch = state.generationMode === 'video'
      && (params.image_mode === 3 || state.params.image_mode === 3)
      && !!state.continueVideoPath
    if (!willEnterContinueBranch) {
      const ipt = (params.image_prompt_type as string) || ''
      if (ipt.includes('V')) {
        params.image_prompt_type = ipt.replace(/V/g, '')
      }
      // Same stale-flag defense for the "T" temporal-alignment flag the
      // continue branch adds to video_prompt_type (see below). Without a
      // source video it's a backend no-op (alignment shift = 0 frames),
      // but stripping keeps restored-from-sidecar state from carrying it
      // into unrelated generations. Only the TRAILING "T" is that flag — an
      // internal "T" is the depth_temporal control letter (PTVG/TVG/TEVG),
      // and a global strip turned "Motion + Temporal Depth" (PTVG) into plain
      // "Transfer Human Motion" (PVG) at submit time, so use /T$/.
      const vptClean = (params.video_prompt_type as string) || ''
      if (vptClean.endsWith('T')) {
        params.video_prompt_type = vptClean.replace(/T$/, '')
      }
    }

    // Multi-clip path
    if (!isOmniReference && state.params.image_mode === 2) {
      const clips = state.clips
      const imagePaths: string[] = []
      const endImagePaths: string[] = []
      const perClipKeyframes: string[][] = []
      let hasAnyEndImage = false

      for (const clip of clips) {
        if (clip.startImage) {
          try {
            const result = await api.uploadImage(clip.startImage)
            imagePaths.push(result.path)
          } catch (e) {
            console.error('Failed to upload clip image:', e)
            imagePaths.push('')
          }
        } else if (clip.startImagePath) {
          imagePaths.push(clip.startImagePath)
        } else {
          imagePaths.push('')
        }

        // Upload end images (seamless mode)
        if (clip.endImage) {
          try {
            const result = await api.uploadImage(clip.endImage)
            endImagePaths.push(result.path)
            hasAnyEndImage = true
          } catch (e) {
            console.error('Failed to upload clip end image:', e)
            endImagePaths.push('')
          }
        } else if (clip.endImagePath) {
          endImagePaths.push(clip.endImagePath)
          hasAnyEndImage = true
        } else {
          endImagePaths.push('')
        }

        const clipKeyframes: string[] = []
        for (const keyframe of clip.keyframes || []) {
          if (keyframe.file) {
            try {
              const result = await api.uploadImage(keyframe.file)
              clipKeyframes.push(result.path)
            } catch (e) {
              console.error('Failed to upload clip keyframe:', e)
            }
          } else if (keyframe.path) {
            clipKeyframes.push(keyframe.path)
          }
        }
        perClipKeyframes.push(clipKeyframes)
      }

      let promptLines: string[]
      if (state.singlePromptMode) {
        const p: string = clips[0]?.prompt || (params.prompt as string) || ''
        promptLines = clips.map(() => p)
      } else {
        promptLines = clips.map(c => c.prompt || '')
      }

      params.prompt = promptLines.join('\n')
      params.image_start = imagePaths
      if (hasAnyEndImage) {
        params.image_end = endImagePaths
      }
      if (perClipKeyframes.some(keyframes => keyframes.length > 0)) {
        params.per_clip_keyframes = perClipKeyframes
      } else {
        delete params.per_clip_keyframes
      }
      params.multi_prompts_gen_type = 3
      params.image_mode = 0
      params.image_prompt_type = hasAnyEndImage ? 'SE' : 'S'
      if (params.input_video_strength == null) params.input_video_strength = _defaultIVS
    }
    // Single I2V path: Upload images if present (new File upload takes priority)
    // Skip in image mode — startImage is for video I2V, not image generation
    else if (!isOmniReference && state.startImage && state.generationMode !== 'image') {
      try {
        const result = await api.uploadImage(state.startImage)
        params.image_start = result.path
        params.image_mode = 0
        const ipt = (params.image_prompt_type as string) || ''
        if (!ipt.includes('S')) params.image_prompt_type = 'S' + ipt
        if (params.input_video_strength == null) params.input_video_strength = _defaultIVS
      } catch (e) {
        console.error('Failed to upload start image:', e)
      }
    } else if (!isOmniReference && params.image_start && state.generationMode !== 'image') {
      // Re-roll case: image_start is already an absolute path from sidecar metadata
      params.image_mode = 0
      const ipt = (params.image_prompt_type as string) || ''
      if (!ipt.includes('S')) params.image_prompt_type = 'S' + ipt
      if (params.input_video_strength == null) params.input_video_strength = _defaultIVS
    }
    if (!isOmniReference && state.endImage) {
      try {
        const result = await api.uploadImage(state.endImage)
        params.image_end = studioUploadReference(result, state.generationMode)
        const ipt = (params.image_prompt_type as string) || ''
        if (!ipt.includes('E')) params.image_prompt_type = ipt + 'E'
      } catch (e) {
        referenceUploadErrors.push(String(e))
        console.error('Failed to upload end image:', e)
      }
    } else if (params.image_end) {
      const ipt = (params.image_prompt_type as string) || ''
      if (!ipt.includes('E')) params.image_prompt_type = ipt + 'E'
    }

    // Continue mode: set video_source and image_prompt_type="V"
    if (!isOmniReference && state.generationMode === 'video' && params.image_mode === 3 && state.continueVideoPath) {
      params.video_source = state.continueVideoPath
      params.image_prompt_type = 'V'
      params.image_mode = 0
      if (params.input_video_strength == null) params.input_video_strength = _defaultIVS
      // Temporal alignment: the UI scopes EVERYTHING to the new content —
      // durationSeconds is the extend length, and ControlVideoSection's
      // injected-frame positions are computed against that timeline. The
      // backend, however, defaults to interpreting frames_positions (and
      // control video / control audio alignment) against the FULL timeline
      // including the source clip (wgp.py: reset_control_aligment = "T" in
      // video_prompt_type; alignment_shift = source frames only when "T").
      // Without "T", a frame injected at "end of the new 20s" of a 10s clip
      // lands at the 20s mark of the 30s output — 10s early; on longer
      // sources the position can fall entirely INSIDE the source span and
      // visibly never happen. "T" = upstream's "Aligned to the beginning of
      // the First Window of the new Video Sample", which matches the UI.
      // Append the alignment flag as a TRAILING "T". Guard on endsWith, not
      // includes: a control value with an internal "T" is depth_temporal
      // (PTVG/TVG/TEVG), and an includes() guard would skip the append for
      // those — silently dropping temporal alignment on an extend that uses a
      // Temporal-Depth control video. endsWith adds the flag while leaving the
      // process letter intact; the display/persist/submit strips remove only
      // this trailing "T" again.
      const vptExtend = (params.video_prompt_type as string) || ''
      if (!vptExtend.endsWith('T')) {
        params.video_prompt_type = vptExtend + 'T'
      }
      // Compensate for the overlap frames the backend adds (video_length +
      // overlap - 1). Without this, a 20s request with a 20s window produces
      // 2 windows because the overlap pushes total frames past one window.
      const swDefaults = state.modelOptions?.sliding_window_defaults as Record<string, number> | undefined
      const overlap = swDefaults?.overlap_default ?? 9
      const overlapFrames = Math.max(0, overlap - 1)
      const currentFrames = (params.video_length as number) || 0
      if (currentFrames > overlapFrames) {
        params.video_length = currentFrames - overlapFrames
      }
    }

    // Safety net: Studio Video mode ALWAYS produces video. The sub-mode
    // branches above translate image_mode 2/3 (Multi-Shot/Extend) to 0 + other
    // flags, but a plain T2V gen (no start image) hits none of them — so a
    // stale non-zero image_mode (e.g. an I2V clip's settings loaded via the
    // pencil, or Extend mode left without a source video) would leak through
    // and the backend (is_image = image_mode > 0) would emit a single PNG
    // instead of a video. Force video output here, after the sub-mode branches
    // have already read image_mode.
    if (state.generationMode === 'video') {
      params.image_mode = 0
    }

    // Image references (from ImageRefSection). H3 FL2VA intentionally sends
    // only its first/last frame; omni references remain visible in the UI but
    // are submitted only after the user explicitly chooses Ref2VA.
    const h3FirstFrameMode = (
      params.model_type === 'minimax_h3'
      || params.model_type === 'minimax_h3_legacy'
    )
      && (params.h3_reference_mode ?? 'first_frame') === 'first_frame'
    if (!h3FirstFrameMode && state.imageRefType && state.imageRefs.length > 0) {
      const refPaths: string[] = []
      for (const file of state.imageRefs) {
        try {
          const result = await api.uploadImage(file)
          refPaths.push(studioUploadReference(result, state.generationMode))
        } catch (e) {
          referenceUploadErrors.push(String(e))
          console.error('Failed to upload reference image:', e)
        }
      }
      if (refPaths.length > 0) {
        params.image_refs = refPaths
        params.remove_background_images_ref = state.removeBackgroundRefs ? 1 : 0
        // Merge image ref letter codes into video_prompt_type
        let vpt = (params.video_prompt_type as string) || ''
        for (const letter of state.imageRefType) {
          if (!vpt.includes(letter)) vpt += letter
        }
        params.video_prompt_type = vpt
      }
    } else if (params.image_refs && (params.image_refs as string[]).length > 0) {
      // Re-roll case: image_refs already populated from sidecar metadata
      params.remove_background_images_ref = params.remove_background_images_ref ?? 0
    } else {
      // No reference images attached for this submission. Strip any
      // image-ref letter codes from video_prompt_type that may have
      // persisted from an earlier task — without this, a user who
      // generates with refs once and then clears them gets stuck with
      // "I" (or other ref-letter codes) baked into the saved per-mode
      // params snapshot, which the backend rejects with "You must
      // provide at least one Reference Image". The backend has a
      // safety net that catches this too, but cleaning at the source
      // keeps the snapshot itself sensible.
      const vpt = (params.video_prompt_type as string) || ''
      if (vpt) {
        // Default ref letters used by Maestro when image refs are
        // present. If imageRefType is configured we trust that;
        // otherwise fall back to the conservative "I" — the most common
        // and the one we've actually observed leaking.
        const refLetters = state.imageRefType || 'I'
        let cleaned = vpt
        for (const letter of refLetters) {
          cleaned = cleaned.split(letter).join('')
        }
        if (cleaned !== vpt) {
          params.video_prompt_type = cleaned
        }
      }
      // Make sure no stale image_refs path list rides along either.
      if (params.image_refs !== undefined && (!params.image_refs || (params.image_refs as string[]).length === 0)) {
        delete params.image_refs
      }
    }

    if (h3FirstFrameMode) {
      delete params.image_refs
      delete params.h3_ref_videos
      delete params.h3_ref_audios
    }

    // Image conditioning alone does not guarantee that a video model will
    // retain an illustrated medium. Prefix every I2V prompt with a compact,
    // deterministic style anchor by default. This is deliberately applied at
    // submit time so it also covers direct Studio jobs, re-rolls and
    // multi-clip generations; Director applies the same policy server-side.
    const hasI2VStart = state.generationMode === 'video'
      && String(params.image_prompt_type || '').includes('S')
      && Boolean(params.image_start)
    if (hasI2VStart && params.preserve_source_style !== false) {
      const anchor = 'Use the supplied image as the exact first frame. Preserve its visual medium, palette, linework, shading and character design throughout, including anime or cel shading when visible; do not restyle it or make an illustrated source photorealistic.'
      const rawPrompt = String(params.prompt || '')
      if (!rawPrompt.toLowerCase().includes('preserve its visual medium')) {
        params.prompt = rawPrompt
          .split('\n')
          .map(line => line.trim() ? `${anchor} ${line.trim()}` : anchor)
          .join('\n')
      }
    }
    // UI-only policy flag: the backend receives the resulting prompt, not an
    // unknown generation parameter.
    delete params.preserve_source_style

    // Voice reference (ID-LoRA) — upload if present, add to params
    if (state.directorVoiceRef) {
      let vrPath = state.directorVoiceRefPath
      if (!vrPath) {
        try {
          const uploaded = await api.uploadAudio(state.directorVoiceRef)
          vrPath = uploaded.path
          set({ directorVoiceRefPath: vrPath })
        } catch { /* skip */ }
      }
      if (vrPath) {
        params.voice_reference = vrPath
        params.identity_guidance_scale = state.directorIdentityGuidanceScale
      }
    }

    const h3WindowStoryboardActive = (
      state.generationMode === 'video'
      && state.modelOptions?.sliding_window_auto_prompt_pacing === true
      && params.minimax_h3_window_storyboard !== false
      && state.params.image_mode !== 2
      && Number(params.video_length || 0) > Number(params.sliding_window_size || 0)
    )
    if (state.modelOptions?.sliding_window_auto_prompt_pacing === true || params.minimax_h3_reference_sequence === true) {
      params.minimax_h3_window_storyboard = h3WindowStoryboardActive
      if (h3WindowStoryboardActive && state.h3WindowPlan) {
        params.h3_window_prompts = state.h3WindowPlan.windows.map(window => window.prompt)
        params.h3_window_plan_signature = state.h3WindowPlan.signature
        params.h3_window_plan = state.h3WindowPlan
      } else {
        delete params.h3_window_prompts
        delete params.h3_window_plan_signature
        delete params.h3_window_plan
      }
    } else {
      delete params.minimax_h3_window_storyboard
      delete params.h3_window_prompts
      delete params.h3_window_plan_signature
      delete params.h3_window_plan
    }

    const submission = await prepareStudioSubmission(params, state, get, submissionContext, referenceUploadErrors)
    const newJob: GenerationJob = {
      id: '',
      status: 'queued',
      progress: 0,
      step: 0,
      totalSteps: 0,
      phase: '',
      message: scheduledPrompt
        ? `Submitting ${scheduledPrompt.position}/${scheduledPrompt.total}...`
        : h3WindowStoryboardActive ? 'Planning H3 windows...' : 'Submitting...',
      outputFiles: [],
      error: null,
      createdAt: Date.now(),
      oomInfo: null,
      generationDetails: _generationDetailsFromParams(submission.params, state.models),
    }

    set(s => {
      return prependJob(s.jobs, newJob)
    })

    try {
      const { job_id, task_id, root_task_id, h3_window_plan } = await submission.submit()

      if (h3_window_plan) {
        const planFps = state.modelOptions?.fps ?? 24
        const effectiveWindowFrames = h3_window_plan.effective_window_frames
          || h3_window_plan.window_frames
        set(s => ({
          h3WindowPlan: h3_window_plan,
          slidingWindowSeconds: effectiveWindowFrames / planFps,
          params: { ...s.params, sliding_window_size: effectiveWindowFrames },
        }))
      }

      // Update the job with its server-assigned ID
      set(s => ({
        jobs: s.jobs.map(j => j === newJob ? {
          ...j,
          id: job_id,
          taskId: task_id || undefined,
          rootTaskId: root_task_id || task_id || undefined,
          status: 'queued',
          message: 'Queued...',
          h3WindowPlan: h3_window_plan ?? null,
        } : j),
      }))

      // Poll for status on this specific job
      const pollInterval = setInterval(async () => {
        // Check if this job was removed (stopped)
        if (!get().jobs.find(j => j.id === job_id)) {
          clearInterval(pollInterval)
          return
        }

        try {
          const status = await api.fetchJobStatus(job_id)

          set(s => ({
            jobs: s.jobs.map(j => j.id !== job_id ? j : {
              ...j,
              status: status.status,
              progress: status.progress / 100,
              step: status.step ?? 0,
              totalSteps: status.total_steps ?? 0,
              phase: status.phase ?? '',
              message: status.message,
              outputFiles: status.output_files,
              error: status.error,
              oomInfo: status.oom_info ?? null,
              taskTimings: status.task_timings ?? [],
              h3WindowPlan: status.h3_window_plan ?? j.h3WindowPlan ?? null,
              ..._jobTimingPatch(status),
            }),
          }))

          // Refresh gallery during generation to show sliding window progress
          if (status.status === 'running') {
            void get().maybeRefreshGallery()
          }

          if (status.status === 'completed') {
            clearInterval(pollInterval)
            // Completed job — remove the placeholder, real output now in gallery
            set(s => {
              const remaining = s.jobs.filter(j => j.id !== job_id)
              return withJobs(remaining)
            })
            void get().maybeRefreshGallery({ message: 'New output ready' })
          } else if (isGenerationJobSettled(status.status)) {
            clearInterval(pollInterval)
            // Keep the failed/cancelled job in the queue so its placeholder
            // card stays visible with the error message. User dismisses via
            // the X button on the tile.
            set(s => withJobs(s.jobs))
          }
        } catch (e) {
          console.error('Status poll error:', e)
        }
      }, 2000)
      return submission.receipt
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Generation failed'
      // Submit itself failed (pre-queue). Convert the placeholder to a failed
      // state in place so the user sees what happened, rather than making the
      // tile disappear and leaving them to wonder.
      set(s => updateJob(s.jobs, j => j === newJob, j => ({
        ...j, id: j.id || `submit-fail-${Date.now()}`, status: 'failed', message: msg, error: msg,
      })))
    }
  },
  rerollGeneration: async (source) => {
    // Await the (now async, self-healing) settings load before generating, so a
    // slow on-demand metadata fetch can't let the reroll fire with stale params.
    if (await get().loadSettingsFromOutput(source) === false) return false
    await get().startGeneration()
  },
})
