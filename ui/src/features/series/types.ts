import type { StoryWritingProvider } from '../stories/types'
import type { LanguageIntent } from '../../lib/languageIntent'

export type SeriesApproval = 'draft' | 'approved'
export type SeriesFormat = 'serial' | 'episodic' | 'hybrid'
export type SeriesSourceMode = 'original' | 'known_universe_experimental' | 'hybrid'
export type SeriesRenderStrategy = 'auto' | 'direct' | 'first_frame' | 'references' | 'first_last'
export type SeriesProductionMethod = 'generated_video' | 'animation_2d' | 'animation_3d' | 'imported_video'
export type SeriesEpisodeStatus = 'draft' | 'outline' | 'script' | 'shot_plan' | 'rendering' | 'completed' | 'archived'
export type SeriesAttemptStatus = 'queued' | 'running' | 'cancelling' | 'completed' | 'failed' | 'cancelled'

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
  characterKitRef?: import('../../lib/characterVoice').CharacterKitRef
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

/** A layer of a 2D set (series_layers.py): a PNG with alpha or a looping video at a depth, 0 the background's far
 * plane (moves least), 1 the nearest. `front` draws it over the cast. x/y (%) put its centre on the background;
 * scale is a fraction of the frame height. A camera push moves each layer by its depth. */
export interface SeriesSetLayer {
  assetId?: string
  file?: string
  depth: number
  front: boolean
  opacity: number
  x: number
  y: number
  scale: number
  /** Idle drift in frame pixels per second, negative to the left (fog, smoke). */
  drift?: number
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
  /** 2D series layout: a background or 3D plate asset, character homes (x %), the plate render state, and set layers
   * with the depth the cast stands at among them (default 0.6). */
  layout2d?: { plateAssetId?: string; backgroundAssetId?: string; homes?: Record<string, number>; plate3d?: Record<string, unknown>
    layers?: SeriesSetLayer[]; castDepth?: number }
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
  /** The room this line alone is heard in, on screen or off (`none` keeps it dry); else the shot's, for its cast. */
  voiceRoom?: SeriesVoiceRoom
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
  /** Who approved or reviewed the take: a person, an MCP agent, Ask to the Wizard or the server render's own approval. */
  approvedBy?: 'user' | 'agent' | 'wizard' | 'server'
  reviewedBy?: 'user' | 'agent' | 'wizard' | 'server'
  reviewDecision?: 'approved' | 'rejected'
  reviewedAt?: string
  /** Set by the server render in a staged production: a cheap preview to review, or the final take. */
  reviewStage?: 'preview' | 'final'
}

/** How an episode is produced: everything at once, plan approval first, or plan + preview approval before the final. */
export type SeriesProductionMode = 'direct' | 'plan' | 'preview'
export type SeriesReviewStatus = 'pending' | 'approved' | 'changes'
export type SeriesReviewStage = 'plan' | 'preview' | 'final'

export interface SeriesReviewNote {
  id: string
  at: string
  stage: SeriesReviewStage
  text: string
  by: SeriesReviewAuthor
}

/** Who decided or wrote: a person, an MCP agent, Ask to the Wizard, or a production approving on its own. */
export type SeriesReviewAuthor = 'user' | 'agent' | 'wizard' | 'server'

/** One shot's review (server-owned). A shot without an entry is pending at every stage. */
export interface SeriesShotReview {
  plan: SeriesReviewStatus
  planAt?: string
  planDigest?: string
  planBy?: SeriesReviewAuthor
  preview: SeriesReviewStatus
  previewAt?: string
  previewDigest?: string
  previewBy?: SeriesReviewAuthor
  /** The take the preview decision is about. */
  previewAttemptId?: string
  notes: SeriesReviewNote[]
}

export interface SeriesEpisodeReview {
  mode: SeriesProductionMode
  updatedAt?: string
  shots: Record<string, SeriesShotReview>
}

/** One change sent to POST /review; the server validates it and owns the stored state. */
export interface SeriesShotReviewChange {
  shotId: string
  plan?: SeriesReviewStatus
  preview?: SeriesReviewStatus
  attemptId?: string
  note?: { id?: string; text: string; stage?: SeriesReviewStage; by?: 'user' | 'agent' }
  removeNoteId?: string
}

export interface SeriesReviewChange {
  baseRevision?: number
  mode?: SeriesProductionMode
  shots?: SeriesShotReviewChange[]
}

export interface SeriesReviewReply {
  revision: number
  episodeId: string
  episodeUpdatedAt: string
  review: SeriesEpisodeReview
  noteIds?: Record<string, string>
  summary?: Record<string, unknown>
}

/** A Video 3D shot (series_shot3d.normalize_scene3d): a template or a saved scene, its cast and objects. */
export interface SeriesShotScene3D {
  template?: string
  scene?: string
  cast?: Array<{ characterId: string; objectId?: string; poseId?: string }>
  objects?: Array<Record<string, unknown>>
  quality?: 'draft' | 'final'
  renderLook?: string
  [key: string]: unknown
}

/** Sound generated from the shot's rendered picture (MMAudio) and mixed under its take; volume is relative to the dialogue. */
export interface SeriesShotFoley {
  prompt: string
  /** Above 0 and up to 2; default 0.5. */
  volume?: number
}

export interface SeriesShot {
  id: string
  sceneId: string
  order: number
  durationSeconds: number
  dialogueDuration?: {
    model: string
    durationMode: 'continuous' | 'discrete' | 'frame_lattice'
    wordCount: number
    syllableCount: number
    secondsPerSyllable: number
    segmentCount: number
    spokenSeconds: number
    estimatedVoiceSeconds: number
    requestedClipSeconds: number
    minimumLimited: boolean
    requiresSplit: boolean
    modelMinimumSeconds: number
    modelMaximumSeconds: number
    fps?: number
    calculatedFrames?: number
    effectiveFrames?: number
    frameLattice?: string
  }
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
  productionMethod?: SeriesProductionMethod
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
  sourceDialogueIds?: string[]
  dialogueOrigin?: 'script' | 'manual'
  scriptDialogueStatus?: 'in_sync' | 'stale' | 'manual_conflict'
  foley?: SeriesShotFoley
  layout2d?: SeriesShotLayout2D
  scene3d?: SeriesShotScene3D
}

/** A shot's 2D plan (series_shot_plan.normalize_layout2d); only the set layers are typed here. Its `layers` replace the
 * location's and `[]` turns them off for this shot; `castDepth` overrides the location's. */
export interface SeriesShotLayout2D {
  layers?: SeriesSetLayer[]
  castDepth?: number
  framing?: 'wide' | 'two' | 'medium' | 'close' | 'insert' | 'title'
  camera?: 'static' | 'push'
  cast?: SeriesShotCastEntry[]
  timing?: { intro?: number; gap?: number; tail?: number }
  [key: string]: unknown
}

/** A cast member of a 2D shot: the character, its Character Kit pose and where it stands (x % of the frame). */
export interface SeriesShotCastEntry {
  characterId: string
  poseId?: string
  x?: number
  scale?: number
  [key: string]: unknown
}

export interface SeriesCanonDeltaItem extends CanonFact {
  decision: 'pending' | 'accepted' | 'rejected'
  decidedAt?: string
}

export interface SeriesLanguageVersion {
  title?: string
  /** Text of each line by its beat id; the shots and line ids are shared with the original. */
  dialogue: Record<string, string>
  cards: Record<string, { title: string; body: string }>
  approvedAttemptIds: Record<string, string>
  assemblyAssetIds: string[]
  latestAssemblyAssetId?: string
  thumbnailAssetId?: string
}

/**
 * One cue of an episode's score: music the assembly lays from the cut before `fromShotId` to the cut after
 * `toShotId` (or over the shots of `sceneId`), looped if shorter and faded in and out inside the cue. With `duck` it
 * dips 9 dB under every recorded line; it is silent under a shot with its own `layout2d.music`. Cues never overlap.
 */
export type SeriesScoreCue = ({ fromShotId: string; toShotId?: string; sceneId?: never } | { sceneId: string; fromShotId?: never; toShotId?: never }) & {
  /** Workspace audio file. */
  file: string
  /** Level relative to the dialogue, 0–2 (default 0.18). */
  volume?: number
  /** Seconds, 0–30 (defaults 1.5 and 2.0). */
  fadeIn?: number
  fadeOut?: number
  /** Lower it under the lines (default true). */
  duck?: boolean
}

export interface SeriesEpisode {
  /** Music laid under runs of shots at assembly; no take depends on it. */
  score?: SeriesScoreCue[]
  /** Dubbed versions by spoken language (english, spanish...); the series language is the original. */
  languageVersions?: Record<string, SeriesLanguageVersion>
  latestAssemblyAssetId?: string
  assemblyAssetIds?: string[]
  /** A frame of the latest cut (after its title card), set by the assembly. */
  thumbnailAssetId?: string
  /** Staged production and per-shot approvals (server-owned; absent means direct, everything pending). */
  review?: SeriesEpisodeReview
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

/** A workspace sound and its level relative to the dialogue (0–2). */
export interface SeriesSoundCue {
  file: string
  volume?: number
}

/** A room the recorded voices are heard in: a processed copy of each line (the dry recording is kept). `none` is dry. */
export type SeriesVoiceRoom = 'none' | 'small_room' | 'room' | 'hall' | 'cathedral' | 'cockpit' | 'outdoor' | 'radio'

/**
 * Sound every shot gets without the script naming it. `ambienceMode` `shot` (default) mixes the location's ambience
 * into each shot; `episode` leaves it out of the shots and the assembly lays one continuous bed per location run.
 * `roomByLocation` makes the voices of the people in a shot sound like the place; a shot's `layout2d.voiceRoom`
 * overrides it and a line's `voiceRoom` overrides both.
 */
export interface SeriesSoundDesign {
  stinger?: SeriesSoundCue
  ambienceByLocation?: Record<string, SeriesSoundCue>
  ambienceMode?: 'shot' | 'episode'
  roomByLocation?: Record<string, SeriesVoiceRoom>
  /** dB the episode-mode beds dip while someone speaks, 0–24 (default 0: off). */
  ambienceDuckDb?: number
}

export interface SeriesProject {
  allowedProductionMethods?: SeriesProductionMethod[]
  version: 1
  id: string
  revision: number
  title: string
  logline: string
  premise: string
  format: SeriesFormat
  defaultEpisodeDurationSeconds: number
  language: string
  spokenLanguage: string
  languageIntent: LanguageIntent
  protagonistConsistency: boolean
  protagonistCharacterId: string
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
  soundDesign?: SeriesSoundDesign
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
  taskId?: string | null
  rootTaskId?: string | null
  jobType?: 'canon' | 'episode'
  workspace: string
  seriesId: string
  episodeId: string
  status: 'queued' | 'running' | 'cancelling' | 'completed' | 'failed' | 'cancelled'
  stage: string
  current: number
  total: number
  message: string
  error?: string | null
  episodeResult?: SeriesEpisode | null
  seriesResult?: (Pick<SeriesProject, 'canon' | 'characters' | 'relationships' | 'locations'> & Partial<Pick<
    SeriesProject,
    'title' | 'premise' | 'logline' | 'format' | 'defaultEpisodeDurationSeconds' | 'language' |
    'spokenLanguage' | 'protagonistConsistency' | 'protagonistCharacterId' |
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

export type {
  SeriesAssemblyActionRequest,
  SeriesAssemblyDiscardResponse,
  SeriesAssemblyJob,
  SeriesAssemblyJobResponse,
  SeriesAssemblyRecoveryResponse,
  SeriesAssemblyStartRequest,
  SeriesAssemblyStatus,
} from './assemblyContract'
