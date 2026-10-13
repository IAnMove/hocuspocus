import { concreteImageResolution } from '../../../lib/imageResolution'
import { defaultSpeechModel } from '../../../lib/preferredModels'
import { h3ModelSwitchSettings } from '../../../lib/h3OptionalSettings'
import { restoreWan1300AudioRecipe, wan1300AudioSelection } from '../../../lib/wan1300Audio'
import { IMAGE_INTENT_PARAMS, emptyImageStudioDraft, imageStudioDraft } from '../imageStudioIntent'
import { restoreAudioReferences, stashAudioReferences, type AudioReferenceStash } from '../audioReferenceState'
import type { AspectRatio, GenerateParams, GenerationMode, ResolutionPreset } from '../../../types'
import { _applyModelDefaults } from '../../../stores/modelOptionsSlice'
import { _saveSettings, restoreModeParams, snapshotModeParams, type SavedModeParams } from '../../../stores/modeSettingsPersistence'
import { _globalModelSelectionModes } from '../../../stores/servicesSlice'
import { getDefaultModelForMode } from '../../../stores/modelsSlice'
import { sfxModelTypes } from '../../../stores/modelCatalog'
import { resolveResolution } from '../../../stores/resolution'
import type { SliceCreator } from '../../../stores/storeApi'
import type { AppState } from '../../../stores/useStore'
import { audioSubModeForModel, captureVideoSubModeStash } from './studioFormHelpers'

// Transient: the LTX model selected before entering either SCAIL-2 edit
// workflow, so leaving Recast/Repaint restores the user's prior edit model.
let _preScail2AvatarModel = ''

const defaultParams: GenerateParams = {
  prompt: '',
  model_type: 'ltx2_22B_distilled_1_1',
  resolution: '1280x720',
  video_length: 251,
  num_inference_steps: 8,
  guidance_scale: 1.0,
  seed: -1,
  image_mode: 0,
  negative_prompt: '',
  repeat_generation: 1,
  activated_loras: [],
  loras_multipliers: '',
  skip_steps_cache_type: '',
  skip_steps_multiplier: 0.08,
  skip_steps_start_step_perc: 25,
  settings_version: 2.52,
}

// The "input spec" — everything the Inputs panel + prompt box write into
// params. Blanked when entering a sub-mode with no stash yet; the
// generic generation settings (steps, resolution, guidance, ...) carry
// over and only diverge per-sub-mode once the user changes them there.
const BLANK_VIDEO_INPUT_PARAMS: Partial<GenerateParams> = {
  prompt: '',
  image_start: undefined,
  image_end: undefined,
  image_refs: undefined,
  h3_ref_videos: undefined,
  h3_ref_audios: undefined,
  frames_positions: undefined,
  injection_strength: undefined,
  video_prompt_type: '',
  image_prompt_type: '',
  audio_prompt_type: '',
  audio_guide: undefined,
  video_guide: undefined,
  video_source: undefined,
  input_video_strength: undefined,
}

export type StudioFormSlice = {
  // Generation mode (top-level: image/video/audio/avatar)
  generationMode: GenerationMode
  setGenerationMode: (mode: GenerationMode) => void
  imageStudioDrafts: Partial<Record<import('../imageStudioIntent').ImageStudioIntent, import('../imageStudioIntent').ImageStudioDraft>>
  imageStudioIntent: import('../imageStudioIntent').ImageStudioIntent
  setImageStudioIntent: (intent: import('../imageStudioIntent').ImageStudioIntent) => void
  resetImageStudio: () => void
  imageBatch?: import('../imageBatch').ImageBatchSettings
  editSubMode: import('../../../types').EditSubMode
  setEditSubMode: (mode: import('../../../types').EditSubMode, recastEngine?: 'scail' | 'viggle') => void
  audioSubMode: import('../../../types').AudioSubMode
  setAudioSubMode: (mode: import('../../../types').AudioSubMode) => void
  audioReferenceStash: AudioReferenceStash
  selectedModelPerAudioSubMode: Partial<Record<import('../../../types').AudioSubMode, string>>
  selectedModelPerMode: Partial<Record<GenerationMode, string>>
  savedLoraPerMode: Partial<Record<GenerationMode, { activated_loras: string[]; loras_multipliers: string; loraWeights: Record<string, number[]>; availableLoras: string[] }>>
  savedParamsPerMode: Partial<Record<GenerationMode, SavedModeParams>>
  savedPromptPerMode: Partial<Record<string, string>>

  // Generation params
  params: GenerateParams
  setParam: <K extends keyof GenerateParams>(key: K, value: GenerateParams[K]) => void
  setParams: (partial: Partial<GenerateParams>) => void

  // Select model (triggers side effects)
  selectModel: (modelType: string, preserveAudioReferences?: boolean) => void
}

/** setAudioSubMode and setParam pass get() into helpers typed as AppState. */
export type StudioFormSliceHost = AppState

export const createStudioFormSlice: SliceCreator<StudioFormSlice, StudioFormSliceHost> = (set, get) => ({
  // Generation mode
  generationMode: 'video',
  imageStudioIntent: 'chooser' as import('../imageStudioIntent').ImageStudioIntent,
  imageStudioDrafts: {},
  setImageStudioIntent: intent => {
    const state = get()
    if (state.imageStudioIntent === intent) return
    const drafts = { ...state.imageStudioDrafts }
    if (state.imageStudioIntent !== 'chooser') drafts[state.imageStudioIntent] = imageStudioDraft(state)
    const draft = drafts[intent] || emptyImageStudioDraft(state.modelOptions)
    const cleared = Object.fromEntries(IMAGE_INTENT_PARAMS.map(key => [key, undefined]))
    set({
      ...draft,
      imageStudioIntent: intent, imageStudioDrafts: drafts,
      params: { ...state.params, ...cleared,
        prompt: '', negative_prompt: '',
        video_prompt_type: '', image_prompt_type: 'T', denoising_strength: 1, masking_strength: 1,
        ...draft.params,
        // Drafts store the sidebar count, not repeat_generation. Re-apply it so
        // Generate does not keep the previous intent's batch size.
        repeat_generation: draft.outputCount,
        resolution: concreteImageResolution(draft.params.resolution || resolveResolution(state.modelOptions, 'auto', 'auto'), state.params.model_type),
      },
    })
  },
  resetImageStudio: () => {
    const state = get()
    const drafts = [imageStudioDraft(state), ...Object.values(state.imageStudioDrafts)]
    void import('../../../lib/localEditImages').then(({ forgetLocalImage }) => {
      for (const draft of drafts) {
        forgetLocalImage(String(draft.params.image_guide || ''))
        forgetLocalImage(String(draft.params.image_mask || ''))
        for (const item of draft.imageBatch?.sources || []) forgetLocalImage(item.url)
      }
    })
    state.setImageStudioIntent('chooser')
    set({ imageStudioDrafts: {}, imageBatch: undefined })
  },
  editSubMode: 'retake' as import('../../../types').EditSubMode,
  setEditSubMode: (mode: import('../../../types').EditSubMode, recastEngine?: 'scail' | 'viggle') => {
    const s = get()
    const prev = s.editSubMode
    const current = (s.params.model_type as string) || ''
    const wantsViggle = mode === 'recast' && recastEngine === 'viggle'
    const engineChange = mode === 'recast' && recastEngine !== undefined
      && (current === 'viggle_animate') !== wantsViggle
    // Viggle has no trim UI. A leftover Recast/Retake range would be sent as
    // start_time/end_time and silently cut the clip (or reject a short one).
    const enteringViggle = wantsViggle && (engineChange || mode !== prev)
    set({
      editSubMode: mode,
      ...(enteringViggle ? { editStartTime: 0, editEndTime: s.editVideoDuration || 0 } : {}),
    })
    if ((mode === prev && !engineChange) || s.generationMode !== 'avatar') return
    // Recast uses SCAIL-2 Replace; Repaint uses the proven SCAIL-2 Animate
    // path from Studio Video/Frames. Swap recipes when moving between those
    // modes and restore the previous LTX edit model when leaving both.
    const isScail2 = (mt: string) => s.models.find(m => m.model_type === mt)?.architecture === 'scail2_14B'
    const enteringScail2Edit = mode === 'recast' || mode === 'restyle'
    const leavingScail2Edit = prev === 'recast' || prev === 'restyle'
    if (enteringScail2Edit) {
      const valid = mode === 'recast'
        ? wantsViggle ? current === 'viggle_animate' : current === 'scail2_14B_recast_fast' || current === 'scail2_14B'
        : current === 'scail2_14B_fast' || current === 'scail2_14B'
      if (!valid) {
        if (!leavingScail2Edit && !isScail2(current)) {
          _preScail2AvatarModel = current
        }
        const preferred = mode === 'recast'
          ? wantsViggle ? 'viggle_animate' : 'scail2_14B_recast_fast'
          : 'scail2_14B_fast'
        const target = s.models.some(m => m.model_type === preferred)
          ? preferred
          : !wantsViggle && s.models.some(m => m.model_type === 'scail2_14B')
            ? 'scail2_14B'
            : undefined
        if (target) get().selectModel(target)
      }
    } else if (leavingScail2Edit && (isScail2(current) || current === 'viggle_animate')) {
      const restore = _preScail2AvatarModel && s.models.some(m => m.model_type === _preScail2AvatarModel)
        ? _preScail2AvatarModel
        : getDefaultModelForMode('avatar', s.families, s.models)
      if (restore) get().selectModel(restore)
    }
  },
  audioSubMode: 'speech' as import('../../../types').AudioSubMode,
  audioReferenceStash: {},
  selectedModelPerAudioSubMode: {} as Partial<Record<import('../../../types').AudioSubMode, string>>,
  setAudioSubMode: (subMode) => {
    const { audioSubMode: prevSub, params, models } = get()
    if (subMode === prevSub && (subMode === 'mixer' || audioSubModeForModel(params.model_type) === subMode)) return
    // Save current model for the sub-mode we're leaving
    const savedModels = { ...get().selectedModelPerAudioSubMode, [prevSub]: params.model_type }
    // Determine model for target sub-mode
    const audioSubModeDefaults: Record<import('../../../types').AudioSubMode, string> = {
      speech: defaultSpeechModel(models),
      // XL SFT LM_4B: the premium CFG variant + strongest LM — the
      // quality default. Turbo variants remain enabled for speed.
      music: 'ace_step_v1_5_xl_sft_lm_4b',
      sfx: 'mmaudio_v2',
      mixer: '',  // Mixer doesn't use a model — it's an ffmpeg-based tool
    }
    const saved = savedModels[subMode]
    const targetModel = (saved && audioSubModeForModel(saved) === subMode && models.some(m => m.model_type === saved))
      ? saved
      : audioSubModeDefaults[subMode]
    const audioReferenceStash = stashAudioReferences(get())
    set({
      ...restoreAudioReferences(get(), subMode, audioReferenceStash),
      audioSubMode: subMode, selectedModelPerAudioSubMode: savedModels, audioReferenceStash,
    })
    if (targetModel && models.some(m => m.model_type === targetModel)) {
      get().selectModel(targetModel, true)
    }
  },
  selectedModelPerMode: {},
  savedLoraPerMode: {},
  savedParamsPerMode: {},
  savedPromptPerMode: {} as Partial<Record<string, string>>,

  setGenerationMode: (mode) => {
    const imageState = get()
    if (imageState.generationMode === 'image' && mode !== 'image' && imageState.imageStudioIntent !== 'chooser') {
      set({ imageStudioDrafts: { ...imageState.imageStudioDrafts, [imageState.imageStudioIntent]: imageStudioDraft(imageState) } })
    }

    // Tools is a non-generative post-processing area — it owns no model, so
    // skip the per-mode model/LoRA/params RESTORE machinery entirely. We still
    // SAVE the leaving mode's state (prompt / model / LoRAs / params snapshot)
    // so returning to it restores correctly, leave `params` untouched (no model
    // load, no defaults reset), and persist the *previous* real mode as the
    // landing mode so a reload doesn't drop into Tools with no model loaded.
    if (mode === 'tools') {
      const s = get()
      const prev = s.generationMode
      if (prev === mode) { set({ generationMode: mode }); return }
      const paramsSnapshot = snapshotModeParams(s.params)
      const savedModels = { ...s.selectedModelPerMode, [prev]: s.params.model_type }
      const savedParams = {
        ...s.savedParamsPerMode,
        [prev]: { ...paramsSnapshot, filmGrainIntensity: s.filmGrainIntensity, filmGrainSaturation: s.filmGrainSaturation, durationSeconds: s.durationSeconds },
      }
      const savedLoras = {
        ...s.savedLoraPerMode,
        [prev]: { activated_loras: s.params.activated_loras || [], loras_multipliers: s.params.loras_multipliers || '', loraWeights: s.loraWeights, availableLoras: s.availableLoras },
      }
      const savedPrompts = { ...s.savedPromptPerMode, [prev]: s.params.prompt }
      set({
        generationMode: mode,
        selectedModelPerMode: savedModels,
        savedParamsPerMode: savedParams,
        savedLoraPerMode: savedLoras,
        savedPromptPerMode: savedPrompts,
      })
      _saveSettings({ generationMode: prev, selectedModelPerMode: savedModels, savedParamsPerMode: savedParams, savedLoraPerMode: savedLoras, savedPromptPerMode: savedPrompts }, s.loraIdByFilename)
      return
    }
    const { families, models, generationMode: prevMode, params, selectedModelPerMode, savedLoraPerMode, savedParamsPerMode, loraWeights, availableLoras, savedPromptPerMode } = get()
    // Save prompt for the mode we're leaving
    const savedPrompts = { ...savedPromptPerMode, [prevMode]: params.prompt }
    // Save current model + LoRA + params state for the mode we're leaving
    const savedModels = { ...selectedModelPerMode, [prevMode]: params.model_type }
    const savedLoras = {
      ...savedLoraPerMode,
      [prevMode]: {
        activated_loras: params.activated_loras || [],
        loras_multipliers: params.loras_multipliers || '',
        loraWeights,
        availableLoras,
      },
    }
    // Save the FULL params snapshot for the leaving mode. Strip the
    // fields that are tracked separately in their own per-mode state
    // structures (model_type → selectedModelPerMode, prompt →
    // savedPromptPerMode, activated_loras / loras_multipliers →
    // savedLoraPerMode) to avoid double-bookkeeping. Everything else
    // — including repeat_generation, negative_prompt, video_prompt_type,
    // video_guide, image_refs, frames_positions, MMAudio_*, etc. — is
    // captured here so it survives a switch-and-return AND doesn't
    // leak into other modes.
    const paramsSnapshot = snapshotModeParams(params)
    const savedParams = {
      ...savedParamsPerMode,
      [prevMode]: {
        ...paramsSnapshot,
        filmGrainIntensity: get().filmGrainIntensity,
        filmGrainSaturation: get().filmGrainSaturation,
        // Save durationSeconds per-mode so audio's 600/1800 (Kugel/Scenema
        // slider max) doesn't leak into video on mode-switch back. Audio
        // mode's loadModelOptions still overrides with the slider.max on
        // model select, so this only matters for video/image/avatar.
        durationSeconds: get().durationSeconds,
      },
    }
    // Restore saved model for target mode, or fall back to default
    const savedModel = savedModels[mode]
    const restoredModel = savedModel && models.some(m => m.model_type === savedModel)
      ? savedModel
      : getDefaultModelForMode(mode, families, models)
    const newModelType = restoredModel || params.model_type
    // Restore saved LoRA state for target mode (if same model)
    const restoredLora = savedLoras[mode]
    const sameModel = restoredLora && savedModel === newModelType
    // Restore the saved params snapshot for the target mode. If the
    // user never visited this mode before, fall back to defaultParams
    // (NOT the previous mode's params — that's what caused the leak).
    const restoredSnapshot = savedParams[mode]
    // Extract film grain from snapshot (top-level store state, not in params)
    const restoredFilmGrain = restoredSnapshot
      ? { filmGrainIntensity: restoredSnapshot.filmGrainIntensity ?? 0, filmGrainSaturation: restoredSnapshot.filmGrainSaturation ?? 0.5 }
      : { filmGrainIntensity: 0, filmGrainSaturation: 0.5 }
    // Restore durationSeconds for the target mode. Non-audio modes (video,
    // avatar, image) fall back to 5s on first visit. Audio mode's
    // durationSeconds gets overridden by loadModelOptions when it sees
    // audio_only && duration_slider, so the snapshot value is mostly
    // ignored there — it's still saved for symmetry.
    const restoredDuration = restoredSnapshot && typeof restoredSnapshot.durationSeconds === 'number'
      ? restoredSnapshot.durationSeconds as number
      : 5
    // Strip filmGrain + durationSeconds keys before applying — they don't belong in params
    const restoredParams = restoreModeParams(restoredSnapshot)
    // Restore saved prompt for target mode (or empty for first visit)
    const restoredPrompt = savedPrompts[mode] ?? ''

    set(() => ({
      generationMode: mode,
      ...(mode === 'image' && prevMode !== 'image'
        ? { imageStudioIntent: 'chooser' as const }
        : {}),
      ...(mode === 'audio' ? { audioSubMode: audioSubModeForModel(newModelType) } : {}),
      selectedModelPerMode: savedModels,
      savedLoraPerMode: savedLoras,
      savedParamsPerMode: savedParams,
      savedPromptPerMode: savedPrompts,
      // Default to Auto resolution + aspect in image mode (matches reference image)
      ...(mode === 'image' ? { resolutionPreset: 'auto' as ResolutionPreset, aspectRatio: 'auto' as AspectRatio } : {}),
      ...restoredFilmGrain,
      durationSeconds: restoredDuration,
      // Build params from defaults + restored snapshot. We deliberately
      // do NOT spread `...s.params` here — that's the line that caused
      // every previous-mode field to leak into the new mode. Starting
      // from defaults ensures only the restored snapshot's fields (the
      // user's actual choices in this mode, or nothing on first visit)
      // are present. Then layer model_type / prompt / LoRAs from their
      // separate stores on top, plus the special image_mode logic.
      params: {
        ...defaultParams,
        ...restoredParams,
        model_type: newModelType,
        prompt: restoredPrompt,
        image_mode: mode === 'image' ? 1 : (restoredParams.image_mode ?? 0),
        activated_loras: sameModel ? restoredLora.activated_loras : [],
        loras_multipliers: sameModel ? restoredLora.loras_multipliers : '',
      },
      h3WindowPlan: null,
      loraWeights: sameModel ? restoredLora.loraWeights : {},
      availableLoras: sameModel ? restoredLora.availableLoras : [],
    }))
    const restoredNativeRecipe = restoreWan1300AudioRecipe(newModelType, get().params)
    if (newModelType && mode !== 'model3d') get().loadModelOptions(newModelType, restoredNativeRecipe)
    if (newModelType && !sfxModelTypes.has(newModelType) && mode !== 'model3d') {
      if (!sameModel) {
        get().loadLoras(newModelType)
      }
      // Mode switch counts as a model selection too — apply the new
      // model's defaults so numeric primaries (steps, CFG, flow_shift,
      // sample_solver) match what that model expects rather than what
      // the previous mode's model was using. See _applyModelDefaults
      // for the field list and rationale. Native YuE2/AuK recipes from
      // the per-mode snapshot win over those defaults.
      _applyModelDefaults(get, set, newModelType, restoredNativeRecipe)
    }
    // Persist to localStorage
    _saveSettings({
      generationMode: mode,
      selectedModelPerMode: savedModels,
      savedParamsPerMode: savedParams,
      savedLoraPerMode: savedLoras,
      savedPromptPerMode: savedPrompts,
    }, get().loraIdByFilename)
  },

  params: { ...defaultParams },
  setParam: (key, value) => {
    // Per-sub-mode isolation: remember the outgoing sub-mode BEFORE the
    // param write flips image_mode (see videoSubModeStash).
    const prevImageMode = key === 'image_mode' ? ((get().params.image_mode as number) ?? 0) : null
    const invalidatesH3Plan = [
      'prompt', 'model_type', 'resolution', 'image_start', 'image_end',
      'image_mode', 'minimax_h3_planning_style', 'minimax_h3_audio_policy',
      'minimax_h3_references', 'minimax_h3_reference_sequence',
    ].includes(String(key))
    set(s => ({
      params: { ...s.params, [key]: value },
      ...(invalidatesH3Plan ? { h3WindowPlan: null } : {}),
    }))
    // Auto-parse speaker names from prompt whenever audio mode has at least
    // one voice slot. Previously gated on audio_prompt_type.includes('B')
    // (multi-voice only), but the user expects single-voice ("Peter: hello")
    // to populate voice slot 1 too. Voice-count gate covers both cases —
    // ttsVoiceCount > 0 means at least one voice clone is active.
    if (key === 'prompt' && typeof value === 'string' && get().generationMode === 'audio'
        && get().audioSubMode === 'speech' && get().ttsVoiceCount > 0) {
      get()._autoParseSpkeakerNames(value)
    }
    // Handle sub-mode transitions (Frames / Multi-Shot / Extend / Blend)
    if (key === 'image_mode') {
      // Each Studio Video sub-mode is an ISOLATED working set: stash the
      // outgoing sub-mode's full state (prompt, input tiles, settings)
      // and bring back the incoming one. A sub-mode visited for the
      // first time keeps the generic settings but starts with blank
      // inputs — so Extend opens clean while the Frames setup (injected
      // keyframes and all) survives the round-trip untouched.
      const s1 = get()
      if (s1.generationMode === 'video' && typeof value === 'number' && prevImageMode !== null && value !== prevImageMode) {
        const stash = { ...s1.videoSubModeStash, [prevImageMode]: captureVideoSubModeStash(s1) }
        const saved = stash[value]
        if (saved) {
          set({
            videoSubModeStash: stash,
            // Model + LoRA selection stay shared across sub-modes — keep
            // the live values, restore everything else.
            params: {
              ...saved.params,
              image_mode: value,
              model_type: s1.params.model_type,
              activated_loras: s1.params.activated_loras,
              loras_multipliers: s1.params.loras_multipliers,
            },
            startImage: saved.startImage,
            endImage: saved.endImage,
            continueVideo: saved.continueVideo,
            continueVideoPath: saved.continueVideoPath,
            continueVideoUrl: saved.continueVideoUrl,
            continueVideoDuration: saved.continueVideoDuration,
            audioGuideFilename: saved.audioGuideFilename,
            imageRefs: saved.imageRefs,
            imageRefType: saved.imageRefType,
            removeBackgroundRefs: saved.removeBackgroundRefs,
            durationSeconds: saved.durationSeconds,
            slidingWindowSeconds: saved.slidingWindowSeconds,
            slidingWindowOverlap: saved.slidingWindowOverlap,
            clips: saved.clips,
            singlePromptMode: saved.singlePromptMode,
            studioFocusedClipIndex: saved.studioFocusedClipIndex ?? 0,
          })
        } else {
          set(s => ({
            videoSubModeStash: stash,
            params: { ...s.params, ...BLANK_VIDEO_INPUT_PARAMS },
            startImage: null,
            endImage: null,
            continueVideo: null,
            continueVideoPath: '',
            continueVideoUrl: '',
            continueVideoDuration: 0,
            audioGuideFilename: null,
            imageRefs: [],
            imageRefType: '',
            removeBackgroundRefs: false,
            // durationSeconds + sliding window intentionally carry over:
            // they're settings, not inputs — they diverge per sub-mode
            // only after the user changes them there.
          }))
        }
      }
      // Multi-clip transitions (after the stash swap so syncClipCount
      // sees the restored duration/params).
      if (value === 2) {
        get().syncClipCount()
      } else {
        set({ clips: [], singlePromptMode: false, studioFocusedClipIndex: 0 })
      }
    }
    // Snapshot the changed param into the current mode's IN-MEMORY
    // record so it survives a mode switch + return within this session.
    // Skip keys that are tracked in their own per-mode structures
    // (model_type, prompt, LoRA fields) to avoid double-bookkeeping.
    // Everything else — repeat_generation, negative_prompt,
    // num_inference_steps, video_prompt_type, video_guide, image_refs,
    // frames_positions, MMAudio_*, etc. — gets snapshotted here.
    //
    // Deliberately NOT written to localStorage: a page refresh starts
    // the working state (prompt, seed, LoRA selection, Advanced values)
    // from the model's defaults. v1.2.0 persisted every edit across
    // refreshes and users found the stale text/seeds surprising —
    // in-session mode-switch persistence is the wanted behavior,
    // refresh is a clean slate (see loadModels).
    if (key !== 'model_type' && key !== 'prompt' && key !== 'activated_loras' && key !== 'loras_multipliers') {
      const s = get()
      const mode = s.generationMode
      const paramsSnapshot = snapshotModeParams(s.params)
      const updatedSavedParams = {
        ...s.savedParamsPerMode,
        [mode]: {
          ...paramsSnapshot,
          filmGrainIntensity: s.filmGrainIntensity,
          filmGrainSaturation: s.filmGrainSaturation,
        },
      }
      set({ savedParamsPerMode: updatedSavedParams })
    }
  },
  setParams: (partial) => {
    set(s => ({ params: { ...s.params, ...partial } }))
  },

  selectModel: (modelType, preserveAudioReferences) => {
    const audioSelection = wan1300AudioSelection(modelType, preserveAudioReferences)
    const currentMode = get().generationMode
    _globalModelSelectionModes.delete(currentMode)
    set(s => ({
      ...audioSelection,
      params: {
        ...s.params,
        ...audioSelection.params,
        model_type: modelType,
        ...h3ModelSwitchSettings(s.params, modelType),
        activated_loras: [],
        loras_multipliers: '',
        minimax_h3_turbo_mode: false,
      },
      selectedModelPerMode: { ...s.selectedModelPerMode, [currentMode]: modelType },
      h3WindowPlan: null,
      loraWeights: {},
      availableLoras: [],
    }))
    const preservedRecipe = preserveAudioReferences
      ? restoreWan1300AudioRecipe(
        modelType,
        get().audioReferenceStash[get().audioSubMode]?.params ?? {},
      )
      : undefined
    if (currentMode !== 'model3d') get().loadModelOptions(modelType, preservedRecipe)
    // Virtual SFX models don't have backend LoRAs or model defaults.
    if (!sfxModelTypes.has(modelType) && currentMode !== 'model3d') {
      get().loadLoras(modelType)
      _applyModelDefaults(get, set, modelType, preservedRecipe)
    }
    // Persist to localStorage
    const s = get()
    _saveSettings({
      generationMode: s.generationMode,
      selectedModelPerMode: s.selectedModelPerMode,
      savedParamsPerMode: s.savedParamsPerMode,
      savedLoraPerMode: s.savedLoraPerMode,
    }, s.loraIdByFilename)
  },
})
