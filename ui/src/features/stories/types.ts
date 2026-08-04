export type StoryWritingProvider =
  | 'maestro'
  | 'deepseek'
  | 'minimax'
  | 'openai'
  | 'openai-compatible'

export type StoryImageProvider = 'maestro' | 'minimax'
export type StoryApprovalState = 'draft' | 'approved'
export type StoryWorkflowMode = 'guided' | 'automatic'

export interface StoryVisualAsset {
  id: string
  name: string
  source: string
  prompt: string
  negativePrompt?: string
  provider: StoryImageProvider | 'upload'
  model?: string
  createdAt: string
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
  kind: 'comic' | 'film'
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
  name: string
  source: string
  prompt: string
  lyrics: string
  provider: 'minimax' | 'local'
  model: string
  durationSeconds: number
  createdAt: string
}

export interface StoryMusicDraft {
  mode: 'original' | 'cover'
  model: 'music-3.0' | 'music-2.6'
  brief: string
  style: string
  sourceLyrics: string
  lyrics: string
  coverReferenceFilename?: string
  coverReferenceName?: string
  targetDurationSeconds: number
  candidateCount: 2 | 3
  candidates: StoryMusicCandidate[]
  selectedCandidateId?: string
}

export interface StoryProviderSettings {
  writingProvider: StoryWritingProvider
  writingModel: string
  writingBaseUrl: string
  imageProvider: StoryImageProvider
  imageModel: string
}

export interface StoryProject {
  version: 1
  id: string
  revision: number
  sectionVersions: Record<'overview' | 'world' | 'characters' | 'relationships' | 'structure', number>
  title: string
  language: string
  genre: string
  tone: string
  audience: string
  premise: string
  logline: string
  synopsis: string
  theme: string
  ending: string
  workflowMode: StoryWorkflowMode
  provider: StoryProviderSettings
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

export type StoryGenerationScope = 'all' | 'overview' | 'world' | 'characters' | 'relationships' | 'structure'
