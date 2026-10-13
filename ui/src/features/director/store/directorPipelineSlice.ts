import * as api from '../../../api/client'
import { productionImageModelType } from '../../../lib/productionProfile'
import { resolveResolution } from '../../../stores/resolution'
import { storyDirectorSubmissionProvenance } from '../../stories/provenance'
import type { GenerationMode } from '../../../types'
import type { DirectorDashboardSlice } from './directorDashboardSlice'
import type { DirectorSlice } from '../../../stores/directorSlice'
import type { GallerySlice } from '../../../stores/gallerySlice'
import type { LlmSlice } from '../../../stores/llmSlice'
import type { ModelOptionsSlice } from '../../../stores/modelOptionsSlice'
import type { ModelsSlice } from '../../../stores/modelsSlice'
import type { SavedModeParams } from '../../../stores/modeSettingsPersistence'
import type { ServicesSlice } from '../../../stores/servicesSlice'
import type { SliceCreator } from '../../../stores/storeApi'

export type DirectorPipelineSlice = {
  // Director Pipeline (server-side)
  pipelineId: string | null
  pipelineStatus: import('../../../api/client').PipelineStatus | null
  activeDirectorPipelines: import('../../../api/client').ActiveDirectorPipeline[]
  pipelinePolling: boolean
  startDirectorPipeline: (useCurrentPlans?: boolean) => Promise<void>
  continuePipeline: (updates?: { clip_plans?: Array<{ video_prompt: string; image_prompt: string }> }) => Promise<void>
  stopPipeline: (pipelineId?: string) => Promise<void>
}

/** startDirectorPipeline reads and writes the director, gallery, and studio fields listed here. pollPipelineStatus stays on the store. */
export type DirectorPipelineSliceHost = DirectorPipelineSlice & Pick<DirectorSlice,
  | 'directorMusicVideoTreatment'
  | 'directorPlannedClips'
  | 'directorSceneDescription'
  | 'directorAudioPath'
  | 'directorAnalysis'
  | 'directorReferenceImagePath'
  | 'directorAutoMode'
  | 'directorSeamless'
  | 'directorShotImageGuidance'
  | 'directorResolution'
  | 'directorAspectRatio'
  | 'directorVideoMaxShotFramesByModel'
  | 'directorH3TurboModeByModel'
  | 'directorSpeakerMappings'
  | 'shortFilmPath'
  | 'shortFilmCharacters'
  | 'shortFilmTargetDuration'
  | 'shortFilmNarrative'
  | 'shortFilmVisualStyle'
  | 'shortFilmPreserveVisualStyle'
  | 'directorCharacterVisualStyle'
  | 'directorAllowClipText'
  | 'directorVideoInferenceStepsByModel'
  | 'directorReferenceImage'
  | 'directorCharacterRefPaths'
  | 'directorCharacterRefs'
  | 'directorLocationRefPaths'
  | 'directorLocationRefs'
  | 'directorH3VideoRefPaths'
  | 'directorH3AudioRefPaths'
  | 'directorH3VideoRefs'
  | 'directorH3AudioRefs'
  | 'directorVoiceRefPath'
  | 'directorVoiceRef'
  | 'directorSpokenLanguage'
  | 'directorCharacterRefLabels'
  | 'directorLocationRefLabels'
  | 'directorClipPlans'
  | 'directorWritingProvider'
  | 'directorWritingModel'
  | 'directorWritingBaseUrl'
  | 'directorIdentityGuidanceScale'
  | 'directorLoading'
  | 'directorError'
  | 'directorStep'
> & Pick<ModelOptionsSlice, 'modelOptions'> & Pick<ServicesSlice, 'servicesConfig' | 'productionProfile'> & Pick<ModelsSlice, 'models'> & Pick<LlmSlice, 'llmStatus'> & Pick<GallerySlice, 'activeWorkspace'> & Pick<DirectorDashboardSlice, 'loadPipelineList'> & {
  selectedModelPerMode: Partial<Record<GenerationMode, string>>
  savedLoraPerMode: Partial<Record<GenerationMode, { activated_loras: string[]; loras_multipliers: string; loraWeights: Record<string, number[]>; availableLoras: string[] }>>
  savedParamsPerMode: Partial<Record<GenerationMode, SavedModeParams>>
  directorImageSpatialUpsampling: string
  directorImageFilmGrainIntensity: number
  directorImageFilmGrainSaturation: number
  directorVideoSpatialUpsampling: string
  directorVideoFilmGrainIntensity: number
  directorVideoFilmGrainSaturation: number
  directorVideoSelfRefiner: number
  directorAudioScale: number
  directorStoryProductionHandoff: {
    workspace: string
    projectId: string
    productionId: string
    cueId?: string
    candidateId?: string
  } | null
  pollPipelineStatus: () => void
}

export const createDirectorPipelineSlice: SliceCreator<DirectorPipelineSlice, DirectorPipelineSliceHost> = (set, get) => ({
  pipelineId: null,
  pipelineStatus: null,
  activeDirectorPipelines: [],
  pipelinePolling: false,

  // ── Director Pipeline (server-side) ──────────────────────────────
  startDirectorPipeline: async (useCurrentPlans = false) => {
    const state = get()
    const directVideo = state.directorMusicVideoTreatment.generation_mode === 'direct_video'
    const { directorPlannedClips, directorSceneDescription,
            directorAudioPath, directorAnalysis, directorReferenceImagePath,
            directorAutoMode, directorSeamless, directorShotImageGuidance,
            directorResolution, directorAspectRatio,
            directorVideoMaxShotFramesByModel, directorH3TurboModeByModel,
            selectedModelPerMode, savedParamsPerMode, savedLoraPerMode,
            directorSpeakerMappings, directorImageSpatialUpsampling,
            directorImageFilmGrainIntensity, directorImageFilmGrainSaturation,
            directorVideoSpatialUpsampling, directorVideoFilmGrainIntensity,
            directorVideoFilmGrainSaturation, directorVideoSelfRefiner,
            shortFilmPath, shortFilmCharacters, shortFilmTargetDuration,
            shortFilmNarrative, shortFilmVisualStyle,
            shortFilmPreserveVisualStyle, directorCharacterVisualStyle,
            directorAllowClipText } = state

    const selectedImageModel = selectedModelPerMode.image
      || productionImageModelType(state.productionProfile)
      || 'flux2_klein_9b'
    const selectedVideoModel = selectedModelPerMode.video || 'ltx2_22B_distilled_1_1'

    // Director model choices are independent from whichever Studio model was
    // edited most recently. Hydrate each selected model's own tuned defaults,
    // then reuse saved Studio overrides only when they explicitly belong to
    // that same model. This prevents a distilled model's settings from
    // leaking into a full model (or vice versa) after a Director-only switch.
    const [imageModelDefaults, videoModelDefaults, fetchedImageOptions, fetchedVideoOptions] = await Promise.all([
      api.fetchDefaults(selectedImageModel).catch(() => ({})),
      api.fetchDefaults(selectedVideoModel).catch(() => ({})),
      api.fetchModelOptions(selectedImageModel).catch(() => null),
      api.fetchModelOptions(selectedVideoModel).catch(() => null),
    ])
    const cachedVideoOptions = state.modelOptions?.model_type === selectedVideoModel
      ? state.modelOptions
      : null
    const directorVideoOptions = fetchedVideoOptions || cachedVideoOptions
    const directorImageOptions = fetchedImageOptions
    const directorImageResolution = resolveResolution(
      directorImageOptions,
      directorResolution,
      directorAspectRatio,
    )
    const directorVideoResolution = resolveResolution(
      directorVideoOptions,
      directorResolution,
      directorAspectRatio,
    )
    const fps = directorVideoOptions?.fps ?? 16
    const savedImageParams = savedParamsPerMode.image || {}
    const savedVideoParams = savedParamsPerMode.video || {}
    const matchingImageParams = savedImageParams.model_type === selectedImageModel
      ? savedImageParams
      : {}
    const matchingVideoParams = savedVideoParams.model_type === selectedVideoModel
      ? savedVideoParams
      : {}
    const rawDefaultVideoSteps = (
      directorVideoOptions?.default_num_inference_steps
      ?? (videoModelDefaults as Record<string, unknown>).num_inference_steps
      ?? 8
    )
    const parsedDefaultVideoSteps = Number(rawDefaultVideoSteps)
    const defaultVideoSteps = Number.isFinite(parsedDefaultVideoSteps) && parsedDefaultVideoSteps > 0
      ? Math.max(1, Math.min(50, Math.round(parsedDefaultVideoSteps)))
      : 8
    const configuredVideoSteps = state.directorVideoInferenceStepsByModel[selectedVideoModel]
    // A model may publish a fixed distilled recipe. In that case the model
    // default wins even if an older adjustable build left an override behind.
    let directorVideoSteps = directorVideoOptions?.lock_inference_steps
      ? defaultVideoSteps
      : (configuredVideoSteps ?? defaultVideoSteps)
    const directorTurboOption = directorVideoOptions?.minimax_h3_turbo
    const savedDirectorVideoLoras = savedLoraPerMode.video
    const directorTurboEnabled = Boolean(
      directorTurboOption
      && directorH3TurboModeByModel[selectedVideoModel] === true
      && savedDirectorVideoLoras?.activated_loras?.includes(directorTurboOption.filename)
    )
    if (directorTurboEnabled) directorVideoSteps = directorTurboOption!.steps
    const directorMaxShotFrames = directorVideoMaxShotFramesByModel[selectedVideoModel]

    // Upload all reference images (main + character + location) if not already uploaded
    let refImagePath = directVideo ? null : directorReferenceImagePath
    if (!directVideo && !refImagePath && state.directorReferenceImage) {
      try {
        const uploaded = await api.uploadImage(state.directorReferenceImage)
        refImagePath = uploaded.path
        set({ directorReferenceImagePath: refImagePath })
      } catch (e) {
        console.error('Failed to upload reference image for pipeline:', e)
      }
    }
    // Upload character refs that haven't been uploaded yet
    const charPaths = directVideo ? [] : [...state.directorCharacterRefPaths]
    for (let i = charPaths.length; !directVideo && i < state.directorCharacterRefs.length; i++) {
      try {
        const uploaded = await api.uploadImage(state.directorCharacterRefs[i])
        charPaths.push(uploaded.path)
      } catch (error) {
        // Paths are a compact prefix aligned with labels. Continuing after a
        // failed middle upload would attach the next character's image to the
        // wrong name, which is worse than omitting the remaining references.
        console.error('Failed to upload a character reference for pipeline:', error)
        break
      }
    }
    if (charPaths.length > state.directorCharacterRefPaths.length) {
      set({ directorCharacterRefPaths: charPaths })
    }
    // Upload location refs that haven't been uploaded yet
    const locPaths = directVideo ? [] : [...state.directorLocationRefPaths]
    for (let i = locPaths.length; !directVideo && i < state.directorLocationRefs.length; i++) {
      try {
        const uploaded = await api.uploadImage(state.directorLocationRefs[i])
        locPaths.push(uploaded.path)
      } catch (error) {
        console.error('Failed to upload a location reference for pipeline:', error)
        break
      }
    }
    if (locPaths.length > state.directorLocationRefPaths.length) {
      set({ directorLocationRefPaths: locPaths })
    }
    const selectedVideoDefinition = state.models.find(
      model => model.model_type === selectedVideoModel,
    )
    const supportsVoiceReference = (
      selectedVideoDefinition?.director?.supports_voice_reference === true
    )
    const voiceReferenceMode = (
      selectedVideoDefinition?.director?.voice_reference_mode ?? 'none'
    )

    // Preserve pre-release arbitrary H3 media references while routing the
    // official Omni model through the same lazy upload path.
    const h3ReferenceMode = directVideo
      ? 'first_frame'
      : savedParamsPerMode.video?.h3_reference_mode || 'first_frame'
    const isH3Omni = selectedVideoModel.startsWith('minimax_h3_ref2va')
      || (
        ['minimax_h3', 'minimax_h3_legacy'].includes(selectedVideoModel)
        && h3ReferenceMode === 'references'
      )
    const h3VideoRefPaths = [...state.directorH3VideoRefPaths]
    const h3AudioRefPaths = [...state.directorH3AudioRefPaths]
    if (!directVideo && isH3Omni) {
      for (let i = h3VideoRefPaths.length; i < state.directorH3VideoRefs.length; i++) {
        try {
          const uploaded = await api.uploadImage(state.directorH3VideoRefs[i])
          h3VideoRefPaths.push(uploaded.path)
        } catch (error) {
          console.error('Failed to upload an H3 video reference:', error)
          break
        }
      }
      for (let i = h3AudioRefPaths.length; i < state.directorH3AudioRefs.length; i++) {
        try {
          const uploaded = await api.uploadAudio(state.directorH3AudioRefs[i])
          h3AudioRefPaths.push(uploaded.path)
        } catch (error) {
          console.error('Failed to upload an H3 audio reference:', error)
          break
        }
      }
      set({ directorH3VideoRefPaths: h3VideoRefPaths, directorH3AudioRefPaths: h3AudioRefPaths })
    }

    // Voice Reference is an LTX-2 ID-LoRA or a native H3 Omni audio
    // reference. Keep the local selection across model switches, but only
    // upload and submit it when the selected Director model can consume it.
    let voiceRefPath = state.directorVoiceRefPath
    if (supportsVoiceReference && !voiceRefPath && state.directorVoiceRef) {
      try {
        const uploaded = await api.uploadAudio(state.directorVoiceRef)
        voiceRefPath = uploaded.path
        set({ directorVoiceRefPath: voiceRefPath })
      } catch { /* skip */ }
    }

    // Determine pipeline type
    let pipelineType = 'music_video'
    if (shortFilmPath === 'story') pipelineType = 'short_film_story'
    else if (shortFilmPath === 'audio') pipelineType = 'short_film_audio'

    const storyProvenance = storyDirectorSubmissionProvenance(
      state.directorStoryProductionHandoff,
    )
    const pipelineParams: Record<string, unknown> = {
      pipeline_type: pipelineType,
      production_kind: (
        /cinematic story trailer|mandatory trailer arc/i.test(directorSceneDescription)
          ? 'trailer'
          : pipelineType === 'music_video' ? 'music_video' : undefined
      ),
      auto_mode: useCurrentPlans ? true : directorAutoMode,
      workspace: get().activeWorkspace,
      ...(storyProvenance ? { provenance: storyProvenance } : {}),
      scene_description: directorSceneDescription,
      spoken_language: state.directorSpokenLanguage || undefined,
      audio_path: directorAudioPath,
      reference_image_path: refImagePath,
      character_ref_paths: charPaths.length > 0 ? charPaths : undefined,
      character_ref_labels: state.directorCharacterRefLabels.length > 0 ? state.directorCharacterRefLabels : undefined,
      location_ref_paths: locPaths.length > 0 ? locPaths : undefined,
      location_ref_labels: state.directorLocationRefLabels.length > 0 ? state.directorLocationRefLabels : undefined,
      planned_clips: directorPlannedClips,
      provided_clip_plans: useCurrentPlans ? state.directorClipPlans : undefined,
      seamless: directVideo ? false : directorSeamless,
      shot_image_guidance: directorShotImageGuidance,
      director_resolution_preset: directorResolution,
      director_aspect_ratio: directorAspectRatio,
      director_max_shot_frames: directorMaxShotFrames,
      fps,
      frames_steps: directorVideoOptions?.frames_steps ?? 4,
      frames_minimum: directorVideoOptions?.frames_minimum ?? 5,

      // Director v2 flag — see prior callsites: ?? not || so explicit
      // user toggle-off is respected (legacy v1), only fall back to
      // true when the field is undefined.
      use_director_v2: state.servicesConfig?.use_director_v2 ?? true,

      // LLM
      llm_model_id: state.servicesConfig?.llm_model_id || state.llmStatus?.model_id,
      llm_device: state.servicesConfig?.llm_device || state.llmStatus?.device,
      llm_provider: state.servicesConfig?.llm_provider || 'local',
      writing_provider: state.directorWritingProvider,
      writing_model: state.directorWritingModel,
      writing_base_url: state.directorWritingBaseUrl,
      lyrics: directorAnalysis?.lyrics || '',
      bpm: directorAnalysis?.bpm,
      speaker_mappings: directorSpeakerMappings,
      characters: shortFilmCharacters,
      target_duration: shortFilmTargetDuration,
      narrative_mode: shortFilmNarrative,
      visual_style: shortFilmVisualStyle || undefined,
      preserve_visual_style: shortFilmPreserveVisualStyle,
      character_visual_style: directorCharacterVisualStyle || undefined,
      allow_clip_text: directorAllowClipText,
      music_video_treatment: pipelineType === 'music_video' || directVideo
        ? state.directorMusicVideoTreatment
        : undefined,

      // Image gen settings
      image_model: selectedImageModel,
      image_params: {
        ...imageModelDefaults,
        ...matchingImageParams,
        resolution: directorImageResolution,
      },
      image_loras: savedLoraPerMode.image || {},
      image_spatial_upsampling: directorImageSpatialUpsampling,
      image_film_grain_intensity: directorImageFilmGrainIntensity,
      image_film_grain_saturation: directorImageFilmGrainSaturation,

      // Video gen settings
      video_model: selectedVideoModel,
      video_params: {
        ...videoModelDefaults,
        ...matchingVideoParams,
        // Director owns this value. Studio's Advanced step count is separate
        // state and must not leak into a new Director project.
        num_inference_steps: directorVideoSteps,
        resolution: directorVideoResolution,
        ...(isH3Omni ? {
          h3_ref_videos: h3VideoRefPaths,
          h3_ref_audios: h3AudioRefPaths,
        } : {}),
        minimax_h3_turbo_mode: directorTurboEnabled,
      },
      video_loras: savedLoraPerMode.video || {},
      video_spatial_upsampling: directorVideoSpatialUpsampling,
      video_film_grain_intensity: directorVideoFilmGrainIntensity,
      video_film_grain_saturation: directorVideoFilmGrainSaturation,
      video_self_refiner: directorVideoSelfRefiner,
      audio_scale: get().directorAudioScale,

      // Voice identity: LTX uses the CelebVHQ ID-LoRA; H3 Omni maps the
      // same upload into each shot's native Ref2VA manifest.
      ...(supportsVoiceReference && voiceRefPath ? {
        voice_reference: voiceRefPath,
        ...(voiceReferenceMode === 'id_lora' ? {
          identity_guidance_scale: state.directorIdentityGuidanceScale,
        } : {}),
      } : {}),
    }

    try {
      const { pipeline_id } = await api.startPipeline(pipelineParams)
      set({
        pipelineId: pipeline_id,
        pipelineStatus: null,
        pipelinePolling: true,
        directorStep: 'plan',
        directorLoading: true,
        directorError: null,
      })
      get().pollPipelineStatus()
      void get().loadPipelineList()
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Pipeline failed to start'
      set({ directorError: msg })
      throw e
    }
  },

  continuePipeline: async (updates) => {
    const pid = get().pipelineId
    if (!pid) return
    try {
      await api.continuePipeline(pid, updates)
      set({ directorLoading: true })
    } catch (e) {
      console.error('Failed to continue pipeline:', e)
    }
  },

  stopPipeline: async (pipelineId) => {
    const pid = pipelineId || get().pipelineId
    if (!pid) return
    set(state => ({
      activeDirectorPipelines: state.activeDirectorPipelines.map(pipeline =>
        pipeline.id === pid
          ? {
              ...pipeline,
              phase: 'cancelling',
              progress: {
                ...pipeline.progress,
                message: 'Cancelling after the current model step…',
              },
            }
          : pipeline),
    }))
    try {
      await api.stopPipeline(pid)
      set(state => ({
        activeDirectorPipelines: state.activeDirectorPipelines.filter(
          pipeline => pipeline.id !== pid,
        ),
        ...(state.pipelineId === pid ? {
          pipelineId: null,
          pipelineStatus: null,
          pipelinePolling: false,
          directorLoading: false,
        } : {}),
      }))
    } catch (e) {
      console.error('Failed to stop pipeline:', e)
      throw e
    }
  },
})
