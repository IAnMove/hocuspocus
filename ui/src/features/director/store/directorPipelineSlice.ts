import * as api from '../../../api/client'
import { mapDirectorClipImages } from '../../../lib/directorClipImages'
import { productionImageModelType } from '../../../lib/productionProfile'
import { resolveResolution } from '../../../stores/resolution'
import { storyDirectorSubmissionProvenance } from '../../stories/provenance'
import type { GenerationMode } from '../../../types'
import { DASHBOARD_PIPELINE_PAGE_SIZE, type DirectorDashboardSlice } from './directorDashboardSlice'
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
  /** True after directorReset: the footer may still list live jobs, but reconnect must not steal this editor. */
  directorEditorDetached: boolean
  startDirectorPipeline: (useCurrentPlans?: boolean) => Promise<void>
  continuePipeline: (updates?: { clip_plans?: Array<{ video_prompt: string; image_prompt: string }> }) => Promise<void>
  stopPipeline: (pipelineId?: string) => Promise<void>
  reconnectDirectorPipelines: () => Promise<void>
  pollPipelineStatus: () => void
}

/** Boot and Dashboard resume may bind the live primary job. A Reset/Story Lab handoff must not. */
export function shouldAutoBindDirectorPipeline(
  pipelineId: string | null | undefined,
  editorDetached: boolean,
): boolean {
  return !pipelineId && !editorDetached
}

/** startDirectorPipeline, pollPipelineStatus, and reconnectDirectorPipelines read and write the director, gallery, and studio fields listed here. */
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
  | 'directorClipImages'
  | 'directorImageGenProgress'
  | 'directorWritingProvider'
  | 'directorWritingModel'
  | 'directorWritingBaseUrl'
  | 'directorIdentityGuidanceScale'
  | 'directorLoading'
  | 'directorError'
  | 'directorStep'
> & Pick<ModelOptionsSlice, 'modelOptions'> & Pick<ServicesSlice, 'servicesConfig' | 'productionProfile'> & Pick<ModelsSlice, 'models'> & Pick<LlmSlice, 'llmStatus'> & Pick<GallerySlice, 'activeWorkspace' | 'refreshOutputs' | 'maybeRefreshGallery'> & Pick<DirectorDashboardSlice, 'loadPipelineList' | 'discoverActiveDirectorRepairs'> & {
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
  llmStreamDone: boolean
}

let directorReconnectTimer: ReturnType<typeof setTimeout> | null = null
let directorReconnectInFlight = false

export const createDirectorPipelineSlice: SliceCreator<DirectorPipelineSlice, DirectorPipelineSliceHost> = (set, get) => ({
  pipelineId: null,
  pipelineStatus: null,
  activeDirectorPipelines: [],
  pipelinePolling: false,
  directorEditorDetached: false,

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
        directorEditorDetached: false,
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

  reconnectDirectorPipelines: async () => {
    if (directorReconnectTimer) clearTimeout(directorReconnectTimer)
    const refresh = async () => {
      if (directorReconnectInFlight) return
      directorReconnectInFlight = true
      try {
        const data = await api.fetchActiveDirectorPipelines()
        set({ activeDirectorPipelines: data.pipelines })

        // Restore the primary pipeline state so Director's existing inspector
        // can reconnect to the same run, while the footer displays every live
        // pipeline returned by the backend.
        const primary = data.pipelines[0]
        if (primary && shouldAutoBindDirectorPipeline(get().pipelineId, get().directorEditorDetached)) {
          set({
            pipelineId: primary.id,
            pipelineStatus: primary as import('../../../api/client').PipelineStatus,
            pipelinePolling: true,
            directorLoading: primary.status === 'running' || primary.status === 'queued',
          })
          get().pollPipelineStatus()
        }
        directorReconnectTimer = data.pipelines.length > 0
          ? setTimeout(refresh, 2000)
          : null
      } catch {
        // Older backends do not expose the in-memory endpoint. Story Lab
        // productions still persist their pipeline id, so recover those runs
        // directly and keep the footer useful during a rolling backend update.
        try {
          const library = await api.fetchStoryLibrary(get().activeWorkspace)
          const pipelineIds = Object.values(library.projects)
            .flatMap(project => project.productions || [])
            .map(production => production.targetSnapshot?.pipelineId)
            .filter((id): id is string => typeof id === 'string' && id.length > 0)
          const uniqueIds = [...new Set(pipelineIds)]
          const statuses = await Promise.allSettled(uniqueIds.map(id => api.fetchPipelineStatus(id)))
          const active = statuses
            .filter((result): result is PromiseFulfilledResult<import('../../../api/client').PipelineStatus> => result.status === 'fulfilled')
            .map(result => result.value)
            .filter((status): status is import('../../../api/client').PipelineStatus & { status: 'running' | 'paused' } =>
              status.status === 'running' || status.status === 'paused')
            .map(status => ({
              ...status,
              pipeline_type: 'music_video',
              created_at: 0,
              updated_at: Date.now(),
            }))
          set({ activeDirectorPipelines: active })
          const primary = active[0]
          if (primary && shouldAutoBindDirectorPipeline(get().pipelineId, get().directorEditorDetached)) {
            set({
              pipelineId: primary.id,
              pipelineStatus: primary,
              pipelinePolling: true,
              directorLoading: true,
            })
            get().pollPipelineStatus()
          }
          directorReconnectTimer = active.length > 0 ? setTimeout(refresh, 2000) : null
        } catch {
          directorReconnectTimer = null
        }
      } finally {
        directorReconnectInFlight = false
      }
    }
    // A reload also drops the Director repair polls while the repair keeps running on the
    // server: rediscover them once from the newest runs, without opening the Dashboard.
    // (Not in `refresh`, which repeats every two seconds.)
    void api.fetchPipelineList({ limit: DASHBOARD_PIPELINE_PAGE_SIZE, offset: 0 })
      .then(({ pipelines }) => get().discoverActiveDirectorRepairs(pipelines))
      .catch(() => { /* older backend or offline: the Dashboard still discovers on open */ })
    await refresh()
  },

  pollPipelineStatus: () => {
    const pid = get().pipelineId
    if (!pid) return

    // The output gallery used to be reloaded on every two-second pipeline
    // heartbeat. Besides rescanning the whole workspace on the backend, that
    // replaced the gallery array even when no file had changed and caused a
    // visible editor blink. Refresh only when the pipeline reports a new
    // completed image/video checkpoint.
    let lastOutputRefreshSignature = ''
    const refreshOutputsWhenChanged = (signature: string) => {
      if (signature === lastOutputRefreshSignature) return
      lastOutputRefreshSignature = signature
      get().refreshOutputs()
    }

    const poll = async () => {
      if (!get().pipelinePolling || get().pipelineId !== pid) return

      try {
        const status = await api.fetchPipelineStatus(pid)
        set({ pipelineStatus: status })

        // Sync pipeline state to director UI state
        if (status.clip_plans?.length && !get().directorClipPlans.length) {
          set({
            directorClipPlans: status.clip_plans,
            directorStep: status.generation_mode === 'direct_video' ? 'review_video' : 'review',
          })
        }

        if (status.clip_images?.length) {
          // Strip empty filenames — those are failed-shot sentinels from the
          // pipeline (clip_images.append("") on exception). If we keep them,
          // downstream <img src={getFileUrl("")} /> hits /api/v1/file/ which
          // can resolve to a stale cached file rather than nothing, producing
          // the "same unrelated image over and over" symptom users see when
          // image gen fails (e.g. incompatible LoRA architecture).
          // clipIndex is captured BEFORE filtering so it stays aligned to
          // the original clip plan position even when failed shots drop out.
          const images = mapDirectorClipImages(
            status.clip_images,
            status.clip_plans || [],
          )
          set({ directorClipImages: images })
        }

        // Handle phase transitions
        if (status.phase === 'polishing_prompts') {
          set({
            directorImageGenProgress: {
              current: status.progress.current,
              total: status.progress.total,
              currentClipLabel: status.progress.message || 'Polishing prompts (3rd pass)...',
              status: 'generating',
            },
          })
        } else if (status.phase === 'preparing_direct_video') {
          set({ directorStep: 'review_video', directorClipImages: [], directorImageGenProgress: null })
        } else if (status.phase === 'generating_images') {
          set({
            directorStep: 'generate_images',
            directorImageGenProgress: {
              current: status.progress.current,
              total: status.progress.total,
              currentClipLabel: status.progress.message,
              status: 'generating',
            },
          })
          const completedImages = (status.clip_images || []).filter(Boolean)
          refreshOutputsWhenChanged(`images:${completedImages.join('|')}`)
        } else if (status.phase === 'preparing_video') {
          // H3 prompt-only/direct-reference projects intentionally skip the
          // image review stage and proceed straight to video rendering.
          set({
            directorStep: 'review_video',
            directorImageGenProgress: null,
          })
        } else if (status.phase === 'generating_video') {
          set({ directorStep: 'review_video' })
          refreshOutputsWhenChanged(
            `video:${status.progress.current}:${(status.output_files || []).join('|')}`,
          )
        }

        // Handle LLM streaming
        if (status.llm_streaming) {
          set({ llmStreamDone: false })
        }

        // Handle pause
        if (status.status === 'paused') {
          set({ directorLoading: false })
          if (status.pause_reason === 'review_prompts') {
            set({ directorStep: 'review' })
          } else if (status.pause_reason === 'review_video_prompts') {
            set({ directorStep: 'review_video' })
          } else if (status.pause_reason === 'review_images') {
            set({ directorStep: 'review_video' })
          }
        }

        // Comic PRE is a deliberate terminal checkpoint: prompts and I2V
        // canvases are ready, but no video generation should start until the
        // user approves all clips or chooses one card in the comic editor.
        if (status.status === 'preview_ready') {
          set({
            pipelinePolling: false,
            directorLoading: false,
          })
          return
        }

        // Handle completion
        if (status.status === 'completed') {
          set({
            pipelinePolling: false,
            directorLoading: false,
            directorStep: 'review_video',
          })
          void get().maybeRefreshGallery({ message: 'Production finished' })
          return  // Stop polling
        }

        // Handle failure
        if (status.status === 'failed' || status.status === 'cancelled') {
          const imageProgress = get().directorImageGenProgress
          set({
            pipelinePolling: false,
            directorLoading: false,
            directorError: status.error || 'Pipeline stopped',
            directorImageGenProgress: imageProgress
              ? { ...imageProgress, status: 'error' }
              : null,
          })
          return  // Stop polling
        }

      } catch (e) {
        console.error('Pipeline poll error:', e)
      }

      // Continue polling
      if (get().pipelinePolling) {
        setTimeout(poll, 2000)
      }
    }

    setTimeout(poll, 1000)
  },
})
