import type { StoryWritingProvider } from '../stories/types'

export type SeriesApproval = 'draft' | 'approved'
export type SeriesFormat = 'serial' | 'episodic' | 'hybrid'
export type SeriesSourceMode = 'original' | 'known_universe_experimental' | 'hybrid'
export type SeriesRenderStrategy = 'auto' | 'direct' | 'first_frame' | 'references' | 'first_last'
export type SeriesEpisodeStatus = 'draft' | 'outline' | 'script' | 'shot_plan' | 'rendering' | 'completed' | 'archived'
export type SeriesAttemptStatus = 'queued' | 'running' | 'completed' | 'failed' | 'cancelled'

export interface SeriesAsset {
  id: string
  workspaceId: string
  kind: 'image' | 'audio' | 'video' | 'character' | 'location' | 'prop' | 'other'
  uri: string
  ownerType: 'series' | 'character' | 'location' | 'prop' | 'episode' | 'shot' | 'attempt'
  ownerId: string
  sourceAssetId?: string
  isDerivedThumbnail: boolean
  metadata: Record<string, unknown>
}

export interface CanonFact {
  id: string
  description: string
  sourceEpisodeId?: string | null
  status: 'draft' | 'proposed' | 'approved' | 'rejected' | 'retired'
}

export interface SeriesCanon {
  worldSummary: string
  immutableRules: CanonFact[]
  currentFacts: CanonFact[]
  forbiddenChanges: string[]
  themes: string[]
  longArcs: Array<{ id: string; title: string; description: string; status: 'planned' | 'active' | 'resolved' | 'abandoned' }>
  timeline: Array<CanonFact & { occurredAt: string }>
  revision: number
  approval: SeriesApproval
  approvedAt?: string
}

export interface SeriesVisualVariant {
  id: string
  label: string
  description: string
  referenceAssetIds: string[]
}

export interface SeriesVoiceProfile {
  provider?: string
  voiceId?: string
  language?: string
  pronunciationDictionary?: Record<string, string>
  pace?: number
  pitch?: number
  emotionalDefaults?: string
  approvedSampleAssetId?: string
  consentSourceNote?: string
  [key: string]: unknown
}

export interface SeriesCharacter {
  id: string
  name: string
  aliases: string[]
  role: string
  personality: string
  desire: string
  need: string
  flaw: string
  longArc: string
  voiceAndDialogue: string
  appearance: string
  identityLock: string
  defaultWardrobeVariantId?: string
  wardrobeVariants: SeriesVisualVariant[]
  referenceAssetIds: string[]
  primaryReferenceAssetId?: string
  voiceProfile?: SeriesVoiceProfile
  currentState: Record<string, unknown>
  approval: SeriesApproval
}

export interface SeriesLocation {
  id: string
  name: string
  purpose: string
  description: string
  referenceAssetIds: string[]
  variants: SeriesVisualVariant[]
  currentState: Record<string, unknown>
  approval: SeriesApproval
}

export interface SeriesProp {
  id: string
  name: string
  kind: string
  description: string
  ownerCharacterId: string
  referenceAssetIds: string[]
  variants: SeriesVisualVariant[]
  currentState: Record<string, unknown>
  approval: SeriesApproval
}

export interface SeriesRelationship {
  id: string
  fromCharacterId: string
  toCharacterId: string
  label: string
  dynamic: string
  evolution: string
  currentState?: string
}

export interface SeriesSeason {
  id: string
  number: number
  title: string
  premise: string
  arc: string
  episodeOrder: string[]
  createdAt: string
  updatedAt: string
}

export interface SeriesDialogueBeat {
  id: string
  characterId: string
  text: string
  emotion: string
  delivery: string
}

export interface SeriesScene {
  id: string
  order: number
  locationId: string
  locationVariantId?: string
  time: string
  participatingCharacterIds: string[]
  purpose: string
  entryState: string
  exitState: string
  beats: Array<{ id: string; kind: 'action' | 'dialogue'; summary: string }>
  dialogue: SeriesDialogueBeat[]
}

export interface SeriesSelectedReference {
  assetId: string
  entityType: 'continuity' | 'character' | 'location' | 'prop' | 'style' | 'motion'
  entityId: string
  variantId?: string
  referenceRole: string
  mediaType: 'image' | 'video' | 'audio'
  priority: number
  reason: string
}

export interface SeriesReferenceManifest {
  strategy: Exclude<SeriesRenderStrategy, 'auto'>
  selected: SeriesSelectedReference[]
  omitted: Array<Omit<SeriesSelectedReference, 'priority'>>
  warnings: string[]
  errors: string[]
  firstFrameRole: 'none' | 'exact' | 'visual_reference'
  capabilitySnapshot: Record<string, unknown>
}

export interface SeriesRenderAttempt {
  id: string
  status: SeriesAttemptStatus
  prompt: string
  negativePrompt: string
  model: string
  referenceManifest: SeriesReferenceManifest
  seed: number | null
  settings: Record<string, unknown>
  startTimeSeconds: number
  endTimeSeconds: number
  createdAt: string
  submittedAt?: string
  completedAt?: string
  elapsedMs: number
  requestPayloadHash?: string
  providerTaskId?: string
  outputAssetIds: string[]
  error?: string
  retryCount: number
  reviewDecision?: 'approved' | 'rejected'
  reviewedAt?: string
}

export interface SeriesShot {
  id: string
  sceneId: string
  order: number
  durationSeconds: number
  framing: string
  camera: string
  action: string
  dialogueBeats: SeriesDialogueBeat[]
  visibleCharacterIds: string[]
  speakingCharacterIds: string[]
  primarySpeakerId?: string
  locationId?: string
  locationVariantId?: string
  wardrobeByCharacterId: Record<string, string>
  propIds: string[]
  emotionalStateByCharacterId: Record<string, string>
  continuityFromShotId?: string
  renderStrategy: SeriesRenderStrategy
  referencePolicy: {
    mode: 'automatic' | 'manual'
    manualIncludeAssetIds: string[]
    manualExcludeAssetIds: string[]
    maxReferencesOverride?: number
  }
  prompt: string
  negativePrompt: string
  referenceManifest?: SeriesReferenceManifest
  attempts: SeriesRenderAttempt[]
  approvedAttemptId?: string
  audioDirection?: string
}

export interface SeriesCanonDeltaItem extends CanonFact {
  decision: 'pending' | 'accepted' | 'rejected'
  decidedAt?: string
}

export interface SeriesEpisode {
  id: string
  seasonId: string
  number: number
  title: string
  premise: string
  logline: string
  targetDurationSeconds: number
  status: SeriesEpisodeStatus
  canonRevisionAtCreation: number
  canonSnapshot: Record<string, unknown> & { revision: number }
  outline: { beats: string[] }
  script: SeriesScene[]
  shots: SeriesShot[]
  continuityIssues?: Array<{
    id: string; kind: string; severity: 'warning' | 'error'; message: string; sceneId?: string; shotId?: string
  }>
  proposedCanonDelta: {
    baseRevision: number
    sourceEpisodeId: string
    add: SeriesCanonDeltaItem[]
    change: SeriesCanonDeltaItem[]
    retire: Array<{ factId: string; decision: 'pending' | 'accepted' | 'rejected'; decidedAt?: string }>
  }
  productionIds: string[]
  createdAt: string
  updatedAt: string
}

export interface SeriesProviderSettings {
  useGlobalProfile: boolean
  writingProvider: StoryWritingProvider
  writingModel: string
  writingBaseUrl?: string
  imageProvider: string
  imageModel: string
  videoModel: string
  videoSettings: {
    renderStrategy?: SeriesRenderStrategy
    resolution?: string
    orientation?: 'landscape' | 'portrait'
    numInferenceSteps?: number
    [key: string]: unknown
  }
  videoCapabilities?: Record<string, unknown>
}

export interface SeriesProject {
  version: 1
  id: string
  revision: number
  title: string
  logline: string
  premise: string
  format: SeriesFormat
  defaultEpisodeDurationSeconds: number
  language: string
  genre: string
  tone: string
  audience: string
  visualStyle: string
  characterVisualStyle: string
  cameraLanguage: string
  allowClipText: boolean
  sourceMode: SeriesSourceMode
  masterUniversePrompt: string
  rightsNote: string
  bestEffortLipSyncAcknowledged: boolean
  importSource: {
    kind: 'story_import' | 'original'
    sourceWorkspaceId: string | null
    sourceStoryId: string | null
    importedAt: string
    historicalProductionIds: string[]
    migrationNotes: string
  }
  canon: SeriesCanon
  characters: SeriesCharacter[]
  relationships: SeriesRelationship[]
  locations: SeriesLocation[]
  props: SeriesProp[]
  seasons: SeriesSeason[]
  episodesById: Record<string, SeriesEpisode>
  assets: Record<string, SeriesAsset>
  provider: SeriesProviderSettings
  createdAt: string
  updatedAt: string
  [key: string]: unknown
}

export interface SeriesLibrary {
  schema: 'series-library'
  version: 1
  workspaceId: string
  seriesOrder: string[]
  seriesById: Record<string, SeriesProject>
}

export interface SeriesJobStatus {
  jobId: string
  jobType?: 'canon' | 'episode'
  workspace: string
  seriesId: string
  episodeId: string
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled'
  stage: string
  current: number
  total: number
  message: string
  error?: string | null
  episodeResult?: SeriesEpisode | null
  seriesResult?: (Pick<SeriesProject, 'canon' | 'characters' | 'relationships' | 'locations'> & Partial<Pick<
    SeriesProject,
    'title' | 'premise' | 'logline' | 'format' | 'defaultEpisodeDurationSeconds' | 'language' |
    'genre' | 'tone' | 'audience' | 'visualStyle' | 'characterVisualStyle' | 'cameraLanguage' |
    'sourceMode' | 'masterUniversePrompt' | 'rightsNote' | 'props'
  >>) | null
  generateImages?: boolean
  bootstrapKnownSeries?: boolean
  autoApply?: boolean
  autoApplied?: boolean
  appliedSeriesRevision?: number
  applyError?: string | null
  items?: Array<{
    shotId: string; attemptId: string; status: SeriesAttemptStatus; childJobId?: string | null
    outputAssetIds?: string[]; elapsedMs?: number; error?: string | null
  }>
  activeShotId?: string | null
  settings?: Record<string, unknown>
  seed?: number
  createdAt?: number
  updatedAt?: number
  finishedAt?: number
}
