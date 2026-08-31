import type {
  AspectRatio,
  AudioAnalysisResult,
  ClipPlan,
  DirectorClipImage,
  DirectorImageGenProgress,
  DirectorShotImageGuidance,
  DirectorV2PlanJob,
  MusicVideoTreatment,
  PlannedClip,
  ResolutionPreset,
  ShortFilmCharacter,
  ShortFilmPath,
  SpeakerMapping,
} from '../types'
import { DEFAULT_DIRECT_VIDEO_MASTER_PROMPT } from '../types'

export type DirectorSlice = {
  directorStep: 'upload' | 'analyze' | 'structure' | 'style' | 'plan' | 'review' | 'generate_images' | 'plan_video' | 'review_video'
  directorAudioFile: File | null
  directorAudioPath: string | null
  directorAnalysis: AudioAnalysisResult | null
  directorPlannedClips: PlannedClip[]
  directorEnergyBias: number
  directorPacingProfile: 'cinematic' | 'balanced' | 'rhythmic'
  directorMusicVideoTreatment: MusicVideoTreatment
  setDirectorMusicVideoTreatment: (partial: Partial<MusicVideoTreatment>) => void
  directorClipPlans: ClipPlan[]
  directorSceneDescription: string
  directorSpokenLanguage: string
  directorLoading: boolean
  directorLoadingMessage: string | null
  directorError: string | null
  directorPlanRecovery: DirectorV2PlanJob | null
  directorReferenceImage: File | null
  directorReferenceImagePath: string | null
  directorCharacterRefs: File[]
  directorCharacterRefPaths: string[]
  directorCharacterRefLabels: string[]
  directorLocationRefs: File[]
  directorLocationRefPaths: string[]
  directorLocationRefLabels: string[]
  directorH3VideoRefs: File[]
  directorH3VideoRefPaths: string[]
  directorH3AudioRefs: File[]
  directorH3AudioRefPaths: string[]
  directorVoiceRef: File | null
  directorVoiceRefPath: string | null
  directorIdentityGuidanceScale: number
  setDirectorVoiceRef: (file: File | null) => void
  setDirectorIdentityGuidanceScale: (v: number) => void
  directorClipImages: DirectorClipImage[]
  directorImageGenProgress: DirectorImageGenProgress | null
  directorSpeakers: string[]
  directorSpeakerMappings: SpeakerMapping[]
  directorAutoMode: boolean
  directorSeamless: boolean
  directorShotImageGuidance: DirectorShotImageGuidance
  directorLlmLog: { stage: string; text: string }[]
  directorAppendLlmLog: (stage: string, text: string) => void
  directorResolution: ResolutionPreset
  directorAspectRatio: AspectRatio
  directorVideoInferenceStepsByModel: Record<string, number>
  directorVideoMaxShotFramesByModel: Record<string, number>
  directorH3TurboModeByModel: Record<string, boolean>
  setDirectorAutoMode: (v: boolean) => void
  setDirectorSeamless: (v: boolean) => void
  setDirectorShotImageGuidance: (v: DirectorShotImageGuidance) => void
  setDirectorResolution: (preset: ResolutionPreset) => void
  setDirectorAspectRatio: (ratio: AspectRatio) => void
  setDirectorVideoInferenceSteps: (modelType: string, steps: number | null) => void
  setDirectorVideoMaxShotFrames: (modelType: string, frames: number | null) => void
  setDirectorH3TurboMode: (modelType: string, enabled: boolean) => void
  shortFilmCharacters: ShortFilmCharacter[]
  shortFilmPath: ShortFilmPath | null
  shortFilmTargetDuration: number
  directorMusicSource: 'upload' | 'generate' | null
  directorSongDescription: string
  directorSongInstrumental: boolean
  directorSongStyle: string
  directorSongLyrics: string
  directorSongDuration: number
  directorTrackGenerating: boolean
  setDirectorMusicSource: (s: 'upload' | 'generate' | null) => void
  setDirectorSongDescription: (v: string) => void
  setDirectorSongInstrumental: (v: boolean) => void
  setDirectorSongStyle: (v: string) => void
  setDirectorSongLyrics: (v: string) => void
  setDirectorSongDuration: (v: number) => void
  directorWritingProvider: 'maestro' | 'deepseek' | 'minimax' | 'openai' | 'openai-compatible' | 'ollama' | 'grok'
  directorWritingModel: string
  directorWritingBaseUrl: string
  shortFilmNarrative: boolean
  shortFilmVisualStyle: string
  shortFilmPreserveVisualStyle: boolean
  directorCharacterVisualStyle: string
  directorAllowClipText: boolean
}

export type DirectorState = DirectorSlice & { directorSeamless: boolean }
type SetDirectorState = (
  partial: Partial<DirectorState> | ((state: DirectorState) => Partial<DirectorState>),
) => void

const defaultTreatment = (): MusicVideoTreatment => ({
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
})

/**
 * Director's state and local reducers. Async orchestration remains in the
 * store for now; this slice gives it a stable, compatible state boundary.
 */
export function createDirectorSlice(set: SetDirectorState): DirectorSlice {
  return {
    directorStep: 'upload',
    directorAudioFile: null,
    directorAudioPath: null,
    directorAnalysis: null,
    directorPlannedClips: [],
    directorEnergyBias: 0,
    directorPacingProfile: 'balanced',
    directorMusicVideoTreatment: defaultTreatment(),
    setDirectorMusicVideoTreatment: partial => set(state => ({
      directorMusicVideoTreatment: { ...state.directorMusicVideoTreatment, ...partial },
      ...(partial.generation_mode === 'direct_video' ? { directorSeamless: false } : {}),
    })),
    directorClipPlans: [],
    directorSceneDescription: '',
    directorSpokenLanguage: 'Español de España',
    directorLoading: false,
    directorLoadingMessage: null,
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
    directorIdentityGuidanceScale: 3.0,
    setDirectorVoiceRef: file => set(file
      ? { directorVoiceRef: file, directorVoiceRefPath: null }
      : { directorVoiceRef: null, directorVoiceRefPath: null }),
    setDirectorIdentityGuidanceScale: v => set({ directorIdentityGuidanceScale: v }),
    directorClipImages: [],
    directorImageGenProgress: null,
    directorSpeakers: [],
    directorSpeakerMappings: [],
    directorAutoMode: true,
    directorSeamless: false,
    directorShotImageGuidance: 'auto',
    directorLlmLog: [],
    directorAppendLlmLog: (stage, text) => set(state => {
      const trimmed = (text || '').trim()
      if (!trimmed) return {}
      const last = state.directorLlmLog[state.directorLlmLog.length - 1]
      if (last && last.stage === stage && last.text === trimmed) return {}
      return { directorLlmLog: [...state.directorLlmLog, { stage, text: trimmed }] }
    }),
    directorResolution: '720p',
    directorAspectRatio: '16:9',
    directorVideoInferenceStepsByModel: {},
    directorVideoMaxShotFramesByModel: {},
    directorH3TurboModeByModel: {},
    setDirectorAutoMode: v => set({ directorAutoMode: v }),
    setDirectorSeamless: v => set({ directorSeamless: v }),
    setDirectorShotImageGuidance: v => set({ directorShotImageGuidance: v }),
    setDirectorResolution: preset => set({ directorResolution: preset }),
    setDirectorAspectRatio: ratio => set({ directorAspectRatio: ratio }),
    setDirectorVideoInferenceSteps: (modelType, steps) => set(state => {
      const next = { ...state.directorVideoInferenceStepsByModel }
      if (steps == null || !Number.isFinite(steps)) delete next[modelType]
      else next[modelType] = Math.max(1, Math.min(50, Math.round(steps)))
      return { directorVideoInferenceStepsByModel: next }
    }),
    setDirectorVideoMaxShotFrames: (modelType, frames) => set(state => {
      const next = { ...state.directorVideoMaxShotFramesByModel }
      if (frames == null || !Number.isFinite(frames) || frames <= 0) delete next[modelType]
      else next[modelType] = Math.round(frames)
      return { directorVideoMaxShotFramesByModel: next }
    }),
    setDirectorH3TurboMode: (modelType, enabled) => set(state => ({
      directorH3TurboModeByModel: { ...state.directorH3TurboModeByModel, [modelType]: enabled },
    })),
    shortFilmCharacters: [],
    shortFilmPath: null,
    shortFilmTargetDuration: 30,
    directorMusicSource: null,
    directorSongDescription: '',
    directorSongInstrumental: false,
    directorSongStyle: '',
    directorSongLyrics: '',
    directorSongDuration: 120,
    directorTrackGenerating: false,
    setDirectorMusicSource: s => set({ directorMusicSource: s }),
    setDirectorSongDescription: v => set({ directorSongDescription: v }),
    setDirectorSongInstrumental: v => set({ directorSongInstrumental: v }),
    setDirectorSongStyle: v => set({ directorSongStyle: v }),
    setDirectorSongLyrics: v => set({ directorSongLyrics: v }),
    setDirectorSongDuration: v => set({ directorSongDuration: v }),
    directorWritingProvider: 'maestro',
    directorWritingModel: '',
    directorWritingBaseUrl: '',
    shortFilmNarrative: false,
    shortFilmVisualStyle: '',
    shortFilmPreserveVisualStyle: true,
    directorCharacterVisualStyle: '',
    directorAllowClipText: false,
  }
}
