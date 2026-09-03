import type {
  AspectRatio,
  GenerateParams,
  GenerationMode,
  H3WindowPlan,
  ModelOptions,
  MultiClip,
  ResolutionPreset,
} from '../types'
import type { SliceCreator } from './storeApi'

type VoiceReference = { filename: string; path: string }
type TtsVoice = { name: string; filename: string | null; path: string | null }

export interface StudioConfigurationSlice {
  resolutionPreset: ResolutionPreset
  setResolutionPreset: (preset: ResolutionPreset) => void
  aspectRatio: AspectRatio
  setAspectRatio: (ratio: AspectRatio) => void
  durationSeconds: number
  setDurationSeconds: (seconds: number) => void
  slidingWindowSeconds: number
  setSlidingWindowSeconds: (seconds: number) => void
  slidingWindowOverlap: number
  setSlidingWindowOverlap: (frames: number) => void
  slidingWindowLocked: boolean
  setSlidingWindowLocked: (locked: boolean) => void
  guideVideoFps: number | null
  setGuideVideoFps: (fps: number | null) => void
  outputCount: number
  setOutputCount: (count: number) => void
  startImage: File | null
  endImage: File | null
  setStartImage: (file: File | null) => void
  setEndImage: (file: File | null) => void
  imageRefs: File[]
  imageRefType: string
  removeBackgroundRefs: boolean
  addImageRef: (file: File) => void
  removeImageRef: (index: number) => void
  reorderImageRefs: (from: number, to: number) => void
  setImageRefType: (type: string) => void
  setRemoveBackgroundRefs: (enabled: boolean) => void
  voiceCloneEnabled: boolean
  setVoiceCloneEnabled: (enabled: boolean) => void
  voiceCloneMode: 'single' | 'two'
  setVoiceCloneMode: (mode: 'single' | 'two') => void
  voiceCloneRefs: VoiceReference[]
  setVoiceCloneRef: (index: number, reference: VoiceReference | null) => void
  spatialUpsampling: string
  setSpatialUpsampling: (value: string) => void
  filmGrainIntensity: number
  setFilmGrainIntensity: (value: number) => void
  filmGrainSaturation: number
  setFilmGrainSaturation: (value: number) => void
  audioGuideFilename: string | null
  setAudioGuideFilename: (name: string | null) => void
  audioGuide2Filename: string | null
  setAudioGuide2Filename: (name: string | null) => void
  ttsSpeakerName1: string
  ttsSpeakerName2: string
  ttsSpeakerNamesManual: boolean
  setTtsSpeakerName1: (name: string) => void
  setTtsSpeakerName2: (name: string) => void
  _autoParseSpkeakerNames: (text: string, force?: boolean) => void
  ttsVoiceCount: number
  ttsVoices: TtsVoice[]
  setTtsVoiceCount: (count: number) => void
  setTtsVoiceName: (index: number, name: string) => void
  setTtsVoiceFile: (index: number, filename: string | null, path: string | null) => void
  addTtsVoice: () => void
  removeTtsVoice: (index: number) => void
  clips: MultiClip[]
  singlePromptMode: boolean
  studioFocusedClipIndex: number
  setClipPrompt: (index: number, prompt: string) => void
  setClipStartImage: (index: number, file: File | null) => void
  addClipKeyframe: (index: number, file: File) => void
  removeClipKeyframe: (index: number, keyframeIndex: number) => void
  setSinglePromptMode: (enabled: boolean) => void
  setStudioFocusedClipIndex: (index: number) => void
  syncClipCount: () => void
  promptSchedulerEnabled: boolean
  setPromptSchedulerEnabled: (enabled: boolean) => void
}

type SavedStudioParams = Partial<GenerateParams> & {
  filmGrainIntensity?: number
  filmGrainSaturation?: number
  durationSeconds?: number
}

interface StudioConfigurationHost extends StudioConfigurationSlice {
  params: GenerateParams
  modelOptions: ModelOptions | null
  h3WindowPlan: H3WindowPlan | null
  generationMode: GenerationMode
  savedParamsPerMode: Partial<Record<GenerationMode, SavedStudioParams>>
}

interface StudioConfigurationDependencies {
  alignFrameCount: (frames: number, options: ModelOptions | null) => number
  resolveResolution: (
    options: ModelOptions | null,
    preset: ResolutionPreset,
    ratio: AspectRatio,
  ) => string
}

export function createStudioConfigurationSlice(
  dependencies: StudioConfigurationDependencies,
): SliceCreator<StudioConfigurationSlice, StudioConfigurationHost> {
  return (set, get) => ({
    resolutionPreset: '720p',
    setResolutionPreset: preset => {
      const resolution = dependencies.resolveResolution(get().modelOptions, preset, get().aspectRatio)
      set(state => ({
        resolutionPreset: preset,
        params: { ...state.params, resolution },
        h3WindowPlan: null,
      }))
    },
    aspectRatio: '16:9',
    setAspectRatio: ratio => {
      const resolution = dependencies.resolveResolution(get().modelOptions, get().resolutionPreset, ratio)
      set(state => ({
        aspectRatio: ratio,
        params: { ...state.params, resolution },
        h3WindowPlan: null,
      }))
    },
    durationSeconds: 5,
    setDurationSeconds: requestedSeconds => {
      const options = get().modelOptions
      const fps = options?.fps ?? 16
      const minimum = Math.max(1, (options?.frames_minimum || fps) / fps)
      const nativeMaximum = options?.frames_maximum ? options.frames_maximum / fps : null
      const maximum = options?.sliding_window || nativeMaximum == null
        ? Number.POSITIVE_INFINITY
        : nativeMaximum
      let seconds = Math.min(maximum, Math.max(minimum, requestedSeconds))
      if (options?.sliding_window && nativeMaximum && seconds <= Math.round(nativeMaximum * 10) / 10) {
        seconds = Math.min(seconds, nativeMaximum)
      }
      const frames = dependencies.alignFrameCount(Math.round(seconds * fps), options)
      set(state => ({
        durationSeconds: seconds,
        params: { ...state.params, video_length: frames },
        h3WindowPlan: null,
      }))
      get().syncClipCount()
    },
    guideVideoFps: null,
    setGuideVideoFps: fps => set({ guideVideoFps: fps }),
    slidingWindowSeconds: 5,
    setSlidingWindowSeconds: requestedSeconds => {
      const options = get().modelOptions
      const fps = options?.fps ?? 16
      const defaults = options?.sliding_window_defaults
      let frames = Math.round(requestedSeconds * fps)
      if (defaults) {
        const minimum = defaults.window_min ?? 1
        const maximum = defaults.window_max ?? frames
        const step = Math.max(1, defaults.window_step ?? 1)
        frames = minimum + Math.round((frames - minimum) / step) * step
        frames = Math.max(minimum, Math.min(maximum, frames))
      }
      set(state => ({
        slidingWindowSeconds: frames / fps,
        params: { ...state.params, sliding_window_size: frames },
        h3WindowPlan: null,
      }))
      get().syncClipCount()
    },
    slidingWindowOverlap: 5,
    setSlidingWindowOverlap: frames => set(state => ({
      slidingWindowOverlap: frames,
      params: { ...state.params, sliding_window_overlap: frames },
      h3WindowPlan: null,
    })),
    slidingWindowLocked: false,
    setSlidingWindowLocked: locked => set({ slidingWindowLocked: locked, h3WindowPlan: null }),
    outputCount: 1,
    setOutputCount: count => set(state => ({
      outputCount: count,
      params: { ...state.params, repeat_generation: count },
    })),
    startImage: null,
    endImage: null,
    setStartImage: file => set(state => ({
      startImage: file,
      params: file === null ? { ...state.params, image_start: undefined } : state.params,
      h3WindowPlan: null,
    })),
    setEndImage: file => set(state => ({
      endImage: file,
      params: file === null ? { ...state.params, image_end: undefined } : state.params,
      h3WindowPlan: null,
    })),
    imageRefs: [],
    imageRefType: '',
    removeBackgroundRefs: false,
    addImageRef: file => set(state => ({ imageRefs: [...state.imageRefs, file] })),
    removeImageRef: index => set(state => {
      const imageRefs = state.imageRefs.filter((_, itemIndex) => itemIndex !== index)
      return {
        imageRefs,
        params: imageRefs.length === 0 ? { ...state.params, image_refs: undefined } : state.params,
      }
    }),
    reorderImageRefs: (from, to) => set(state => {
      const imageRefs = [...state.imageRefs]
      const [moved] = imageRefs.splice(from, 1)
      imageRefs.splice(to, 0, moved)
      return { imageRefs }
    }),
    setImageRefType: imageRefType => set({ imageRefType }),
    setRemoveBackgroundRefs: removeBackgroundRefs => set({ removeBackgroundRefs }),
    voiceCloneEnabled: false,
    setVoiceCloneEnabled: voiceCloneEnabled => set({ voiceCloneEnabled }),
    voiceCloneMode: 'single',
    setVoiceCloneMode: voiceCloneMode => set({ voiceCloneMode }),
    voiceCloneRefs: [],
    setVoiceCloneRef: (index, reference) => set(state => {
      const voiceCloneRefs = [...state.voiceCloneRefs]
      if (reference === null) voiceCloneRefs.splice(index, 1)
      else {
        while (voiceCloneRefs.length <= index) voiceCloneRefs.push({ filename: '', path: '' })
        voiceCloneRefs[index] = reference
      }
      return { voiceCloneRefs }
    }),
    spatialUpsampling: '',
    setSpatialUpsampling: spatialUpsampling => set({ spatialUpsampling }),
    filmGrainIntensity: 0,
    setFilmGrainIntensity: filmGrainIntensity => {
      set({ filmGrainIntensity })
      const state = get()
      set({
        savedParamsPerMode: {
          ...state.savedParamsPerMode,
          [state.generationMode]: {
            num_inference_steps: state.params.num_inference_steps,
            guidance_scale: state.params.guidance_scale,
            resolution: state.params.resolution,
            seed: state.params.seed,
            filmGrainIntensity,
            filmGrainSaturation: state.filmGrainSaturation,
          },
        },
      })
    },
    filmGrainSaturation: 0.5,
    setFilmGrainSaturation: filmGrainSaturation => {
      set({ filmGrainSaturation })
      const state = get()
      set({
        savedParamsPerMode: {
          ...state.savedParamsPerMode,
          [state.generationMode]: {
            num_inference_steps: state.params.num_inference_steps,
            guidance_scale: state.params.guidance_scale,
            resolution: state.params.resolution,
            seed: state.params.seed,
            filmGrainIntensity: state.filmGrainIntensity,
            filmGrainSaturation,
          },
        },
      })
    },
    audioGuideFilename: null,
    setAudioGuideFilename: audioGuideFilename => set({ audioGuideFilename }),
    audioGuide2Filename: null,
    setAudioGuide2Filename: audioGuide2Filename => set({ audioGuide2Filename }),
    ttsSpeakerName1: '',
    ttsSpeakerName2: '',
    ttsSpeakerNamesManual: false,
    setTtsSpeakerName1: name => set(state => {
      const ttsVoices = [...state.ttsVoices]
      if (ttsVoices.length > 0) ttsVoices[0] = { ...ttsVoices[0], name }
      return { ttsSpeakerName1: name, ttsSpeakerNamesManual: true, ttsVoices }
    }),
    setTtsSpeakerName2: name => set(state => {
      const ttsVoices = [...state.ttsVoices]
      if (ttsVoices.length > 1) ttsVoices[1] = { ...ttsVoices[1], name }
      return { ttsSpeakerName2: name, ttsSpeakerNamesManual: true, ttsVoices }
    }),
    _autoParseSpkeakerNames: (text, force) => {
      if (!force && get().ttsSpeakerNamesManual) return
      const matches = text.match(/^(.+?)\s*:/gm)
      if (!matches) return
      const names = [...new Set(matches.map(match => match.replace(/\s*:$/, '').trim()))]
      const voiceCount = get().ttsVoiceCount
      const ttsVoices = [...get().ttsVoices]
      while (ttsVoices.length < voiceCount) {
        ttsVoices.push({ name: '', filename: null, path: null })
      }
      for (let index = 0; index < Math.min(names.length, voiceCount); index += 1) {
        ttsVoices[index] = { ...ttsVoices[index], name: names[index] }
      }
      set({
        ttsVoices,
        ttsSpeakerName1: names[0] || '',
        ttsSpeakerName2: names[1] || '',
        ...(force ? { ttsSpeakerNamesManual: false } : {}),
      })
    },
    ttsVoiceCount: 0,
    ttsVoices: [],
    setTtsVoiceCount: count => {
      const previousCount = get().ttsVoiceCount
      const ttsVoices = [...get().ttsVoices]
      while (ttsVoices.length < count) ttsVoices.push({ name: '', filename: null, path: null })
      const selection = (get().modelOptions?.audio_prompt_type_sources?.selection as string[] | undefined) || ['', 'A', 'AB']
      const audioType = selection[Math.min(count, selection.length - 1)]
      set(state => ({
        ttsVoiceCount: count,
        ttsVoices: ttsVoices.slice(0, Math.max(count, ttsVoices.length)),
        params: { ...state.params, audio_prompt_type: audioType + ((state.params.audio_prompt_type as string || '').replace(/[^NV]/g, '')) },
      }))
      if (count > previousCount) {
        const prompt = get().params.prompt
        if (typeof prompt === 'string' && prompt.trim()) get()._autoParseSpkeakerNames(prompt, true)
      }
    },
    setTtsVoiceName: (index, name) => set(state => {
      const ttsVoices = [...state.ttsVoices]
      if (index < ttsVoices.length) ttsVoices[index] = { ...ttsVoices[index], name }
      return {
        ttsVoices,
        ttsSpeakerNamesManual: true,
        ...(index === 0 ? { ttsSpeakerName1: name } : {}),
        ...(index === 1 ? { ttsSpeakerName2: name } : {}),
      }
    }),
    setTtsVoiceFile: (index, filename, path) => set(state => {
      const ttsVoices = [...state.ttsVoices]
      if (index < ttsVoices.length) ttsVoices[index] = { ...ttsVoices[index], filename, path }
      return {
        ttsVoices,
        ...(index === 0 ? { audioGuideFilename: filename } : {}),
        ...(index === 1 ? { audioGuide2Filename: filename } : {}),
      }
    }),
    addTtsVoice: () => {
      const count = get().ttsVoiceCount
      const maximum = ((get().modelOptions as { max_voice_count?: number } | null)?.max_voice_count) ?? 6
      if (count < maximum) get().setTtsVoiceCount(count + 1)
    },
    removeTtsVoice: index => set(state => {
      const ttsVoices = state.ttsVoices.filter((_, voiceIndex) => voiceIndex !== index)
      const count = Math.max(0, state.ttsVoiceCount - 1)
      const selection = (state.modelOptions?.audio_prompt_type_sources?.selection as string[] | undefined) || ['', 'A', 'AB']
      const audioType = selection[Math.min(count, selection.length - 1)]
      return {
        ttsVoices,
        ttsVoiceCount: count,
        ttsSpeakerName1: ttsVoices[0]?.name || '',
        ttsSpeakerName2: ttsVoices[1]?.name || '',
        audioGuideFilename: ttsVoices[0]?.filename || null,
        audioGuide2Filename: ttsVoices[1]?.filename || null,
        params: { ...state.params, audio_prompt_type: audioType + ((state.params.audio_prompt_type as string || '').replace(/[^NV]/g, '')) },
      }
    }),
    clips: [],
    singlePromptMode: false,
    studioFocusedClipIndex: 0,
    setClipPrompt: (index, prompt) => {
      const clips = [...get().clips]
      if (!clips[index]) return
      clips[index] = { ...clips[index], prompt }
      set({ clips })
    },
    setClipStartImage: (index, file) => {
      const clips = [...get().clips]
      if (!clips[index]) return
      clips[index] = { ...clips[index], startImage: file, startImagePath: null }
      set({ clips })
    },
    addClipKeyframe: (index, file) => {
      const clips = [...get().clips]
      if (!clips[index]) return
      clips[index] = {
        ...clips[index],
        keyframes: [...(clips[index].keyframes || []), { file, path: null }],
      }
      set({ clips })
    },
    removeClipKeyframe: (index, keyframeIndex) => {
      const clips = [...get().clips]
      if (!clips[index]) return
      clips[index] = {
        ...clips[index],
        keyframes: (clips[index].keyframes || []).filter((_, itemIndex) => itemIndex !== keyframeIndex),
      }
      set({ clips })
    },
    setSinglePromptMode: singlePromptMode => set({ singlePromptMode }),
    setStudioFocusedClipIndex: index => set({
      studioFocusedClipIndex: Number.isFinite(index) ? Math.floor(index) : 0,
    }),
    syncClipCount: () => {
      const state = get()
      if (state.params.image_mode !== 2) return
      const fps = state.modelOptions?.fps ?? 16
      const overlapSeconds = state.slidingWindowOverlap / fps
      const effectiveWindow = state.slidingWindowSeconds - overlapSeconds
      const count = effectiveWindow > 0
        ? Math.max(1, Math.ceil((state.durationSeconds - overlapSeconds) / effectiveWindow))
        : Math.max(1, Math.ceil(state.durationSeconds / state.slidingWindowSeconds))
      if (count === state.clips.length) return
      if (count < state.clips.length) {
        set({ clips: state.clips.slice(0, count) })
        return
      }
      const clips = [...state.clips]
      for (let index = clips.length; index < count; index += 1) {
        clips.push({
          prompt: '',
          startImage: null,
          startImagePath: null,
          endImage: null,
          endImagePath: null,
          keyframes: [],
        })
      }
      set({ clips })
    },
    promptSchedulerEnabled: false,
    setPromptSchedulerEnabled: promptSchedulerEnabled => set({ promptSchedulerEnabled }),
  })
}
