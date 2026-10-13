import { concreteImageResolution } from '../lib/imageResolution'
import { IMAGE_INTENT_PARAMS, emptyImageStudioDraft, imageStudioDraft } from '../features/studio/imageStudioIntent'
import { imageSettingsMode, restoreStudioImageSettings } from '../features/studio/imageSettingsRestore'
import { restoreWan1300AudioRecipe, wan1300AudioSelection } from '../lib/wan1300Audio'
import {
  h3WindowMaximumFrames,
  requestedVideoFrames,
  restoredH3ExtendedDuration,
} from '../lib/h3ExtendedDuration'
import { h3ModelSwitchSettings, projectStudioH3RequestParams, restoreSemanticBridgeSettings } from '../lib/h3OptionalSettings'
import { restoredEditingTrim, restoreWangpSettings, viggleSubmissionOptions } from '../lib/wangpUi'
import { viggleEditingParameters } from '../lib/viggleWorkflow'
import { beginWangpRestore, legacyEditingPath, restoredGenericImageRefs } from '../lib/wangpRestore'
import { create, type StoreApi } from 'zustand'
import type { GenerateParams, AspectRatio, ResolutionPreset, GenerationDetails, GenerationJob, ModelDef, GenerationMode, MultiClip, AudioAnalysisResult, DirectorClipImage, SpeakerMapping, DirectorSkill, DirectorShotImageGuidance, RecastCharacterMapping, RepaintRegionMapping, H3WindowPlan, DirectorV2PlanResponse } from '../types'
import { DEFAULT_DIRECT_VIDEO_MASTER_PROMPT } from '../types'
import * as api from '../api/client'
import i18n from '../i18n'
import { contentLanguageForUi } from '../lib/contentLanguage'
import { splitPromptSchedule } from '../lib/promptScheduler'
import { resolveSupportedVideoFormat } from '../lib/productionProfile'
import { defaultSpeechModel } from '../lib/preferredModels'
import { isGenerationJobActive, isGenerationJobInterrupted, isGenerationJobSettled } from '../lib/generationJobState'
import { isHttpStatus } from '../api/http'
import { mapDirectorClipImages } from '../lib/directorClipImages'
import { llmActivityPreview } from '../lib/llmActivityPreview'
import { createDeveloperModeSlice, type DeveloperModeSlice } from './developerModeSlice'
import { createDirectorSlice, type DirectorSlice } from './directorSlice'
import { createDirectorDashboardSlice, disposeDirectorRepairPolls, type DirectorDashboardSlice } from '../features/director/store/directorDashboardSlice'
import { createShortFilmSlice, type ShortFilmSlice } from '../features/director/store/shortFilmSlice'
import { createDirectorPipelineSlice, type DirectorPipelineSlice } from '../features/director/store/directorPipelineSlice'
import { createStudioEditSlice, DEFAULT_RECAST_MAPPING, type StudioEditSlice, type VideoSubModeStash } from '../features/studio/store/studioEditSlice'
import { createRetakeDialogSlice, type RetakeDialogSlice } from './retakeDialogSlice'
import { createSettingsSlice, type SettingsSlice } from './settingsSlice'
import { createSidebarSlice, type SidebarSlice } from './sidebarSlice'
import { createSystemSlice, type SystemSlice } from './systemSlice'
import { _downloadTimestampMs, createCivitaiSlice, disposeCivitaiDownloadPoll, type CivitaiSlice } from './civitaiSlice'
import { createPresetsSlice, type PresetsSlice } from '../features/studio/store/presetsSlice'
import { _jobTimingPatch, createToolsSlice, type ToolsSlice } from '../features/studio/store/toolsSlice'
import { createRecipesSlice, type RecipesSlice } from './recipesSlice'
import {
  _applyModelDefaults,
  _PRIMARY_MODEL_DEFAULT_FIELDS,
  advanceModelOptionsSeq,
  alignFrameCount,
  createModelOptionsSlice,
  invalidateModelOptionsLoad,
  type ModelOptionsSlice,
} from './modelOptionsSlice'
export { alignFrameCount, invalidateModelOptionsLoad }
import { _globalModelSelectionModes, createServicesSlice, type ServicesSlice } from './servicesSlice'
import { createLorasSlice, type LorasSlice } from './lorasSlice'
import { createModelsSlice, getDefaultModelForMode, type ModelsSlice } from './modelsSlice'
import {
  _saveSettings,
  restoreModeParams,
  snapshotModeParams,
  type SavedModeParams,
} from './modeSettingsPersistence'
import {
  beginAppActivity,
  createActivitySlice,
  type ActivitySlice,
  type ForegroundActivity,
} from '../features/activity/store'
export type { ForegroundActivity }
import { bindSlice } from './storeApi'
import { createThemeSlice, type ThemeSlice } from './themeSlice'
import { createGallerySlice, type GallerySlice } from './gallerySlice'
import { createLlmSlice, UNLOADED_LLM_STATUS, type LlmSlice } from './llmSlice'
import { createStudioConfigurationSlice, type StudioConfigurationSlice } from './studioConfigurationSlice'
import {
  createStudioMusicSlice,
  restoredStudioMusicForm,
  type StudioMusicSlice,
} from './studioMusicSlice'
import {
  getDisplayFamily,
  getFamiliesForMode,
  getFamilyMode,
  getModelMode,
  getModelsForFamily,
  isMusicModelType,
  sfxModelTypes,
} from './modelCatalog'
export {
  getDisplayFamily,
  getFamiliesForMode,
  getFamilyMode,
  getModelMode,
  getModelsForFamily,
}
import { findResolutionSelection, resolveResolution } from './resolution'
export { findResolutionSelection, resolveResolution }
import { applyStudioAudioSubmitParams } from './studioAudioSubmit'
import { markJobsCancelling, prependJob, removeJob, updateJob, withJobs } from './jobReducers'
import {
  extractSingleClipStudioParams,
  isJoinedSequenceOutput,
  restoredSfxSettings,
  splitStudioClipPrompts,
} from '../features/studio/studioRestore'
import {
  generationProvenancePayload,
  type GenerationSubmissionContext,
} from '../features/studio/generationProvenance'
import type { GenerationReceiptLike } from '../api/generationCommandClient'
import { prepareStudioSubmission, studioUploadReference } from '../features/studio/studioSubmission'
import {
  startStudioImageGenerationFromStore,
  type StudioImageStoreHost,
} from '../features/studio/startGeneration'
import { submitBlendEdit } from '../features/studio/blendSubmission'
import { submitOutpaintEdit } from '../features/studio/outpaintSubmission'
import { audioReferenceParams, restoreAudioReferences, stashAudioReferences, type AudioReferenceStash } from '../features/studio/audioReferenceState'
import { beginOutputSettingsRestore, type OutputSettingsSource } from '../features/studio/outputSettingsRestore'

type OutpaintAspect = 'source' | '16:9' | '9:16' | '1:1' | '4:3' | '3:4'

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

const RECONNECT_POLL_MS = 2000
// Consecutive failed polls before the tile says the connection is lost.
const RECONNECT_OFFLINE_AFTER = 3
const RECONNECT_OFFLINE_MESSAGE = 'Connection lost — retrying…'

function _jobStatusPatch(job: GenerationJob, status: api.ApiJobStatus): GenerationJob {
  return {
    ...job,
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
    h3WindowPlan: status.h3_window_plan ?? job.h3WindowPlan ?? null,
    ..._jobTimingPatch(status),
  }
}

/** Follow a job restored on page load. A backend restart or a proxy 502
 *  keeps the tile and retries with backoff; only a 404 means the job is gone. */
function _pollReconnectedJob(
  jobId: string,
  set: StoreApi<AppState>['setState'],
  get: StoreApi<AppState>['getState'],
): void {
  let failures = 0
  const patchJob = (update: (job: GenerationJob) => GenerationJob) =>
    set(s => ({ jobs: s.jobs.map(j => j.id === jobId ? update(j) : j) }))
  const tick = async () => {
    if (!get().jobs.some(j => j.id === jobId)) return
    try {
      const status = await api.fetchJobStatus(jobId)
      failures = 0
      patchJob(j => _jobStatusPatch(j, status))
      if (isGenerationJobInterrupted(status.status)) {
        set(s => withJobs(s.jobs))
        return
      }
      if (status.status === 'completed' || status.status === 'failed' || status.status === 'cancelled') {
        set(s => removeJob(s.jobs, j => j.id === jobId))
        void get().maybeRefreshGallery({ message: 'New output ready' })
        return
      }
    } catch (reason) {
      if (isHttpStatus(reason, 404)) {
        set(s => removeJob(s.jobs, j => j.id === jobId))
        return
      }
      failures += 1
      if (failures >= RECONNECT_OFFLINE_AFTER) {
        patchJob(j => ({ ...j, phase: RECONNECT_OFFLINE_MESSAGE, message: RECONNECT_OFFLINE_MESSAGE }))
      }
    }
    window.setTimeout(() => void tick(), RECONNECT_POLL_MS * 2 ** Math.min(failures, 4))
  }
  window.setTimeout(() => void tick(), RECONNECT_POLL_MS)
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

// Vite can replace this module without a full page unload. Abort the old
// async loop so HMR never leaves an orphaned polling timer behind.
if (import.meta.hot) {
  import.meta.hot.dispose(() => {
    disposeCivitaiDownloadPoll()
    disposeDirectorRepairPolls()
  })
}

function audioSubModeForModel(modelType: string): import('../types').AudioSubMode {
  if (sfxModelTypes.has(modelType)) return 'sfx'
  return isMusicModelType(modelType) ? 'music' : 'speech'
}

// Transient: the LTX model selected before entering either SCAIL-2 edit
// workflow, so leaving Recast/Repaint restores the user's prior edit model.
let _preScail2AvatarModel = ''

/** Trailer excerpt and transcription hints, shared by every way audio can
 *  reach Director. */
type DirectorAudioOptions = {
  lyricsHint?: string
  trimStart?: number
  trimEnd?: number
  totalDuration?: number
}

/** How one track reaches Director. Only the delivery differs — posting the
 *  bytes, or naming a file the server already has — and it answers with the
 *  server-side path the rest of the flow works from. Adopted songs stay in
 *  their workspace folder, so that workspace has to travel with the path. */
type DirectorAudioSource = {
  name: string
  phase: 'uploading_audio' | 'adopting_audio'
  activityMessage: string
  loadingMessage: string
  workspace?: string
  deliver: () => Promise<{ path: string }>
}

interface ScheduledPromptSubmission {
  prompt: string
  position: number
  total: number
}

export interface AppState extends LlmSlice, StudioConfigurationSlice, StudioMusicSlice, DirectorSlice, ThemeSlice, SettingsSlice, SidebarSlice, RetakeDialogSlice, GallerySlice, DeveloperModeSlice, SystemSlice, PresetsSlice, ActivitySlice, CivitaiSlice, ToolsSlice, RecipesSlice, ServicesSlice, LorasSlice, ModelOptionsSlice, ModelsSlice, DirectorDashboardSlice, ShortFilmSlice, DirectorPipelineSlice, StudioEditSlice {
  wangpRestoreError: string
  // Generation mode (top-level: image/video/audio/avatar)
  generationMode: GenerationMode
  setGenerationMode: (mode: GenerationMode) => void
  imageStudioDrafts: Partial<Record<import('../features/studio/imageStudioIntent').ImageStudioIntent, import('../features/studio/imageStudioIntent').ImageStudioDraft>>
  imageStudioIntent: import('../features/studio/imageStudioIntent').ImageStudioIntent
  setImageStudioIntent: (intent: import('../features/studio/imageStudioIntent').ImageStudioIntent) => void
  resetImageStudio: () => void
  imageBatch?: import('../features/studio/imageBatch').ImageBatchSettings
  editSubMode: import('../types').EditSubMode
  setEditSubMode: (mode: import('../types').EditSubMode, recastEngine?: 'scail' | 'viggle') => void
  audioSubMode: import('../types').AudioSubMode
  setAudioSubMode: (mode: import('../types').AudioSubMode) => void
  audioReferenceStash: AudioReferenceStash
  selectedModelPerAudioSubMode: Partial<Record<import('../types').AudioSubMode, string>>
  selectedModelPerMode: Partial<Record<GenerationMode, string>>
  savedLoraPerMode: Partial<Record<GenerationMode, { activated_loras: string[]; loras_multipliers: string; loraWeights: Record<string, number[]>; availableLoras: string[] }>>
  savedParamsPerMode: Partial<Record<GenerationMode, SavedModeParams>>
  savedPromptPerMode: Partial<Record<string, string>>
  /** Snapshot of lora_id → filename loaded from localStorage at boot.
   *  Used by `refreshLoraIdMap` reconciliation to rewrite filenames that
   *  changed since save (LoRA version updates). Internal-only; not part
   *  of the persisted runtime state. */
  _loraFilenameSnapshotAtLoad?: Record<string, string>

  // Generation params
  params: GenerateParams
  setParam: <K extends keyof GenerateParams>(key: K, value: GenerateParams[K]) => void
  setParams: (partial: Partial<GenerateParams>) => void

  // Director-mode post-processing (separate image/video)
  directorImageSpatialUpsampling: string
  setDirectorImageSpatialUpsampling: (v: string) => void
  directorImageFilmGrainIntensity: number
  setDirectorImageFilmGrainIntensity: (v: number) => void
  directorImageFilmGrainSaturation: number
  setDirectorImageFilmGrainSaturation: (v: number) => void
  directorVideoSpatialUpsampling: string
  setDirectorVideoSpatialUpsampling: (v: string) => void
  directorVideoFilmGrainIntensity: number
  setDirectorVideoFilmGrainIntensity: (v: number) => void
  directorVideoFilmGrainSaturation: number
  setDirectorVideoFilmGrainSaturation: (v: number) => void
  directorVideoSelfRefiner: number
  setDirectorVideoSelfRefiner: (v: number) => void
  directorAudioScale: number
  setDirectorAudioScale: (v: number) => void

  // Generation state (queue)
  jobs: GenerationJob[]
  isGenerating: boolean
  startGeneration: (
    scheduledPrompt?: ScheduledPromptSubmission,
    submissionContext?: GenerationSubmissionContext,
  ) => Promise<void | GenerationReceiptLike>
  stopGeneration: (jobId?: string) => void
  dismissJob: (jobId: string) => void
  reconnectJobs: () => Promise<void>
  reconnectDirectorPipelines: () => Promise<void>

  // Select model (triggers side effects)
  selectModel: (modelType: string, preserveAudioReferences?: boolean) => void

  // Storage Manager overlay
  storageDashboardOpen: boolean
  setStorageDashboardOpen: (open: boolean) => void

  // LoRA picker sort order — store-backed (not per-component state) so
  // simultaneously mounted pickers (e.g. Director's Image + Video
  // accordions) stay in sync; persisted to localStorage.
  loraPickerSort: 'name' | 'newest'
  setLoraPickerSort: (sort: 'name' | 'newest') => void

  loadSettingsFromOutput: (source?: OutputSettingsSource) => Promise<boolean | void>
  rerollGeneration: (source?: OutputSettingsSource) => Promise<boolean | void>

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
  directorUploadAndAnalyze: (file: File, opts?: DirectorAudioOptions) => Promise<void>
  /** Bring in a track the server already holds — a workspace output, an
   *  earlier upload — by name. Story Lab's generated songs come this way:
   *  pulling the file into the browser only to post the same bytes back is a
   *  round trip over the network for a file already on that disk, and it is
   *  what broke when the UI is driven from another machine. */
  directorAdoptAndAnalyze: (reference: { audio_path: string; workspace?: string }, name: string, opts?: DirectorAudioOptions) => Promise<void>
  /** The hand-off both of the above share: deliver the audio, optionally cut
   *  the trailer excerpt, then analyze and plan. */
  directorLoadAudioSource: (source: DirectorAudioSource, opts?: DirectorAudioOptions) => Promise<void>
  // Music Video: generate-the-track source + song setup
  directorWriteSong: () => Promise<void>
  directorGenerateTrack: () => Promise<void>
  directorAnalyzeAndPlan: (audioPath: string, opts?: { transcribe?: boolean; lyricsHint?: string; classifyLyricsHint?: string; activityId?: string; totalDuration?: number; workspace?: string }) => Promise<void>
  directorSetEnergyBias: (bias: number) => Promise<void>
  directorSetPacingProfile: (profile: 'cinematic' | 'balanced' | 'rhythmic') => Promise<void>
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

  // LLM streaming
  llmStreamText: string
  llmStreamDone: boolean

  pollPipelineStatus: () => void
}

let directorReconnectTimer: ReturnType<typeof setTimeout> | null = null
let directorReconnectInFlight = false

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

const captureVideoSubModeStash = (s: AppState): VideoSubModeStash => ({
  params: { ...s.params },
  startImage: s.startImage,
  endImage: s.endImage,
  continueVideo: s.continueVideo,
  continueVideoPath: s.continueVideoPath,
  continueVideoUrl: s.continueVideoUrl,
  continueVideoDuration: s.continueVideoDuration,
  audioGuideFilename: s.audioGuideFilename,
  imageRefs: s.imageRefs,
  imageRefType: s.imageRefType,
  removeBackgroundRefs: s.removeBackgroundRefs,
  durationSeconds: s.durationSeconds,
  slidingWindowSeconds: s.slidingWindowSeconds,
  slidingWindowOverlap: s.slidingWindowOverlap,
  clips: s.clips,
  singlePromptMode: s.singlePromptMode,
  studioFocusedClipIndex: s.studioFocusedClipIndex,
})

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

export const useStore = create<AppState>((set, get) => {
  const developerMode = bindSlice(set, get, createDeveloperModeSlice)
  return {
  ...bindSlice(set, get, createDirectorSlice),
  ...bindSlice(set, get, createThemeSlice),
  ...bindSlice(set, get, createSettingsSlice),
  ...bindSlice(set, get, createSidebarSlice),
  ...bindSlice(set, get, createRetakeDialogSlice),
  ...bindSlice(set, get, createGallerySlice),
  ...bindSlice(set, get, createLlmSlice),
  ...bindSlice(set, get, createStudioConfigurationSlice({ alignFrameCount, resolveResolution })),
  ...bindSlice(set, get, createStudioMusicSlice),
  ...bindSlice(set, get, createSystemSlice),
  ...bindSlice(set, get, createPresetsSlice),
  ...bindSlice(set, get, createActivitySlice),
  ...bindSlice(set, get, createCivitaiSlice),
  ...bindSlice(set, get, createToolsSlice),
  ...bindSlice(set, get, createRecipesSlice),
  ...bindSlice(set, get, createServicesSlice),
  ...bindSlice(set, get, createLorasSlice),
  ...bindSlice(set, get, createModelOptionsSlice),
  ...bindSlice(set, get, createModelsSlice),
  ...bindSlice(set, get, createDirectorDashboardSlice),
  ...bindSlice(set, get, createShortFilmSlice),
  ...bindSlice(set, get, createDirectorPipelineSlice),
  ...bindSlice(set, get, createStudioEditSlice),
  ...developerMode,
  setDeveloperMode: (enabled: boolean) => {
    developerMode.setDeveloperMode(enabled)
    if (!enabled && get().mediaFilter === 'auditdev') {
      get().setMediaFilter('all')
    }
  },
  // Generation mode
  generationMode: 'video',
  imageStudioIntent: 'chooser' as import('../features/studio/imageStudioIntent').ImageStudioIntent,
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
    void import('../lib/localEditImages').then(({ forgetLocalImage }) => {
      for (const draft of drafts) {
        forgetLocalImage(String(draft.params.image_guide || ''))
        forgetLocalImage(String(draft.params.image_mask || ''))
        for (const item of draft.imageBatch?.sources || []) forgetLocalImage(item.url)
      }
    })
    state.setImageStudioIntent('chooser')
    set({ imageStudioDrafts: {}, imageBatch: undefined })
  },
  editSubMode: 'retake' as import('../types').EditSubMode,
  setEditSubMode: (mode: import('../types').EditSubMode, recastEngine?: 'scail' | 'viggle') => {
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
  audioSubMode: 'speech' as import('../types').AudioSubMode,
  audioReferenceStash: {},
  selectedModelPerAudioSubMode: {} as Partial<Record<import('../types').AudioSubMode, string>>,
  setAudioSubMode: (subMode) => {
    const { audioSubMode: prevSub, params, models } = get()
    if (subMode === prevSub && (subMode === 'mixer' || audioSubModeForModel(params.model_type) === subMode)) return
    // Save current model for the sub-mode we're leaving
    const savedModels = { ...get().selectedModelPerAudioSubMode, [prevSub]: params.model_type }
    // Determine model for target sub-mode
    const audioSubModeDefaults: Record<import('../types').AudioSubMode, string> = {
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

  // Director-mode post-processing (separate image/video)
  directorImageSpatialUpsampling: '',
  setDirectorImageSpatialUpsampling: (v) => set({ directorImageSpatialUpsampling: v }),
  directorImageFilmGrainIntensity: 0,
  setDirectorImageFilmGrainIntensity: (v) => set({ directorImageFilmGrainIntensity: v }),
  directorImageFilmGrainSaturation: 0.5,
  setDirectorImageFilmGrainSaturation: (v) => set({ directorImageFilmGrainSaturation: v }),
  directorVideoSpatialUpsampling: '',
  setDirectorVideoSpatialUpsampling: (v) => set({ directorVideoSpatialUpsampling: v }),
  directorVideoFilmGrainIntensity: 0,
  setDirectorVideoFilmGrainIntensity: (v) => set({ directorVideoFilmGrainIntensity: v }),
  directorVideoFilmGrainSaturation: 0.5,
  setDirectorVideoFilmGrainSaturation: (v) => set({ directorVideoFilmGrainSaturation: v }),
  directorVideoSelfRefiner: 0,
  setDirectorVideoSelfRefiner: (v) => set({ directorVideoSelfRefiner: v }),
  directorAudioScale: 1.0,
  setDirectorAudioScale: (v) => set({ directorAudioScale: v }),

  jobs: [],
  isGenerating: false,
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
    // Standalone branch: the prompt is OPTIONAL here (the server has a
    // sensible default), unlike the shared edit block below which
    // hard-requires one.
    // Repaint is the easy front door to the proven Studio Video/Frames
    // SCAIL-2 Animate path: an edited first frame defines the finished look
    // while the source video supplies motion and camera movement.
    if (state.generationMode === 'avatar' && state.editSubMode === 'restyle') {
      if (!state.editVideoPath || !state.editRepaintFramePath) return
      const repaintMappings = state.editRepaintMappings.slice(0, 5)
      if (repaintMappings.some(mapping => !mapping.source.trim() || !mapping.target.trim())) return
      const promptText = ((state.params.prompt as string) || '').trim()
      const newJob: GenerationJob = {
        id: '', status: 'queued', progress: 0, step: 0, totalSteps: 0,
        phase: '', message: 'Submitting repaint...', outputFiles: [], error: null, oomInfo: null,
      }
      set(s => {
        return prependJob(s.jobs, newJob)
      })

      try {
        const repaintModel = (state.params.model_type as string) || ''
        const repaintIsScail2 = repaintModel === 'scail2_14B_fast' || repaintModel === 'scail2_14B'
        const result = await api.submitRepaint({
          video_path: state.editVideoPath,
          target_frame_path: state.editRepaintFramePath,
          region_mappings: repaintMappings.map(mapping => ({
            id: mapping.id,
            source: mapping.source.trim(),
            target: mapping.target.trim(),
          })),
          ...(promptText ? { prompt: promptText } : {}),
          resolution_profile: state.editRepaintResolutionProfile,
          ...(repaintIsScail2 ? {
            model_type: repaintModel,
            num_inference_steps: (state.params.num_inference_steps as number) ?? undefined,
            ...(repaintModel === 'scail2_14B' ? {
              guidance_scale: (state.params.guidance_scale as number) ?? undefined,
            } : {}),
          } : {}),
          start_time: state.editStartTime,
          end_time: state.editEndTime,
          seed: (state.params.seed as number) ?? -1,
          negative_prompt: (state.params.negative_prompt as string) || '',
          activated_loras: (state.params.activated_loras as string[]) || [],
          loras_multipliers: (state.params.loras_multipliers as string) || '',
          workspace: state.activeWorkspace,
        })

        set(s => ({
          jobs: s.jobs.map(j => j === newJob
            ? { ...j, id: result.job_id, status: 'queued', message: 'Queued...' }
            : j),
        }))

        const pollInterval = setInterval(async () => {
          if (!get().jobs.find(j => j.id === result.job_id)) {
            clearInterval(pollInterval)
            return
          }
          try {
            const status = await api.fetchJobStatus(result.job_id)
            set(s => ({
              jobs: s.jobs.map(j => j.id !== result.job_id ? j : {
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
                ..._jobTimingPatch(status),
              }),
            }))
            if (status.status === 'running') void get().maybeRefreshGallery()
            if (status.status === 'completed') {
              clearInterval(pollInterval)
              set(s => {
                const remaining = s.jobs.filter(j => j.id !== result.job_id)
                return withJobs(remaining)
              })
              void get().maybeRefreshGallery({ message: 'New output ready' })
            } else if (isGenerationJobSettled(status.status)) {
              clearInterval(pollInterval)
              set(s => withJobs(s.jobs))
            }
          } catch { /* ignore poll errors */ }
        }, 2000)
      } catch (e) {
        const msg = e instanceof Error ? e.message : 'Repaint failed'
        set(s => updateJob(s.jobs, j => j === newJob, j => ({
          ...j, id: j.id || `submit-fail-${Date.now()}`, status: 'failed', message: msg, error: msg,
        })))
        console.error('Repaint failed:', msg)
      }
      return
    }

    if (state.generationMode === 'avatar' && state.editSubMode === 'recast') {
      const recastIsViggle = state.params.model_type === 'viggle_animate'
      const recastMappings = state.editRecastMappings.slice(0, recastIsViggle ? 1 : 5)
      if (
        !state.editVideoPath
        || recastMappings.length === 0
        || recastMappings.some(mapping => (!recastIsViggle && !mapping.target.trim()) || !mapping.refPath)
      ) return
      const promptText = ((state.params.prompt as string) || '').trim()

      const newJob: GenerationJob = {
        id: '', status: 'queued', progress: 0, step: 0, totalSteps: 0,
        phase: '', message: 'Submitting recast...', outputFiles: [], error: null, oomInfo: null,
      }
      set(s => {
        return prependJob(s.jobs, newJob)
      })

      try {
        // Honor the selector's Recast SCAIL-2 choice (dedicated Fast vs
        // native base). Guard on
        // architecture so a stale LTX model_type can never reach the
        // recast endpoint — the server then falls back to Fast.
        const recastModel = (state.params.model_type as string) || ''
        const recastIsScail2 = state.models.find(m => m.model_type === recastModel)?.architecture === 'scail2_14B'
        const result = await api.submitRecast({
          video_path: state.editVideoPath,
          // Legacy fields remain populated for old sidecars/API clients, while
          // the explicit cards provide deterministic target/color assignment.
          ref_image_path: recastMappings[0].refPath,
          target: recastMappings[0].target || 'person',
          person_count: recastMappings.length,
          reference_aligned_to_source: recastMappings[0].referenceAlignedToSource,
          character_mappings: recastMappings.map(mapping => ({
            id: mapping.id,
            target: mapping.target.trim(),
            ref_image_path: mapping.refPath,
            additional_ref_image_paths: mapping.additionalRefs
              .map(reference => reference.path)
              .filter(Boolean),
            reference_aligned_to_source: mapping.referenceAlignedToSource,
          })),
          // Simplified Recast recipe: identity preparation and native
          // bystander preservation are automatic; prompt rewriting and the
          // seam-prone post-composite remain off. The backend still accepts
          // all legacy fields for saved/API callers.
          isolate_reference: true,
          auto_face_detail: true,
          enhance_prompt: false,
          protect_bystanders: false,
          preserve_bystanders: true,
          use_relighting: state.editRecastUseRelighting,
          resolution_profile: state.editRecastResolutionProfile,
          ...(promptText ? { prompt: promptText } : {}),
          ...viggleSubmissionOptions(state.params, state.spatialUpsampling),
          ...(recastIsScail2 ? {
            model_type: recastModel,
            num_inference_steps: (state.params.num_inference_steps as number) ?? undefined,
            ...(recastModel === 'scail2_14B' ? {
              guidance_scale: (state.params.guidance_scale as number) ?? undefined,
            } : {}),
          } : {}),
          start_time: state.editStartTime,
          end_time: state.editEndTime,
          seed: (state.params.seed as number) ?? -1,
          negative_prompt: (state.params.negative_prompt as string) || '',
          activated_loras: (state.params.activated_loras as string[]) || [],
          loras_multipliers: (state.params.loras_multipliers as string) || '',
          workspace: state.activeWorkspace,
        })

        set(s => ({
          jobs: s.jobs.map(j => j === newJob ? { ...j, id: result.job_id, status: 'queued', message: 'Queued...' } : j),
        }))

        const pollInterval = setInterval(async () => {
          if (!get().jobs.find(j => j.id === result.job_id)) { clearInterval(pollInterval); return }
          try {
            const status = await api.fetchJobStatus(result.job_id)
            set(s => ({
              jobs: s.jobs.map(j => j.id !== result.job_id ? j : {
                ...j, status: status.status, progress: status.progress / 100,
                step: status.step ?? 0, totalSteps: status.total_steps ?? 0,
                phase: status.phase ?? '', message: status.message,
                outputFiles: status.output_files, error: status.error, oomInfo: status.oom_info ?? null,
                ..._jobTimingPatch(status),
              }),
            }))
            if (status.status === 'running') void get().maybeRefreshGallery()
            if (status.status === 'completed') {
              clearInterval(pollInterval)
              set(s => {
                const remaining = s.jobs.filter(j => j.id !== result.job_id)
                return withJobs(remaining)
              })
              void get().maybeRefreshGallery({ message: 'New output ready' })
            } else if (isGenerationJobSettled(status.status)) {
              clearInterval(pollInterval)
              set(s => withJobs(s.jobs))
            }
          } catch { /* ignore poll errors */ }
        }, 2000)
      } catch (e) {
        const msg = e instanceof Error ? e.message : 'Recast failed'
        set(s => updateJob(s.jobs, j => j === newJob, j => ({
          ...j, id: j.id || `submit-fail-${Date.now()}`, status: 'failed', message: msg, error: msg,
        })))
        console.error('Recast failed:', msg)
      }
      return
    }

    // ── Edit mode: Retake / Inpaint / Edit Anything ─────────────
    if (state.generationMode === 'avatar' && (state.editSubMode === 'retake' || state.editSubMode === 'inpaint' || state.editSubMode === 'edit_anything')) {
      if (!state.editVideoPath) return
      const prompt = (state.params.prompt as string || '').trim()
      if (!prompt) return

    const newJob: GenerationJob = {
      id: '', status: 'queued', progress: 0, step: 0, totalSteps: 0,
      phase: '', message: 'Submitting...', outputFiles: [], error: null, oomInfo: null, createdAt: Date.now(),
      }
      set(s => {
        return prependJob(s.jobs, newJob)
      })

      try {
        let result: { job_id: string }
        if (state.editSubMode === 'edit_anything') {
          result = await api.submitEditAnything({
            video_path: state.editVideoPath,
            prompt,
            model_type: state.params.model_type as string,
            start_time: state.editStartTime,
            end_time: state.editEndTime,
            lora_strength: state.editAnythingLoraStrength,
            retake_strength: state.editRetakeStrength,
            seed: (state.params.seed as number) ?? -1,
            // Edit Anything LoRA card: start with CFG=1 on distilled; raise
            // only if the edit is too weak. We route the user's global CFG
            // slider through so they can experiment.
            guidance_scale: (state.params.guidance_scale as number) ?? 1.0,
            num_inference_steps: (state.params.num_inference_steps as number) ?? 8,
            negative_prompt: (state.params.negative_prompt as string) || '',
            activated_loras: (state.params.activated_loras as string[]) || [],
            loras_multipliers: (state.params.loras_multipliers as string) || '',
            workspace: state.activeWorkspace,
            // Optional boundary anchors. Empty values mean "use source
            // frames" (today's auto-extract behavior); ltx2.py treats
            // missing/null/empty path as "fall back to source".
            ...(state.editAnythingStartAnchor ? { start_anchor_path: state.editAnythingStartAnchor } : {}),
            ...(state.editAnythingEndAnchor ? { end_anchor_path: state.editAnythingEndAnchor } : {}),
          })
        } else if (state.editSubMode === 'inpaint') {
          result = await api.submitInpaint({
            video_path: state.editVideoPath,
            description: prompt,
            sam_target: state.editSamTarget || undefined,
            invert_mask: state.editInvertMask || undefined,
            start_time: state.editStartTime,
            end_time: state.editEndTime,
            model_type: state.params.model_type as string,
            seed: (state.params.seed as number) ?? -1,
            // Inpaint needs CFG > 1.0 to make the prompt actually influence
            // the masked region. The edit-specific editPromptStrength slider
            // (default 3.5) drives this; the global params.guidance_scale is
            // fine for normal generation but would silently default to 1.0
            // and silently break inpaint.
            guidance_scale: state.editPromptStrength,
            retake_strength: state.editRetakeStrength,
            num_inference_steps: (state.params.num_inference_steps as number) ?? 8,
            negative_prompt: (state.params.negative_prompt as string) || '',
            resolution: (state.params.resolution as string) || '',
            activated_loras: (state.params.activated_loras as string[]) || [],
            loras_multipliers: (state.params.loras_multipliers as string) || '',
            masks_path: state.editMasksPath || undefined,
            workspace: state.activeWorkspace,
          })
        } else {
          result = await api.submitRetake({
            video_path: state.editVideoPath,
            start_time: state.editStartTime,
            end_time: state.editEndTime,
            prompt,
            model_type: state.params.model_type as string,
            retake_strength: state.editRetakeStrength,
            retake_engine: state.editRetakeEngine,
            regenerate_audio: state.editRegenerateAudio,
            seed: (state.params.seed as number) ?? -1,
            // Retake also benefits from CFG > 1.0 when the user provides a
            // prompt that should drive the regenerated region (e.g. new
            // outfit, different style). Previously stuck at 1.0 via
            // params.guidance_scale fallback — same silent bug as inpaint.
            guidance_scale: state.editPromptStrength,
            num_inference_steps: (state.params.num_inference_steps as number) ?? 8,
            negative_prompt: (state.params.negative_prompt as string) || '',
            resolution: (state.params.resolution as string) || '',
            activated_loras: (state.params.activated_loras as string[]) || [],
            loras_multipliers: (state.params.loras_multipliers as string) || '',
            workspace: state.activeWorkspace,
          })
        }

        set(s => ({
          jobs: s.jobs.map(j => j === newJob ? { ...j, id: result.job_id, status: 'queued', message: 'Queued...' } : j),
        }))

        // Standard job polling (same as regular generation)
        const pollInterval = setInterval(async () => {
          if (!get().jobs.find(j => j.id === result.job_id)) { clearInterval(pollInterval); return }
          try {
            const status = await api.fetchJobStatus(result.job_id)
            set(s => ({
              jobs: s.jobs.map(j => j.id !== result.job_id ? j : {
                ...j, status: status.status, progress: status.progress / 100,
                step: status.step ?? 0, totalSteps: status.total_steps ?? 0,
                phase: status.phase ?? '', message: status.message,
                outputFiles: status.output_files, error: status.error, oomInfo: status.oom_info ?? null,
                ..._jobTimingPatch(status),
              }),
            }))
            if (status.status === 'running') void get().maybeRefreshGallery()
            if (status.status === 'completed') {
              clearInterval(pollInterval)
              set(s => {
                const remaining = s.jobs.filter(j => j.id !== result.job_id)
                return withJobs(remaining)
              })
              void get().maybeRefreshGallery({ message: 'New output ready' })
            } else if (isGenerationJobSettled(status.status)) {
              clearInterval(pollInterval)
              // Keep the failed/cancelled job in the queue so its placeholder
              // stays visible with the error message — user dismisses via X.
              set(s => withJobs(s.jobs))
            }
          } catch { /* ignore poll errors */ }
        }, 2000)
      } catch (e) {
        const msg = e instanceof Error ? e.message : 'Generation failed'
        // Submit itself failed (pre-queue). Convert the placeholder to a
        // failed state in place so the user sees what went wrong instead of
        // the tile silently disappearing.
        set(s => updateJob(s.jobs, j => j === newJob, j => ({
          ...j, id: j.id || `submit-fail-${Date.now()}`, status: 'failed', message: msg, error: msg,
        })))
        console.error('Edit generation failed:', msg)
      }
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

  stopGeneration: (jobId) => {
    const currentJobs = get().jobs
    const targetIds = jobId
      ? currentJobs
          .filter(j => j.id === jobId && isGenerationJobActive(j.status) && j.status !== 'cancelling')
          .map(j => j.id)
      : currentJobs
          .filter(j => j.id && isGenerationJobActive(j.status) && j.status !== 'cancelling')
          .map(j => j.id)
    if (targetIds.length === 0) return
    const previousStatuses = new Map(
      currentJobs
        .filter(j => targetIds.includes(j.id))
        .map(j => [j.id, j.status] as const),
    )

    // Keep the job visible while the worker unwinds. Removing it immediately
    // made a still-running model download look as if Cancel had done nothing
    // and hid backend errors. Existing status polling will publish the final
    // cancelled state once the endpoint acknowledges the request.
    const targets = new Set(targetIds)
    set(s => markJobsCancelling(s.jobs, targets))
    targetIds.forEach(id => {
      void api.cancelJob(id).catch(e => {
        const message = e instanceof Error ? e.message : 'Cancel failed'
        console.error('Cancel failed:', e)
        set(s => ({
          jobs: s.jobs.map(j => j.id === id
            ? {
                ...j,
                status: j.status === 'cancelling'
                  ? (previousStatuses.get(id) ?? 'running')
                  : j.status,
                message: `Cancel failed: ${message}`,
                phase: j.phase,
              }
            : j),
        }))
      })
    })
  },

  // UI-only removal of a job tile (e.g. dismissing a failed/cancelled
  // placeholder). No backend call — the job is already terminal.
  dismissJob: (jobId) => {
    set(s => removeJob(s.jobs, j => j.id === jobId))
  },

  reconnectJobs: async () => {
    // On page load, check backend for any active jobs and restore them
    try {
      const data = await api.fetchActiveJobs()
      if (data.jobs.length > 0) {
        const existingIds = new Set(get().jobs.map(j => j.id))
        const newJobs: GenerationJob[] = data.jobs
          .filter(j => !existingIds.has(j.job_id))
          .map(j => ({
            id: j.job_id,
            status: j.status as GenerationJob['status'],
            progress: j.progress / 100,
            step: j.step,
            totalSteps: j.total_steps,
            phase: j.phase,
            message: j.message,
            outputFiles: j.output_files,
            error: j.error,
            createdAt: j.created_at < 1_000_000_000_000 ? j.created_at * 1000 : j.created_at,
            startedAt: _downloadTimestampMs(j.started_at) ?? undefined,
            finishedAt: _downloadTimestampMs(j.finished_at) ?? undefined,
            queuePosition: j.queue_position,
            oomInfo: (j as { oom_info?: import('../types').OomInfo | null }).oom_info ?? null,
            taskTimings: j.task_timings ?? [],
            h3WindowPlan: j.h3_window_plan ?? null,
            generationDetails: j.generation_details,
          }))
        if (newJobs.length > 0) {
          set(s => withJobs([...s.jobs, ...newJobs]))
          newJobs.forEach(job => _pollReconnectedJob(job.id, set, get))
          console.log(`[Queue] Reconnected to ${newJobs.length} active job(s)`)
        }
      }
    } catch {
      // Backend might not have the endpoint yet, silently ignore
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
        if (primary && !get().pipelineId) {
          set({
            pipelineId: primary.id,
            pipelineStatus: primary as import('../api/client').PipelineStatus,
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
            .filter((result): result is PromiseFulfilledResult<import('../api/client').PipelineStatus> => result.status === 'fulfilled')
            .map(result => result.value)
            .filter((status): status is import('../api/client').PipelineStatus & { status: 'running' | 'paused' } =>
              status.status === 'running' || status.status === 'paused')
            .map(status => ({
              ...status,
              pipeline_type: 'music_video',
              created_at: 0,
              updated_at: Date.now(),
            }))
          set({ activeDirectorPipelines: active })
          const primary = active[0]
          if (primary && !get().pipelineId) {
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
    await refresh()
  },

  // Director (Music Video Director)
  sidebarMode: 'studio' as const,
  directorSkill: null,
  directorStoryProductionHandoff: null,
  llmStreamText: '',
  llmStreamDone: true,
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

  directorUploadAndAnalyze: (file, opts) => get().directorLoadAudioSource({
    name: file.name,
    phase: 'uploading_audio',
    activityMessage: `Uploading “${file.name}”…`,
    loadingMessage: 'Uploading audio...',
    deliver: () => api.uploadAudio(file),
  }, opts),

  directorAdoptAndAnalyze: (reference, name, opts) => get().directorLoadAudioSource({
    name,
    phase: 'adopting_audio',
    activityMessage: `Loading “${name}”…`,
    loadingMessage: 'Loading audio...',
    workspace: reference.workspace,
    deliver: () => api.adoptAudio(reference),
  }, opts),

  directorLoadAudioSource: async (source, opts) => {
    const activityId = `director-audio:${Date.now()}:${Math.random().toString(36).slice(2, 8)}`
    get().upsertActivity({
      id: activityId,
      kind: 'audio_analysis',
      title: 'Prepare music video',
      status: 'running',
      phase: source.phase,
      message: source.activityMessage,
      current: 1,
      total: 10,
    })
    set({
      directorLoading: true,
      directorLoadingMessage: source.loadingMessage,
      directorError: null,
      directorAudioName: source.name,
      directorStep: 'analyze',
    })
    let analysisStarted = false
    try {
      const delivered = await source.deliver()
      const shouldTrim = Number.isFinite(opts?.trimStart)
        && Number.isFinite(opts?.trimEnd)
        && Number(opts?.trimEnd) > Number(opts?.trimStart) + 0.99
      if (shouldTrim) {
        get().upsertActivity({
          id: activityId,
          kind: 'audio_analysis',
          title: 'Prepare musical trailer',
          status: 'running',
          phase: 'trimming_audio',
          message: `Cutting ${Number(opts?.trimStart).toFixed(1)}s–${Number(opts?.trimEnd).toFixed(1)}s…`,
          current: 1,
          total: 10,
        })
      }
      const workspace = source.workspace ?? get().activeWorkspace
      const prepared = shouldTrim
        ? await api.trimAudio({
            audio_path: delivered.path,
            start: Number(opts?.trimStart),
            end: Number(opts?.trimEnd),
            workspace,
          })
        : delivered
      analysisStarted = true
      await get().directorAnalyzeAndPlan(prepared.path, {
        transcribe: true,
        lyricsHint: opts?.lyricsHint,
        classifyLyricsHint: shouldTrim ? '' : opts?.lyricsHint,
        activityId,
        totalDuration: opts?.totalDuration,
        workspace,
      })
    } catch (e: unknown) {
      if (analysisStarted) return
      const msg = e instanceof Error ? e.message : 'The audio could not be loaded'
      console.error('Director audio hand-off failed:', e)
      set({ directorLoading: false, directorLoadingMessage: null, directorError: msg, directorStep: 'upload' })
      if (get().activities[activityId]?.status !== 'failed') {
        get().upsertActivity({
          id: activityId,
          kind: 'audio_analysis',
          title: 'Prepare music video',
          status: 'failed',
          phase: source.phase,
          message: msg,
          error: msg,
        })
      }
    }
  },

  // Shared analyze → section-classify → plan-structure chain. Works for an
  // UPLOADED track or a GENERATED one — both converge here with an audio path
  // on disk and land on the 'structure' step, so everything downstream is
  // identical regardless of where the audio came from.
  directorAnalyzeAndPlan: async (audioPath, opts) => {
    const transcribe = opts?.transcribe !== false
    const activityId = opts?.activityId
      || `director-audio:${Date.now()}:${Math.random().toString(36).slice(2, 8)}`
    let frontendActivityOpen = true
    let backendAccepted = false
    let postActivity: ReturnType<typeof beginAppActivity> | null = null
    const analysisSteps: Record<string, number> = {
      loading_audio: 2,
      detecting_beats: 3,
      identifying_sections: 4,
      loading_vocal_model: 4,
      extracting_vocals: 5,
      loading_transcription_model: 5,
      transcribing: 6,
      loading_diarization_model: 6,
      identifying_speakers: 7,
      finalizing: 8,
    }
    const reportActivity = (phase: string, message: string, current?: number) => {
      if (!frontendActivityOpen) return
      get().upsertActivity({
        id: activityId,
        kind: 'audio_analysis',
        title: 'Prepare music video',
        status: 'running',
        phase,
        message,
        current: current ?? analysisSteps[phase] ?? 2,
        total: 10,
      })
    }
    reportActivity('analyzing_audio', 'Analyzing audio…', 2)
    set({
      directorAudioPath: audioPath,
      directorLoading: true,
      directorLoadingMessage: 'Analyzing audio...',
      directorError: null,
      directorStep: 'analyze',
    })
    try {
      const accepted = await api.startAudioAnalysisJob({
        audio_path: audioPath,
        transcribe,
        extract_vocals: transcribe,
        lyrics_hint: opts?.lyricsHint || undefined,
        workspace: opts?.workspace ?? get().activeWorkspace,
      })
      backendAccepted = true
      get().upsertActivity({
        id: activityId,
        kind: 'audio_analysis',
        title: 'Prepare music video',
        status: 'completed',
        phase: 'handed_off',
        message: `Continuing as recoverable audio job ${accepted.job_id}`,
        current: 1,
        total: 1,
      })
      frontendActivityOpen = false
      window.setTimeout(() => get().removeActivity(activityId), 4000)
      void get().reconnectJobs()

      let analysis: AudioAnalysisResult | null = null
      for (;;) {
        const status = await api.fetchAudioAnalysisJob(accepted.job_id)
        set({ directorLoadingMessage: status.message })
        if (status.status === 'completed') {
          analysis = status.result
          break
        }
        if (status.status === 'failed') throw new Error(status.error || status.message)
        if (status.status === 'cancelled') throw new Error('Audio analysis cancelled')
        await new Promise(resolve => window.setTimeout(resolve, 1000))
      }
      if (!analysis) throw new Error('Audio analysis completed without a result')

      postActivity = beginAppActivity(get, {
        kind: 'director_audio_structure',
        title: 'Prepare music video',
        phase: 'classifying_sections',
        message: 'Preparing the editable song structure…',
        total: 2,
      })

      // Try LLM-based section classification (falls back to heuristic)
      if (analysis.lyrics && analysis.lyrics.length > 0) {
        try {
          set({ directorLoadingMessage: 'Identifying sections (LLM)...' })
          postActivity.report(
            'classifying_sections',
            'Classifying verses, choruses and bridges…',
            0,
            2,
          )
          const classified = await api.classifySections({
            analysis,
            lyrics_hint: (opts?.classifyLyricsHint ?? opts?.lyricsHint) || undefined,
          })
          analysis = {
            ...analysis,
            sections: classified.sections,
            song_structure: classified.song_structure || null,
          }
        } catch {
          // LLM not available — keep heuristic labels
        }
      }

      set({ directorAnalysis: analysis })

      // Extract unique speakers from diarized lyrics
      const speakers: string[] = []
      if (analysis.lyrics) {
        const seen = new Set<string>()
        for (const seg of analysis.lyrics) {
          if (seg.speaker && !seen.has(seg.speaker)) {
            seen.add(seg.speaker)
            speakers.push(seg.speaker)
          }
        }
      }
      const speakerMappings: SpeakerMapping[] = speakers.map(s => ({
        speakerId: s,
        name: '',
        role: '' as const,
      }))
      set({ directorSpeakers: speakers, directorSpeakerMappings: speakerMappings })

      // Plan beat-aligned clip structure
      set({ directorLoadingMessage: 'Planning clip structure...' })
      postActivity.report('planning_clips', 'Planning beat-aligned clips…', 1, 2)
      const structure = await api.planClipStructure({
        analysis,
        energy_bias: get().directorEnergyBias,
        pacing_profile: get().directorSkill === 'music_video' ? get().directorPacingProfile : undefined,
        fps: get().modelOptions?.fps ?? 16,
        frames_steps: get().modelOptions?.frames_steps ?? 4,
        frames_minimum: get().modelOptions?.frames_minimum ?? 5,
        total_duration: Number.isFinite(opts?.totalDuration) && Number(opts?.totalDuration) > 0
          ? Number(opts?.totalDuration)
          : undefined,
        // Authoritative: the Director's video model (modelOptions above may
        // belong to a music model — e.g. ACE-Step after generating a track —
        // whose fps fallback of 16 used to shrink clips by 16/25).
        video_model: get().selectedModelPerMode.video || undefined,
      })
      set({
        directorPlannedClips: structure.clips,
        directorStep: 'structure',
        directorLoading: false,
        directorLoadingMessage: null,
      })
      postActivity.finish(`${structure.clips.length} clips planned — review the pacing`)
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Analysis failed'
      console.error('Director analysis failed:', e)
      postActivity?.fail(e, 'preparing_structure')
      if (msg === 'Audio analysis cancelled') {
        set({ directorLoading: false, directorLoadingMessage: null, directorError: null, directorStep: 'upload' })
        return
      }
      set({ directorLoading: false, directorLoadingMessage: null, directorError: msg, directorStep: 'upload' })
      if (!backendAccepted) {
        frontendActivityOpen = false
        get().upsertActivity({
          id: activityId,
          kind: 'audio_analysis',
          title: 'Prepare music video',
          status: 'failed',
          phase: 'analyzing_audio',
          message: msg,
          error: msg,
        })
      }
      throw e
    }
  },

  // Music Video: write the song (Style + Lyrics) from the description, with
  // the optional reference image informing the style via the vision LLM.
  // Throws on failure so the UI can surface it inline.
  directorWriteSong: async () => {
    const s = get()
    const description = s.directorSongDescription.trim()
    if (!description) return
    const activity = beginAppActivity(get, {
      kind: 'director_songwriting',
      title: 'Music Video Director',
      phase: 'writing_song',
      message: 'Writing the music prompt and structured lyrics…',
      total: 2,
      generationDetails: {
        text_provider: s.productionProfile.text.provider,
        text_model: s.productionProfile.text.model,
      },
    })
    let refPath = s.directorReferenceImagePath
    try {
      if (!refPath && s.directorReferenceImage) {
        activity.report('uploading_artwork', 'Uploading the visual reference…', 1, 2)
        try {
          refPath = (await api.uploadImage(s.directorReferenceImage)).path
          set({ directorReferenceImagePath: refPath })
        } catch { /* image upload is best-effort */ }
      }
      activity.report('writing_song', 'Writing the music prompt and structured lyrics…', 1, 2)
      set({ directorError: null })
      const r = await api.writeSong({
        description,
        instrumental: s.directorSongInstrumental,
        reference_image_path: refPath || undefined,
      })
      set({
        directorSongStyle: r.style || '',
        directorSongLyrics: s.directorSongInstrumental ? '[Instrumental]' : (r.lyrics || ''),
      })
      activity.finish('Song prompt and lyrics ready')
    } catch (error) {
      activity.fail(error)
      throw error
    }
  },

  // Music Video: generate the track (writing the song first if the user only
  // gave a description), then hand off to the SAME analyze → plan-structure
  // chain the upload flow uses. In Auto mode, continue straight into the
  // pipeline so it's fully hands-off.
  directorGenerateTrack: async () => {
    const s = get()
    const instrumental = s.directorSongInstrumental
    const description = s.directorSongDescription.trim()
    const style = s.directorSongStyle.trim()
    const lyrics = s.directorSongLyrics.trim()
    if (!description && !style && !lyrics) {
      set({ directorError: 'Describe your song (or fill in Style / Lyrics) first.' })
      return
    }
    const activity = beginAppActivity(get, {
      kind: 'director_music',
      title: 'Music Video Director',
      phase: 'generating_music',
      message: 'Preparing music generation…',
      total: 2,
      generationDetails: {
        model_type: `${s.productionProfile.music.provider}:${s.productionProfile.music.model}`,
        model_name: s.productionProfile.music.model,
        duration_seconds: s.directorSongDuration,
      },
    })
    // Upload the reference image so it can inform BOTH the music and visuals.
    let refPath = s.directorReferenceImagePath
    if (!refPath && s.directorReferenceImage) {
      try {
        refPath = (await api.uploadImage(s.directorReferenceImage)).path
        set({ directorReferenceImagePath: refPath })
      } catch { /* image upload is best-effort */ }
    }
    set({
      directorTrackGenerating: true,
      directorError: null,
      directorLoading: true,
      directorLoadingMessage: 'Generating music track…',
      directorStep: 'analyze',
    })
    try {
      // generateMusic is a BLOCKING POST — the browser only learns the job id
      // when it finishes — but the backend registers the job immediately. Run
      // the same discovery a fresh browser uses at page load (reconnectJobs:
      // deduped, self-polling) so the gallery shows a live placeholder card
      // during the render instead of nothing until LLM planning.
      const trackPromise = api.generateMusic({
        description: description || undefined,
        style: style || undefined,
        lyrics: instrumental ? '[Instrumental]' : (lyrics || undefined),
        instrumental,
        duration_seconds: s.directorSongDuration,
        reference_image_path: refPath || undefined,
        workspace: get().activeWorkspace || undefined,
        initiator: 'Director · Music video',
      })
      setTimeout(() => { void get().reconnectJobs() }, 1200)
      setTimeout(() => { void get().reconnectJobs() }, 5000)
      activity.report('generating_music', 'Generating the music track…', 1, 2)
      const r = await trackPromise
      // Persist the (possibly LLM-written) song back into the editable fields.
      set({
        directorSongStyle: r.style || style,
        directorSongLyrics: instrumental ? '[Instrumental]' : (r.lyrics || lyrics),
        directorTrackGenerating: false,
      })
      // Pre-fill the scene description from the song brief so the visual
      // planner has context. The 'style' step shows it (editable); Auto mode
      // uses it directly.
      if (!get().directorSceneDescription.trim() && description) {
        set({ directorSceneDescription: description })
      }
      activity.finish('Music track ready; starting audio analysis')
      // Same analyze → plan-structure chain as the upload flow. Instrumental
      // tracks skip transcription (no lyrics to find). For vocal tracks we
      // KNOW the written lyrics — seed Whisper with them so the timed
      // transcription matches what ACE-Step actually sang.
      await get().directorAnalyzeAndPlan(r.audio_path, {
        transcribe: !instrumental,
        lyricsHint: instrumental ? undefined : (r.lyrics || lyrics || undefined),
        totalDuration: s.directorSongDuration,
      })
      // Manual mode now pauses on the visible structure review. Auto mode
      // accepts the selected pacing profile and continues hands-free.
      if (get().directorStep === 'structure' && get().directorAutoMode) {
        get().directorConfirmStructure()
        await get().startDirectorPipeline()
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Music generation failed'
      console.error('Director music generation failed:', e)
      set({
        directorTrackGenerating: false,
        directorLoading: false,
        directorLoadingMessage: null,
        directorError: msg,
        directorStep: 'upload',
      })
      activity.fail(e, 'generating_music')
    }
  },

  directorSetEnergyBias: async (bias) => {
    const { directorAnalysis } = get()
    if (!directorAnalysis) return
    const activity = beginAppActivity(get, {
      kind: 'clip_replanning', title: 'Director', phase: 'planning_clips',
      message: 'Recalculating clip structure…', total: 1,
    })
    set({ directorLoading: true, directorEnergyBias: bias })
    try {
      const structure = await api.planClipStructure({
        analysis: directorAnalysis,
        energy_bias: bias,
        fps: get().modelOptions?.fps ?? 16,
        frames_steps: get().modelOptions?.frames_steps ?? 4,
        frames_minimum: get().modelOptions?.frames_minimum ?? 5,
        video_model: get().selectedModelPerMode.video || undefined,
      })
      set({ directorPlannedClips: structure.clips, directorLoading: false })
      activity.finish(`${structure.clips.length} clips replanned`)
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Failed to update structure'
      set({ directorLoading: false, directorError: msg })
      activity.fail(e, 'planning_clips')
    }
  },

  directorSetPacingProfile: async (profile) => {
    const { directorAnalysis } = get()
    set({ directorPacingProfile: profile })
    if (!directorAnalysis) return
    const activity = beginAppActivity(get, {
      kind: 'clip_replanning', title: 'Music Video Director', phase: 'planning_clips',
      message: `Applying ${profile} editing rhythm…`, total: 1,
    })
    set({ directorLoading: true, directorError: null })
    try {
      const structure = await api.planClipStructure({
        analysis: directorAnalysis,
        pacing_profile: profile,
        fps: get().modelOptions?.fps ?? 16,
        frames_steps: get().modelOptions?.frames_steps ?? 4,
        frames_minimum: get().modelOptions?.frames_minimum ?? 5,
        video_model: get().selectedModelPerMode.video || undefined,
      })
      set({ directorPlannedClips: structure.clips, directorLoading: false })
      activity.finish(`${structure.clips.length} clips planned with ${profile} pacing`)
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Failed to update music-video pacing'
      set({ directorLoading: false, directorError: msg })
      activity.fail(e, 'planning_clips')
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
      // but its poller must not overwrite the next story loaded into Director.
      pipelineId: null,
      pipelineStatus: null,
      pipelinePolling: false,
    })
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

  wangpRestoreError: '',
  storageDashboardOpen: false,
  setStorageDashboardOpen: (open) => set({ storageDashboardOpen: open }),

  loraPickerSort: (() => {
    try { return localStorage.getItem('maestro_lora_picker_sort') === 'newest' ? 'newest' as const : 'name' as const } catch { return 'name' as const }
  })(),
  setLoraPickerSort: (sort) => {
    try { localStorage.setItem('maestro_lora_picker_sort', sort) } catch { /* private mode */ }
    set({ loraPickerSort: sort })
  },

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
        const recordedSub = p._audio_sub_mode as import('../types').AudioSubMode | undefined
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

  rerollGeneration: async (source) => {
    // Await the (now async, self-healing) settings load before generating, so a
    // slow on-demand metadata fetch can't let the reroll fire with stale params.
    if (await get().loadSettingsFromOutput(source) === false) return false
    await get().startGeneration()
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
  }
})
