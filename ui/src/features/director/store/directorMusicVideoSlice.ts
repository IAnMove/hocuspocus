import * as api from '../../../api/client'
import type { GenerationReceiptLike } from '../../../api/generationCommandClient'
import { beginAppActivity, type ActivitySlice } from '../../activity/store'
import type { GenerationSubmissionContext } from '../../studio/generationProvenance'
import { contentLanguageForUi } from '../../../lib/contentLanguage'
import { llmActivityPreview } from '../../../lib/llmActivityPreview'
import { resolveSupportedVideoFormat } from '../../../lib/productionProfile'
import type { DirectorClipImage, DirectorShotImageGuidance, DirectorSkill, DirectorV2PlanResponse, GenerateParams, GenerationMode, MultiClip, ResolutionPreset, SpeakerMapping } from '../../../types'
import { DEFAULT_DIRECT_VIDEO_MASTER_PROMPT } from '../../../types'
import type { GallerySlice } from '../../../stores/gallerySlice'
import { UNLOADED_LLM_STATUS, type LlmSlice } from '../../../stores/llmSlice'
import type { LorasSlice } from '../../../stores/lorasSlice'
import type { SavedModeParams } from '../../../stores/modeSettingsPersistence'
import { _saveSettings } from '../../../stores/modeSettingsPersistence'
import type { ModelOptionsSlice } from '../../../stores/modelOptionsSlice'
import { _PRIMARY_MODEL_DEFAULT_FIELDS } from '../../../stores/modelOptionsSlice'
import type { ModelsSlice } from '../../../stores/modelsSlice'
import { resolveResolution } from '../../../stores/resolution'
import type { ServicesSlice } from '../../../stores/servicesSlice'
import { _globalModelSelectionModes } from '../../../stores/servicesSlice'
import type { SliceCreator } from '../../../stores/storeApi'
import type { DirectorPipelineSlice } from './directorPipelineSlice'
import type { DirectorSlice } from '../../../stores/directorSlice'

export type DirectorMusicVideoSlice = {
  // Director (Music Video Director)
  sidebarMode: 'director' | 'studio'
  directorSkill: DirectorSkill | null
  /** Exact Story production currently loaded by the embedded Wizard. */
  directorStoryProductionHandoff: {
    workspace: string
    projectId: string
    productionId: string
    cueId?: string
    candidateId?: string
  } | null
  setDirectorSkill: (skill: DirectorSkill) => void
  selectDirectorImageModel: (modelType: string) => void
  selectDirectorVideoModel: (modelType: string) => Promise<void>
  setDirectorH3Profile: (profile: 'balanced' | 'quality' | 'low_memory') => void
  setDirectorH3ReferenceMode: (mode: 'first_frame' | 'references') => void
  directorSetLora: (mode: 'image' | 'video', activated_loras: string[], loras_multipliers: string, loraWeights: Record<string, number[]>, availableLoras: string[]) => void
  setSidebarMode: (mode: 'director' | 'studio') => void
  directorSetSpeakerMapping: (speakerId: string, name: string, role: SpeakerMapping['role']) => void
  directorInsertSpeakerMention: (speakerId: string) => void
  directorConfirmStructure: () => void
  directorSetSceneDescription: (prompt: string) => void
  directorSetReferenceImage: (file: File | null) => void
  directorAddCharacterRef: (file: File) => void
  directorRemoveCharacterRef: (index: number) => void
  directorSetCharacterRefLabel: (index: number, label: string) => void
  directorReorderCharacterRefs: (from: number, to: number) => void
  directorAddLocationRef: (file: File) => void
  directorRemoveLocationRef: (index: number) => void
  directorSetLocationRefLabel: (index: number, label: string) => void
  directorReorderLocationRefs: (from: number, to: number) => void
  directorAddH3VideoRef: (file: File) => void
  directorRemoveH3VideoRef: (index: number) => void
  directorAddH3AudioRef: (file: File) => void
  directorRemoveH3AudioRef: (index: number) => void
  directorPlanPrompts: () => Promise<void>
  directorResumePlan: () => Promise<void>
  directorPlanVideoPrompts: () => Promise<void>
  directorGenerateStartImages: () => Promise<void>
  directorApplyToClips: () => void
  directorGenerate: () => void
  directorReset: () => void
  directorEditClipPlan: (index: number, field: 'video_prompt' | 'image_prompt', value: string) => void
  _uploadDirectorRefs: () => Promise<{ refImagePath: string | null; charPaths: string[]; locPaths: string[] }>
}

/** Plan, generate, start images, reset, and reference actions read and write the fields listed here. */
export type DirectorMusicVideoSliceHost = DirectorMusicVideoSlice & ActivitySlice & Pick<DirectorSlice,
  | 'directorAllowClipText'
  | 'directorAnalysis'
  | 'directorAspectRatio'
  | 'directorAudioName'
  | 'directorAudioPath'
  | 'directorAutoMode'
  | 'directorCharacterRefLabels'
  | 'directorCharacterRefPaths'
  | 'directorCharacterRefs'
  | 'directorCharacterVisualStyle'
  | 'directorClipImages'
  | 'directorClipPlans'
  | 'directorEnergyBias'
  | 'directorError'
  | 'directorH3AudioRefPaths'
  | 'directorH3AudioRefs'
  | 'directorH3VideoRefPaths'
  | 'directorH3VideoRefs'
  | 'directorImageGenProgress'
  | 'directorLlmLog'
  | 'directorLoading'
  | 'directorLocationRefLabels'
  | 'directorLocationRefPaths'
  | 'directorLocationRefs'
  | 'directorMusicSource'
  | 'directorMusicVideoTreatment'
  | 'directorPacingProfile'
  | 'directorPlanRecovery'
  | 'directorPlannedClips'
  | 'directorReferenceImage'
  | 'directorReferenceImagePath'
  | 'directorResolution'
  | 'directorSceneDescription'
  | 'directorSeamless'
  | 'directorShotImageGuidance'
  | 'directorSongDescription'
  | 'directorSongDuration'
  | 'directorSongInstrumental'
  | 'directorSongLyrics'
  | 'directorSongStyle'
  | 'directorSpeakerMappings'
  | 'directorSpeakers'
  | 'directorSpokenLanguage'
  | 'directorStep'
  | 'directorTrackGenerating'
  | 'directorVideoInferenceStepsByModel'
  | 'directorVoiceRef'
  | 'directorVoiceRefPath'
  | 'directorWritingBaseUrl'
  | 'directorWritingModel'
  | 'directorWritingProvider'
  | 'shortFilmCharacters'
  | 'shortFilmNarrative'
  | 'shortFilmPath'
  | 'shortFilmPreserveVisualStyle'
  | 'shortFilmTargetDuration'
  | 'shortFilmVisualStyle'
> & Pick<DirectorPipelineSlice, 'pipelineId' | 'pipelineStatus' | 'pipelinePolling' | 'directorEditorDetached' | 'startDirectorPipeline'> & Pick<GallerySlice, 'activeWorkspace'> & Pick<LlmSlice, 'llmStatus'> & Pick<LorasSlice, 'loraIdByFilename'> & Pick<ModelOptionsSlice, 'loadModelOptions' | 'modelOptions'> & Pick<ModelsSlice, 'models'> & Pick<ServicesSlice, 'servicesConfig' | 'productionProfile'> & {
  params: GenerateParams
  setParam: <K extends keyof GenerateParams>(key: K, value: GenerateParams[K]) => void
  generationMode: GenerationMode
  selectedModelPerMode: Partial<Record<GenerationMode, string>>
  savedLoraPerMode: Partial<Record<GenerationMode, { activated_loras: string[]; loras_multipliers: string; loraWeights: Record<string, number[]>; availableLoras: string[] }>>
  savedParamsPerMode: Partial<Record<GenerationMode, SavedModeParams>>
  savedPromptPerMode: Partial<Record<string, string>>
  startGeneration: (
    scheduledPrompt?: { prompt: string; position: number; total: number },
    submissionContext?: GenerationSubmissionContext,
  ) => Promise<void | GenerationReceiptLike>
  reconnectJobs: () => Promise<void>
  directorImageSpatialUpsampling: string
  directorImageFilmGrainIntensity: number
  directorImageFilmGrainSaturation: number
  directorVideoSpatialUpsampling: string
  directorVideoFilmGrainIntensity: number
  directorVideoFilmGrainSaturation: number
  directorVideoSelfRefiner: number
}

export const createDirectorMusicVideoSlice: SliceCreator<DirectorMusicVideoSlice, DirectorMusicVideoSliceHost> = (set, get) => ({
  // Director (Music Video Director)
  sidebarMode: 'studio' as const,
  directorSkill: null,
  directorStoryProductionHandoff: null,
  setDirectorSkill: (skill) => {
    set({ directorSkill: skill, ...(skill === 'music_video' ? { directorPacingProfile: 'balanced' as const } : {}) })
    // Music director default for image-to-video reference strength is
    // 0.7 (loosens the lock to the start frame so motion can develop
    // naturally) rather than 1.0 (rigid frame). Only initialize when
    // the param is unset OR still at the global 1.0 default — preserves
    // any value the user has already adjusted in this session.
    //
    // Goes through setParam (not a direct `params` write) so the value
    // propagates into savedParamsPerMode.video — that's what the
    // Director pipeline reads when building video_params for the
    // submission. Without this routing the slider would show 0.7 but
    // the pipeline would still send 1.0.
    if (skill === 'music_video') {
      const current = get().params.input_video_strength
      if (current == null || current === 1.0) {
        get().setParam('input_video_strength', 0.7)
      }
    }
  },
  selectDirectorImageModel: (modelType) => {
    _globalModelSelectionModes.delete('image')
    set(s => ({
      selectedModelPerMode: { ...s.selectedModelPerMode, image: modelType },
    }))
    const s = get()
    _saveSettings({
      generationMode: s.generationMode,
      selectedModelPerMode: s.selectedModelPerMode,
      savedParamsPerMode: s.savedParamsPerMode,
      savedLoraPerMode: s.savedLoraPerMode,
      savedPromptPerMode: s.savedPromptPerMode,
    }, s.loraIdByFilename)
  },

  selectDirectorVideoModel: async (modelType) => {
    _globalModelSelectionModes.delete('video')
    set(s => ({
      selectedModelPerMode: { ...s.selectedModelPerMode, video: modelType },
      ...(s.generationMode === 'video' ? {
        params: { ...s.params, model_type: modelType },
      } : {}),
    }))
    await get().loadModelOptions(modelType)
    if (modelType.startsWith('minimax_h3')) {
      const state = get()
      const request = state.productionProfile.video.model === modelType
        ? state.productionProfile.video.settings
        : { resolution: '540p' as ResolutionPreset, aspectRatio: state.directorAspectRatio }
      const format = resolveSupportedVideoFormat(
        state.modelOptions,
        request.resolution,
        request.aspectRatio,
      )
      set({
        directorResolution: format.resolution,
        directorAspectRatio: format.aspectRatio,
      })
    }
    try {
      const defaults = await api.fetchDefaults(modelType)
      if (get().selectedModelPerMode.video === modelType) {
        const overrides: Record<string, unknown> = {}
        for (const field of _PRIMARY_MODEL_DEFAULT_FIELDS) {
          if (defaults[field] !== undefined) overrides[field] = defaults[field]
        }
        if (Object.keys(overrides).length > 0) {
          set(s => ({
            savedParamsPerMode: {
              ...s.savedParamsPerMode,
              video: { ...(s.savedParamsPerMode.video || {}), ...overrides },
            },
            ...(s.generationMode === 'video' ? {
              params: { ...s.params, ...overrides, model_type: modelType } as GenerateParams,
            } : {}),
          }))
        }
      }
    } catch {
      // Model selection remains usable if the optional defaults request fails.
    }
    const s = get()
    _saveSettings({
      generationMode: s.generationMode,
      selectedModelPerMode: s.selectedModelPerMode,
      savedParamsPerMode: s.savedParamsPerMode,
      savedLoraPerMode: s.savedLoraPerMode,
    }, s.loraIdByFilename)
  },

  setDirectorH3Profile: (profile) => {
    set(s => ({
      savedParamsPerMode: {
        ...s.savedParamsPerMode,
        video: { ...(s.savedParamsPerMode.video || {}), h3_model_profile: profile },
      },
      ...(s.generationMode === 'video' ? {
        params: { ...s.params, h3_model_profile: profile },
      } : {}),
    }))
    const s = get()
    _saveSettings({
      generationMode: s.generationMode,
      selectedModelPerMode: s.selectedModelPerMode,
      savedParamsPerMode: s.savedParamsPerMode,
      savedLoraPerMode: s.savedLoraPerMode,
    }, s.loraIdByFilename)
  },

  setDirectorH3ReferenceMode: (mode) => {
    set(s => ({
      savedParamsPerMode: {
        ...s.savedParamsPerMode,
        video: { ...(s.savedParamsPerMode.video || {}), h3_reference_mode: mode },
      },
      ...(s.generationMode === 'video' ? {
        params: { ...s.params, h3_reference_mode: mode },
      } : {}),
    }))
    const s = get()
    _saveSettings({
      generationMode: s.generationMode,
      selectedModelPerMode: s.selectedModelPerMode,
      savedParamsPerMode: s.savedParamsPerMode,
      savedLoraPerMode: s.savedLoraPerMode,
    }, s.loraIdByFilename)
  },

  directorSetLora: (mode, activated_loras, loras_multipliers, loraWeights, availableLoras) => {
    const s = get()
    const updatedLoraPerMode = {
      ...s.savedLoraPerMode,
      [mode]: { activated_loras, loras_multipliers, loraWeights, availableLoras },
    }
    set({ savedLoraPerMode: updatedLoraPerMode })
    _saveSettings({
      generationMode: s.generationMode,
      selectedModelPerMode: s.selectedModelPerMode,
      savedParamsPerMode: s.savedParamsPerMode,
      savedLoraPerMode: updatedLoraPerMode,
    }, s.loraIdByFilename)
  },

  directorSetSpeakerMapping: (speakerId, name, role) => {
    set(s => ({
      directorSpeakerMappings: s.directorSpeakerMappings.map(m =>
        m.speakerId === speakerId ? { ...m, name, role } : m
      ),
    }))
  },

  directorInsertSpeakerMention: (speakerId) => {
    set(s => ({
      directorSceneDescription: s.directorSceneDescription
        ? `${s.directorSceneDescription} @${speakerId}`
        : `@${speakerId}`,
    }))
  },

  setSidebarMode: (mode) => {
    if (mode === 'director') {
      const { sidebarMode, directorAudioName } = get()
      if (sidebarMode !== 'director') {
        if (!directorAudioName) {
          set({ sidebarMode: 'director', directorStep: 'upload', directorError: null })
        } else {
          set({ sidebarMode: 'director' })
        }
      }
    } else {
      set({ sidebarMode: 'studio' })
    }
  },

  directorConfirmStructure: () => {
    set({ directorStep: 'style', directorLoading: false })
  },

  directorSetReferenceImage: (file) => set({ directorReferenceImage: file }),
  directorAddCharacterRef: (file) => set(s => ({
    directorCharacterRefs: [...s.directorCharacterRefs, file],
    directorCharacterRefLabels: [...s.directorCharacterRefLabels, ''],
  })),
  directorRemoveCharacterRef: (index) => set(s => ({
    directorCharacterRefs: s.directorCharacterRefs.filter((_, i) => i !== index),
    directorCharacterRefPaths: s.directorCharacterRefPaths.filter((_, i) => i !== index),
    directorCharacterRefLabels: s.directorCharacterRefLabels.filter((_, i) => i !== index),
  })),
  directorSetCharacterRefLabel: (index, label) => set(s => {
    const labels = [...s.directorCharacterRefLabels]
    labels[index] = label
    return { directorCharacterRefLabels: labels }
  }),
  directorReorderCharacterRefs: (from, to) => set(s => {
    const refs = [...s.directorCharacterRefs]
    const paths = [...s.directorCharacterRefPaths]
    const labels = [...s.directorCharacterRefLabels]
    const [rF] = refs.splice(from, 1); refs.splice(to, 0, rF)
    const [pF] = paths.splice(from, 1); paths.splice(to, 0, pF)
    const [lF] = labels.splice(from, 1); labels.splice(to, 0, lF)
    return { directorCharacterRefs: refs, directorCharacterRefPaths: paths, directorCharacterRefLabels: labels }
  }),
  directorAddLocationRef: (file) => set(s => ({
    directorLocationRefs: [...s.directorLocationRefs, file],
    directorLocationRefLabels: [...s.directorLocationRefLabels, ''],
  })),
  directorRemoveLocationRef: (index) => set(s => ({
    directorLocationRefs: s.directorLocationRefs.filter((_, i) => i !== index),
    directorLocationRefPaths: s.directorLocationRefPaths.filter((_, i) => i !== index),
    directorLocationRefLabels: s.directorLocationRefLabels.filter((_, i) => i !== index),
  })),
  directorSetLocationRefLabel: (index, label) => set(s => {
    const labels = [...s.directorLocationRefLabels]
    labels[index] = label
    return { directorLocationRefLabels: labels }
  }),
  directorReorderLocationRefs: (from, to) => set(s => {
    const refs = [...s.directorLocationRefs]
    const paths = [...s.directorLocationRefPaths]
    const labels = [...s.directorLocationRefLabels]
    const [rF] = refs.splice(from, 1); refs.splice(to, 0, rF)
    const [pF] = paths.splice(from, 1); paths.splice(to, 0, pF)
    const [lF] = labels.splice(from, 1); labels.splice(to, 0, lF)
    return { directorLocationRefs: refs, directorLocationRefPaths: paths, directorLocationRefLabels: labels }
  }),
  directorAddH3VideoRef: (file) => {
    set(s => s.directorH3VideoRefs.length >= 3 ? {} : ({
      directorH3VideoRefs: [...s.directorH3VideoRefs, file],
      savedParamsPerMode: {
        ...s.savedParamsPerMode,
        video: { ...(s.savedParamsPerMode.video || {}), h3_reference_mode: 'references' },
      },
    }))
  },
  directorRemoveH3VideoRef: (index) => set(s => ({
    directorH3VideoRefs: s.directorH3VideoRefs.filter((_, i) => i !== index),
    directorH3VideoRefPaths: s.directorH3VideoRefPaths.filter((_, i) => i !== index),
  })),
  directorAddH3AudioRef: (file) => {
    set(s => s.directorH3AudioRefs.length >= 3 ? {} : ({
      directorH3AudioRefs: [...s.directorH3AudioRefs, file],
      savedParamsPerMode: {
        ...s.savedParamsPerMode,
        video: { ...(s.savedParamsPerMode.video || {}), h3_reference_mode: 'references' },
      },
    }))
  },
  directorRemoveH3AudioRef: (index) => set(s => ({
    directorH3AudioRefs: s.directorH3AudioRefs.filter((_, i) => i !== index),
    directorH3AudioRefPaths: s.directorH3AudioRefPaths.filter((_, i) => i !== index),
  })),

  directorSetSceneDescription: (prompt) => set({ directorSceneDescription: prompt }),

  // Helper: upload all Director reference images (main + characters + locations)
  _uploadDirectorRefs: async () => {
    const s = get()
    // Upload main reference
    let refImagePath = s.directorReferenceImagePath
    if (s.directorReferenceImage && !refImagePath) {
      const uploaded = await api.uploadImage(s.directorReferenceImage)
      refImagePath = uploaded.path
      set({ directorReferenceImagePath: refImagePath })
    }
    // Upload character refs
    const charPaths = [...s.directorCharacterRefPaths]
    for (let i = charPaths.length; i < s.directorCharacterRefs.length; i++) {
      const uploaded = await api.uploadImage(s.directorCharacterRefs[i])
      charPaths.push(uploaded.path)
    }
    if (charPaths.length > s.directorCharacterRefPaths.length) {
      set({ directorCharacterRefPaths: charPaths })
    }
    // Upload location refs
    const locPaths = [...s.directorLocationRefPaths]
    for (let i = locPaths.length; i < s.directorLocationRefs.length; i++) {
      const uploaded = await api.uploadImage(s.directorLocationRefs[i])
      locPaths.push(uploaded.path)
    }
    if (locPaths.length > s.directorLocationRefPaths.length) {
      set({ directorLocationRefPaths: locPaths })
    }
    return { refImagePath, charPaths, locPaths }
  },

  directorPlanPrompts: async () => {
    const { directorPlannedClips, directorSceneDescription, directorAnalysis } = get()
    if (!directorPlannedClips.length || !directorSceneDescription.trim()) return
    const directVideo = get().directorMusicVideoTreatment.generation_mode === 'direct_video'
    const activity = beginAppActivity(get, {
      kind: 'director_planning',
      title: 'Music Video Director',
      phase: 'uploading_artwork',
      message: 'Preparing visual references…',
      total: 3,
    })
    set({ directorLoading: true, directorError: null, directorPlanRecovery: null, directorStep: 'plan' })
    try {
      // Upload all reference images
      const { refImagePath, charPaths, locPaths } = directVideo
        ? { refImagePath: null, charPaths: [] as string[], locPaths: [] as string[] }
        : await get()._uploadDirectorRefs()
      activity.report('planning', `Planning ${directorPlannedClips.length} shots with the LLM…`, 1, 3)
      const { directorCharacterRefLabels: charLabels, directorLocationRefLabels: locLabels } = get()
      const extraRefs = {
        ...(charPaths.length > 0 ? { character_ref_paths: charPaths, character_ref_labels: charLabels } : {}),
        ...(locPaths.length > 0 ? { location_ref_paths: locPaths, location_ref_labels: locLabels } : {}),
      }

      // Build speaker_mappings from user-assigned names (only those with names filled in)
      const speakerMappings: Record<string, { name: string; role: string }> = {}
      for (const m of get().directorSpeakerMappings) {
        if (m.name.trim()) {
          speakerMappings[m.speakerId] = { name: m.name, role: m.role }
        }
      }

      // Generate both image and video prompts
      // ?? not || — an explicit user-toggled `false` must be respected
      // (legacy v1 path); only fall back to true when servicesConfig
      // hasn't loaded yet or the field is undefined.
      const useV2 = directVideo || (get().servicesConfig?.use_director_v2 ?? true)
      let plans: Array<{ video_prompt: string; image_prompt: string }>

      if (useV2) {
        // Director v2: structured planning → rendering → validation
        let keepPollingPlan = true
        const progressPoll = (async () => {
          while (keepPollingPlan) {
            try {
              const progress = await api.getDirectorV2PlanProgress(activity.id)
              if (progress) {
                const streamPreview = llmActivityPreview(progress.stream_text)
                const detail = (
                  progress.phase === 'writing_scenes' && streamPreview
                    ? streamPreview
                    : progress.detail || streamPreview || 'The LLM is preparing the next visual prompt…'
                ).trim()
                activity.report(
                  progress.phase || 'planning',
                  `Planning ${directorPlannedClips.length} shots with the LLM…`,
                  1,
                  3,
                  {
                    detailMessage: detail,
                    detailVolatile: Boolean(streamPreview),
                    detailCurrent: progress.current || 0,
                    detailTotal: progress.total || directorPlannedClips.length,
                    tokenUsage: progress.usage ? {
                      promptTokens: progress.usage.prompt_tokens || 0,
                      completionTokens: progress.usage.completion_tokens || 0,
                      totalTokens: progress.usage.total_tokens || 0,
                      calls: progress.usage.calls || 0,
                    } : undefined,
                  },
                )
              }
            } catch { /* Progress is informative; the main planning request owns errors. */ }
            await new Promise(resolve => window.setTimeout(resolve, 800))
          }
        })()
        let result: DirectorV2PlanResponse
        try {
          result = await api.directorV2Plan({
            activity_id: activity.id,
            workspace: get().activeWorkspace,
            skill_type: 'music_video',
            clips: directorPlannedClips,
            scene_description: directorSceneDescription,
            lyrics: directorAnalysis?.lyrics ?? undefined,
            bpm: directorAnalysis?.bpm ?? 120,
            reference_image_path: refImagePath ?? undefined,
            ...extraRefs,
            speaker_mappings: Object.keys(speakerMappings).length > 0 ? speakerMappings : undefined,
            image_model: get().selectedModelPerMode.image || undefined,
            video_model: get().selectedModelPerMode.video || undefined,
            h3_reference_mode: get().savedParamsPerMode.video?.h3_reference_mode as 'first_frame' | 'references' | undefined,
            h3_audio_prompt: get().savedParamsPerMode.video?.h3_audio_prompt as string | undefined,
            music_video_treatment: get().directorMusicVideoTreatment,
            prompt_type: 'both',
          })
        } finally {
          keepPollingPlan = false
          await progressPoll
        }
        plans = result.clip_plans.map(p => ({
          video_prompt: p.video_prompt || '',
          image_prompt: p.image_prompt || '',
        }))
      } else {
        // Legacy: direct LLM prompt generation
        const result = await api.planClipPromptsAndImages({
          clips: directorPlannedClips,
          scene_description: directorSceneDescription,
          lyrics: directorAnalysis?.lyrics ?? undefined,
          bpm: directorAnalysis?.bpm ?? 120,
          reference_image_path: refImagePath,
          ...extraRefs,
          speaker_mappings: Object.keys(speakerMappings).length > 0 ? speakerMappings : undefined,
          prompt_type: 'both',
          music_video_treatment: get().directorMusicVideoTreatment,
          video_model: get().selectedModelPerMode.video || undefined,
          h3_reference_mode: get().savedParamsPerMode.video?.h3_reference_mode as 'first_frame' | 'references' | undefined,
          h3_audio_prompt: get().savedParamsPerMode.video?.h3_audio_prompt as string | undefined,
        })
        plans = result.clip_plans.map(p => ({
          video_prompt: p.video_prompt || '',
          image_prompt: p.image_prompt || '',
        }))
      }
      set({
        directorClipPlans: plans,
        directorStep: directVideo ? 'review_video' : 'review',
        directorLoading: false,
        directorPlanRecovery: null,
      })
      activity.finish(`${plans.length} visual shot plans ready for review`)

      // Auto-mode: skip review, proceed to image gen. directorGenerateStartImages
      // now generates an establishing/anchor image first when no reference was
      // provided, so every clip shares a consistent look (instead of skipping
      // images entirely as it used to).
      if (get().directorAutoMode) {
        if (directVideo) get().directorGenerate()
        else get().directorGenerateStartImages()
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Planning failed'
      console.error('Director planning failed:', e)
      set({
        directorLoading: false,
        directorError: msg,
        directorPlanRecovery: e instanceof api.DirectorV2PlanError ? e.job : null,
        directorStep: 'style',
      })
      activity.fail(e, 'planning')
    }
  },

  directorResumePlan: async () => {
    const recovery = get().directorPlanRecovery
    if (!recovery || recovery.status === 'completed') return
    if (recovery.workspace !== get().activeWorkspace) {
      set({ directorError: `This plan belongs to workspace “${recovery.workspace}”. Switch back to resume it.` })
      return
    }
    const activity = beginAppActivity(get, {
      kind: 'director_planning',
      title: 'Music Video Director',
      phase: 'resuming',
      message: `Resuming ${recovery.missingIndices.length} missing clip plans…`,
      total: recovery.total,
    })
    set({ directorLoading: true, directorError: null, directorStep: 'plan' })
    try {
      const result = await api.resumeDirectorV2PlanJob(
        recovery.jobId,
        recovery.workspace,
        activity.id,
      )
      const plans = result.clip_plans.map(plan => ({
        video_prompt: plan.video_prompt || '',
        image_prompt: plan.image_prompt || '',
      }))
      const directVideo = get().directorMusicVideoTreatment.generation_mode === 'direct_video'
      set({
        directorClipPlans: plans,
        directorStep: directVideo ? 'review_video' : 'review',
        directorLoading: false,
        directorPlanRecovery: null,
      })
      activity.finish(`${plans.length} visual shot plans ready for review`)

      // Rendering is intentionally gated behind a complete resumed response.
      // A failed/partial response never reaches either generation action.
      if (get().directorAutoMode) {
        if (directVideo) get().directorGenerate()
        else get().directorGenerateStartImages()
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Planning resume failed'
      console.error('Director planning resume failed:', e)
      set({
        directorLoading: false,
        directorError: msg,
        directorPlanRecovery: e instanceof api.DirectorV2PlanError ? e.job : recovery,
        directorStep: 'style',
      })
      activity.fail(e, 'resuming')
    }
  },

  directorPlanVideoPrompts: async () => {
    if (get().directorMusicVideoTreatment.generation_mode === 'direct_video') {
      await get().directorPlanPrompts()
      return
    }
    const { directorPlannedClips, directorSceneDescription, directorAnalysis, directorClipPlans, directorReferenceImagePath } = get()
    if (!directorPlannedClips.length || !directorClipPlans.length) return
    const activity = beginAppActivity(get, {
      kind: 'director_video_prompts',
      title: 'Music Video Director',
      phase: 'planning',
      message: `Planning motion for ${directorPlannedClips.length} clips…`,
      total: directorPlannedClips.length,
    })
    set({ directorLoading: true, directorError: null, directorStep: 'plan_video' })
    try {
      // Build speaker_mappings
      const speakerMappings: Record<string, { name: string; role: string }> = {}
      for (const m of get().directorSpeakerMappings) {
        if (m.name.trim()) {
          speakerMappings[m.speakerId] = { name: m.name, role: m.role }
        }
      }

      // Phase 2: generate video prompts, passing existing image prompts as context
      const existingImagePrompts = directorClipPlans.map(p => p.image_prompt || '')
      const { directorCharacterRefPaths: crp, directorLocationRefPaths: lrp } = get()
      const result = await api.planClipPromptsAndImages({
        clips: directorPlannedClips,
        scene_description: directorSceneDescription,
        lyrics: directorAnalysis?.lyrics ?? undefined,
        bpm: directorAnalysis?.bpm ?? 120,
        reference_image_path: directorReferenceImagePath,
        ...(crp.length > 0 ? { character_ref_paths: crp } : {}),
        ...(lrp.length > 0 ? { location_ref_paths: lrp } : {}),
        speaker_mappings: Object.keys(speakerMappings).length > 0 ? speakerMappings : undefined,
        prompt_type: 'video',
        existing_image_prompts: existingImagePrompts,
        music_video_treatment: get().directorMusicVideoTreatment,
        video_model: get().selectedModelPerMode.video || undefined,
        h3_reference_mode: get().savedParamsPerMode.video?.h3_reference_mode as 'first_frame' | 'references' | undefined,
        h3_audio_prompt: get().savedParamsPerMode.video?.h3_audio_prompt as string | undefined,
      })
      // Merge video prompts into existing clip plans
      const updatedPlans = directorClipPlans.map((plan, i) => ({
        ...plan,
        video_prompt: result.clip_plans[i]?.video_prompt || '',
      }))
      set({
        directorClipPlans: updatedPlans,
        directorStep: 'review_video',
        directorLoading: false,
      })
      activity.finish(`${updatedPlans.length} video prompts ready`)

      // Auto-mode: skip review, apply to editor and start generation
      if (get().directorAutoMode) {
        get().directorGenerate()
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Video prompt planning failed'
      console.error('Director video planning failed:', e)
      set({ directorLoading: false, directorError: msg, directorStep: 'generate_images' })
      activity.fail(e, 'planning')
    }
  },

  directorEditClipPlan: (index, field, value) => {
    set(s => {
      const plans = [...s.directorClipPlans]
      if (plans[index]) {
        plans[index] = { ...plans[index], [field]: value }
      }
      return { directorClipPlans: plans }
    })
  },

  directorGenerateStartImages: async () => {
    if (get().directorMusicVideoTreatment.generation_mode === 'direct_video') {
      set({
        directorClipImages: [],
        directorImageGenProgress: null,
        directorStep: 'review_video',
        directorLoading: false,
      })
      if (get().directorAutoMode) get().directorGenerate()
      return
    }
    const { directorClipPlans, directorPlannedClips, params, selectedModelPerMode, savedParamsPerMode, savedLoraPerMode, directorResolution, directorAspectRatio, directorSceneDescription } = get()
    if (!directorClipPlans.length) return
    const needsAnchor = !get().directorReferenceImage && !get().directorReferenceImagePath
    const activityTotal = directorClipPlans.length + (needsAnchor ? 1 : 0)
    const imageModel = selectedModelPerMode.image || 'flux2_klein_9b'
    const activity = beginAppActivity(get, {
      kind: 'director_images',
      title: 'Music Video Director',
      phase: 'generating_images',
      message: `Preparing ${activityTotal} start images…`,
      total: activityTotal,
      generationDetails: {
        model_type: imageModel,
        model_name: get().models.find(model => model.model_type === imageModel)?.name || imageModel,
        generation_mode: 'image',
        repeat: activityTotal,
      },
    })

    // Use saved image-mode settings if available, otherwise fall back to defaults
    const imageOptions = await api.fetchModelOptions(imageModel).catch(() => null)
    const directorRes = resolveResolution(
      imageOptions,
      directorResolution,
      directorAspectRatio,
    )
    // Director's hardcoded image_model fallback is flux2_klein_9b, which is
    // step-distilled to 4 inference steps (per app/defaults/flux2_klein_9b.json).
    const imageParams = savedParamsPerMode.image || { num_inference_steps: 4, guidance_scale: 1, resolution: directorRes }
    imageParams.resolution = directorRes
    const imageLora = savedLoraPerMode.image
    activity.report(
      'generating_images',
      `Preparing ${activityTotal} start images…`,
      0,
      activityTotal,
      {
        generationDetails: {
          model_type: imageModel,
          model_name: get().models.find(model => model.model_type === imageModel)?.name || imageModel,
          generation_mode: 'image',
          resolution: String(imageParams.resolution || directorRes),
          steps: Number(imageParams.num_inference_steps || 0) || undefined,
          guidance: Number(imageParams.guidance_scale || 0) || undefined,
          repeat: activityTotal,
        },
      },
    )

    const buildImgPostProc = (): Record<string, unknown> => {
      const pp: Record<string, unknown> = {}
      const imgSpatial = get().directorImageSpatialUpsampling
      if (imgSpatial) pp.spatial_upsampling = imgSpatial
      const imgGrainIntensity = get().directorImageFilmGrainIntensity
      if (imgGrainIntensity > 0) {
        pp.film_grain_intensity = imgGrainIntensity
        pp.film_grain_saturation = get().directorImageFilmGrainSaturation
      }
      return pp
    }

    // Submit one image generation, poll to completion, download the result as a File.
    const genImage = async (prompt: string, refs: string[], label: string): Promise<{ file: File; filename: string }> => {
      const genParams = {
        model_type: imageModel,
        prompt,
        image_refs: refs,
        image_mode: 1,
        num_inference_steps: imageParams.num_inference_steps,
        guidance_scale: imageParams.guidance_scale,
        // 'KI' carries an image reference; plain T2I (the anchor) needs no ref flag.
        video_prompt_type: refs.length ? 'KI' : '',
        resolution: imageParams.resolution,
        seed: -1,
        settings_version: 2.52,
        generation_mode: 'image',
        workspace: get().activeWorkspace,
        repeat_generation: 1,
        negative_prompt: '',
        video_length: 1,
        activated_loras: imageLora?.activated_loras || params.activated_loras || [],
        loras_multipliers: imageLora?.loras_multipliers || params.loras_multipliers || '',
        ...buildImgPostProc(),
      }
      const { job_id } = await api.submitGeneration(genParams)
      void get().reconnectJobs()
      let outputFiles: string[] = []
      let attempts = 0
      const maxAttempts = 300  // 300 × 2s = 10 minutes
      while (attempts < maxAttempts) {
        await new Promise(r => setTimeout(r, 2000))
        const status = await api.fetchJobStatus(job_id)
        activity.report(
          'generating_images',
          `${label} · ${status.message || `${Math.round(status.progress)}%`}`,
          Math.min(activityTotal, get().directorClipImages.length),
          activityTotal,
        )
        if (status.status === 'completed') { outputFiles = status.output_files; break }
        if (status.status === 'failed') throw new Error(status.error || `${label} generation failed`)
        attempts++
      }
      if (attempts >= maxAttempts) throw new Error(`${label} generation timed out`)
      if (outputFiles.length === 0) throw new Error(`No output file for ${label}`)
      const filename = outputFiles[0]
      const imgRes = await fetch(api.getFileUrl(filename))
      const blob = await imgRes.blob()
      const file = new File([blob], filename, { type: blob.type || 'image/png' })
      return { file, filename }
    }

    // Auto-unload LLM before GPU-heavy image generation to free VRAM
    if (get().llmStatus?.loaded) {
      try {
        await api.unloadLlm()
        set({ llmStatus: UNLOADED_LLM_STATUS })
      } catch { /* best-effort */ }
    }

    set({ directorStep: 'generate_images', directorLoading: true, directorError: null, directorClipImages: [], directorImageGenProgress: null })

    try {
      // If no reference image was provided, generate a single establishing /
      // "anchor" image from the scene description and adopt it as the reference, so every
      // clip's start image shares a consistent look (Settings › Services › Director shared reference).
      let anchorMade = false
      if (!get().directorReferenceImage && !get().directorReferenceImagePath && get().servicesConfig?.director_reference_anchor !== 'off' && !(get().servicesConfig?.director_reference_anchor === 'no_cast_refs' && (get().directorCharacterRefs.length || get().directorCharacterRefPaths.length))) {
        anchorMade = true
        set({
          directorImageGenProgress: {
            current: 0,
            total: directorClipPlans.length + 1,
            currentClipLabel: 'Establishing image…',
            status: 'generating',
          },
        })
        const anchorPrompt = directorSceneDescription.trim() || directorClipPlans[0]?.image_prompt || 'establishing shot'
        activity.report('generating_images', 'Generating the shared establishing image…', 0, activityTotal)
        const { file: anchorFile } = await genImage(anchorPrompt, [], 'Establishing image')
        // Adopt as the reference image (uploaded just below via _uploadDirectorRefs).
        set({ directorReferenceImage: anchorFile, directorReferenceImagePath: null })
      }

      // Upload all reference images (main/anchor + character + location)
      const { refImagePath: refPath, charPaths, locPaths } = await get()._uploadDirectorRefs()
      const allRefs = [refPath, ...charPaths, ...locPaths].filter(Boolean) as string[]

      const total = directorClipPlans.length + (anchorMade ? 1 : 0)
      const base = anchorMade ? 1 : 0
      const generatedImages: DirectorClipImage[] = []

      // Generate one start image per clip sequentially.
      for (let i = 0; i < directorClipPlans.length; i++) {
        const clip = directorPlannedClips[i]
        const plan = directorClipPlans[i]
        const clipLabel = `Clip ${i + 1} (${clip?.section_label || 'verse'})`
        set({
          directorImageGenProgress: { current: base + i, total, currentClipLabel: clipLabel, status: 'generating' },
        })
        activity.report('generating_images', `Generating ${clipLabel}…`, base + i, total)
        const { file, filename } = await genImage(plan.image_prompt, allRefs, clipLabel)
        generatedImages.push({ clipIndex: i, prompt: plan.image_prompt, file, filename })
        set({ directorClipImages: [...generatedImages] })
      }

      set({
        directorImageGenProgress: { current: total, total, currentClipLabel: '', status: 'done' },
        directorLoading: false,
      })
      activity.finish(`${total} start images ready`)

      // Video prompts already generated in the combined LLM pass — go straight to review
      const hasVideoPrompts = get().directorClipPlans.some(p => p.video_prompt)
      if (hasVideoPrompts) {
        set({ directorStep: 'review_video' })
        if (get().directorAutoMode) {
          get().directorGenerate()
        }
      } else {
        // Fallback: if video prompts are missing, plan them separately
        get().directorPlanVideoPrompts()
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Image generation failed'
      console.error('Director image generation failed:', e)
      set({
        directorLoading: false,
        directorError: msg,
        directorImageGenProgress: get().directorImageGenProgress
          ? { ...get().directorImageGenProgress!, status: 'error' }
          : null,
      })
      activity.fail(e, 'generating_images')
    }
  },

  directorApplyToClips: () => {
    const { directorClipPlans, directorPlannedClips, directorAnalysis, directorClipImages,
            directorAudioPath, directorAudioName, directorSeamless,
            selectedModelPerMode, savedParamsPerMode, savedLoraPerMode } = get()
    if (!directorClipPlans.length) return
    const directVideo = get().directorMusicVideoTreatment.generation_mode === 'direct_video'

    // Use saved video-mode settings if available
    const videoModel = selectedModelPerMode.video || 'ltx2_22B_distilled_1_1'
    const videoParams = savedParamsPerMode.video
      ? { ...savedParamsPerMode.video }
      : {}
    const directorSteps = get().directorVideoInferenceStepsByModel[videoModel]
    if (directorSteps != null) videoParams.num_inference_steps = directorSteps
    const videoLora = savedLoraPerMode.video

    const fps = get().modelOptions?.fps ?? 16
    const totalDuration = directorAnalysis?.duration ?? 180
    const totalDurationCapped = Math.min(totalDuration, 300)

    // Build clips with per-clip durations and images
    const clips: MultiClip[] = directorClipPlans.map((plan, i) => {
      const plannedClip = directorPlannedClips[i]
      const clipImage = directVideo ? undefined : directorClipImages.find(img => img.clipIndex === i)

      // Seamless mode: use next clip's start image as this clip's end image
      let endImage: File | null = null
      if (!directVideo && directorSeamless && i < directorClipPlans.length - 1) {
        const nextClipImage = directorClipImages.find(img => img.clipIndex === i + 1)
        endImage = nextClipImage?.file ?? null
      }

      return {
        prompt: plan.video_prompt,
        startImage: clipImage?.file ?? null,
        startImagePath: null,
        endImage,
        endImagePath: null,
        durationFrames: plannedClip?.duration_frames,
        keyframes: [],
      }
    })

    // Build per-clip frame counts for variable-duration support
    const perClipFrames = clips.map(c => c.durationFrames ?? Math.round(5 * fps))
    const totalFrames = perClipFrames.reduce((sum, f) => sum + f, 0)
    const maxClipFrames = Math.max(...perClipFrames)

    // Auto-set soundtrack mode with the already-uploaded audio
    const audioParams: Record<string, unknown> = {}
    if (directorAudioPath) {
      audioParams.audio_prompt_type = 'A'
      audioParams.audio_guide = directorAudioPath
    }

    set(s => ({
      params: {
        ...s.params,
        ...(videoModel ? { model_type: videoModel } : {}),
        ...(videoParams || {}),
        ...(videoLora ? { activated_loras: videoLora.activated_loras, loras_multipliers: (videoLora.loras_multipliers || '').split(' ').map(m => m.split(';')[0]).join(' ') } : {}),
        image_mode: 2,
        video_length: totalFrames,
        sliding_window_size: maxClipFrames,
        per_clip_frames: perClipFrames,
        ...audioParams,
      },
      clips,
      singlePromptMode: false,
      durationSeconds: totalDurationCapped,
      slidingWindowSeconds: maxClipFrames / fps,
      audioGuideFilename: directorAudioName,
      sidebarMode: 'studio' as const,
      // startGeneration reads generationMode, not Director intent. Leave Edit
      // or Mixer in place and Generate becomes a retake, a silent no-op, or
      // "audio is not generative" after the clips were staged.
      generationMode: 'video' as const,
    }))
  },

  directorGenerate: () => {
    const { directorClipPlans, directorPlannedClips, directorAnalysis,
            directorClipImages, directorAudioPath, directorAudioName,
            directorSeamless, directorResolution, directorAspectRatio,
            selectedModelPerMode, savedParamsPerMode, savedLoraPerMode } = get()
    if (!directorClipPlans.length) return
    const directVideo = get().directorMusicVideoTreatment.generation_mode === 'direct_video'
    if (directVideo) {
      // H3's generic Studio endpoint treats a multi-shot request as one H3
      // generation.  Keep reviewed direct prompts in Director's sequential,
      // resumable server pipeline and do not ask the LLM to plan them again.
      void get().startDirectorPipeline(true)
      return
    }

    // Use saved video-mode settings if available, override resolution with director's choice
    const videoModel = selectedModelPerMode.video || 'ltx2_22B_distilled_1_1'
    const cachedDirectorVideoOptions = get().modelOptions?.model_type === videoModel
      ? get().modelOptions
      : null
    const directorRes = resolveResolution(
      cachedDirectorVideoOptions,
      directorResolution,
      directorAspectRatio,
    )
    const videoParams = savedParamsPerMode.video ? { ...savedParamsPerMode.video, resolution: directorRes } : { num_inference_steps: 8, guidance_scale: 1, resolution: directorRes }
    const directorSteps = get().directorVideoInferenceStepsByModel[videoModel]
    if (directorSteps != null) videoParams.num_inference_steps = directorSteps
    const videoLora = savedLoraPerMode.video

    const fps = get().modelOptions?.fps ?? 16
    const totalDuration = directorAnalysis?.duration ?? 180
    const totalDurationCapped = Math.min(totalDuration, 300)

    const clips: MultiClip[] = directorClipPlans.map((plan, i) => {
      const plannedClip = directorPlannedClips[i]
      const clipImage = directVideo ? undefined : directorClipImages.find(img => img.clipIndex === i)

      // Seamless mode: use next clip's start image as this clip's end image
      let endImage: File | null = null
      if (!directVideo && directorSeamless && i < directorClipPlans.length - 1) {
        const nextClipImage = directorClipImages.find(img => img.clipIndex === i + 1)
        endImage = nextClipImage?.file ?? null
      }

      return {
        prompt: plan.video_prompt,
        startImage: clipImage?.file ?? null,
        startImagePath: null,
        endImage,
        endImagePath: null,
        durationFrames: plannedClip?.duration_frames,
        keyframes: [],
      }
    })

    const perClipFrames = clips.map(c => c.durationFrames ?? Math.round(5 * fps))
    const totalFrames = perClipFrames.reduce((sum, f) => sum + f, 0)
    const maxClipFrames = Math.max(...perClipFrames)

    const audioParams: Record<string, unknown> = {}
    if (get().shortFilmPath === 'story') {
      // Path C: LTX generates video + audio from text (dialogue in quotes)
      audioParams.audio_prompt_type = ''
    } else if (directorAudioPath) {
      audioParams.audio_prompt_type = 'A'
      audioParams.audio_guide = directorAudioPath
    }

    // Apply director video post-processing to shared state (read by startGeneration)
    const vidSelfRefiner = get().directorVideoSelfRefiner

    set(s => ({
      params: {
        ...s.params,
        ...(videoModel ? { model_type: videoModel } : {}),
        ...(videoParams || {}),
        ...(videoLora ? { activated_loras: videoLora.activated_loras, loras_multipliers: (videoLora.loras_multipliers || '').split(' ').map(m => m.split(';')[0]).join(' ') } : {}),
        image_mode: 2,
        video_length: totalFrames,
        sliding_window_size: maxClipFrames,
        per_clip_frames: perClipFrames,
        self_refiner_setting: vidSelfRefiner,
        ...audioParams,
      },
      clips,
      singlePromptMode: false,
      durationSeconds: totalDurationCapped,
      slidingWindowSeconds: maxClipFrames / fps,
      audioGuideFilename: directorAudioName,
      // Apply director video post-processing to shared state
      spatialUpsampling: get().directorVideoSpatialUpsampling,
      filmGrainIntensity: get().directorVideoFilmGrainIntensity,
      filmGrainSaturation: get().directorVideoFilmGrainSaturation,
      // startGeneration branches on generationMode (image, audio, Edit)
      // before it reads these clips; a previous Edit mode must not win.
      generationMode: 'video' as const,
    }))

    setTimeout(() => get().startGeneration(), 200)
  },

  directorReset: () => {
    set({
      sidebarMode: 'studio' as const,
      directorStep: 'upload',
      directorAudioName: null,
      directorAudioPath: null,
      directorAnalysis: null,
      directorPlannedClips: [],
      directorEnergyBias: 0,
      directorPacingProfile: 'balanced',
      directorMusicVideoTreatment: {
        generation_mode: 'image_guided',
        direct_video_master_prompt: DEFAULT_DIRECT_VIDEO_MASTER_PROMPT,
        mode: 'hybrid',
        performer_presence: 60,
        lip_sync: 'frequent',
        recurring_sets: ['Main performance set', 'Story world', 'Bridge contrast set'],
        wardrobe: '',
        palette: '',
        camera_language: 'Controlled cinematic movement; intimate verses and bold chorus coverage',
        recurring_motif: '',
        chorus_signature: 'Return to the main performance set with direct-to-camera delivery and the boldest lighting',
        surrealism: 35,
        forbidden_elements: '',
      },
      directorClipPlans: [],
      directorSceneDescription: '',
      directorLoading: false,
      directorError: null,
      directorPlanRecovery: null,
      directorReferenceImage: null,
      directorReferenceImagePath: null,
      directorCharacterRefs: [],
      directorCharacterRefPaths: [],
      directorCharacterRefLabels: [],
      directorLocationRefs: [],
      directorLocationRefPaths: [],
      directorLocationRefLabels: [],
      directorH3VideoRefs: [],
      directorH3VideoRefPaths: [],
      directorH3AudioRefs: [],
      directorH3AudioRefPaths: [],
      directorVoiceRef: null,
      directorVoiceRefPath: null,
      directorClipImages: [],
      directorImageGenProgress: null,
      directorSpeakers: [],
      directorSpeakerMappings: [],
      directorAutoMode: true,
      directorSeamless: false,
      directorShotImageGuidance: 'auto' as DirectorShotImageGuidance,
      directorLlmLog: [],
      directorSkill: null,
      directorStoryProductionHandoff: null,
      directorMusicSource: null,
      directorSongDescription: '',
      directorSongInstrumental: false,
      directorSongStyle: '',
      directorSongLyrics: '',
      directorSongDuration: 120,
      directorTrackGenerating: false,
      shortFilmCharacters: [],
      shortFilmPath: null,
      shortFilmTargetDuration: 30,
      directorWritingProvider: 'maestro',
      directorWritingModel: '',
      directorWritingBaseUrl: '',
      shortFilmNarrative: false,
      shortFilmVisualStyle: '',
      shortFilmPreserveVisualStyle: true,
      directorCharacterVisualStyle: '',
      directorAllowClipText: false,
      directorSpokenLanguage: contentLanguageForUi().spokenLanguage,
      // Detach this editor session from any prior recoverable pipeline. The
      // backend job is intentionally not cancelled and remains in Dashboard,
      // but its poller and the boot reconnect timer must not overwrite the
      // next story loaded into Director.
      pipelineId: null,
      pipelineStatus: null,
      pipelinePolling: false,
      directorEditorDetached: true,
    })
  },
})
