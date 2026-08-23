import type { AspectRatio, ResolutionPreset } from '../../types'

export type StoryWritingProvider =
  | 'maestro'
  | 'deepseek'
  | 'minimax'
  | 'openai'
  | 'openai-compatible'

export type StoryImageProvider = 'maestro' | 'minimax'
export type StoryApprovalState = 'draft' | 'approved'
export type StoryWorkflowMode = 'guided' | 'automatic'
export type StoryProjectType = 'full_story' | 'music_video' | 'trailer' | 'quick_video'
export type StoryMusicVideoGenerationMode = 'image_guided' | 'direct_references' | 'direct_video'
export type StoryDirectVideoPromptMode = 'inherit' | 'custom'
export type StoryQuickFormat = 'dialogue' | 'meme' | 'parody' | 'sketch' | 'viral' | 'announcement'
export type StoryTrailerFormat = 'theatrical' | 'teaser' | 'character'
export type StoryTrailerNarration = 'hybrid' | 'voice_over' | 'dialogue' | 'visual'
export type StoryTrailerSpoiler = 'mystery' | 'balanced' | 'revealing'
export type StoryTrailerIntensity = 'rising' | 'relentless' | 'prestige'
export type StoryAssetKind = 'world' | 'location' | 'character' | 'prop' | 'style' | 'ignore'

export interface StoryVisualAsset {
  id: string
  name: string
  source: string
  prompt: string
  negativePrompt?: string
  provider: StoryImageProvider | 'upload'
  model?: string
  createdAt: string
  /** Smart-import metadata remains editable/auditable after assignment. */
  assetKind?: StoryAssetKind
  description?: string
  confidence?: number
  originalName?: string
  importBatchId?: string
  /** Only approved assets are sent to downstream productions. */
  approval: StoryApprovalState
  /** Original upload or a non-destructive style variant derived from it. */
  variantKind?: 'original' | 'styled'
  /** Stable lineage keeps the real source beside every generated treatment. */
  derivedFromAssetId?: string
  /** Exact style instruction used to create a styled variant. */
  stylePrompt?: string
}

export interface StoryLocation {
  id: string
  name: string
  purpose: string
  description: string
  visualPrompt: string
  negativePrompt: string
  referenceAssetIds: string[]
}

export interface StoryWorld {
  summary: string
  period: string
  geography: string
  society: string
  technology: string
  rules: string[]
  visualLanguage: string
  visualPrompt: string
  negativePrompt: string
  locations: StoryLocation[]
  referenceAssetIds: string[]
}

export interface StoryCharacter {
  id: string
  name: string
  role: string
  age: string
  pronouns: string
  personality: string
  desire: string
  need: string
  flaw: string
  conflict: string
  arc: string
  voice: string
  appearance: string
  wardrobe: string
  visualPrompt: string
  negativePrompt: string
  referenceAssetIds: string[]
  primaryReferenceAssetId?: string
  approval: StoryApprovalState
}

export interface StoryRelationship {
  id: string
  fromCharacterId: string
  toCharacterId: string
  label: string
  dynamic: string
  evolution: string
}

export interface StoryBeat {
  id: string
  stage: string
  title: string
  summary: string
  goal: string
  conflict: string
  turn: string
}

export interface StoryProduction {
  id: string
  kind: 'comic' | 'film' | 'music_video' | 'trailer'
  title: string
  createdAt: string
  sourceVersion: number
  sourceSnapshot?: Partial<StoryProject>
  targetId?: string
  targetName?: string
  /** Reopenable staged payload. Kept deliberately generic to avoid coupling story data to an editor schema. */
  targetSnapshot?: Record<string, unknown>
  status: 'draft' | 'staged'
}

export interface StoryMusicCandidate {
  id: string
  /** Human-readable identity; the provider filename remains in `name`. */
  displayName?: string
  title?: string
  language?: string
  version?: number
  name: string
  source: string
  prompt: string
  lyrics: string
  provider: 'minimax' | 'lyria' | 'local'
  model: string
  durationSeconds: number
  createdAt: string
  /** Canonical backend identity for audit, cancellation and exact output correlation. */
  taskId?: string
  rootTaskId?: string
}

export interface StoryMusicCue {
  id: string
  kind: 'world' | 'character' | 'story'
  targetId: string
  title: string
  purpose: string
  /** Editable inspiration input; generation must reinterpret, never copy it. */
  referenceSong: string
  brief: string
  style: string
  lyrics: string
  /** Language of the current editable lyrics, updated by lyric translation. */
  lyricsLanguage?: string
  /** Paste-ready Google AI Studio prompt; Maestro does not call Lyria directly. */
  lyriaPrompt: string
  instrumental: boolean
  durationSeconds: number
  candidates: StoryMusicCandidate[]
  selectedCandidateId?: string
}

export interface StoryMusicDraft {
  mode: 'original' | 'cover'
  model: 'music-3.0' | 'music-2.6' | 'ace_step_v1_5_xl_sft_lm_4b'
  brief: string
  style: string
  sourceLyrics: string
  lyrics: string
  lyricsLanguage?: string
  coverReferenceFilename?: string
  coverReferenceName?: string
  targetDurationSeconds: number
  candidateCount: 2 | 3
  cues: StoryMusicCue[]
  candidates: StoryMusicCandidate[]
  selectedCandidateId?: string
}

export interface StoryProviderSettings {
  /** New projects inherit the global production profile; legacy projects default to an explicit override. */
  useGlobalProfile: boolean
  writingProvider: StoryWritingProvider
  writingModel: string
  writingBaseUrl: string
  imageProvider: StoryImageProvider
  imageModel: string
}

export interface StoryVideoOverride {
  /** Empty only while a legacy project captures the old shared Director selection once. */
  model: string
  resolution: ResolutionPreset
  aspectRatio: AspectRatio
}

export interface StoryProject {
  version: 1
  id: string
  revision: number
  sectionVersions: Record<'overview' | 'world' | 'characters' | 'relationships' | 'structure', number>
  title: string
  projectType: StoryProjectType
  creativeBrief: {
    /** One free-form source brief: idea, style, avatar requirements and successful prompt examples. */
    generalIdea: string
    context: string
    performer: string
    musicStyle: string
    songStory: string
    subjects: string
    setting: string
    action: string
    quickFormat: StoryQuickFormat
    durationSeconds: number
  }
  language: string
  /** Exact spoken language/accent contract for generated native video audio. Empty means auto. */
  spokenLanguage: string
  /** Prefer distinct settings across music-video clips instead of repeating one scene. */
  locationVariety: 'balanced' | 'single_location'
  /** Require one approved primary protagonist image before video production. */
  protagonistConsistency: boolean
  protagonistCharacterId: string
  genre: string
  tone: string
  audience: string
  /** Global art direction, kept separate from narrative and subject prompts. */
  visualStyle: string
  /** Rendering/material contract applied consistently to every visible person. */
  characterVisualStyle: string
  /** Compose visualStyle as a highest-priority lock whenever Story renders an image. */
  enforceVisualStyle: boolean
  /** Permit intentional readable lettering inside generated video clips. */
  allowClipText: boolean
  /** Music-video rendering path selected in Story Lab Productions. */
  musicVideoGenerationMode: StoryMusicVideoGenerationMode
  /** Keep the direct-video master prompt synchronized with the Story visual-style fields or edit it independently. */
  directVideoMasterPromptMode: StoryDirectVideoPromptMode
  /** Immutable world/style contract repeated in every direct T2V request. */
  directVideoMasterPrompt: string
  premise: string
  logline: string
  synopsis: string
  theme: string
  ending: string
  workflowMode: StoryWorkflowMode
  provider: StoryProviderSettings
  /** Durable Story-only video recipe; ignored while the global profile is inherited. */
  videoOverride: StoryVideoOverride
  world: StoryWorld
  characters: StoryCharacter[]
  relationships: StoryRelationship[]
  beats: StoryBeat[]
  assets: Record<string, StoryVisualAsset>
  /** Durable local Maestro image jobs, keyed by world/character/location target. */
  visualJobs: Record<string, string>
  music: StoryMusicDraft
  productions: StoryProduction[]
  approvals: {
    overview?: { approvedAt: string; version: number }
    world?: { approvedAt: string; version: number }
    characters?: { approvedAt: string; version: number }
    relationships?: { approvedAt: string; version: number }
    structure?: { approvedAt: string; version: number }
  }
  createdAt: string
  updatedAt: string
}

export type StoryGenerationScope = 'all' | 'overview' | 'world' | 'characters' | 'relationships' | 'structure' | 'music'
