import * as api from '../api/client'
import type {
  GenerateParams,
  GenerationMode,
  H3WindowPlan,
  LlmModelOption,
  LlmStatus,
  ModelOptions,
  ProductionProfile,
  ServicesConfig,
} from '../types'
import type { SliceCreator, SliceSet } from './storeApi'

export const UNLOADED_LLM_STATUS: LlmStatus = {
  loaded: false,
  model_id: null,
  device: null,
  provider: '',
}

export type LlmSlice = {
  llmStatus: LlmStatus | null
  llmLoading: boolean
  llmModels: LlmModelOption[]
  loadLlmStatus: () => Promise<void>
  loadLlmModels: () => Promise<void>
  loadLlm: () => Promise<void>
  unloadLlm: () => Promise<void>
  isEnhancing: boolean
  enhancePrompt: (ttsMode?: string) => Promise<void>
  h3WindowPlan: H3WindowPlan | null
  updateH3WindowPrompt: (index: number, prompt: string) => void
  clearH3WindowPlan: () => void
}

/** Host fields the LLM drawer reads or writes without owning generate. */
export type LlmSliceHost = LlmSlice & {
  servicesConfig: ServicesConfig | null
  productionProfile: ProductionProfile
  params: GenerateParams
  generationMode: GenerationMode
  startImage: File | null
  endImage: File | null
  imageRefs: File[]
  modelOptions: ModelOptions | null
  slidingWindowOverlap: number
  durationSeconds: number
  slidingWindowSeconds: number
  slidingWindowLocked: boolean
  ttsVoiceCount: number
  _autoParseSpkeakerNames: (text: string, force?: boolean) => void
}

type EnhanceMedia = {
  imagePaths: string[]
  referenceContext?: string
}

type EnhanceWindowLayout = {
  fps: number
  discardFrames: number
  windowCount: number
  shouldPlanH3Windows: boolean
}

function omniAudioLabel(note: string, intent: string, audioIndex: number): string {
  if (intent === 'drive') {
    return `<Audio ${audioIndex}>: ${note}; intent=AUDIO REUSE / PERFORMANCE DRIVER; retention=partially_copy; preserve its audible timeline and synchronize action to it`
  }
  if (intent === 'style') {
    return `<Audio ${audioIndex}>: ${note}; intent=AUDIO REFERENCE; retention=weak_reference; borrow only rhythm/style/texture and do not copy the source signal or words`
  }
  return `<Audio ${audioIndex}>: ${note}; intent=VOICE REFERENCE; retention=reference; use timbre/emotion/delivery for new scripted dialogue without copying source words, timing, or waveform`
}

function collectOmniEnhanceMedia(params: GenerateParams): EnhanceMedia {
  const imagePaths: string[] = []
  let pictureIndex = 0
  let videoIndex = 0
  let audioIndex = 0
  const labelLines: string[] = []
  for (const reference of params.minimax_h3_references ?? []) {
    const note = (reference.role || reference.filename || 'reference').trim()
    if (reference.type === 'audio') {
      labelLines.push(omniAudioLabel(note, reference.audio_intent ?? 'voice', ++audioIndex))
      continue
    }
    if (reference.type === 'image') {
      labelLines.push(`<Picture ${++pictureIndex}>: visual identity/appearance reference for ${note}; retention=reference for identity only; do not reproduce its background, framing, composition, or pose`)
      if (reference.path) imagePaths.push(reference.path)
      continue
    }
    const nextVideoIndex = videoIndex + 1
    if ((reference.has_audio || reference.audio_path) && reference.include_audio !== false) {
      labelLines.push(omniAudioLabel(
        `soundtrack paired with <Video ${nextVideoIndex}>`,
        'drive',
        ++audioIndex,
      ))
    }
    videoIndex = nextVideoIndex
    labelLines.push(`<Video ${videoIndex}>: motion/camera/scene/timing reference for ${note}`)
  }
  return { imagePaths, referenceContext: labelLines.join('\n') }
}

async function uploadBestEffort(file: File, imagePaths: string[]): Promise<void> {
  try {
    const uploaded = await api.uploadImage(file)
    imagePaths.push(uploaded.path)
  } catch { /* best effort */ }
}

async function collectEnhanceMedia(state: LlmSliceHost): Promise<EnhanceMedia> {
  if (state.modelOptions?.omni_reference === true) {
    return collectOmniEnhanceMedia(state.params)
  }
  const imagePaths: string[] = []
  if (state.generationMode === 'image') {
    for (const ref of state.imageRefs) {
      await uploadBestEffort(ref, imagePaths)
    }
    return { imagePaths }
  }
  if (state.startImage) {
    await uploadBestEffort(state.startImage, imagePaths)
  } else if (state.params.image_start && typeof state.params.image_start === 'string') {
    imagePaths.push(state.params.image_start)
  }
  return { imagePaths }
}

function enhanceWindowLayout(state: LlmSliceHost): EnhanceWindowLayout {
  const fps = state.modelOptions?.fps ?? 16
  const swDefaults = (state.modelOptions as Record<string, unknown> | null)?.sliding_window_defaults as Record<string, number> | undefined
  const discardFrames = swDefaults?.discard_last_frames ?? 0
  const overlapSec = state.slidingWindowOverlap / fps
  const discardSec = discardFrames / fps
  const stride = state.slidingWindowSeconds - discardSec - overlapSec
  const supportsSlidingWindows = state.modelOptions?.sliding_window === true
  const windowCount = supportsSlidingWindows && stride > 0 && state.durationSeconds > state.slidingWindowSeconds
    ? 1 + Math.ceil((state.durationSeconds - state.slidingWindowSeconds + discardSec) / stride)
    : 1
  return {
    fps,
    discardFrames,
    windowCount,
    shouldPlanH3Windows: (
      state.generationMode === 'video'
      && state.modelOptions?.sliding_window_auto_prompt_pacing === true
      && state.params.image_mode !== 2
      && windowCount > 1
    ),
  }
}

async function appendEndImage(state: LlmSliceHost, imagePaths: string[]): Promise<void> {
  if (state.endImage) {
    await uploadBestEffort(state.endImage, imagePaths)
    return
  }
  if (state.params.image_end && typeof state.params.image_end === 'string') {
    imagePaths.push(state.params.image_end)
  }
}

async function applyH3WindowPlan(
  state: LlmSliceHost,
  set: SliceSet<LlmSliceHost>,
  imagePaths: string[],
  layout: EnhanceWindowLayout,
): Promise<void> {
  // The ordinary H3 enhancer writes one complete Context-IR timeline.
  // Multi-window H3 instead needs a structured storyboard whose prompts
  // contain only their own local actions. Include both endpoint images
  // so the planner can preserve the requested visual trajectory.
  await appendEndImage(state, imagePaths)
  const { params } = state
  const plan = await api.planH3Windows({
    prompt: params.prompt,
    model_type: params.model_type,
    resolution: params.resolution,
    total_frames: Math.max(1, Math.round(state.durationSeconds * layout.fps)),
    window_frames: Math.max(1, Math.round(state.slidingWindowSeconds * layout.fps)),
    overlap_frames: state.slidingWindowOverlap,
    discard_frames: layout.discardFrames,
    sliding_window_memory_override: state.slidingWindowLocked,
    has_start_image: !!(state.startImage || params.image_start),
    has_end_image: !!(state.endImage || params.image_end),
    image_paths: imagePaths.length > 0 ? imagePaths : undefined,
  })
  const effectiveWindowFrames = plan.effective_window_frames || plan.window_frames
  set(s => ({
    h3WindowPlan: plan,
    slidingWindowSeconds: effectiveWindowFrames / layout.fps,
    // Clicking Enhance on a multi-window H3 First/Last job is an
    // explicit request to plan the idea across those windows. Turn the
    // planner back on even when an old saved setting left legacy mode
    // disabled; otherwise the ordinary H3 enhancer flattens every
    // window into one globally timed screenplay.
    params: {
      ...s.params,
      sliding_window_size: effectiveWindowFrames,
      minimax_h3_window_storyboard: true,
    },
    isEnhancing: false,
  }))
}

function timedModeFields(state: LlmSliceHost, windowCount: number) {
  if (state.generationMode !== 'video' && state.generationMode !== 'avatar') {
    return {
      duration_seconds: undefined as number | undefined,
      window_count: undefined as number | undefined,
      window_size_seconds: undefined as number | undefined,
    }
  }
  return {
    duration_seconds: state.durationSeconds,
    window_count: windowCount,
    window_size_seconds: state.slidingWindowSeconds,
  }
}

export const createLlmSlice: SliceCreator<LlmSlice, LlmSliceHost> = (set, get) => ({
  llmStatus: null,
  llmLoading: false,
  llmModels: [],
  loadLlmStatus: async () => {
    try {
      const status = await api.fetchLlmStatus()
      set({ llmStatus: status })
    } catch (e) {
      console.error('Failed to load LLM status:', e)
    }
  },
  loadLlmModels: async () => {
    try {
      const provider = get().servicesConfig?.llm_provider || get().productionProfile.text.provider
      const data = await api.fetchLlmModels(provider)
      set({ llmModels: data.models })
    } catch (e) {
      console.error('Failed to load LLM models:', e)
    }
  },
  loadLlm: async () => {
    set({ llmLoading: true })
    try {
      const result = await api.loadLlm()
      set({
        llmStatus: {
          loaded: result.loaded,
          model_id: result.model_id,
          device: result.device,
          provider: result.provider || '',
        },
        llmLoading: false,
      })
    } catch (e) {
      console.error('Failed to load LLM:', e)
      set({ llmLoading: false })
    }
  },
  unloadLlm: async () => {
    try {
      await api.unloadLlm()
      set({ llmStatus: UNLOADED_LLM_STATUS })
    } catch (e) {
      console.error('Failed to unload LLM:', e)
    }
  },

  isEnhancing: false,
  h3WindowPlan: null,
  updateH3WindowPrompt: (index, prompt) => set(s => {
    if (!s.h3WindowPlan || index < 0 || index >= s.h3WindowPlan.windows.length) return {}
    const windows = s.h3WindowPlan.windows.map((window, windowIndex) => (
      windowIndex === index ? { ...window, prompt } : window
    ))
    return {
      h3WindowPlan: {
        ...s.h3WindowPlan,
        windows,
        window_prompts: windows.map(window => window.prompt),
      },
    }
  }),
  clearH3WindowPlan: () => set({ h3WindowPlan: null }),
  enhancePrompt: async (ttsMode?: string) => {
    const state = get()
    if (!state.params.prompt.trim()) return
    set({ isEnhancing: true })
    try {
      const media = await collectEnhanceMedia(state)
      const layout = enhanceWindowLayout(state)
      if (layout.shouldPlanH3Windows) {
        await applyH3WindowPlan(state, set, media.imagePaths, layout)
        return
      }
      const timed = timedModeFields(state, layout.windowCount)
      const result = await api.llmEnhancePrompt({
        prompt: state.params.prompt,
        mode: state.generationMode,
        model_type: state.params.model_type,
        max_new_tokens: (state.generationMode === 'audio' && ttsMode) ? 2048 : undefined,
        image_paths: media.imagePaths.length > 0 ? media.imagePaths : undefined,
        duration_seconds: timed.duration_seconds,
        window_count: timed.window_count,
        window_size_seconds: timed.window_size_seconds,
        activated_loras: state.params.activated_loras.length > 0 ? state.params.activated_loras : undefined,
        tts_enhance_mode: ttsMode || undefined,
        tts_voice_count: state.ttsVoiceCount || undefined,
        reference_context: media.referenceContext,
      })
      set(s => ({
        params: { ...s.params, prompt: result.enhanced },
        isEnhancing: false,
      }))
      if (ttsMode && get().ttsVoiceCount > 0) {
        get()._autoParseSpkeakerNames(result.enhanced, true)
      }
    } catch (e) {
      console.error('Failed to enhance prompt:', e)
      set({ isEnhancing: false })
    }
  },
})
