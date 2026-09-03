import { getModelsForFamily, getFamiliesForMode, useStore } from '../../stores/useStore'
import { comicArtworkInventory } from '../comics/generateArtwork'
import { buildWizardContextSnapshot, buildWizardLabSnapshots, comicLabSnapshot, type BuildWizardContextOptions, type WizardContextSnapshot } from './wizardContext'
import type { AspectRatio, ResolutionPreset } from '../../types'
import type { AgentExecutionReport, AgentExecutionTarget } from './agentContract'
import type { CommandEnvelope, CommandResult } from './commandContract'
import {
  bindDirectorProductionTarget,
  bindGenerateComicTarget,
  executionKey,
  executionReport,
  inferExecutionState,
  isExpensiveAction,
  orderCompoundActions,
  requiredPredecessor,
  rememberExecution,
  reuseExecution,
} from './agentContract'
import type {
  AgentApplyCharacterKitPresetAction,
  AgentAttachCharacterKitReferencesAction,
  AgentBuildCharacterKitAction,
  AgentCreateCharacterKitAction,
  AgentOpenCharacterKitAction,
  AgentOpenCharacterKitRigAction,
  AgentTrackCharacterKitJobAction,
  AgentUpdateCharacterKitAction,
} from './characterKitActions'
import type {
  AgentAddVideoEditorAudioAction,
  AgentAddVideoEditorClipsAction,
  AgentCreateVideoEditorProjectAction,
  AgentExportVideoEditorAction,
  AgentOpenVideoEditorProjectAction,
  AgentOrderVideoEditorClipsAction,
  AgentTrackVideoEditorExportAction,
  AgentTrimVideoEditorClipAction,
  AgentValidateVideoEditorTimelineAction,
} from './videoEditorActions'
import type {
  AgentAttachVideoclipAlternativeSongAction,
  AgentMountVideoclipAlternativeSongAction,
} from './alternativeSongActions'
import type { ExampleConversation } from './agentExamples'
import type { AgentSeriesSection, AgentStorySection } from './agentUiBus'
import { ARCADE_HORDE_SFX_PACK, type AgentSfxClip } from './sfxPack'
import {
  AGENT_TABS,
  currentAgentInterfaceLanguage,
  extractVerbatimSegments,
  getCapability,
  isLanguageAwareCapability,
  LANGUAGE_INTENT_SCHEMA,
  listCapabilities,
  mergeLanguageIntent,
  normalizeLanguageIntent,
  normalizeConversationLanguageTag,
  parseRegisteredCapability,
  registeredCapabilitySchemas,
  type AgentTab,
  type LanguageIntent,
} from './capabilityRegistry'
import { defaultApplicationAdapters } from './applicationAdapters'
import { runRegisteredCapability } from './capabilityRunner'
import { inferStoryProjectTypeFromText, isNewMusicVideoSongRequest, newMusicVideoStoryAction } from '../stories/musicVideoLook'

export { isNewMusicVideoSongRequest } from '../stories/musicVideoLook'

export type { ExampleConversation }
export { AGENT_TABS }
export type { AgentTab }

export interface AgentLanguageAwareAction {
  languageIntent?: LanguageIntent
}

export interface AgentOpenTabAction {
  type: 'open_tab'
  tab: AgentTab
}

export interface AgentPrepareVideoAction extends AgentLanguageAwareAction {
  type: 'prepare_video'
  prompt: string
  modelType?: string
  durationSeconds?: number
  resolutionPreset?: ResolutionPreset
  resolution?: string
  aspectRatio?: AspectRatio
  negativePrompt?: string
  seed?: number
  inferenceSteps?: number
  guidanceScale?: number
  outputCount?: number
  audioDirection?: string
  turbo?: boolean
}

export interface AgentPrepareImageAction extends AgentLanguageAwareAction {
  type: 'prepare_image'
  prompt: string
  modelType?: string
  resolutionPreset?: ResolutionPreset
  resolution?: string
  aspectRatio?: AspectRatio
  negativePrompt?: string
  seed?: number
  inferenceSteps?: number
  guidanceScale?: number
  outputCount?: number
}

export interface AgentPrepareAudioAction extends AgentLanguageAwareAction {
  type: 'prepare_audio'
  subMode: 'speech' | 'music' | 'sfx'
  prompt: string
  modelType?: string
  durationSeconds?: number
  negativePrompt?: string
}

export interface AgentQueueSfxPackAction extends AgentLanguageAwareAction {
  type: 'queue_sfx_pack'
  style: string
  clips: AgentSfxClip[]
  modelType?: string
  negativePrompt?: string
  confirm: true
}

export interface AgentPrepare3dAction extends AgentLanguageAwareAction {
  type: 'prepare_3d'
  prompt: string
  modelType?: string
  preset?: string
  seed?: number
}

export interface AgentStartGenerationAction {
  type: 'start_generation'
  confirm: true
}

export interface AgentOpenStorySectionAction {
  type: 'open_story_section'
  section: AgentStorySection
}

export interface AgentOpenSeriesSectionAction {
  type: 'open_series_section'
  section: AgentSeriesSection
}

export interface AgentCreativeCharacter {
  name: string
  role: string
  personality: string
  desire: string
  flaw: string
  appearance: string
  voice: string
}

export interface AgentCreativeLocation {
  name: string
  purpose: string
  description: string
}

export interface AgentCreateStoryAction extends AgentLanguageAwareAction {
  type: 'create_story'
  title: string
  projectType: 'full_story' | 'music_video' | 'trailer' | 'quick_video'
  creativeBrief: string
  premise: string
  logline: string
  synopsis: string
  theme: string
  ending: string
  genre: string
  tone: string
  visualStyle: string
  worldSummary: string
  language: string
  characters: AgentCreativeCharacter[]
  locations: AgentCreativeLocation[]
  outlineBeats: string[]
  durationSeconds?: number
}

export interface AgentUpdateStoryAction extends AgentLanguageAwareAction {
  type: 'update_story'
  targetStoryTitle: string
  title: string
  creativeBrief: string
  premise: string
  logline: string
  synopsis: string
  theme: string
  ending: string
  genre: string
  tone: string
  visualStyle: string
  worldSummary: string
  language: string
  characters: AgentCreativeCharacter[]
  locations: AgentCreativeLocation[]
  outlineBeats: string[]
  durationSeconds?: number
}

export interface AgentGenerateStorySectionAction extends AgentLanguageAwareAction {
  type: 'generate_story_section'
  targetStoryTitle: string
  scope: 'all' | 'overview' | 'world' | 'characters' | 'relationships' | 'structure'
  instruction: string
  confirm: true
}

export interface AgentApplyStoryProposalAction {
  type: 'apply_story_proposal'
  targetStoryTitle: string
  confirm: true
}

export interface AgentApproveStorySectionAction {
  type: 'approve_story_section'
  targetStoryTitle: string
  section: 'overview' | 'world' | 'characters' | 'relationships' | 'structure'
  confirm: true
}

export interface AgentStoryVisualSelection {
  targetKind: 'world' | 'location' | 'character'
  targetName: string
  assetName: string
  primary: boolean
}

export interface AgentApproveStoryVisualsAction {
  type: 'approve_story_visuals'
  targetStoryTitle: string
  selections: AgentStoryVisualSelection[]
  confirm: true
}

export interface AgentGenerateStoryVisualsAction {
  type: 'generate_story_visuals'
  targetStoryTitle: string
  scope: 'world' | 'locations' | 'characters' | 'all'
  targetNames: string[]
  confirm: true
}

export interface AgentStageStoryComicAction extends AgentLanguageAwareAction {
  type: 'stage_story_comic'
  targetStoryTitle: string
  direction: string
  pageCount: number
  panelsPerPage: number
  confirm: true
}

export interface AgentStageStoryVideoAction extends AgentLanguageAwareAction {
  type: 'stage_story_video'
  targetStoryTitle: string
  kind: 'film' | 'trailer'
  direction: string
  durationSeconds?: number
  confirm: true
}

export interface AgentStartDirectorProductionAction {
  type: 'start_director_production'
  targetStoryId?: string
  targetStoryTitle: string
  productionId?: string
  kind?: 'film' | 'trailer' | 'music_video'
  confirm: true
}

export interface AgentStageStoryMusicVideoAction extends AgentLanguageAwareAction {
  type: 'stage_story_music_video'
  targetStoryId?: string
  targetStoryTitle: string
  songName: string
  cueTitle: string
  cueId?: string
  pacing: 'cinematic' | 'balanced' | 'rhythmic'
  confirm: true
}

export interface AgentConfigureStorySongAction extends AgentLanguageAwareAction {
  type: 'configure_story_song'
  targetStoryId?: string
  targetStoryTitle: string
  songTitle: string
  brief: string
  style: string
  lyrics: string
  writeLyrics: boolean
  lyricsLanguage: string
  instrumental: boolean
  model: 'music-3.0' | 'music-2.6' | 'ace_step_v1_5_xl_sft_lm_4b'
  durationSeconds?: number
}

export interface AgentGenerateStorySongAction {
  type: 'generate_story_song'
  targetStoryId?: string
  targetStoryTitle: string
  cueTitle: string
  cueId?: string
  confirm: true
}

export interface AgentCreateSeriesEpisodeAction extends AgentLanguageAwareAction {
  type: 'create_series_episode'
  seriesTitle: string
  seriesPremise: string
  seriesLogline: string
  episodeTitle: string
  episodePremise: string
  episodeLogline: string
  genre: string
  tone: string
  visualStyle: string
  worldSummary: string
  theme: string
  ending: string
  language: string
  characters: AgentCreativeCharacter[]
  locations: AgentCreativeLocation[]
  outlineBeats: string[]
  targetDurationSeconds?: number
  createIfMissing: boolean
  knownUniverse: boolean
}

export interface AgentUpdateSeriesEpisodeAction extends AgentLanguageAwareAction {
  type: 'update_series_episode'
  seriesTitle: string
  targetEpisodeTitle: string
  episodeTitle: string
  episodePremise: string
  episodeLogline: string
  outlineBeats: string[]
  targetDurationSeconds?: number
}

export interface AgentGenerateSeriesPlanAction extends AgentLanguageAwareAction {
  type: 'generate_series_plan'
  seriesTitle: string
  targetEpisodeTitle: string
  scope: 'outline' | 'script' | 'shots' | 'complete'
  instruction: string
  confirm: true
}

export interface AgentApplySeriesPlanAction {
  type: 'apply_series_plan'
  seriesTitle: string
  targetEpisodeTitle: string
  jobId: string
  confirm: true
}

export interface AgentRenderSeriesShotsAction {
  type: 'render_series_shots'
  seriesTitle: string
  targetEpisodeTitle: string
  mode: 'selected' | 'missing' | 'failed' | 'all'
  shotIds: string[]
  seed?: number
  confirm: true
}

export interface AgentReviewSeriesAttemptsAction {
  type: 'review_series_attempts'
  seriesTitle: string
  targetEpisodeTitle: string
  decision: 'approve' | 'reject'
  scope: 'selected_latest' | 'all_latest'
  shotNumbers: number[]
  attemptId: string
  confirm: true
}

export interface AgentAssembleSeriesEpisodeAction {
  type: 'assemble_series_episode'
  seriesTitle: string
  targetEpisodeTitle: string
  confirm: true
}

export interface AgentCommitSeriesCanonAction {
  type: 'commit_series_canon'
  seriesTitle: string
  targetEpisodeTitle: string
  decision: 'accept_all' | 'reject_all' | 'accept_selected' | 'reject_selected'
  itemIds: string[]
  confirm: true
}

export interface AgentApply3dRhythmAction {
  type: 'apply_3d_rhythm'
  sceneName: string
  layerName: string
  audioOutputName: string
  cueSource: 'beats' | 'downbeats'
  profile: 'pulse' | 'bounce' | 'peek' | 'camera-punch'
  intensity: number
  confirm: true
}

export interface AgentCreateRhythmic3dVideoAction extends AgentLanguageAwareAction {
  type: 'create_rhythmic_3d_video'
  sceneName: string
  musicPrompt: string
  audioOutputName: string
  visualOutputName: string
  layerName: string
  durationSeconds: number
  cueSource: 'beats' | 'downbeats'
  profile: 'pulse' | 'bounce' | 'peek' | 'camera-punch'
  intensity: number
  confirm: true
}

export type AgentSceneWorkflowAction =
  | { type: 'create_3d_scene'; sceneName: string; durationSeconds: number; width: number; height: number; fps: 30 | 60; confirm: true }
  | { type: 'set_3d_scene_properties'; sceneName: string; durationSeconds?: number; width?: number; height?: number; fps?: 30 | 60; confirm: true }
  | { type: 'add_3d_scene_layer'; sceneName: string; layerName: string; layerType: 'model3d' | 'image' | 'video' | 'overlay' | 'camera'; outputName: string; confirm: true }
  | { type: 'update_3d_scene_layer'; sceneName: string; layerName: string; visible?: boolean; locked?: boolean; confirm: true }
  | { type: 'remove_3d_scene_layer'; sceneName: string; layerName: string; confirm: true }
  | { type: 'attach_3d_scene_audio'; sceneName: string; audioOutputName: string; confirm: true }
  | { type: 'analyze_3d_scene_audio'; sceneName: string; audioOutputName: string; confirm: true }
  | { type: 'apply_3d_choreography'; sceneName: string; layerName: string; audioOutputName: string; cueSource: 'beats' | 'downbeats'; profile: 'pulse' | 'bounce' | 'peek' | 'camera-punch'; intensity: number; confirm: true }

export interface AgentOpen3dSceneAction {
  type: 'open_3d_scene'
  sceneName: string
  layerName: string
  confirm: true
}

export interface AgentSave3dSceneAction {
  type: 'save_3d_scene'
  sceneName: string
  confirm: true
}

export interface AgentExport3dSceneAction {
  type: 'export_3d_scene'
  sceneName: string
  confirm: true
}

export interface AgentComicPanel {
  caption: string
  dialogue: string
  sfx: string
  scene?: string
}
export interface AgentComicPage { title: string; stage: string; panels: AgentComicPanel[] }

export interface AgentCreateComicAction extends AgentLanguageAwareAction {
  type: 'create_comic'
  title: string
  synopsis: string
  language: string
  styleName: string
  characters: AgentCreativeCharacter[]
  panels: AgentComicPanel[]
  pages: AgentComicPage[]
  imageProvider: 'profile' | 'maestro' | 'minimax'
  imageModel: string
  factualBiography: boolean
}

export interface AgentGenerateComicAction {
  type: 'generate_comic'
  imageProvider: 'keep' | 'maestro' | 'minimax'
  imageModel: string
  scope: 'all' | 'missing' | 'failed'
  pages: number[]
  pilot: boolean
  biographyReview: boolean
  confirm: true
}

export interface AgentGenerateComicPanelAction {
  type: 'generate_comic_panel'
  pageNumber: number
  panelNumber: number
  confirm: true
}

export interface AgentAttachStudioReferencesAction {
  type: 'attach_studio_references'
  outputNames: string[]
  role: 'start_frame' | 'subject' | 'style'
  replaceExisting: boolean
  removeBackground: boolean
}

export interface AgentStudioLoraSelection {
  name: string
  weight: number
}

export interface AgentConfigureStudioLorasAction {
  type: 'configure_studio_loras'
  loras: AgentStudioLoraSelection[]
  replaceExisting: boolean
}

export interface AgentInspectQueueAction {
  type: 'inspect_queue'
  scope: 'active' | 'all'
}

export interface AgentCancelTaskAction {
  type: 'cancel_task'
  taskId: string
  confirm: true
}

export interface AgentResumeTaskAction {
  type: 'resume_task'
  taskId: string
  confirm: true
}

export interface AgentRetryTaskAction {
  type: 'retry_task'
  taskId: string
  confirm: true
}

export interface AgentSelectWorkspaceAction {
  type: 'select_workspace'
  workspaceName: string
}

export interface AgentCreateWorkspaceAction {
  type: 'create_workspace'
  workspaceName: string
}

export interface AgentCreateWorkspaceCollectionAction {
  type: 'create_workspace_collection'
  name: string
  description: string
  projectIds: string[]
  assetIds: string[]
  productionIds: string[]
}

export interface AgentUpdateWorkspaceCollectionAction {
  type: 'update_workspace_collection'
  workspaceId: string
  expectedRevision?: number
  name?: string
  description?: string
  projectIds?: string[]
  assetIds?: string[]
  productionIds?: string[]
}

export type AgentAction = AgentOpenTabAction
  | AgentOpenStorySectionAction
  | AgentOpenSeriesSectionAction
  | AgentPrepareVideoAction
  | AgentPrepareImageAction
  | AgentPrepareAudioAction
  | AgentQueueSfxPackAction
  | AgentPrepare3dAction
  | AgentStartGenerationAction
  | AgentCreateStoryAction
  | AgentUpdateStoryAction
  | AgentGenerateStorySectionAction
  | AgentApplyStoryProposalAction
  | AgentApproveStorySectionAction
  | AgentApproveStoryVisualsAction
  | AgentGenerateStoryVisualsAction
  | AgentStageStoryComicAction
  | AgentStageStoryVideoAction
  | AgentConfigureStorySongAction
  | AgentGenerateStorySongAction
  | AgentStageStoryMusicVideoAction
  | AgentStartDirectorProductionAction
  | AgentCreateSeriesEpisodeAction
  | AgentUpdateSeriesEpisodeAction
  | AgentGenerateSeriesPlanAction
  | AgentApplySeriesPlanAction
  | AgentRenderSeriesShotsAction
  | AgentReviewSeriesAttemptsAction
  | AgentAssembleSeriesEpisodeAction
  | AgentCommitSeriesCanonAction
  | AgentOpen3dSceneAction
  | AgentSave3dSceneAction
  | AgentExport3dSceneAction
  | AgentApply3dRhythmAction
  | AgentCreateRhythmic3dVideoAction
  | AgentSceneWorkflowAction
  | AgentCreateComicAction
  | AgentGenerateComicAction
  | AgentGenerateComicPanelAction
  | AgentAttachStudioReferencesAction
  | AgentConfigureStudioLorasAction
  | AgentInspectQueueAction
  | AgentCancelTaskAction
  | AgentResumeTaskAction
  | AgentRetryTaskAction
  | AgentSelectWorkspaceAction
  | AgentCreateWorkspaceAction
  | AgentCreateWorkspaceCollectionAction
  | AgentUpdateWorkspaceCollectionAction
  | AgentCreateCharacterKitAction
  | AgentOpenCharacterKitAction
  | AgentUpdateCharacterKitAction
  | AgentAttachCharacterKitReferencesAction
  | AgentBuildCharacterKitAction
  | AgentOpenCharacterKitRigAction
  | AgentApplyCharacterKitPresetAction
  | AgentTrackCharacterKitJobAction
  | AgentCreateVideoEditorProjectAction
  | AgentOpenVideoEditorProjectAction
  | AgentAddVideoEditorClipsAction
  | AgentOrderVideoEditorClipsAction
  | AgentTrimVideoEditorClipAction
  | AgentAddVideoEditorAudioAction
  | AgentValidateVideoEditorTimelineAction
  | AgentExportVideoEditorAction
  | AgentTrackVideoEditorExportAction
  | AgentAttachVideoclipAlternativeSongAction
  | AgentMountVideoclipAlternativeSongAction

export interface AgentTurn {
  reply: string
  actions: AgentAction[]
  /** ISO language tag inferred from the user's final message, not the UI. */
  conversationLanguage?: string
}

export interface AgentActionResult {
  action: AgentAction
  ok: boolean
  message: string
  report?: AgentExecutionReport
  command?: CommandEnvelope<AgentAction>
  commandResult?: CommandResult
}

export interface AgentAppSnapshot {
  /** Versioned, canonical read model. Labels are display-only; actions target IDs. */
  context: WizardContextSnapshot
  /** Presentation preference only. It never selects an authored language. */
  interface_language: string
  current: {
    media_filter: string
    sidebar_mode: string
    sidebar_open: boolean
    generation_mode: string
    selected_model: string
    prompt_preview: string
    duration_seconds: number
    resolution: string
    aspect_ratio: string
  }
  available_video_models: Array<{
    model_type: string
    name: string
    family: string
    installed: boolean
    enabled: boolean
    text_to_video: boolean
  }>
  available_image_models: Array<{
    model_type: string
    name: string
    family: string
    installed: boolean
    enabled: boolean
  }>
  recent_image_outputs: Array<{ name: string }>
  recent_scene_outputs: Array<{ name: string; title: string }>
  current_studio_loras: {
    available: string[]
    active: string[]
  }
  workspaces: {
    active: string
    available: Array<{ name: string; file_count: number }>
  }
  comic?: {
    project_id: string
    title: string
    pages: number
    panels: number
    completed: number
    failed: number
    provider: string
    active_page: number
  }
  director?: {
    pipeline_id: string
    state: string
  }
  story?: {
    project_id: string
    title: string
    project_type: string
    characters: number
    productions: number
    visual_jobs: number
    active_cue_title: string
    selected_song_name: string
    selected_song_id: string
    state: string
  }
  series?: {
    series_id: string
    title: string
    episode_id: string
    episode_title: string
    shots: number
    approved: number
    failed: number
    state: string
  }
  video_3d?: {
    scene_id: string
    title: string
    layers: number
    state: string
  }
  character_kit?: {
    kit_id: string
    title: string
    poses: number
    mouth: number
    eyes: number
    state: string
  }
  video_editor?: {
    project_id: string
    title: string
    clips: number
    duration: number
    export_job: string
    state: string
  }
}

const RESOLUTION_PRESETS = new Set<ResolutionPreset>(['auto', '480p', '540p', '720p', '768p', '1080p'])
const ASPECT_RATIOS = new Set<AspectRatio>(['auto', '21:9', '16:9', '9:16', '1:1', '4:3', '3:4'])
const STORY_PROJECT_TYPES = new Set<AgentCreateStoryAction['projectType']>([
  'full_story', 'music_video', 'trailer', 'quick_video',
])
const STORY_GENERATION_SCOPES = new Set<AgentGenerateStorySectionAction['scope']>([
  'all', 'overview', 'world', 'characters', 'relationships', 'structure',
])
const STORY_APPROVAL_SECTIONS = new Set<AgentApproveStorySectionAction['section']>([
  'overview', 'world', 'characters', 'relationships', 'structure',
])
const STORY_VISUAL_TARGETS = new Set<AgentStoryVisualSelection['targetKind']>(['world', 'location', 'character'])
const STORY_VISUAL_SCOPES = new Set<AgentGenerateStoryVisualsAction['scope']>(['world', 'locations', 'characters', 'all'])
const SERIES_PLAN_SCOPES = new Set<AgentGenerateSeriesPlanAction['scope']>([
  'outline', 'script', 'shots', 'complete',
])
const SERIES_RENDER_MODES = new Set<AgentRenderSeriesShotsAction['mode']>([
  'selected', 'missing', 'failed', 'all',
])
const SERIES_REVIEW_DECISIONS = new Set<AgentReviewSeriesAttemptsAction['decision']>(['approve', 'reject'])
const SERIES_REVIEW_SCOPES = new Set<AgentReviewSeriesAttemptsAction['scope']>(['selected_latest', 'all_latest'])
const SERIES_CANON_DECISIONS = new Set<AgentCommitSeriesCanonAction['decision']>([
  'accept_all', 'reject_all', 'accept_selected', 'reject_selected',
])
const STORY_SECTIONS = new Set<AgentStorySection>([
  'overview', 'world', 'characters', 'relationships', 'structure', 'productions',
])
const SERIES_SECTIONS = new Set<AgentSeriesSection>([
  'setup', 'canon', 'episode', 'shots', 'review',
])
const MAX_ACTIONS = 6
const AUDIO_SUB_MODES = new Set<AgentPrepareAudioAction['subMode']>(['speech', 'music', 'sfx'])
const ACTION_TYPE_ALIASES: Record<string, AgentAction['type']> = {
  opentab: 'open_tab',
  openstorysection: 'open_story_section',
  openseriessection: 'open_series_section',
  preparevideo: 'prepare_video',
  prepareimage: 'prepare_image',
  prepareaudio: 'prepare_audio',
  prepare3d: 'prepare_3d',
  queuesfxpack: 'queue_sfx_pack',
  startgeneration: 'start_generation',
  createstory: 'create_story',
  updatestory: 'update_story',
  generatestorysection: 'generate_story_section',
  applystoryproposal: 'apply_story_proposal',
  approvestorysection: 'approve_story_section',
  approvestoryvisuals: 'approve_story_visuals',
  generatestoryvisuals: 'generate_story_visuals',
  stagestorycomic: 'stage_story_comic',
  stagestoryvideo: 'stage_story_video',
  stagestorymusicvideo: 'stage_story_music_video',
  startdirectorproduction: 'start_director_production',
  createseriesepisode: 'create_series_episode',
  updateseriesepisode: 'update_series_episode',
  generateseriesplan: 'generate_series_plan',
  applyseriesplan: 'apply_series_plan',
  renderseriesshots: 'render_series_shots',
  reviewseriesattempts: 'review_series_attempts',
  assembleseriesepisode: 'assemble_series_episode',
  commitseriescanon: 'commit_series_canon',
  open3dscene: 'open_3d_scene',
  save3dscene: 'save_3d_scene',
  export3dscene: 'export_3d_scene',
  apply3drhythm: 'apply_3d_rhythm',
  createcomic: 'create_comic',
  generatecomic: 'generate_comic',
  generatecomicpanel: 'generate_comic_panel',
  createcharacterkit: 'create_character_kit',
  opencharacterkit: 'open_character_kit',
  updatecharacterkit: 'update_character_kit',
  attachcharacterkitreferences: 'attach_character_kit_references',
  buildcharacterkit: 'build_character_kit',
  opencharacterkitrig: 'open_character_kit_rig',
  applycharacterkitpreset: 'apply_character_kit_preset',
  trackcharacterkitjob: 'track_character_kit_job',
  createvideoeditorproject: 'create_video_editor_project',
  openvideoeditorproject: 'open_video_editor_project',
  addvideoeditorclips: 'add_video_editor_clips',
  ordervideoeditorclips: 'order_video_editor_clips',
  trimvideoeditorclip: 'trim_video_editor_clip',
  addvideoeditoraudio: 'add_video_editor_audio',
  validatevideoeditortimeline: 'validate_video_editor_timeline',
  exportvideoeditor: 'export_video_editor',
  trackvideoeditorexport: 'track_video_editor_export',
  attachvideoclipalternativesong: 'attach_videoclip_alternative_song',
  mountvideoclipalternativesong: 'mount_videoclip_alternative_song',
  attachstudioreferences: 'attach_studio_references',
  configurestudioloras: 'configure_studio_loras',
  inspectqueue: 'inspect_queue',
  canceltask: 'cancel_task',
  resumetask: 'resume_task',
  retrytask: 'retry_task',
  selectworkspace: 'select_workspace',
  createworkspace: 'create_workspace',
  createworkspacecollection: 'create_workspace_collection',
  updateworkspacecollection: 'update_workspace_collection',
}

const cleanString = (value: unknown, maxLength: number): string => (
  typeof value === 'string' ? value.trim().slice(0, maxLength) : ''
)

function canonicalActionType(value: unknown): string {
  const raw = cleanString(value, 40)
  const collapsed = raw.toLowerCase().replace(/[^a-z0-9]/g, '')
  return ACTION_TYPE_ALIASES[collapsed] || raw
}

const optionalNumber = (
  value: unknown,
  minimum: number,
  maximum: number,
  integer = false,
): number | undefined => {
  if (typeof value !== 'number' || !Number.isFinite(value)) return undefined
  const bounded = Math.max(minimum, Math.min(maximum, value))
  return integer ? Math.round(bounded) : bounded
}

const optionalPositiveNumber = (
  value: unknown,
  minimum: number,
  maximum: number,
  integer = false,
): number | undefined => (
  typeof value === 'number' && value > 0
    ? optionalNumber(value, minimum, maximum, integer)
    : undefined
)

const stringArray = (value: unknown, maxItems: number, maxLength: number): string[] => (
  Array.isArray(value)
    ? value.slice(0, maxItems).flatMap(item => {
      const text = cleanString(item, maxLength)
      return text ? [text] : []
    })
    : []
)

const positiveIntegerArray = (value: unknown, maxItems: number): number[] => (
  Array.isArray(value)
    ? [...new Set(value.slice(0, maxItems).filter(item => (
      typeof item === 'number' && Number.isInteger(item) && item > 0 && item <= 10_000
    )))]
    : []
)

const creativeCharacters = (value: unknown): AgentCreativeCharacter[] => (
  Array.isArray(value) ? value.slice(0, 16).flatMap(item => {
    if (!item || typeof item !== 'object' || Array.isArray(item)) return []
    const raw = item as Record<string, unknown>
    const name = cleanString(raw.name, 160)
    if (!name) return []
    return [{
      name,
      role: cleanString(raw.role, 300),
      personality: cleanString(raw.personality, 1_000),
      desire: cleanString(raw.desire, 1_000),
      flaw: cleanString(raw.flaw, 1_000),
      appearance: cleanString(raw.appearance, 1_000),
      voice: cleanString(raw.voice, 1_000),
    }]
  }) : []
)

const creativeLocations = (value: unknown): AgentCreativeLocation[] => (
  Array.isArray(value) ? value.slice(0, 16).flatMap(item => {
    if (!item || typeof item !== 'object' || Array.isArray(item)) return []
    const raw = item as Record<string, unknown>
    const name = cleanString(raw.name, 160)
    if (!name) return []
    return [{
      name,
      purpose: cleanString(raw.purpose, 1_000),
      description: cleanString(raw.description, 1_500),
    }]
  }) : []
)

const extractJsonObject = (raw: string): Record<string, unknown> | null => {
  const trimmed = raw.trim().replace(/^```(?:json)?\s*/i, '').replace(/\s*```$/, '')
  const start = trimmed.indexOf('{')
  if (start < 0) return null
  for (let end = trimmed.lastIndexOf('}'); end > start; end = trimmed.lastIndexOf('}', end - 1)) {
    try {
      const parsed = JSON.parse(trimmed.slice(start, end + 1))
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
        return parsed as Record<string, unknown>
      }
    } catch {
      continue
    }
  }
  return null
}

const CANONICAL_FIELD_NAMES = [
  'type', 'tab', 'story_section', 'series_section', 'prompt', 'model_type',
  'duration_seconds', 'resolution_preset', 'resolution', 'aspect_ratio',
  'negative_prompt', 'seed', 'inference_steps', 'guidance_scale', 'output_count',
  'audio_direction', 'turbo', 'title', 'target_story_title', 'story_generation_scope', 'series_plan_scope', 'instruction', 'direction', 'page_count', 'panels_per_page', 'project_type', 'creative_brief',
  'premise', 'logline', 'synopsis', 'theme', 'ending', 'genre', 'tone',
  'visual_style', 'world_summary', 'language', 'series_title', 'series_premise',
  'series_logline', 'target_episode_title', 'episode_title', 'episode_premise', 'episode_logline',
  'target_duration_seconds', 'create_if_missing', 'known_universe',
  'queue_scope', 'task_id', 'job_id', 'shot_ids', 'shot_numbers', 'attempt_id', 'render_mode',
  'review_decision', 'review_scope', 'canon_decision', 'canon_item_ids', 'production_kind',
  'song_name', 'cue_title', 'pacing',
  'scene_name', 'layer_name', 'audio_output_name', 'videoclip_name', 'cue_source', 'rhythm_profile', 'intensity',
  'confirm', 'characters', 'locations', 'outline_beats', 'story_visual_selections', 'story_visual_scope', 'target_names',
  'target_kind', 'target_name', 'asset_name', 'primary',
  'audio_sub_mode', 'sfx_clips', 'name', 'preset', 'comic_panels', 'comic_pages', 'caption', 'stage', 'image_provider',
  'page_number', 'panel_number', 'page_numbers', 'pilot',
  'factual_biography', 'biography_review',
  'kit_name', 'look_notes', 'preset_id',
  'clip_names', 'clip_name', 'trim_start', 'trim_end', 'project_name',
  'reference_output_names', 'reference_role', 'replace_existing', 'remove_background',
  'loras', 'weight',
  'workspace_name', 'workspace_id', 'expected_revision', 'description',
  'project_ids', 'asset_ids', 'production_ids',
  'dialogue', 'sfx', 'scene', 'actions', 'reply',
] as const

function collapsedKey(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9]/g, '')
}

export function humanReply(raw: string): string {
  const object = extractJsonObject(raw)
  if (typeof object?.reply === 'string' && object.reply.trim()) return object.reply.trim()
  const quoted = raw.match(/"reply"\s*:\s*"((?:\\.|[^"\\])*)"/)
  if (quoted) {
    try {
      return JSON.parse(`"${quoted[1]}"`)
    } catch {
      return quoted[1].replace(/\\n/g, '\n')
    }
  }
  return raw.trim()
}

function canonicalRecord(raw: Record<string, unknown>): Record<string, unknown> {
  const collapsed = new Map<string, unknown>()
  for (const [key, value] of Object.entries(raw)) collapsed.set(collapsedKey(key), value)
  const next: Record<string, unknown> = { ...raw }
  for (const name of CANONICAL_FIELD_NAMES) {
    if (next[name] === undefined) {
      const hit = collapsed.get(collapsedKey(name))
      if (hit !== undefined) next[name] = hit
    }
  }
  if (Array.isArray(next.sfx_clips)) {
    next.sfx_clips = next.sfx_clips.map(item => (
      item && typeof item === 'object' && !Array.isArray(item)
        ? canonicalRecord(item as Record<string, unknown>)
        : item
    ))
  }
  if (Array.isArray(next.comic_panels)) {
    next.comic_panels = next.comic_panels.map(item => (
      item && typeof item === 'object' && !Array.isArray(item)
        ? canonicalRecord(item as Record<string, unknown>)
        : item
    ))
  }
  if (Array.isArray(next.comic_pages)) next.comic_pages = next.comic_pages.map(item => {
    if (!item || typeof item !== 'object' || Array.isArray(item)) return item
    const page = canonicalRecord(item as Record<string, unknown>)
    if (Array.isArray(page.comic_panels)) page.comic_panels = page.comic_panels.map(panel => panel && typeof panel === 'object' && !Array.isArray(panel) ? canonicalRecord(panel as Record<string, unknown>) : panel)
    return page
  })
  if (Array.isArray(next.loras)) {
    next.loras = next.loras.map(item => (
      item && typeof item === 'object' && !Array.isArray(item)
        ? canonicalRecord(item as Record<string, unknown>)
        : item
    ))
  }
  if (Array.isArray(next.story_visual_selections)) {
    next.story_visual_selections = next.story_visual_selections.map(item => (
      item && typeof item === 'object' && !Array.isArray(item)
        ? canonicalRecord(item as Record<string, unknown>)
        : item
    ))
  }
  return next
}

function parseStoryVisualSelections(value: unknown): AgentStoryVisualSelection[] {
  return Array.isArray(value) ? value.slice(0, 40).flatMap(item => {
    if (!item || typeof item !== 'object' || Array.isArray(item)) return []
    const raw = canonicalRecord(item as Record<string, unknown>)
    const targetKind = cleanString(raw.target_kind, 30) as AgentStoryVisualSelection['targetKind']
    const assetName = cleanString(raw.asset_name, 300)
    if (!STORY_VISUAL_TARGETS.has(targetKind) || !assetName) return []
    const targetName = cleanString(raw.target_name, 300)
    if (targetKind !== 'world' && !targetName) return []
    return [{ targetKind, targetName, assetName, primary: raw.primary === true }]
  }) : []
}

function parseComicPanels(value: unknown): AgentComicPanel[] {
  return Array.isArray(value) ? value.slice(0, 12).flatMap(item => {
    if (!item || typeof item !== 'object' || Array.isArray(item)) return []
    const raw = canonicalRecord(item as Record<string, unknown>)
    const caption = cleanString(raw.caption, 400)
    const dialogue = cleanString(raw.dialogue, 400)
    const sfx = cleanString(raw.sfx, 80)
    const scene = cleanString(raw.scene, 800)
    if (!caption && !dialogue && !sfx && !scene) return []
    return [{ caption, dialogue, sfx, scene: scene || undefined }]
  }) : []
}
function parseComicPages(value: unknown): AgentComicPage[] {
  return Array.isArray(value) ? value.slice(0, 30).flatMap((item, index) => {
    if (!item || typeof item !== 'object' || Array.isArray(item)) return []
    const raw = canonicalRecord(item as Record<string, unknown>)
    const panels = parseComicPanels(raw.comic_panels)
    return panels.length ? [{ title: cleanString(raw.title, 300) || `Página ${index + 1}`, stage: cleanString(raw.stage, 600), panels }] : []
  }) : []
}

function parseSfxClips(value: unknown): AgentSfxClip[] {
  return Array.isArray(value) ? value.slice(0, 12).flatMap(item => {
    if (!item || typeof item !== 'object' || Array.isArray(item)) return []
    const raw = item as Record<string, unknown>
    const name = cleanString(raw.name, 80)
    const prompt = cleanString(raw.prompt, 1_500)
    if (!name || !prompt) return []
    return [{
      name,
      prompt,
      durationSeconds: optionalPositiveNumber(raw.duration_seconds, 1, 20) ?? 1,
    }]
  }) : []
}

function parseAction(value: unknown): AgentAction | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  const raw = canonicalRecord(value as Record<string, unknown>)
  const type = canonicalActionType(raw.type)
  const registered = parseRegisteredCapability(type, raw)
  if (registered !== undefined) return registered
  if (type === 'open_story_section') {
    const section = cleanString(raw.story_section, 40) as AgentStorySection
    return STORY_SECTIONS.has(section) ? { type: 'open_story_section', section } : null
  }
  if (type === 'open_series_section') {
    const section = cleanString(raw.series_section, 40) as AgentSeriesSection
    return SERIES_SECTIONS.has(section) ? { type: 'open_series_section', section } : null
  }
  if (type === 'prepare_video') {
    const prompt = cleanString(raw.prompt, 8_000)
    if (!prompt) return null
    const resolutionPreset = cleanString(raw.resolution_preset, 12) as ResolutionPreset
    const aspectRatio = cleanString(raw.aspect_ratio, 12) as AspectRatio
    const resolution = cleanString(raw.resolution, 20)
    const turbo = raw.turbo === 'on' ? true : raw.turbo === 'off' ? false : undefined
    return {
      type: 'prepare_video',
      prompt,
      modelType: cleanString(raw.model_type, 160) || undefined,
      durationSeconds: optionalPositiveNumber(raw.duration_seconds, 1, 300),
      resolutionPreset: RESOLUTION_PRESETS.has(resolutionPreset) ? resolutionPreset : undefined,
      resolution: /^\d{2,4}x\d{2,4}$/.test(resolution) ? resolution : undefined,
      aspectRatio: ASPECT_RATIOS.has(aspectRatio) ? aspectRatio : undefined,
      negativePrompt: cleanString(raw.negative_prompt, 2_000) || undefined,
      seed: optionalNumber(raw.seed, -1, 2_147_483_647, true),
      inferenceSteps: optionalPositiveNumber(raw.inference_steps, 1, 100, true),
      guidanceScale: typeof raw.guidance_scale === 'number' && raw.guidance_scale >= 0
        ? optionalNumber(raw.guidance_scale, 0, 30)
        : undefined,
      outputCount: optionalPositiveNumber(raw.output_count, 1, 8, true),
      audioDirection: cleanString(raw.audio_direction, 1_000) || undefined,
      turbo,
    }
  }
  if (type === 'prepare_image') {
    const prompt = cleanString(raw.prompt, 8_000)
    if (!prompt) return null
    const resolutionPreset = cleanString(raw.resolution_preset, 12) as ResolutionPreset
    const aspectRatio = cleanString(raw.aspect_ratio, 12) as AspectRatio
    const resolution = cleanString(raw.resolution, 20)
    return {
      type: 'prepare_image',
      prompt,
      modelType: cleanString(raw.model_type, 160) || undefined,
      resolutionPreset: RESOLUTION_PRESETS.has(resolutionPreset) ? resolutionPreset : undefined,
      resolution: /^\d{2,4}x\d{2,4}$/.test(resolution) ? resolution : undefined,
      aspectRatio: ASPECT_RATIOS.has(aspectRatio) ? aspectRatio : undefined,
      negativePrompt: cleanString(raw.negative_prompt, 2_000) || undefined,
      seed: optionalNumber(raw.seed, -1, 2_147_483_647, true),
      inferenceSteps: optionalPositiveNumber(raw.inference_steps, 1, 100, true),
      guidanceScale: typeof raw.guidance_scale === 'number' && raw.guidance_scale >= 0
        ? optionalNumber(raw.guidance_scale, 0, 30)
        : undefined,
      outputCount: optionalPositiveNumber(raw.output_count, 1, 8, true),
    }
  }
  if (type === 'prepare_audio') {
    const prompt = cleanString(raw.prompt, 8_000)
    if (!prompt) return null
    const subMode = cleanString(raw.audio_sub_mode, 12) as AgentPrepareAudioAction['subMode']
    return {
      type: 'prepare_audio',
      subMode: AUDIO_SUB_MODES.has(subMode) ? subMode : 'sfx',
      prompt,
      modelType: cleanString(raw.model_type, 160) || undefined,
      durationSeconds: optionalPositiveNumber(raw.duration_seconds, 1, 20),
      negativePrompt: cleanString(raw.negative_prompt, 2_000) || undefined,
    }
  }
  if (type === 'prepare_3d') {
    const prompt = cleanString(raw.prompt, 8_000)
    if (!prompt) return null
    return {
      type: 'prepare_3d',
      prompt,
      modelType: cleanString(raw.model_type, 160) || undefined,
      preset: cleanString(raw.preset, 40) || undefined,
      seed: optionalNumber(raw.seed, -1, 2_147_483_647, true),
    }
  }
  if (type === 'queue_sfx_pack') {
    if (raw.confirm !== true) return null
    const clips = parseSfxClips(raw.sfx_clips)
    if (!clips.length) return null
    return {
      type: 'queue_sfx_pack',
      style: cleanString(raw.visual_style, 2_000) || cleanString(raw.theme, 1_000),
      clips,
      modelType: cleanString(raw.model_type, 160) || undefined,
      negativePrompt: cleanString(raw.negative_prompt, 2_000) || undefined,
      confirm: true,
    }
  }
  if (type === 'start_generation') return raw.confirm === true ? { type: 'start_generation', confirm: true } : null
  if (type === 'create_story') {
    const title = cleanString(raw.title, 300)
    const premise = cleanString(raw.premise, 2_000)
    if (!title || !premise) return null
    const projectType = cleanString(raw.project_type, 30) as AgentCreateStoryAction['projectType']
    const inferred = inferStoryProjectTypeFromText(
      title, premise, cleanString(raw.creative_brief, 4_000), cleanString(raw.visual_style, 2_000),
    )
    return {
      type: 'create_story',
      title,
      projectType: STORY_PROJECT_TYPES.has(projectType) ? projectType : inferred || 'full_story',
      creativeBrief: cleanString(raw.creative_brief, 4_000),
      premise,
      logline: cleanString(raw.logline, 2_000),
      synopsis: cleanString(raw.synopsis, 6_000),
      theme: cleanString(raw.theme, 1_000),
      ending: cleanString(raw.ending, 2_000),
      genre: cleanString(raw.genre, 300),
      tone: cleanString(raw.tone, 500),
      visualStyle: cleanString(raw.visual_style, 2_000),
      worldSummary: cleanString(raw.world_summary, 3_000),
      language: cleanString(raw.language, 120),
      characters: creativeCharacters(raw.characters),
      locations: creativeLocations(raw.locations),
      outlineBeats: stringArray(raw.outline_beats, 24, 1_500),
      durationSeconds: optionalPositiveNumber(raw.target_duration_seconds, 15, 3_600, true),
    }
  }
  if (type === 'update_story') {
    const action: AgentUpdateStoryAction = {
      type: 'update_story',
      targetStoryTitle: cleanString(raw.target_story_title, 300),
      title: cleanString(raw.title, 300),
      creativeBrief: cleanString(raw.creative_brief, 4_000),
      premise: cleanString(raw.premise, 2_000),
      logline: cleanString(raw.logline, 2_000),
      synopsis: cleanString(raw.synopsis, 6_000),
      theme: cleanString(raw.theme, 1_000),
      ending: cleanString(raw.ending, 2_000),
      genre: cleanString(raw.genre, 300),
      tone: cleanString(raw.tone, 500),
      visualStyle: cleanString(raw.visual_style, 2_000),
      worldSummary: cleanString(raw.world_summary, 3_000),
      language: cleanString(raw.language, 120),
      characters: creativeCharacters(raw.characters),
      locations: creativeLocations(raw.locations),
      outlineBeats: stringArray(raw.outline_beats, 24, 1_500),
      durationSeconds: optionalPositiveNumber(raw.target_duration_seconds, 15, 3_600, true),
    }
    const hasPatch = action.title || action.creativeBrief || action.premise || action.logline
      || action.synopsis || action.theme || action.ending || action.genre || action.tone
      || action.visualStyle || action.worldSummary || action.language
      || action.characters.length || action.locations.length || action.outlineBeats.length
      || action.durationSeconds !== undefined
    return hasPatch ? action : null
  }
  if (type === 'generate_story_section') {
    if (raw.confirm !== true) return null
    const scope = cleanString(raw.story_generation_scope, 40) as AgentGenerateStorySectionAction['scope']
    if (!STORY_GENERATION_SCOPES.has(scope)) return null
    return {
      type: 'generate_story_section',
      targetStoryTitle: cleanString(raw.target_story_title, 300),
      scope,
      instruction: cleanString(raw.instruction, 4_000),
      confirm: true,
    }
  }
  if (type === 'apply_story_proposal') {
    if (raw.confirm !== true) return null
    return {
      type: 'apply_story_proposal',
      targetStoryTitle: cleanString(raw.target_story_title, 300),
      confirm: true,
    }
  }
  if (type === 'approve_story_section') {
    if (raw.confirm !== true) return null
    const section = cleanString(raw.story_section, 40) as AgentApproveStorySectionAction['section']
    if (!STORY_APPROVAL_SECTIONS.has(section)) return null
    return {
      type: 'approve_story_section',
      targetStoryTitle: cleanString(raw.target_story_title, 300),
      section,
      confirm: true,
    }
  }
  if (type === 'approve_story_visuals') {
    if (raw.confirm !== true) return null
    const selections = parseStoryVisualSelections(raw.story_visual_selections)
    if (!selections.length) return null
    return {
      type: 'approve_story_visuals',
      targetStoryTitle: cleanString(raw.target_story_title, 300),
      selections,
      confirm: true,
    }
  }
  if (type === 'generate_story_visuals') {
    if (raw.confirm !== true) return null
    const scope = cleanString(raw.story_visual_scope, 30) as AgentGenerateStoryVisualsAction['scope']
    if (!STORY_VISUAL_SCOPES.has(scope)) return null
    return {
      type: 'generate_story_visuals',
      targetStoryTitle: cleanString(raw.target_story_title, 300),
      scope,
      targetNames: stringArray(raw.target_names, 40, 300),
      confirm: true,
    }
  }
  if (type === 'stage_story_comic') {
    if (raw.confirm !== true) return null
    return {
      type: 'stage_story_comic',
      targetStoryTitle: cleanString(raw.target_story_title, 300),
      direction: cleanString(raw.direction, 4_000),
      pageCount: optionalPositiveNumber(raw.page_count, 1, 100, true) ?? 4,
      panelsPerPage: optionalPositiveNumber(raw.panels_per_page, 1, 12, true) ?? 4,
      confirm: true,
    }
  }
  if (type === 'stage_story_video') {
    if (raw.confirm !== true) return null
    const kind = cleanString(raw.production_kind, 30) as AgentStageStoryVideoAction['kind']
    if (kind !== 'film' && kind !== 'trailer') return null
    return { type: 'stage_story_video', targetStoryTitle: cleanString(raw.target_story_title, 300), kind, direction: cleanString(raw.direction, 4_000), durationSeconds: optionalPositiveNumber(raw.duration_seconds, 15, 3_600, true), confirm: true }
  }
  if (type === 'stage_story_music_video') {
    if (raw.confirm !== true) return null
    const pacing = cleanString(raw.pacing, 20) as AgentStageStoryMusicVideoAction['pacing']
    return {
      type: 'stage_story_music_video',
      targetStoryTitle: cleanString(raw.target_story_title, 300),
      songName: cleanString(raw.song_name, 300),
      cueTitle: cleanString(raw.cue_title, 300),
      pacing: pacing === 'cinematic' || pacing === 'rhythmic' ? pacing : 'balanced',
      confirm: true,
    }
  }
  if (type === 'start_director_production') {
    if (raw.confirm !== true) return null
    const rawKind = cleanString(raw.production_kind, 30)
    if (rawKind && rawKind !== 'film' && rawKind !== 'trailer' && rawKind !== 'music_video') return null
    return {
      type: 'start_director_production',
      targetStoryTitle: cleanString(raw.target_story_title, 300),
      kind: rawKind ? rawKind as AgentStartDirectorProductionAction['kind'] : undefined,
      confirm: true,
    }
  }
  if (type === 'create_series_episode') {
    const seriesTitle = cleanString(raw.series_title, 300)
    const episodePremise = cleanString(raw.episode_premise, 3_000)
    if (!seriesTitle || !episodePremise) return null
    return {
      type: 'create_series_episode',
      seriesTitle,
      seriesPremise: cleanString(raw.series_premise, 3_000),
      seriesLogline: cleanString(raw.series_logline, 2_000),
      episodeTitle: cleanString(raw.episode_title, 300),
      episodePremise,
      episodeLogline: cleanString(raw.episode_logline, 2_000),
      genre: cleanString(raw.genre, 300),
      tone: cleanString(raw.tone, 500),
      visualStyle: cleanString(raw.visual_style, 2_000),
      worldSummary: cleanString(raw.world_summary, 3_000),
      theme: cleanString(raw.theme, 1_000),
      ending: cleanString(raw.ending, 2_000),
      language: cleanString(raw.language, 120),
      characters: creativeCharacters(raw.characters),
      locations: creativeLocations(raw.locations),
      outlineBeats: stringArray(raw.outline_beats, 24, 1_500),
      targetDurationSeconds: optionalPositiveNumber(raw.target_duration_seconds, 15, 3_600, true),
      createIfMissing: raw.create_if_missing === true,
      knownUniverse: raw.known_universe === true,
    }
  }
  if (type === 'update_series_episode') {
    const action: AgentUpdateSeriesEpisodeAction = {
      type: 'update_series_episode',
      seriesTitle: cleanString(raw.series_title, 300),
      targetEpisodeTitle: cleanString(raw.target_episode_title, 300),
      episodeTitle: cleanString(raw.episode_title, 300),
      episodePremise: cleanString(raw.episode_premise, 3_000),
      episodeLogline: cleanString(raw.episode_logline, 2_000),
      outlineBeats: stringArray(raw.outline_beats, 24, 1_500),
      targetDurationSeconds: optionalPositiveNumber(raw.target_duration_seconds, 15, 3_600, true),
    }
    return action.episodeTitle || action.episodePremise || action.episodeLogline
      || action.outlineBeats.length || action.targetDurationSeconds !== undefined
      ? action : null
  }
  if (type === 'generate_series_plan') {
    if (raw.confirm !== true) return null
    const scope = cleanString(raw.series_plan_scope, 40) as AgentGenerateSeriesPlanAction['scope']
    if (!SERIES_PLAN_SCOPES.has(scope)) return null
    return {
      type: 'generate_series_plan',
      seriesTitle: cleanString(raw.series_title, 300),
      targetEpisodeTitle: cleanString(raw.target_episode_title, 300),
      scope,
      instruction: cleanString(raw.instruction, 4_000),
      confirm: true,
    }
  }
  if (type === 'apply_series_plan') {
    if (raw.confirm !== true) return null
    return {
      type: 'apply_series_plan',
      seriesTitle: cleanString(raw.series_title, 300),
      targetEpisodeTitle: cleanString(raw.target_episode_title, 300),
      jobId: cleanString(raw.job_id, 160),
      confirm: true,
    }
  }
  if (type === 'render_series_shots') {
    if (raw.confirm !== true) return null
    const mode = cleanString(raw.render_mode, 30) as AgentRenderSeriesShotsAction['mode']
    if (!SERIES_RENDER_MODES.has(mode)) return null
    const shotIds = stringArray(raw.shot_ids, 200, 160)
    if (mode === 'selected' && !shotIds.length) return null
    return {
      type: 'render_series_shots',
      seriesTitle: cleanString(raw.series_title, 300),
      targetEpisodeTitle: cleanString(raw.target_episode_title, 300),
      mode,
      shotIds,
      seed: optionalNumber(raw.seed, -1, 2_147_483_647, true),
      confirm: true,
    }
  }
  if (type === 'review_series_attempts') {
    if (raw.confirm !== true) return null
    const decision = cleanString(raw.review_decision, 30) as AgentReviewSeriesAttemptsAction['decision']
    const scope = cleanString(raw.review_scope, 30) as AgentReviewSeriesAttemptsAction['scope']
    if (!SERIES_REVIEW_DECISIONS.has(decision) || !SERIES_REVIEW_SCOPES.has(scope)) return null
    const shotNumbers = positiveIntegerArray(raw.shot_numbers, 200)
    const attemptId = cleanString(raw.attempt_id, 160)
    if (scope === 'selected_latest' && !shotNumbers.length) return null
    if (scope === 'all_latest' && (decision !== 'approve' || shotNumbers.length || attemptId)) return null
    if (decision === 'reject' && (shotNumbers.length !== 1 || scope !== 'selected_latest')) return null
    if (attemptId && shotNumbers.length !== 1) return null
    return {
      type: 'review_series_attempts',
      seriesTitle: cleanString(raw.series_title, 300),
      targetEpisodeTitle: cleanString(raw.target_episode_title, 300),
      decision,
      scope,
      shotNumbers,
      attemptId,
      confirm: true,
    }
  }
  if (type === 'assemble_series_episode') {
    if (raw.confirm !== true) return null
    return {
      type: 'assemble_series_episode',
      seriesTitle: cleanString(raw.series_title, 300),
      targetEpisodeTitle: cleanString(raw.target_episode_title, 300),
      confirm: true,
    }
  }
  if (type === 'commit_series_canon') {
    if (raw.confirm !== true) return null
    const decision = cleanString(raw.canon_decision, 40) as AgentCommitSeriesCanonAction['decision']
    if (!SERIES_CANON_DECISIONS.has(decision)) return null
    const itemIds = stringArray(raw.canon_item_ids, 200, 160)
    const selected = decision === 'accept_selected' || decision === 'reject_selected'
    if (selected !== Boolean(itemIds.length)) return null
    return { type: 'commit_series_canon', seriesTitle: cleanString(raw.series_title, 300), targetEpisodeTitle: cleanString(raw.target_episode_title, 300), decision, itemIds, confirm: true }
  }
  if (type === 'open_3d_scene') {
    if (raw.confirm !== true) return null
    const sceneName = cleanString(raw.scene_name, 300)
    if (!sceneName) return null
    return { type: 'open_3d_scene', sceneName, layerName: cleanString(raw.layer_name, 300), confirm: true }
  }
  if (type === 'save_3d_scene') {
    if (raw.confirm !== true) return null
    return { type: 'save_3d_scene', sceneName: cleanString(raw.scene_name, 300), confirm: true }
  }
  if (type === 'export_3d_scene') {
    if (raw.confirm !== true) return null
    return { type: 'export_3d_scene', sceneName: cleanString(raw.scene_name, 300), confirm: true }
  }
  if (type === 'create_comic') {
    const title = cleanString(raw.title, 300)
    if (!title) return null
    const panels = parseComicPanels(raw.comic_panels)
    const pages = parseComicPages(raw.comic_pages)
    const beats = stringArray(raw.outline_beats, 12, 400)
    const requestedProvider = cleanString(raw.image_provider, 30)
    return {
      type: 'create_comic',
      title,
      synopsis: cleanString(raw.synopsis, 6_000) || cleanString(raw.premise, 2_000),
      language: cleanString(raw.language, 120),
      styleName: cleanString(raw.visual_style, 2_000),
      characters: creativeCharacters(raw.characters),
      pages,
      imageProvider: requestedProvider === 'minimax' || requestedProvider === 'maestro' ? requestedProvider : 'profile',
      imageModel: cleanString(raw.model_type, 160),
      factualBiography: raw.factual_biography === true,
      panels: panels.length
        ? panels
        : beats.map(beat => ({ caption: beat, dialogue: '', sfx: '' })),
    }
  }
  if (type === 'generate_comic') {
    if (raw.confirm !== true) return null
    const requestedProvider = cleanString(raw.image_provider, 30)
    const renderMode = cleanString(raw.render_mode, 20)
    const scope = renderMode === 'all' || renderMode === 'failed' ? renderMode : 'missing'
    const pages = positiveIntegerArray(raw.page_numbers, 30)
    return {
      type: 'generate_comic',
      imageProvider: requestedProvider === 'minimax' || requestedProvider === 'maestro' ? requestedProvider : 'keep',
      imageModel: cleanString(raw.model_type, 160),
      scope,
      pages,
      pilot: raw.pilot === true,
      biographyReview: raw.biography_review === true,
      confirm: true,
    }
  }
  if (type === 'generate_comic_panel') {
    if (raw.confirm !== true) return null
    const pageNumber = optionalPositiveNumber(raw.page_number, 1, 100, true)
    const panelNumber = optionalPositiveNumber(raw.panel_number, 1, 100, true)
    if (!pageNumber || !panelNumber) return null
    return { type: 'generate_comic_panel', pageNumber, panelNumber, confirm: true }
  }
  if (type === 'attach_studio_references') {
    const outputNames = stringArray(raw.reference_output_names, 12, 300)
    if (!outputNames.length) return null
    const requestedRole = cleanString(raw.reference_role, 30)
    const role: AgentAttachStudioReferencesAction['role'] = requestedRole === 'start_frame'
      ? 'start_frame'
      : requestedRole === 'style'
        ? 'style'
        : 'subject'
    return {
      type: 'attach_studio_references',
      outputNames,
      role,
      replaceExisting: raw.replace_existing !== false,
      removeBackground: raw.remove_background === true,
    }
  }
  if (type === 'configure_studio_loras') {
    const loras: AgentStudioLoraSelection[] = Array.isArray(raw.loras)
      ? raw.loras.slice(0, 12).flatMap(item => {
        if (!item || typeof item !== 'object' || Array.isArray(item)) return []
        const entry = item as Record<string, unknown>
        const name = cleanString(entry.name, 300)
        if (!name) return []
        return [{ name, weight: optionalNumber(entry.weight, 0, 2) ?? 1 }]
      })
      : []
    if (!loras.length && raw.replace_existing !== true) return null
    return {
      type: 'configure_studio_loras',
      loras,
      replaceExisting: raw.replace_existing === true,
    }
  }
  if (type === 'inspect_queue') {
    const scope = cleanString(raw.queue_scope, 12)
    return { type: 'inspect_queue', scope: scope === 'all' ? 'all' : 'active' }
  }
  if (type === 'cancel_task') {
    if (raw.confirm !== true) return null
    return { type: 'cancel_task', taskId: cleanString(raw.task_id, 160), confirm: true }
  }
  if (type === 'resume_task') {
    if (raw.confirm !== true) return null
    return { type: 'resume_task', taskId: cleanString(raw.task_id, 160), confirm: true }
  }
  if (type === 'retry_task') {
    if (raw.confirm !== true) return null
    return { type: 'retry_task', taskId: cleanString(raw.task_id, 160), confirm: true }
  }
  if (type === 'select_workspace' || type === 'create_workspace') {
    const workspaceName = cleanString(raw.workspace_name, 120)
    if (!workspaceName) return null
    return type === 'select_workspace'
      ? { type: 'select_workspace', workspaceName }
      : { type: 'create_workspace', workspaceName }
  }
  if (type === 'create_workspace_collection' || type === 'update_workspace_collection') {
    const ids = (value: unknown): string[] | undefined => {
      if (!Array.isArray(value)) return undefined
      return [...new Set(value.map(item => cleanString(item, 200)).filter(Boolean))].slice(0, 500)
    }
    const name = cleanString(raw.name, 160)
    const description = cleanString(raw.description, 2000)
    const projectIds = ids(raw.project_ids)
    const assetIds = ids(raw.asset_ids)
    const productionIds = ids(raw.production_ids)
    if (type === 'create_workspace_collection') {
      if (!name) return null
      return { type, name, description, projectIds: projectIds || [], assetIds: assetIds || [], productionIds: productionIds || [] }
    }
    const workspaceId = cleanString(raw.workspace_id, 200)
    if (!workspaceId) return null
    const expectedRevision = optionalNumber(raw.expected_revision, 1, Number.MAX_SAFE_INTEGER, true)
    if (raw.expected_revision !== undefined && expectedRevision === undefined) return null
    if (!name && raw.description === undefined && projectIds === undefined && assetIds === undefined && productionIds === undefined) return null
    return { type, workspaceId, expectedRevision, name: name || undefined, description: raw.description === undefined ? undefined : description, projectIds, assetIds, productionIds }
  }
  if (type === 'create_character_kit') {
    const name = cleanString(raw.title, 160) || cleanString(raw.kit_name, 160)
    if (!name) return null
    const style = cleanString(raw.visual_style, 40)
    return {
      type: 'create_character_kit',
      name,
      style: style === 'children-illustration' || style === 'anime-2d' ? style : 'cutout',
    }
  }
  if (type === 'open_character_kit') {
    const kitName = cleanString(raw.kit_name, 160) || cleanString(raw.title, 160)
    if (!kitName) return null
    return { type: 'open_character_kit', kitName }
  }
  if (type === 'update_character_kit') {
    const style = cleanString(raw.visual_style, 40)
    return {
      type: 'update_character_kit',
      kitName: cleanString(raw.kit_name, 160),
      name: cleanString(raw.title, 160),
      lookNotes: cleanString(raw.look_notes, 4_000),
      style: style === 'children-illustration' || style === 'anime-2d' || style === 'cutout' ? style : '',
    }
  }
  if (type === 'attach_character_kit_references') {
    const outputNames = stringArray(raw.reference_output_names, 8, 300)
    if (!outputNames.length) return null
    return { type: 'attach_character_kit_references', kitName: cleanString(raw.kit_name, 160), outputNames }
  }
  if (type === 'build_character_kit') {
    return { type: 'build_character_kit', kitName: cleanString(raw.kit_name, 160) }
  }
  if (type === 'open_character_kit_rig') {
    return { type: 'open_character_kit_rig', kitName: cleanString(raw.kit_name, 160) }
  }
  if (type === 'apply_character_kit_preset') {
    const presetId = cleanString(raw.preset_id, 160)
    if (!presetId) return null
    return { type: 'apply_character_kit_preset', kitName: cleanString(raw.kit_name, 160), presetId }
  }
  if (type === 'track_character_kit_job') {
    return { type: 'track_character_kit_job', kitName: cleanString(raw.kit_name, 160) }
  }
  if (type === 'create_video_editor_project') {
    const projectName = cleanString(raw.project_name, 160) || cleanString(raw.title, 160)
    if (!projectName) return null
    return { type: 'create_video_editor_project', projectName }
  }
  if (type === 'open_video_editor_project') {
    return { type: 'open_video_editor_project', projectName: cleanString(raw.project_name, 160) || cleanString(raw.title, 160) }
  }
  if (type === 'add_video_editor_clips') {
    const outputNames = stringArray(raw.reference_output_names, 24, 300)
    if (!outputNames.length) return null
    return { type: 'add_video_editor_clips', outputNames }
  }
  if (type === 'order_video_editor_clips') {
    const clipNames = stringArray(raw.clip_names, 40, 300)
    if (!clipNames.length) return null
    return { type: 'order_video_editor_clips', clipNames }
  }
  if (type === 'trim_video_editor_clip') {
    const clipName = cleanString(raw.clip_name, 300)
    const trimStart = optionalNumber(raw.trim_start, 0, 86_400) ?? 0
    const trimEnd = optionalNumber(raw.trim_end, 0, 86_400)
    if (!clipName || trimEnd == null) return null
    return { type: 'trim_video_editor_clip', clipName, trimStart, trimEnd }
  }
  if (type === 'add_video_editor_audio') {
    const outputName = cleanString(raw.audio_output_name, 300)
    if (!outputName) return null
    return { type: 'add_video_editor_audio', clipName: cleanString(raw.clip_name, 300), outputName }
  }
  if (type === 'validate_video_editor_timeline') {
    return { type: 'validate_video_editor_timeline' }
  }
  if (type === 'export_video_editor') {
    if (raw.confirm !== true) return null
    return { type: 'export_video_editor', confirm: true }
  }
  if (type === 'track_video_editor_export') {
    return { type: 'track_video_editor_export' }
  }
  return null
}

/**
 * Treat model output as an untrusted proposal. Only known actions and bounded
 * fields survive, and generation can start only after this same turn prepared
 * a Studio form. That prevents stale chat context from firing the current form.
 */
export function parseAgentTurn(raw: string): AgentTurn {
  const object = extractJsonObject(raw)
  if (!object) return { reply: humanReply(raw.trim()), actions: [] }
  let reply = cleanString(object.reply, 8_000)
  if (reply.startsWith('{')) {
    const nested = extractJsonObject(reply)
    if (typeof nested?.reply === 'string') reply = cleanString(nested.reply, 8_000)
  }
  const proposed = Array.isArray(object.actions) ? object.actions.slice(0, MAX_ACTIONS) : []
  const actions: AgentAction[] = []
  let preparedStudio = false
  let startedGeneration = false
  for (const value of proposed) {
    const action = parseAction(value)
    if (!action) continue
    if (action.type === 'prepare_video' || action.type === 'prepare_image' || action.type === 'prepare_audio' || action.type === 'prepare_3d') preparedStudio = true
    if (action.type === 'start_generation') {
      if (!preparedStudio || startedGeneration) continue
      startedGeneration = true
    }
    actions.push(action)
  }
  const conversationLanguage = normalizeConversationLanguageTag(object.conversation_language)
  return {
    reply: reply || (actions.length ? 'El hechizo está trazado; voy a mover HocusPocus.' : humanReply(raw.trim())),
    actions,
    ...(conversationLanguage ? { conversationLanguage } : {}),
  }
}

export function protectUserVerbatimSegments(request: string, turn: AgentTurn): AgentTurn {
  const verbatimSegments = extractVerbatimSegments(request)
  if (!verbatimSegments.length) return turn
  return {
    ...turn,
    actions: turn.actions.map(action => {
      if (!isLanguageAwareCapability(action.type)) return action
      const current = 'languageIntent' in action ? action.languageIntent : undefined
      const contentLanguage = 'language' in action && typeof action.language === 'string' ? action.language : ''
      const lyricsLanguage = 'lyricsLanguage' in action && typeof action.lyricsLanguage === 'string'
        ? action.lyricsLanguage : ''
      const explicitSpokenLanguage = verbatimSegments.find(segment => (
        (segment.kind === 'dialogue' || segment.kind === 'lyrics') && segment.language
      ))?.language || ''
      const spokenLanguage = explicitSpokenLanguage || current?.spokenLanguage || lyricsLanguage || contentLanguage
      const deterministic = normalizeLanguageIntent({
        conversation_language: current?.conversationLanguage || turn.conversationLanguage,
        content_language: current?.contentLanguage || contentLanguage,
        spoken_language: spokenLanguage,
        technical_prompt_language: current?.technicalPromptLanguage || 'en',
        verbatim_segments: verbatimSegments.map(segment => ({
          ...segment,
          language: segment.language || spokenLanguage,
        })),
      })
      return {
        ...action,
        languageIntent: mergeLanguageIntent(current, deterministic),
      } as AgentAction
    }),
  }
}

const EXPLICIT_VIDEO_REQUESTS = [
  /\b(?:hazme|hacedme|generame|genérame|creame|créame)\b[^.!?\n]*\b(?:video|vídeo|clip)\b/i,
  /\b(?:haz|haced|genera|generad|crea|cread|lanza|lanzad|renderiza|renderizad|encola|encolad)\b[^.!?\n]*\b(?:video|vídeo|clip)\b/i,
  /\b(?:quiero|quisiera)\s+que\s+(?:me\s+)?(?:hagas|generes|crees|lances|pongas\s+en\s+marcha|env[ií]es)\b[^.!?\n]*\b(?:video|vídeo|clip)\b/i,
  /\b(?:puedes|podr[ií]as)\s+(?:hacerme|generarme|crearme|lanzar|poner\s+en\s+marcha|enviar)\b[^.!?\n]*\b(?:video|vídeo|clip)\b/i,
  /\b(?:ponme|pones|pon|poned)\b[^.!?\n]*\ben\s+marcha\b[^.!?\n]*\b(?:video|vídeo|clip)\b/i,
  /\b(?:pon|poned)\b[^.!?\n]*\b(?:video|vídeo|clip)\b[^.!?\n]*\b(?:en\s+marcha|a\s+generar|en\s+cola)\b/i,
  /\b(?:manda|mandad|env[ií]a|enviad)\b[^.!?\n]*\b(?:video|vídeo|clip)\b[^.!?\n]*\b(?:cola|generaci[oó]n)\b/i,
  /\b(?:make|create|generate|render|launch|start|queue)\b[^.!?\n]*\b(?:video|clip)\b/i,
  /\b(?:video|v[ií]deo|clip)\b[^.!?\n]*\b(?:gen[eé]ralo|l[aá]nzalo|enc[oó]lalo|ejec[uú]talo|render[ií]zalo|generate\s+it|launch\s+it|start\s+it|queue\s+it)\b/i,
]

const NEGATED_VIDEO_REQUEST = /\b(?:no|sin|don['’]?t|do\s+not)\b[^.!?\n]{0,32}\b(?:hagas|generes|crees|lances|encoles|hacer|generar|crear|lanzar|encolar|make|create|generate|render|launch|start|queue)\b/i

const EXPLICIT_CANCEL_REQUESTS = [
  /\b(?:cancela|cancelad|cancelar|para|parad|det[eé]n|detened)\b[^.!?\n]*\b(?:tarea|trabajo|job|cola|generaci[oó]n|v[ií]deo|video|clip)\b/i,
  /\b(?:para|parad|det[eé]n)\b[^.!?\n]*\b(?:lo que est[aá] (?:generando|renderizando|en cola|corriendo))\b/i,
  /\b(?:cancel|stop|abort)\b[^.!?\n]*\b(?:task|job|queue|generation|video|clip|active)\b/i,
]
const NEGATED_CANCEL_REQUEST = /\b(?:no|sin|don['’]?t|do\s+not)\b[^.!?\n]{0,24}\b(?:cancel|cancela|canceles|pares|detengas|stop|abort)\b/i

export function isExplicitCancelRequest(request: string): boolean {
  const text = request.trim()
  if (!text || NEGATED_CANCEL_REQUEST.test(text)) return false
  return EXPLICIT_CANCEL_REQUESTS.some(pattern => pattern.test(text))
}

const EXPLICIT_RETRY_REQUESTS = [
  /\b(?:reintenta|reintentad|reintentar|repite|repetid)\b[^.!?\n]*\b(?:tarea|trabajo|job|generaci[oó]n|fallo|fallida|cancelada|interrumpida)\b/i,
  /\b(?:retry|try\s+again)\b[^.!?\n]*\b(?:task|job|generation|failed|cancelled|interrupted)\b/i,
]
const NEGATED_RETRY_REQUEST = /\b(?:no|sin|don['’]?t|do\s+not)\b[^.!?\n]{0,24}\b(?:reintent|repet|retry|try\s+again)\b/i

export function isExplicitRetryRequest(request: string): boolean {
  const text = request.trim()
  return Boolean(text)
    && !NEGATED_RETRY_REQUEST.test(text)
    && EXPLICIT_RETRY_REQUESTS.some(pattern => pattern.test(text))
}

export function isExplicitVideoGenerationRequest(request: string): boolean {
  const text = request.trim()
  if (!text || NEGATED_VIDEO_REQUEST.test(text)) return false
  return EXPLICIT_VIDEO_REQUESTS.some(pattern => pattern.test(text))
}

export function isResumePreparedStudioVideoRequest(request: string): boolean {
  const text = request.trim()
  if (!text || NEGATED_VIDEO_REQUEST.test(text)) return false
  const match = text.match(
    /\b(?:genera|generad|lanza|lanzad|encola|encolad|env[ií]a|enviad|start|queue|launch)\b[^.!?\n]{0,24}\b(?:el|la|este|esta|the)\s+(?:video|v[ií]deo|clip)\b(.*)$/i,
  )
  if (!match) return false
  const leftover = match[1]
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[¿?¡!.,:;]/g, ' ')
    .replace(/\b(?:por favor|please|ya|ahora|now)\b/g, ' ')
    .replace(/\s+/g, '')
  return leftover.length === 0
}

const EXPLICIT_IMAGE_REQUESTS = [
  /\b(?:hazme|hacedme|generame|genérame|creame|créame)\b[^.!?\n]*\b(?:imagen|im[aá]genes|foto|fotos|retrato|ilustraci[oó]n)\b/i,
  /\b(?:haz|haced|genera|generad|crea|cread|lanza|lanzad|encola|encolad)\b[^.!?\n]*\b(?:imagen|im[aá]genes|foto|fotos|retrato|ilustraci[oó]n)\b/i,
  /\b(?:quiero|quisiera)\s+que\s+(?:me\s+)?(?:hagas|generes|crees|lances)\b[^.!?\n]*\b(?:imagen|foto|retrato)\b/i,
  /\b(?:make|create|generate|render|queue)\b[^.!?\n]*\b(?:image|picture|photo|portrait|illustration)\b/i,
]

export function isExplicitImageGenerationRequest(request: string): boolean {
  const text = request.trim()
  if (!text || NEGATED_VIDEO_REQUEST.test(text)) return false
  if (isExplicitVideoGenerationRequest(text)) return false
  return EXPLICIT_IMAGE_REQUESTS.some(pattern => pattern.test(text))
}

const EXPLICIT_AUDIO_GENERATION_REQUESTS = [
  /\b(?:gen[eé]ra(?:la|lo|r|d|me)?|crea(?:la|lo|r|d|me)?|lanza(?:la|lo|r|d)?|encola(?:la|lo|r|d)?)\b[^.!?\n]{0,120}\b(?:audio|canci[oó]n|m[uú]sica|voz|speech)\b/i,
  /\b(?:audio|canci[oó]n|m[uú]sica|voz|speech)\b[^.!?\n]{0,160}\b(?:gen[eé]ra(?:la|lo|r|d|me)?|l[aá]nza(?:la|lo|r|d)?|enc[oó]la(?:la|lo|r|d)?)\b/i,
]
const STUDIO_AUDIO_CONTEXT = [
  /\bstudio\s*(?:(?:→|->|›|\/|-)\s*)?audio\b/i,
  /\baudio\s+(?:de|del|en)\s+studio\b/i,
  /\b(?:pestaña|tab|secci[oó]n|modo|panel|formulario)\s+(?:de\s+)?audio\b/i,
]

export function isExplicitAudioGenerationRequest(request: string): boolean {
  const text = request.trim()
  if (!text || NEGATED_VIDEO_REQUEST.test(text) || MUSIC_VIDEO_CONTEXT.test(text)) return false
  if (isExplicitSfxGenerationRequest(text)) return false
  if (!STUDIO_AUDIO_CONTEXT.some(pattern => pattern.test(text))) return false
  return EXPLICIT_AUDIO_GENERATION_REQUESTS.some(pattern => pattern.test(text))
}

const EXPLICIT_SFX_REQUESTS = [
  /\b(?:efectos?(?:\s+de\s+sonido)?|sfx|sound effects?|sonidos?)\b/i,
]
const EXPLICIT_SFX_GENERATE = [
  /\b(?:genera(?:r|d|me)?|crea(?:r|d|me|ndo)?|hazme|hacedme|lanza(?:r|d)?|encola(?:r|d)?|make|creat(?:e|ing)|generat(?:e|ing)|queue)\b/i,
]
const GAME_SFX_HINT = /\b(?:vampire\s*survivors|oleadas?|horde|twin[\s-]?stick|arcade|juego|game)\b/i

const EXPLICIT_3D_REQUESTS = [
  /\b(?:hazme|hacedme|generame|genérame|creame|créame|haz|haced|genera|generad|crea|cread|lanza|lanzad)\b[^.!?\n]*\b(?:modelo|objeto|asset|malla)?\s*3d\b/i,
  /\b(?:make|create|generate|queue)\b[^.!?\n]*\b3d\s*(?:model|object|asset|mesh)\b/i,
  /\bhunyuan\s*3d\b/i,
]

export function isExplicit3dGenerationRequest(request: string): boolean {
  const text = request.trim()
  if (!text || NEGATED_VIDEO_REQUEST.test(text)) return false
  if (isExplicitVideoGenerationRequest(text) || isExplicitImageGenerationRequest(text) || isExplicitSfxGenerationRequest(text)) return false
  return EXPLICIT_3D_REQUESTS.some(pattern => pattern.test(text))
}

const MUSIC_VIDEO_CONTEXT = /\b(?:videoclip|videoclips|music\s*videos?|clip\s+musical|canci[oó]n\s+visual)\b/i
const MUSIC_VIDEO_STAGE_REQUESTS = [
  /\b(?:prepara|preparad|preparar|abre|abrid|carga|cargad|monta|montad|montar)\b[^.!?\n]*\b(?:videoclip|videoclips|music\s*videos?|clip\s+musical)\b/i,
  /\b(?:hazme|hacedme|crea|cread|creame|créame)\b[^.!?\n]*\b(?:videoclip|music\s*video|clip\s+musical)\b/i,
]
const MUSIC_VIDEO_START_REQUESTS = [
  /\b(?:l[aá]nzalo|lanzarlo|in[ií]cialo|iniciarlo|arr[aá]ncalo|arrancarlo|ejec[uú]talo|ejecutarlo|enc[oó]lalo|encolarlo)\b/i,
  /\b(?:l[aá]nza|inicia|arranca|ejecuta|genera|encola)\b[^.!?\n]*\b(?:videoclip|music\s*video|clip\s+musical|producci[oó]n\s+musical)\b/i,
  /\b(?:hazme|hacedme|crea|cread|creame|créame)\b[^.!?\n]*\b(?:videoclip|music\s*video|clip\s+musical)\b/i,
]
const NEGATED_MUSIC_VIDEO_PRODUCTION = /\b(?:(?:todav[ií]a|a[uú]n)\s+no|no)\s+(?:(?:quiero|queremos)\s+que\s+)?(?:(?:lo|la|el)\s+)?(?:prepares?|preparar|montes?|montar|inicies?|iniciar|arranques?|arrancar|ejecutes?|ejecutar|generes?|generar|encoles?|encolar)\b[^.!?\n]{0,48}\b(?:el\s+)?(?:videoclip|music\s*video|clip\s+musical)\b/i

function inferMusicVideoContext(text: string, history: ExampleConversation[]): boolean {
  if (MUSIC_VIDEO_CONTEXT.test(text)) return true
  return [...history].reverse().some(entry => MUSIC_VIDEO_CONTEXT.test(entry.text))
}

export function isExplicitMusicVideoStageRequest(request: string): boolean {
  const text = request.trim()
  if (!text || NEGATED_VIDEO_REQUEST.test(text) || NEGATED_MUSIC_VIDEO_PRODUCTION.test(text) || COMIC_LAUNCH_HOW.test(text)) return false
  return MUSIC_VIDEO_STAGE_REQUESTS.some(pattern => pattern.test(text))
}

export function isExplicitMusicVideoStartRequest(request: string, history: ExampleConversation[] = []): boolean {
  const text = request.trim()
  if (!text || NEGATED_VIDEO_REQUEST.test(text) || NEGATED_MUSIC_VIDEO_PRODUCTION.test(text) || COMIC_LAUNCH_HOW.test(text)) return false
  if (!MUSIC_VIDEO_START_REQUESTS.some(pattern => pattern.test(text))) return false
  return inferMusicVideoContext(text, history)
}

export function isExplicitSfxGenerationRequest(request: string): boolean {
  const text = request.trim()
  if (!text || NEGATED_VIDEO_REQUEST.test(text)) return false
  return EXPLICIT_SFX_REQUESTS.some(pattern => pattern.test(text))
    && EXPLICIT_SFX_GENERATE.some(pattern => pattern.test(text))
}

const COMIC_LAUNCH_HOW = /\b(?:c[oó]mo\s+(?:lo|la|las|los|puedo|se|lanz\w*|gener\w*|dibuj\w*|render\w*)\b|how(?:\s+do(?:\s+i)?)?)\b/i
const COMIC_LAUNCH_COMMAND = [
  /\b(?:l[aá]nzalo|dib[uú]jalo|p[ií]ntalo|generalo|regeneralo|render[ií]zalo)\b/i,
  /\b(?:l[aá]nza|dibuja|pinta|genera|regenera|render(?:iza)?)\b[^.!?\n]*\b(?:c[oó]mic|im[aá]genes?|vi[nñ]etas?|paneles?|p[aá]gina|artwork|dibujos?)\b/i,
  /\b(?:reintenta|reanuda|contin[uú]a)\b[^.!?\n]*\b(?:c[oó]mic|vi[nñ]etas?|fallid|pendientes|lote)\b/i,
  /\b(?:generate|regenerate|draw|render|launch|retry|resume)\b[^.!?\n]*\b(?:comic|panels?|page|artwork|failed)\b/i,
]

function comicPanelTarget(
  request: string,
  history: ExampleConversation[],
): { pageNumber: number; panelNumber: number } | null {
  if (NEGATED_VIDEO_REQUEST.test(request) || COMIC_LAUNCH_HOW.test(request)) return null
  if (!/\b(?:genera|regenera|dibuja|pinta|render(?:iza)?|generate|regenerate|draw|render)\b/i.test(request)) return null
  const panel = request.match(/\b(?:vi[nñ]eta|panel)\s*(?:n(?:[úu]mero|[º°])?\s*)?#?\s*(\d{1,2})\b/i)
  if (!panel || !inferComicContext(request, history)) return null
  const page = request.match(/\bp[aá]gina\s*(?:n(?:[úu]mero|[º°])?\s*)?#?\s*(\d{1,2})\b/i)
  return {
    pageNumber: Math.max(1, Number(page?.[1] || 1)),
    panelNumber: Math.max(1, Number(panel[1])),
  }
}

export function isComicLaunchHowQuestion(request: string, history: ExampleConversation[] = []): boolean {
  const text = request.trim()
  if (!text || !COMIC_LAUNCH_HOW.test(text)) return false
  if (!/\b(?:l[aá]nz|dibuj|pint|genera|render|launch|draw)/i.test(text)) return false
  return inferComicContext(text, history)
}

function comicGenerateIntent(request: string): Pick<AgentGenerateComicAction, 'scope' | 'pages' | 'pilot' | 'biographyReview'> {
  const text = request.trim()
  const pilot = /\b(?:piloto|p[aá]gina\s+piloto|s[oó]lo\s+la\s+primera\s+p[aá]gina)\b/i.test(text)
  const failed = /\b(?:fallidas?|reintenta(?:r)?\s+las\s+fallidas?|errores\s+del\s+c[oó]mic)\b/i.test(text)
  const all = /\b(?:regenera|desde\s+cero|de\s+nuevo)\b[^.!?\n]{0,40}\b(?:todas|im[aá]genes|vi[nñ]etas)\b/i.test(text)
  const pageMatch = text.match(/\bp[aá]ginas?\s+(\d+(?:\s*(?:,|y|and)\s*\d+)*)/i)
  const pages = pageMatch
    ? [...pageMatch[1].matchAll(/\d+/g)].map(match => Number(match[0])).filter(value => value >= 1)
    : (pilot ? [1] : [])
  return {
    scope: all ? 'all' : failed ? 'failed' : 'missing',
    pages,
    pilot,
    biographyReview: /\b(?:revisi[oó]n\s+factual|hechos\s+confirmados|biography_review)\b/i.test(text),
  }
}

export function isExplicitComicArtworkRequest(request: string, history: ExampleConversation[] = []): boolean {
  const text = request.trim()
  if (!text || NEGATED_VIDEO_REQUEST.test(text) || COMIC_LAUNCH_HOW.test(text)) return false
  if (!COMIC_LAUNCH_COMMAND.some(pattern => pattern.test(text))) return false
  return inferComicContext(text, history)
}

function inferComicContext(text: string, history: ExampleConversation[]): boolean {
  if (/\b(?:c[oó]mics?|vi[nñ]etas?|tebeo)\b/i.test(text)) return true
  return [...history].reverse().some(entry => (
    entry.role === 'user' && /\b(?:c[oó]mics?|vi[nñ]etas?|tebeo)\b/i.test(entry.text)
  )) || [...history].reverse().some(entry => (
    /\b(?:c[oó]mics?|vi[nñ]etas?|Comics Lab|Comic Director)\b/i.test(entry.text)
  ))
}

function comicCreateFallback(request: string): AgentCreateComicAction | undefined {
  if (!/\b(?:hazme|hacedme|crea(?:me)?|cread|crear|make|create)\b[^.!?\n]{0,120}\b(?:c[oó]mic|tebeo)\b/i.test(request)) return undefined
  const exactTitle = request.match(/\b(?:c[oó]mic|tebeo)\b[^.!?\n]{0,80}\btitulad[oa]\s+(?:exactamente\s+)?["“]([^"”]+)["”]/i)?.[1]?.trim()
  const topic = request.match(/\b(?:sobre|acerca\s+de)\s+([^.!?\n]+)/i)?.[1]?.trim()
    || request.match(/\b(?:c[oó]mic|tebeo)\s+de\s+([^.!?\n]+)/i)?.[1]?.trim()
    || 'una aventura inventada por el usuario'
  const pageCount = Math.min(24, Math.max(1, Number(request.match(/\b(\d{1,2})\s+p[aá]ginas?\b/i)?.[1] || 1)))
  const panelsPerPage = Math.min(12, Math.max(1, Number(request.match(/\b(\d{1,2})\s+vi[nñ]etas?[^.!?\n]{0,40}\bpor\s+p[aá]gina\b/i)?.[1] || 4)))
  const title = exactTitle || topic.slice(0, 100) || 'Nuevo cómic'
  const pages: AgentComicPage[] = Array.from({ length: pageCount }, (_, pageIndex) => ({
    title: `Página ${pageIndex + 1}`,
    stage: `Etapa ${pageIndex + 1} de ${pageCount}`,
    panels: Array.from({ length: panelsPerPage }, (_, panelIndex) => ({
      caption: `Página ${pageIndex + 1} · Viñeta ${panelIndex + 1}`,
      dialogue: '',
      sfx: '',
      scene: `${topic}. Momento ${panelIndex + 1} de la etapa ${pageIndex + 1}; composición distinta y continuidad visual con las demás viñetas.`,
    })),
  }))
  return {
    type: 'create_comic',
    title,
    synopsis: topic,
    language: /\b(?:espa[nñ]ol|castellano)\b/i.test(request) ? 'Español' : '',
    styleName: 'Dirección visual coherente con la petición del usuario',
    characters: [],
    panels: [],
    pages,
    imageProvider: 'profile',
    imageModel: '',
    factualBiography: /\b(?:biograf[ií]a|biogr[aá]fico|vida\s+de)\b/i.test(request),
  }
}

/**
 * The LLM remains the planner, but an unmistakable user command must not turn
 * into a clarification loop. Repair that one high-value intent locally with
 * conservative defaults. This is deliberately narrow: questions such as
 * “how do I generate a video?” and negated requests remain read-only.
 */
export async function reconcileAgentTurnWithRequest(
  request: string,
  turn: AgentTurn,
  history: ExampleConversation[] = [],
): Promise<AgentTurn> {
  const { maybeExampleTurn } = await import('./agentExamples')
  const exactEpisodeTitle = request.match(/\bepisodio\s+titulad[oa]\s+(?:exactamente\s+)?["“]([^"”]+)["”]/i)?.[1]?.trim()
  const preserveExactEpisodeTitle = (candidate: AgentTurn): AgentTurn => exactEpisodeTitle
    ? {
        ...candidate,
        actions: candidate.actions.map(action => action.type === 'create_series_episode'
          ? { ...action, episodeTitle: exactEpisodeTitle }
          : action),
      }
    : candidate
  turn = preserveExactEpisodeTitle(turn)
  if (isResumePreparedStudioVideoRequest(request)) {
    const existing = turn.actions.find(
      (action): action is AgentPrepareVideoAction => action.type === 'prepare_video',
    )
    const state = useStore.getState()
    const studioPrompt = state.generationMode === 'video'
      ? String(state.params.prompt || '').trim()
      : String(state.savedPromptPerMode?.video || '').trim()
    const prompt = existing?.prompt.trim() || studioPrompt
    if (!prompt) {
      return {
        reply: 'Studio no tiene un prompt preparado. Dime la escena y la encolo.',
        actions: [{ type: 'open_tab', tab: 'studio' }],
      }
    }
    const prepare: AgentPrepareVideoAction = existing || {
      type: 'prepare_video',
      prompt,
      durationSeconds: state.generationMode === 'video' ? state.durationSeconds : undefined,
      resolutionPreset: state.generationMode === 'video' ? state.resolutionPreset : undefined,
      aspectRatio: state.generationMode === 'video' ? state.aspectRatio : undefined,
    }
    return {
      reply: 'Lanzo a la cola el vídeo ya preparado en Studio. 🪄',
      actions: [prepare, { type: 'start_generation', confirm: true }],
    }
  }
  const exampleTurn = maybeExampleTurn(request, turn, history)
  if (exampleTurn) return preserveExactEpisodeTitle(exampleTurn)
  const rhythmic3dWorkflow = turn.actions.find(
    (action): action is AgentCreateRhythmic3dVideoAction => action.type === 'create_rhythmic_3d_video',
  )
  if (rhythmic3dWorkflow) {
    return {
      reply: 'Invocaré la canción y esperaré su taskId real; después crearé la escena 3D, convertiré sus beats en keyframes editables, guardaré el proyecto y publicaré el MP4. Si un paso falla, el hechizo podrá reanudarse desde ese punto. 🪄',
      actions: [rhythmic3dWorkflow],
    }
  }
  if (isComicLaunchHowQuestion(request, history)) {
    return {
      reply: [
        'No hay un botón llamado **Render page**.',
        'El dibujo de las viñetas es **Generate all images** en Comic Director (barra de Comics), o dímelo aquí: **lánzalo**.',
        'Las viñetas entran en la **misma GPU**, una detrás de otra, no en paralelo. No es un segundo motor.',
      ].join('\n\n'),
      actions: [{ type: 'open_tab', tab: 'comics' }],
    }
  }
  const targetedComicPanel = comicPanelTarget(request, history)
  if (targetedComicPanel) {
    return {
      reply: `Regeneraré sólo la viñeta ${targetedComicPanel.panelNumber} de la página ${targetedComicPanel.pageNumber}; las demás quedan intactas. 🪄`,
      actions: [{
        type: 'generate_comic_panel',
        pageNumber: targetedComicPanel.pageNumber,
        panelNumber: targetedComicPanel.panelNumber,
        confirm: true,
      }],
    }
  }
  const plannedComic = turn.actions.find((action): action is AgentCreateComicAction => action.type === 'create_comic')
    || comicCreateFallback(request)
  const compoundComicRender = Boolean(plannedComic) && /\b(?:genera|dibuja|pinta|render(?:iza)?|generate|draw|render)\b[^.!?\n]*\b(?:im[aá]genes|artwork|vi[nñ]etas?|paneles?)\b/i.test(request)
  if (isExplicitComicArtworkRequest(request, history) || compoundComicRender) {
    const create = plannedComic
    const requestedMiniMax = /\bminimax\b/i.test(request)
    const requestedLocal = /\b(?:proveedor|modelo|generador)\s+local\b|\b(?:local|hocuspocus|maestro)\s+(?:provider|model|image\s+provider)\b/i.test(request)
    const requestedProvider = requestedMiniMax ? 'minimax' as const : requestedLocal ? 'maestro' as const : 'keep' as const
    const intent = comicGenerateIntent(request)
    const generate: AgentGenerateComicAction = {
      type: 'generate_comic',
      imageProvider: requestedProvider,
      imageModel: requestedMiniMax ? 'image-01' : '',
      scope: intent.scope,
      pages: intent.pages,
      pilot: intent.pilot,
      biographyReview: intent.biographyReview,
      confirm: true,
    }
    if (create) {
      const prepared = requestedProvider === 'minimax'
        ? { ...create, imageProvider: 'minimax' as const, imageModel: 'image-01' }
        : requestedProvider === 'maestro'
          ? { ...create, imageProvider: 'maestro' as const, imageModel: '' }
          : create
      const panels = (prepared.pages.length ? prepared.pages : [{ panels: prepared.panels }])
        .reduce((sum, page) => sum + page.panels.length, 0)
      const estimate = intent.pilot ? (prepared.pages[0]?.panels.length || prepared.panels.length) : panels
      return {
        reply: `Crearé “${prepared.title}” con ${prepared.pages.length || 1} páginas reales y después dibujaré ${intent.pilot ? 'la página piloto' : intent.scope === 'failed' ? 'las viñetas fallidas' : 'las viñetas pendientes'} con ${requestedMiniMax ? 'MiniMax image-01' : requestedLocal ? 'el proveedor local' : 'el proveedor elegido'}. Estimación: ${estimate} llamadas${requestedMiniMax ? ' MiniMax' : ''}. 🪄`,
        actions: [prepared, generate],
      }
    }
    const inventory = comicArtworkInventory()
    const estimate = intent.pilot
      ? Math.max(1, Math.ceil(inventory.panels / Math.max(1, inventory.pages)))
      : intent.scope === 'failed' ? inventory.failed : inventory.pending
    return {
      reply: `Voy a dibujar ${intent.pilot ? 'la página piloto' : intent.scope === 'failed' ? 'las viñetas fallidas' : 'las viñetas pendientes'} del cómic abierto con ${requestedMiniMax ? 'MiniMax image-01' : requestedLocal ? 'el proveedor local' : 'su proveedor configurado'}. Estimación: ${estimate} llamadas${requestedMiniMax ? ' MiniMax' : ''} (${inventory.completed}/${inventory.panels} ya listas). 🪄`,
      actions: [generate],
    }
  }
  if (NEGATED_MUSIC_VIDEO_PRODUCTION.test(request)) {
    let safeActions = turn.actions.filter(action => (
      action.type !== 'stage_story_music_video'
      && action.type !== 'start_director_production'
    ))
    let songDraft = safeActions.find(
      (action): action is AgentConfigureStorySongAction => action.type === 'configure_story_song',
    )
    const createdMusicVideo = safeActions.find(
      (action): action is AgentCreateStoryAction => action.type === 'create_story' && action.projectType === 'music_video',
    )
    const explicitlyConfigureSong = /\b(?:rellena|rellenar|escribe|escribir|comp[oó]n|componer|prepara|preparar|crea|crear|genera|generar)\b[^.!?\n]{0,160}\bcanci[oó]n\b/i.test(request)
    if (!songDraft && createdMusicVideo && explicitlyConfigureSong) {
      songDraft = {
        type: 'configure_story_song',
        targetStoryTitle: createdMusicVideo.title,
        songTitle: createdMusicVideo.title,
        brief: createdMusicVideo.creativeBrief || createdMusicVideo.premise,
        style: request.trim().slice(0, 4_000),
        lyrics: '',
        writeLyrics: true,
        lyricsLanguage: createdMusicVideo.language || 'Español',
        instrumental: false,
        model: 'ace_step_v1_5_xl_sft_lm_4b',
        durationSeconds: createdMusicVideo.durationSeconds || 90,
      }
      safeActions = [...safeActions, songDraft]
    }
    const explicitlyGenerateSong = /\bgenera(?:r|d|me)?\b[^.!?\n]{0,96}\b(?:primera\s+versi[oó]n\s+de\s+la\s+)?canci[oó]n\b/i.test(request)
    const correlatedActions = songDraft
      ? safeActions.map(action => action.type === 'generate_story_song'
        ? { ...action, targetStoryTitle: songDraft.targetStoryTitle, cueTitle: songDraft.songTitle }
        : action)
      : safeActions
    const actions = songDraft && explicitlyGenerateSong
      && !correlatedActions.some(action => action.type === 'generate_story_song')
      ? [...correlatedActions, {
          type: 'generate_story_song' as const,
          targetStoryTitle: songDraft.targetStoryTitle,
          cueTitle: songDraft.songTitle,
          confirm: true as const,
        }]
      : correlatedActions
    return {
      ...turn,
      actions,
    }
  }
  const musicVideoStage = isExplicitMusicVideoStageRequest(request)
  const musicVideoStart = isExplicitMusicVideoStartRequest(request, history)
  if (musicVideoStage || musicVideoStart) {
    const proposedActions = turn.actions.map(action => (
      action.type === 'create_story' && action.projectType !== 'music_video'
        ? { ...action, projectType: 'music_video' as const }
        : action
    ))
    const newSongRequest = isNewMusicVideoSongRequest(request)
    const omittedNewSongStory = newSongRequest
      && !proposedActions.some(action => action.type === 'create_story')
    // A request for "a song about..." describes a new authored object. Empty
    // stage fields must never reinterpret that request as "use the currently
    // selected song", because UI selection is mutable and may belong to an
    // unrelated project. Recover the omitted plan before resolving any target.
    const actions: AgentAction[] = omittedNewSongStory
      ? [newMusicVideoStoryAction(request, turn.conversationLanguage), ...proposedActions]
      : proposedActions
    const storySongSetup = actions.filter(action => (
      action.type === 'create_story'
      || action.type === 'configure_story_song'
      || action.type === 'generate_story_song'
    ))
    const existingStage = actions.find(
      (action): action is AgentStageStoryMusicVideoAction => action.type === 'stage_story_music_video',
    )
    const songDraft = actions.find(
      (action): action is AgentConfigureStorySongAction => action.type === 'configure_story_song',
    )
    const createdMusicVideo = actions.find(
      (action): action is AgentCreateStoryAction => action.type === 'create_story' && action.projectType === 'music_video',
    )
    const automaticDraft: AgentConfigureStorySongAction | undefined = !songDraft && createdMusicVideo
      ? {
          type: 'configure_story_song',
          targetStoryTitle: createdMusicVideo.title,
          songTitle: createdMusicVideo.title,
          brief: createdMusicVideo.creativeBrief || createdMusicVideo.premise,
          style: request.trim().slice(0, 4_000),
          lyrics: '',
          writeLyrics: true,
          lyricsLanguage: createdMusicVideo.language || 'Español',
          instrumental: false,
          model: 'ace_step_v1_5_xl_sft_lm_4b',
          durationSeconds: createdMusicVideo.durationSeconds || 90,
        }
      : undefined
    const effectiveSongDraft = songDraft || automaticDraft
    const songTarget = newSongRequest && createdMusicVideo ? createdMusicVideo.title : effectiveSongDraft?.targetStoryTitle || ''
    const songTitle = effectiveSongDraft?.songTitle || createdMusicVideo?.title || ''
    const completeSongSetup = automaticDraft ? [...storySongSetup, automaticDraft] : storySongSetup
    // A rendered candidate label ("Title · Español · v1") does not exist yet
    // while the song is only a cue. Correlate every later step with the exact
    // cue that this same plan configures instead of trusting independently
    // guessed names from the LLM.
    const correlatedSongSetup = effectiveSongDraft
      ? completeSongSetup.map(action => {
          if (action.type === 'configure_story_song') return { ...effectiveSongDraft, targetStoryId: newSongRequest && createdMusicVideo ? undefined : effectiveSongDraft.targetStoryId, targetStoryTitle: songTarget, songTitle }
          if (action.type === 'generate_story_song') {
            return {
              ...action,
              targetStoryId: newSongRequest && createdMusicVideo ? undefined : action.targetStoryId,
              targetStoryTitle: songTarget, cueId: newSongRequest && createdMusicVideo ? undefined : action.cueId, cueTitle: songTitle,
            }
          }
          return action
        })
      : completeSongSetup
    const stageSeed: AgentStageStoryMusicVideoAction = existingStage || {
      type: 'stage_story_music_video',
      targetStoryTitle: songTarget || createdMusicVideo?.title || '',
      songName: '',
      cueTitle: songTitle,
      pacing: 'balanced',
      confirm: true,
    }
    const stage: AgentStageStoryMusicVideoAction = {
      ...stageSeed,
      targetStoryId: newSongRequest && createdMusicVideo ? undefined : stageSeed.targetStoryId,
      targetStoryTitle: songTarget || createdMusicVideo?.title || stageSeed.targetStoryTitle || '', cueId: newSongRequest && createdMusicVideo ? undefined : stageSeed.cueId, cueTitle: songTitle || stageSeed.cueTitle || '',
      songName: effectiveSongDraft ? '' : stageSeed.songName,
    }
    if (musicVideoStage && musicVideoStart) {
      const configuredSong = correlatedSongSetup.some(action => action.type === 'configure_story_song')
      const songActions = configuredSong && !correlatedSongSetup.some(action => action.type === 'generate_story_song')
        ? [...correlatedSongSetup, { type: 'generate_story_song' as const, targetStoryTitle: stage.targetStoryTitle, cueTitle: stage.cueTitle, confirm: true as const }]
        : correlatedSongSetup
      return {
        reply: configuredSong
          ? 'Guardaré la canción y su letra en Story Lab, generaré el audio real y sólo entonces prepararé e iniciaré el videoclip. En marcha no es terminado. 🪄'
          : 'Prepararé el videoclip en Music Video Director y, si el plan queda listo, lo iniciaré. Preparado no es en cola; en marcha no es terminado. 🪄',
        actions: [...songActions, stage, { type: 'start_director_production', targetStoryTitle: stage.targetStoryTitle, kind: 'music_video', confirm: true }],
      }
    }
    if (musicVideoStart) {
      return {
        reply: 'Iniciaré la producción de videoclip ya preparada en Director y devolveré el pipelineId real. En marcha no es terminado. 🪄',
        actions: [{ type: 'start_director_production', targetStoryTitle: '', kind: 'music_video', confirm: true }],
      }
    }
    return {
      reply: 'Prepararé el videoclip en Music Video Director con la historia, la canción y el cue exactos. No iniciaré generación. 🪄',
      actions: [stage],
    }
  }
  if (isExplicitSfxGenerationRequest(request)) {
    const existing = turn.actions.find(
      (action): action is AgentQueueSfxPackAction => action.type === 'queue_sfx_pack',
    )
    const clips = existing?.clips.length
      ? existing.clips
      : GAME_SFX_HINT.test(request) ? ARCADE_HORDE_SFX_PACK : []
    if (clips.length) {
      return {
        reply: 'Prepararé Studio → Audio → SFX y encolaré el pack de efectos. Irán detrás de lo que ya use la GPU. La galería Audios solo muestra resultados cuando terminen. 🪄',
        actions: [{
          type: 'queue_sfx_pack',
          style: existing?.style || 'retro fantasy arcade',
          clips,
          confirm: true,
        }],
      }
    }
  }
  if (isExplicitCancelRequest(request)) {
    const existing = turn.actions.find(
      (action): action is AgentCancelTaskAction => action.type === 'cancel_task',
    )
    return {
      reply: 'Cancelaré la tarea activa en la cola canónica y dejaré Activity a la vista. 🪄',
      actions: [{ type: 'cancel_task', taskId: existing?.taskId || '', confirm: true }],
    }
  }
  if (isExplicitRetryRequest(request)) {
    const existing = turn.actions.find(
      (action): action is AgentRetryTaskAction => action.type === 'retry_task',
    )
    const latest = /(?:[uú]ltim[oa]|latest|last)/i.test(request)
    return {
      reply: 'Reintentaré la tarea canónica indicada desde su estado persistido y abriré Activity para mostrar el resultado. 🪄',
      actions: [{
        type: 'retry_task',
        taskId: existing?.taskId || (latest ? 'latest' : ''),
        confirm: true,
      }],
    }
  }
  if (isExplicitAudioGenerationRequest(request)) {
    const navigation = turn.actions
      .filter((action): action is AgentOpenTabAction => action.type === 'open_tab')
      .slice(0, MAX_ACTIONS - 2)
    const prepare = turn.actions.find(
      (action): action is AgentPrepareAudioAction => action.type === 'prepare_audio',
    ) || {
        type: 'prepare_audio',
        subMode: /\b(?:voz|speech|tts)\b/i.test(request) ? 'speech' : 'music',
        prompt: request.trim().slice(0, 8_000),
        durationSeconds: 15,
      } satisfies AgentPrepareAudioAction
    return {
      reply: 'Prepararé Studio → Audio con los valores visibles y enviaré la generación a la cola. 🪄',
      actions: [...navigation, prepare, { type: 'start_generation', confirm: true }],
    }
  }
  if (isExplicitVideoGenerationRequest(request)) {
    const navigation = turn.actions
      .filter((action): action is AgentOpenTabAction => action.type === 'open_tab')
      .slice(0, MAX_ACTIONS - 2)
    const prepare = turn.actions.find(
      (action): action is AgentPrepareVideoAction => action.type === 'prepare_video',
    ) || {
        type: 'prepare_video',
        prompt: request.trim().slice(0, 8_000),
        durationSeconds: 5,
        resolutionPreset: '720p',
        aspectRatio: '16:9',
        seed: -1,
        outputCount: 1,
      } satisfies AgentPrepareVideoAction

    return {
      reply: '¡La petición está clara! Usaré un conjuro de vídeo estándar con los ajustes disponibles, prepararé Studio → Video y lo enviaré a la cola. 🪄',
      actions: [...navigation, prepare, { type: 'start_generation', confirm: true }],
    }
  }
  if (isExplicit3dGenerationRequest(request)) {
    const navigation = turn.actions
      .filter((action): action is AgentOpenTabAction => action.type === 'open_tab')
      .slice(0, MAX_ACTIONS - 2)
    const prepare = turn.actions.find(
      (action): action is AgentPrepare3dAction => action.type === 'prepare_3d',
    ) || {
        type: 'prepare_3d',
        prompt: request.trim().slice(0, 8_000),
        preset: 'balanced',
        seed: 1234,
      } satisfies AgentPrepare3dAction
    return {
      reply: 'Prepararé Studio → 3D (Hunyuan3D) con un preset equilibrado y lo enviaré a generar. 🪄',
      actions: [...navigation, prepare, { type: 'start_generation', confirm: true }],
    }
  }
  if (NEGATED_VIDEO_REQUEST.test(request)) {
    const blocked = new Set([
      'start_generation', 'generate_comic', 'generate_comic_panel', 'queue_sfx_pack',
      'start_director_production', 'generate_story_visuals', 'generate_story_section',
      'render_series_shots', 'assemble_series_episode', 'export_3d_scene',
    ])
    return { ...turn, actions: turn.actions.filter(action => !blocked.has(action.type)) }
  }
  if (!isExplicitImageGenerationRequest(request)) return turn

  const navigation = turn.actions
    .filter((action): action is AgentOpenTabAction => action.type === 'open_tab')
    .slice(0, MAX_ACTIONS - 2)
  const prepare = turn.actions.find(
    (action): action is AgentPrepareImageAction => action.type === 'prepare_image',
  ) || {
      type: 'prepare_image',
      prompt: request.trim().slice(0, 8_000),
      resolutionPreset: 'auto',
      aspectRatio: 'auto',
      seed: -1,
      outputCount: 1,
    } satisfies AgentPrepareImageAction

  return {
    reply: '¡La petición está clara! Prepararé Studio → Image con un modelo compatible y lo enviaré a la cola. 🪄',
    actions: [...navigation, prepare, { type: 'start_generation', confirm: true }],
  }
}

export const HOCUSPOCUS_REGISTERED_ACTION_SCHEMAS = registeredCapabilitySchemas()

export const HOCUSPOCUS_AGENT_RESPONSE_SCHEMA: Record<string, unknown> = {
  type: 'object',
  additionalProperties: false,
  properties: {
    reply: { type: 'string', maxLength: 8_000 },
    conversation_language: { type: 'string', maxLength: 120 },
    actions: {
      type: 'array',
      maxItems: MAX_ACTIONS,
      items: {
        type: 'object',
        additionalProperties: false,
        properties: {
          type: { type: 'string', enum: listCapabilities().map(item => item.name) },
          language_intent: LANGUAGE_INTENT_SCHEMA,
          tab: { type: 'string', enum: ['', ...AGENT_TABS] },
          story_section: { type: 'string', enum: ['', ...STORY_SECTIONS] },
          series_section: { type: 'string', enum: ['', ...SERIES_SECTIONS] },
          prompt: { type: 'string', maxLength: 8_000 },
          model_type: { type: 'string', maxLength: 160 },
          duration_seconds: { type: 'number', minimum: 0, maximum: 300 },
          resolution_preset: { type: 'string', enum: ['', 'auto', '480p', '540p', '720p', '768p', '1080p'] },
          resolution: { type: 'string', maxLength: 20 },
          aspect_ratio: { type: 'string', enum: ['', 'auto', '21:9', '16:9', '9:16', '1:1', '4:3', '3:4'] },
          negative_prompt: { type: 'string', maxLength: 2_000 },
          seed: { type: 'integer', minimum: -1, maximum: 2_147_483_647 },
          inference_steps: { type: 'integer', minimum: 0, maximum: 100 },
          guidance_scale: { type: 'number', minimum: -1, maximum: 30 },
          output_count: { type: 'integer', minimum: 0, maximum: 8 },
          audio_direction: { type: 'string', maxLength: 1_000 },
          turbo: { type: 'string', enum: ['keep', 'on', 'off'] },
          title: { type: 'string', maxLength: 300 },
          target_story_title: { type: 'string', maxLength: 300 },
          story_generation_scope: { type: 'string', enum: ['', 'all', 'overview', 'world', 'characters', 'relationships', 'structure'] },
          story_visual_scope: { type: 'string', enum: ['', 'world', 'locations', 'characters', 'all'] },
          series_plan_scope: { type: 'string', enum: ['', 'outline', 'script', 'shots', 'complete'] },
          instruction: { type: 'string', maxLength: 4_000 },
          direction: { type: 'string', maxLength: 4_000 },
          page_count: { type: 'integer', minimum: 0, maximum: 100 },
          panels_per_page: { type: 'integer', minimum: 0, maximum: 12 },
          project_type: { type: 'string', enum: ['', 'full_story', 'music_video', 'trailer', 'quick_video'] },
          production_kind: { type: 'string', enum: ['', 'film', 'trailer', 'music_video'] },
          song_name: { type: 'string', maxLength: 300 },
          song_title: { type: 'string', maxLength: 300 },
          cue_title: { type: 'string', maxLength: 300 },
          song_brief: { type: 'string', maxLength: 4_000 },
          music_style: { type: 'string', maxLength: 4_000 },
          lyrics: { type: 'string', maxLength: 12_000 },
          write_lyrics: { type: 'boolean' },
          lyrics_language: { type: 'string', maxLength: 120 },
          instrumental: { type: 'boolean' },
          pacing: { type: 'string', enum: ['', 'cinematic', 'balanced', 'rhythmic'] },
          creative_brief: { type: 'string', maxLength: 4_000 },
          premise: { type: 'string', maxLength: 2_000 },
          logline: { type: 'string', maxLength: 2_000 },
          synopsis: { type: 'string', maxLength: 6_000 },
          theme: { type: 'string', maxLength: 1_000 },
          ending: { type: 'string', maxLength: 2_000 },
          genre: { type: 'string', maxLength: 300 },
          tone: { type: 'string', maxLength: 500 },
          visual_style: { type: 'string', maxLength: 2_000 },
          world_summary: { type: 'string', maxLength: 3_000 },
          language: { type: 'string', maxLength: 120 },
          series_title: { type: 'string', maxLength: 300 },
          series_premise: { type: 'string', maxLength: 3_000 },
          series_logline: { type: 'string', maxLength: 2_000 },
          episode_title: { type: 'string', maxLength: 300 },
          target_episode_title: { type: 'string', maxLength: 300 },
          episode_premise: { type: 'string', maxLength: 3_000 },
          episode_logline: { type: 'string', maxLength: 2_000 },
          target_duration_seconds: { type: 'number', minimum: 0, maximum: 3_600 },
          create_if_missing: { type: 'boolean' },
          known_universe: { type: 'boolean' },
          queue_scope: { type: 'string', enum: ['', 'active', 'all'] },
          task_id: { type: 'string', maxLength: 160 },
          job_id: { type: 'string', maxLength: 160 },
          render_mode: { type: 'string', enum: ['', 'selected', 'missing', 'failed', 'all'] },
          shot_ids: { type: 'array', maxItems: 200, items: { type: 'string', maxLength: 160 } },
          shot_numbers: { type: 'array', maxItems: 200, items: { type: 'integer', minimum: 1, maximum: 10_000 } },
          attempt_id: { type: 'string', maxLength: 160 },
          review_decision: { type: 'string', enum: ['', 'approve', 'reject'] },
          review_scope: { type: 'string', enum: ['', 'selected_latest', 'all_latest'] },
          canon_decision: { type: 'string', enum: ['', 'accept_all', 'reject_all', 'accept_selected', 'reject_selected'] },
          canon_item_ids: { type: 'array', maxItems: 200, items: { type: 'string', maxLength: 160 } },
          target_names: { type: 'array', maxItems: 40, items: { type: 'string', maxLength: 300 } },
          scene_name: { type: 'string', maxLength: 300 },
          layer_name: { type: 'string', maxLength: 300 },
          audio_output_name: { type: 'string', maxLength: 300 },
          visual_output_name: { type: 'string', maxLength: 300 },
          cue_source: { type: 'string', enum: ['', 'beats', 'downbeats'] },
          rhythm_profile: { type: 'string', enum: ['', 'pulse', 'bounce', 'peek', 'camera-punch'] },
          intensity: { type: 'number', minimum: 0, maximum: 1 },
          layer_type: { type: 'string', enum: ['', 'model3d', 'image', 'video', 'overlay', 'camera'] },
          output_name: { type: 'string', maxLength: 300 },
          width: { type: 'integer', minimum: 320, maximum: 7680 },
          height: { type: 'integer', minimum: 240, maximum: 4320 },
          fps: { type: 'integer', enum: [30, 60] },
          visible: { type: 'boolean' },
          locked: { type: 'boolean' },
          confirm: { type: 'boolean' },
          page_number: { type: 'integer', minimum: 0, maximum: 100 },
          panel_number: { type: 'integer', minimum: 0, maximum: 100 },
          reference_output_names: { type: 'array', maxItems: 12, items: { type: 'string', maxLength: 300 } },
          reference_role: { type: 'string', enum: ['', 'start_frame', 'subject', 'style'] },
          replace_existing: { type: 'boolean' },
          remove_background: { type: 'boolean' },
          workspace_name: { type: 'string', maxLength: 120 },
          workspace_id: { type: 'string', maxLength: 200 },
          expected_revision: { type: 'integer', minimum: 1 },
          description: { type: 'string', maxLength: 2_000 },
          project_ids: { type: 'array', maxItems: 500, items: { type: 'string', maxLength: 200 } },
          asset_ids: { type: 'array', maxItems: 500, items: { type: 'string', maxLength: 200 } },
          production_ids: { type: 'array', maxItems: 500, items: { type: 'string', maxLength: 200 } },
          loras: {
            type: 'array', maxItems: 12,
            items: {
              type: 'object', additionalProperties: false,
              properties: {
                name: { type: 'string', maxLength: 300 },
                weight: { type: 'number', minimum: 0, maximum: 2 },
              },
              required: ['name', 'weight'],
            },
          },
          audio_sub_mode: { type: 'string', enum: ['', 'speech', 'music', 'sfx'] },
          preset: { type: 'string', maxLength: 40 },
          sfx_clips: {
            type: 'array', maxItems: 12,
            items: {
              type: 'object', additionalProperties: false,
              properties: {
                name: { type: 'string', maxLength: 80 },
                prompt: { type: 'string', maxLength: 1_500 },
                duration_seconds: { type: 'number', minimum: 0, maximum: 20 },
              },
              required: ['name', 'prompt', 'duration_seconds'],
            },
          },
          story_visual_selections: {
            type: 'array', maxItems: 40,
            items: {
              type: 'object', additionalProperties: false,
              properties: {
                target_kind: { type: 'string', enum: ['world', 'location', 'character'] },
                target_name: { type: 'string', maxLength: 300 },
                asset_name: { type: 'string', maxLength: 300 },
                primary: { type: 'boolean' },
              },
              required: ['target_kind', 'target_name', 'asset_name', 'primary'],
            },
          },
          characters: {
            type: 'array', maxItems: 16,
            items: {
              type: 'object', additionalProperties: false,
              properties: {
                name: { type: 'string', maxLength: 160 },
                role: { type: 'string', maxLength: 300 },
                personality: { type: 'string', maxLength: 1_000 },
                desire: { type: 'string', maxLength: 1_000 },
                flaw: { type: 'string', maxLength: 1_000 },
                appearance: { type: 'string', maxLength: 1_000 },
                voice: { type: 'string', maxLength: 1_000 },
              },
              required: ['name', 'role', 'personality', 'desire', 'flaw', 'appearance', 'voice'],
            },
          },
          locations: {
            type: 'array', maxItems: 16,
            items: {
              type: 'object', additionalProperties: false,
              properties: {
                name: { type: 'string', maxLength: 160 },
                purpose: { type: 'string', maxLength: 1_000 },
                description: { type: 'string', maxLength: 1_500 },
              },
              required: ['name', 'purpose', 'description'],
            },
          },
          outline_beats: { type: 'array', maxItems: 24, items: { type: 'string', maxLength: 1_500 } },
          comic_panels: {
            type: 'array', maxItems: 12,
            items: {
              type: 'object', additionalProperties: false,
              properties: {
                caption: { type: 'string', maxLength: 400 },
                dialogue: { type: 'string', maxLength: 400 },
                sfx: { type: 'string', maxLength: 80 },
                scene: { type: 'string', maxLength: 800 },
              },
              required: ['caption', 'dialogue', 'sfx'],
            },
          },
          comic_pages: {
            type: 'array', maxItems: 30,
            items: {
              type: 'object', additionalProperties: false,
              properties: {
                title: { type: 'string', maxLength: 300 }, stage: { type: 'string', maxLength: 600 },
                comic_panels: {
                  type: 'array', maxItems: 12,
                  items: {
                    type: 'object', additionalProperties: false,
                    properties: { caption: { type: 'string', maxLength: 400 }, dialogue: { type: 'string', maxLength: 400 }, sfx: { type: 'string', maxLength: 80 }, scene: { type: 'string', maxLength: 800 } },
                    required: ['caption', 'dialogue', 'sfx'],
                  },
                },
              },
              required: ['title', 'stage', 'comic_panels'],
            },
          },
          image_provider: { type: 'string', enum: ['', 'profile', 'keep', 'maestro', 'minimax'] },
          page_numbers: { type: 'array', maxItems: 30, items: { type: 'integer', minimum: 1, maximum: 100 } },
          pilot: { type: 'boolean' },
          factual_biography: { type: 'boolean' },
          biography_review: { type: 'boolean' },
          kit_name: { type: 'string', maxLength: 160 },
          look_notes: { type: 'string', maxLength: 4_000 },
          preset_id: { type: 'string', maxLength: 160 },
          project_name: { type: 'string', maxLength: 160 },
          clip_names: { type: 'array', maxItems: 40, items: { type: 'string', maxLength: 300 } },
          clip_name: { type: 'string', maxLength: 300 },
          videoclip_name: { type: 'string', maxLength: 300 },
          trim_start: { type: 'number', minimum: 0, maximum: 86_400 },
          trim_end: { type: 'number', minimum: 0, maximum: 86_400 },
        },
        required: ['type'],
      },
    },
  },
  required: ['reply', 'actions'],
}

export function buildAgentAppSnapshot(contextOptions: BuildWizardContextOptions = {}): AgentAppSnapshot {
  const state = useStore.getState()
  return {
    context: buildWizardContextSnapshot(contextOptions),
    interface_language: currentAgentInterfaceLanguage(),
    current: {
      media_filter: state.mediaFilter,
      sidebar_mode: state.sidebarMode,
      sidebar_open: state.sidebarOpen,
      generation_mode: state.generationMode,
      selected_model: state.params.model_type,
      prompt_preview: String(state.params.prompt || '').slice(0, 500),
      duration_seconds: state.durationSeconds,
      resolution: state.params.resolution,
      aspect_ratio: state.aspectRatio,
    },
    available_video_models: state.models
      .filter(model => model.is_t2v && !model.tool_only)
      .slice(0, 80)
      .map(model => ({
        model_type: model.model_type,
        name: model.name,
        family: model.family,
        installed: model.is_downloaded === true,
        enabled: state.enabledModels.has(model.model_type),
        text_to_video: model.is_t2v,
      })),
    available_image_models: getFamiliesForMode('image', state.families)
      .flatMap(family => getModelsForFamily(family.id, state.models, 'image'))
      .filter(model => !model.tool_only)
      .slice(0, 80)
      .map(model => ({
        model_type: model.model_type,
        name: model.name,
        family: model.family,
        installed: model.is_downloaded === true,
        enabled: state.enabledModels.has(model.model_type),
      })),
    recent_image_outputs: state.outputs
      .filter(output => output.type === 'image')
      .slice(0, 40)
      .map(output => ({ name: output.name })),
    recent_scene_outputs: state.outputs
      .filter(output => output.type === 'scene')
      .slice(0, 40)
      .map(output => ({
        name: output.name,
        title: output.name
          .replace(/\.scene\.json$/i, '')
          .replace(/^\d{4}-\d{2}-\d{2}-\d{2}h\d{2}m\d{2}s_/, '')
          .replace(/_[a-f0-9]{6}$/i, '')
          .replace(/[-_]+/g, ' ')
          .trim(),
      })),
    current_studio_loras: {
      available: state.availableLoras.slice(0, 120),
      active: [...(state.params.activated_loras || [])],
    },
    workspaces: {
      active: state.activeWorkspace,
      available: state.workspaces.map(workspace => ({
        name: workspace.name,
        file_count: workspace.file_count || 0,
      })),
    },
    comic: comicLabSnapshot(),
    director: {
      pipeline_id: state.pipelineId || '',
      state: state.pipelineStatus?.status || (state.pipelineId ? 'running' : ''),
    },
    ...buildWizardLabSnapshots(),
  }
}

const TAB_LABELS: Record<AgentTab, string> = {
  studio: 'Studio',
  director: 'Director',
  productions: 'Productions',
  images: 'Images',
  videos: 'Videos',
  audio: 'Audio',
  '3d': '3D',
  story_lab: 'Story Lab',
  series_lab: 'Series Lab',
  comics: 'Comics',
  video_editor: 'Video Editor',
  video_3d: '3D Video',
  animate_3d: 'Animate 3D',
  character_creator: 'Character Creator',
  character_kit: 'CharacterKit',
  workspaces: 'Workspaces',
  settings: 'Settings',
}

export async function executeAgentActions(
  actions: AgentAction[],
  onStep?: (message: string) => void,
): Promise<AgentActionResult[]> {
  const results: AgentActionResult[] = []
  let executionWorkspace = useStore.getState().activeWorkspace || 'default'
  let preparedStudio = false
  let preparedStudioAction: AgentPrepareVideoAction | AgentPrepareImageAction | AgentPrepareAudioAction | AgentPrepare3dAction | null = null
  let createdComicId = ''
  let createdStoryId = ''
  let createdStoryTitle = ''
  let stagedProductionId = ''
  let configuredStorySong: {
    targetStoryId: string
    targetStoryTitle: string
    cueId: string
    cueTitle: string
    configuration: AgentConfigureStorySongAction
  } | null = null
  const orderedActions = orderCompoundActions(actions)
  const failedActionTypes = new Set<string>()
  for (const plannedAction of orderedActions) {
    let action = plannedAction
    let actionExecutionKey = ''
    // Runtime correlation is the final guard: the configure capability returns
    // the canonical cue title after persistence, so downstream steps consume
    // that identity even when the original LLM plan used a future candidate
    // display label or stale language/version suffix.
    if (createdStoryId && action.type === 'configure_story_song' && !action.targetStoryId) {
      action = { ...action, targetStoryId: createdStoryId, targetStoryTitle: createdStoryTitle }
    }
    if (configuredStorySong && action.type === 'generate_story_song') {
      action = {
        ...action,
        targetStoryId: configuredStorySong.targetStoryId,
        targetStoryTitle: configuredStorySong.targetStoryTitle,
        cueId: configuredStorySong.cueId,
        cueTitle: configuredStorySong.cueTitle,
      }
    } else if (configuredStorySong && action.type === 'stage_story_music_video') {
      action = {
        ...action,
        targetStoryId: configuredStorySong.targetStoryId,
        targetStoryTitle: configuredStorySong.targetStoryTitle,
        cueId: configuredStorySong.cueId,
        cueTitle: configuredStorySong.cueTitle,
        songName: '',
      }
    } else if (stagedProductionId && action.type === 'start_director_production') {
      action = { ...action, productionId: stagedProductionId }
    }
    if (action.type === 'start_director_production' && !action.productionId) {
      const handoffProductionId = useStore.getState().directorStoryProductionHandoff?.productionId || ''
      if (handoffProductionId) action = { ...action, productionId: handoffProductionId }
    }
    const predecessors = (requiredPredecessor(action.type) || '').split('|').filter(Boolean)
    const failedPredecessor = predecessors.find(type => (
      failedActionTypes.has(type) && orderedActions.some(candidate => candidate.type === type)
    ))
    if (failedPredecessor) {
      results.push({
        action,
        ok: false,
        message: `No ejecuto ${action.type}: el paso requerido ${failedPredecessor} ha fallado.`,
        report: executionReport({
          state: 'failed',
          message: `Bloqueado por el fallo de ${failedPredecessor}.`,
          recoverable: true,
        }),
      })
      failedActionTypes.add(action.type)
      continue
    }
    const changesOutputFolder = action.type === 'select_workspace' || action.type === 'create_workspace'
    const visibleWorkspace = useStore.getState().activeWorkspace || 'default'
    if (!changesOutputFolder && visibleWorkspace !== executionWorkspace) {
      const message = `El output folder cambió de “${executionWorkspace}” a “${visibleWorkspace}” durante el hechizo. ¿Quieres que continúe en “${visibleWorkspace}” o que vuelva a “${executionWorkspace}”?`
      results.push({
        action,
        ok: false,
        message,
        report: executionReport({ state: 'awaiting_input', message, recoverable: true }),
      })
      break
    }
    const registeredProgress = getCapability(action.type)?.progress
    const working = registeredProgress || (action.type === 'open_tab'
      ? `Abriendo ${TAB_LABELS[action.tab]}…`
      : action.type === 'open_story_section'
        ? `Abriendo Story Lab → ${action.section}…`
        : action.type === 'open_series_section'
          ? `Abriendo Series Lab → ${action.section}…`
      : action.type === 'prepare_video'
        ? 'Trazando el hechizo de vídeo en Studio…'
        : action.type === 'prepare_image'
          ? 'Trazando el hechizo de imagen en Studio…'
        : action.type === 'prepare_audio'
          ? 'Trazando el hechizo de audio en Studio…'
        : action.type === 'prepare_3d'
          ? 'Trazando el hechizo 3D en Studio…'
        : action.type === 'queue_sfx_pack'
          ? 'Encolando el pack de efectos SFX…'
        : action.type === 'start_generation'
          ? 'Enviando a la cola…'
          : action.type === 'create_story'
            ? 'Escribiendo y guardando la nueva historia…'
            : action.type === 'update_story'
              ? 'Actualizando y guardando la historia…'
            : action.type === 'generate_story_section'
              ? `Invocando una propuesta de Story Lab (${action.scope})…`
            : action.type === 'apply_story_proposal'
              ? 'Aplicando la propuesta revisable al canon de Story Lab…'
            : action.type === 'approve_story_section'
              ? `Validando y aprobando Story Lab → ${action.section}…`
            : action.type === 'approve_story_visuals'
              ? 'Vinculando y aprobando referencias visuales de Story Lab…'
            : action.type === 'generate_story_visuals'
              ? `Generando referencias visuales de Story Lab (${action.scope})…`
            : action.type === 'stage_story_comic'
              ? 'Adaptando la historia a Comic Director…'
            : action.type === 'stage_story_video'
              ? `Adaptando la historia como ${action.kind === 'trailer' ? 'tráiler' : 'cortometraje'}…`
            : action.type === 'stage_story_music_video'
              ? 'Preparando el videoclip en Music Video Director…'
            : action.type === 'start_director_production'
              ? 'Abriendo el portal de producción en Director…'
            : action.type === 'create_series_episode'
              ? 'Preparando la serie y el nuevo episodio…'
            : action.type === 'update_series_episode'
              ? 'Actualizando y guardando el episodio…'
            : action.type === 'generate_series_plan'
              ? `Invocando el plan de Series Lab (${action.scope})…`
            : action.type === 'apply_series_plan'
              ? 'Aplicando la propuesta de Series Lab al episodio…'
            : action.type === 'render_series_shots'
              ? `Encolando render de Series Lab (${action.mode})…`
            : action.type === 'review_series_attempts'
              ? `${action.decision === 'approve' ? 'Aprobando' : 'Rechazando'} intentos de Series Lab…`
            : action.type === 'assemble_series_episode'
              ? 'Uniendo las tomas aprobadas del episodio…'
            : action.type === 'commit_series_canon'
              ? 'Registrando las decisiones de canon del episodio…'
            : action.type === 'open_3d_scene'
              ? `Abriendo la escena 3D ${action.sceneName}…`
            : action.type === 'save_3d_scene'
              ? 'Guardando la escena 3D editable…'
            : action.type === 'export_3d_scene'
              ? 'Renderizando y publicando el MP4 de la escena 3D…'
            : action.type === 'apply_3d_rhythm'
              ? 'Analizando la canción y creando keyframes rítmicos…'
              : action.type === 'create_character_kit'
                ? `Creando el Character Kit ${action.name}…`
              : action.type === 'open_character_kit'
                ? `Abriendo Character Kit ${action.kitName}…`
              : action.type === 'update_character_kit'
                ? 'Actualizando la identidad del Character Kit…'
              : action.type === 'attach_character_kit_references'
                ? 'Adjuntando referencias al Character Kit…'
              : action.type === 'build_character_kit'
                ? 'Montando el kit de personaje…'
              : action.type === 'open_character_kit_rig'
                ? 'Abriendo el Face Rig…'
              : action.type === 'apply_character_kit_preset'
                ? `Aplicando el preset ${action.presetId}…`
              : action.type === 'track_character_kit_job'
                ? 'Consultando el trabajo del Character Kit…'
              : action.type === 'create_video_editor_project'
                ? `Creando el proyecto de Video Editor ${action.projectName}…`
              : action.type === 'open_video_editor_project'
                ? 'Abriendo Video Editor…'
              : action.type === 'add_video_editor_clips'
                ? 'Añadiendo clips exactos a Video Editor…'
              : action.type === 'order_video_editor_clips'
                ? 'Reordenando la línea de tiempo…'
              : action.type === 'trim_video_editor_clip'
                ? `Recortando ${action.clipName}…`
              : action.type === 'add_video_editor_audio'
                ? 'Añadiendo audio a la línea de tiempo…'
              : action.type === 'validate_video_editor_timeline'
                ? 'Validando la línea de tiempo…'
              : action.type === 'export_video_editor'
                ? 'Encolando la exportación de Video Editor…'
              : action.type === 'track_video_editor_export'
                ? 'Consultando la exportación de Video Editor…'
              : action.type === 'create_comic'
                ? 'Montando el cómic de ejemplo…'
              : action.type === 'generate_comic'
                ? 'Dibujando las viñetas del cómic…'
              : action.type === 'generate_comic_panel'
                ? `Regenerando la viñeta ${action.panelNumber} de la página ${action.pageNumber}…`
              : action.type === 'attach_studio_references'
                ? 'Adjuntando referencias verificadas a Studio…'
              : action.type === 'configure_studio_loras'
                ? 'Configurando LoRAs compatibles en Studio…'
              : action.type === 'inspect_queue'
                ? 'Consultando la cola canónica…'
                : action.type === 'cancel_task'
                  ? 'Cancelando la tarea en la cola…'
                  : action.type === 'resume_task'
                    ? 'Reanudando la tarea en la cola…'
                    : action.type === 'retry_task'
                      ? 'Reintentando la tarea en la cola…'
                      : action.type === 'select_workspace'
                        ? `Cambiando al workspace ${action.workspaceName}…`
                        : `Creando el workspace ${String((action as { workspaceName?: string }).workspaceName || '')}…`)
    onStep?.(working)
    if (isExpensiveAction(action.type)) {
      let targetId = createdComicId
      if (action.type === 'generate_comic' || action.type === 'generate_comic_panel') {
        const { useComicStore } = await import('../comics/store')
        const project = useComicStore.getState().project
        targetId = bindGenerateComicTarget(createdComicId, project.id, project.title)
      }
      if (action.type === 'start_director_production') {
        const handoff = useStore.getState().directorStoryProductionHandoff
        targetId = bindDirectorProductionTarget(
          stagedProductionId,
          handoff?.productionId || '',
          handoff?.productionId || 'producción abierta',
        )
      }
      const keyParams = action.type === 'start_generation' && preparedStudioAction
        ? { action, preparedStudioAction }
        : action.type === 'generate_story_song' && configuredStorySong
          ? { action, configuration: configuredStorySong.configuration }
          : action
      const key = executionKey({
        workspace: executionWorkspace,
        type: action.type,
        targetId,
        params: keyParams,
      })
      actionExecutionKey = key
      const reused = reuseExecution(key)
      const reusedTaskId = String(reused?.taskId || '')
      const reusedJob = reusedTaskId
        ? useStore.getState().jobs.find(job => (
            job.id === reusedTaskId
            || job.taskId === reusedTaskId
            || job.rootTaskId === reusedTaskId
            || `task-generation-${job.id}` === reusedTaskId
          ))
        : undefined
      const reusableTask = !reusedJob || !['failed', 'cancelled', 'canceled'].includes(reusedJob.status)
      if (reused && reusableTask) {
        results.push({
          action,
          ok: true,
          message: `Reutilizo la ejecución anterior (${reused.state}). ${reused.message}`,
          report: reused,
        })
        continue
      }
    }
    try {
      if (action.type === 'start_generation' && !preparedStudio) {
        throw new Error('Studio no se preparó en este turno; no lo he lanzado.')
      }
      const registeredResult = await runRegisteredCapability(action, {
        adapters: defaultApplicationAdapters,
        workspace: executionWorkspace,
        onStep,
      })
      if (registeredResult) {
        results.push(registeredResult)
        if (changesOutputFolder && registeredResult.ok) {
          executionWorkspace = useStore.getState().activeWorkspace || executionWorkspace
        }
        if (action.type === 'prepare_video' || action.type === 'prepare_image'
          || action.type === 'prepare_audio' || action.type === 'prepare_3d') {
          preparedStudio = true
          preparedStudioAction = action
        }
        if (action.type === 'create_story' && registeredResult.report?.target?.id) {
          createdStoryId = registeredResult.report.target.id
          createdStoryTitle = registeredResult.report.target.title
        }
        if (action.type === 'configure_story_song' && registeredResult.report?.target?.title) {
          const configuredProject = registeredResult.report.projectTarget
          if (!configuredProject?.id) throw new Error('Story Lab no devolvió el ID exacto de la historia configurada.')
          configuredStorySong = {
            targetStoryId: configuredProject.id,
            targetStoryTitle: configuredProject.title,
            cueId: registeredResult.report.target.id,
            cueTitle: registeredResult.report.target.title,
            configuration: action,
          }
        }
        if ((action.type === 'stage_story_video' || action.type === 'stage_story_music_video') && registeredResult.report?.target?.id) {
          stagedProductionId = registeredResult.report.target.id
        }
      } else if (action.type === 'open_story_section') {
        await defaultApplicationAdapters.storyLab.open()
        const { openAgentStorySection } = await import('./agentUiBus')
        openAgentStorySection(action.section)
        results.push({ action, ok: true, message: `He abierto Story Lab → ${action.section}.` })
      } else if (action.type === 'open_series_section') {
        await defaultApplicationAdapters.seriesLab.open()
        const { openAgentSeriesSection } = await import('./agentUiBus')
        openAgentSeriesSection(action.section)
        results.push({ action, ok: true, message: `He abierto Series Lab → ${action.section}.` })
      } else if (action.type === 'prepare_video') {
        const outcome = await defaultApplicationAdapters.studio.prepareVideo(action)
        preparedStudio = true
        preparedStudioAction = action
        results.push({ action, ok: true, message: outcome.message, report: outcome.report })
      } else if (action.type === 'prepare_image') {
        const outcome = await defaultApplicationAdapters.studio.prepareImage(action)
        preparedStudio = true
        preparedStudioAction = action
        results.push({ action, ok: true, message: outcome.message, report: outcome.report })
      } else if (action.type === 'prepare_audio') {
        const outcome = await defaultApplicationAdapters.studio.prepareAudio(action)
        preparedStudio = true
        preparedStudioAction = action
        results.push({ action, ok: true, message: outcome.message, report: outcome.report })
      } else if (action.type === 'prepare_3d') {
        const outcome = await defaultApplicationAdapters.studio.prepare3d(action)
        preparedStudio = true
        preparedStudioAction = action
        results.push({ action, ok: true, message: outcome.message, report: outcome.report })
      } else if (action.type === 'queue_sfx_pack') {
        const outcome = await defaultApplicationAdapters.studio.queueSfxPack(action)
        results.push({ action, ok: true, message: outcome.message, report: outcome.report })
      } else if (action.type === 'start_generation') {
        if (!preparedStudio) throw new Error('Studio no se preparó en este turno; no lo he lanzado.')
        const outcome = await defaultApplicationAdapters.studio.startGeneration(action)
        results.push({ action, ok: true, message: outcome.message, report: outcome.report })
      } else if (action.type === 'create_story') {
        const outcome = await defaultApplicationAdapters.storyLab.create(action)
        results.push({ action, ok: true, message: outcome.message, report: outcome.report })
      } else if (action.type === 'update_story') {
        const outcome = await defaultApplicationAdapters.storyLab.update(action)
        results.push({ action, ok: true, message: outcome.message, report: outcome.report })
      } else if (action.type === 'generate_story_section') {
        const outcome = await defaultApplicationAdapters.storyLab.generateProposal(action, onStep)
        results.push({ action, ok: true, message: outcome.message, report: outcome.report })
      } else if (action.type === 'apply_story_proposal') {
        const outcome = await defaultApplicationAdapters.storyLab.applyProposal(action)
        results.push({ action, ok: true, message: outcome.message, report: outcome.report })
      } else if (action.type === 'approve_story_section') {
        const outcome = await defaultApplicationAdapters.storyLab.approveSection(action)
        results.push({ action, ok: true, message: outcome.message, report: outcome.report })
      } else if (action.type === 'approve_story_visuals') {
        const outcome = await defaultApplicationAdapters.storyLab.approveVisuals(action)
        results.push({ action, ok: true, message: outcome.message, report: outcome.report })
      } else if (action.type === 'generate_story_visuals') {
        const outcome = await defaultApplicationAdapters.storyLab.generateVisuals(action)
        results.push({ action, ok: true, message: outcome.message, report: outcome.report })
      } else if (action.type === 'stage_story_comic') {
        const outcome = await defaultApplicationAdapters.storyLab.stageComic(action)
        results.push({ action, ok: true, message: outcome.message, report: outcome.report })
      } else if (action.type === 'stage_story_video') {
        const outcome = await defaultApplicationAdapters.storyLab.stageVideo(action)
        stagedProductionId = useStore.getState().directorStoryProductionHandoff?.productionId || ''
        results.push({ action, ok: true, message: outcome.message, report: outcome.report })
      } else if (action.type === 'stage_story_music_video') {
        const outcome = await defaultApplicationAdapters.storyLab.stageMusicVideo(action)
        stagedProductionId = useStore.getState().directorStoryProductionHandoff?.productionId || ''
        results.push({ action, ok: true, message: outcome.message, report: outcome.report })
      } else if (action.type === 'start_director_production') {
        const outcome = await defaultApplicationAdapters.storyLab.startDirectorProduction(action, stagedProductionId || undefined)
        results.push({
          action,
          ok: true,
          message: outcome.message,
          report: executionReport({
            state: 'running',
            message: outcome.message,
            pipelineId: outcome.pipelineId,
            target: outcome.target,
            recoverable: true,
            executionKey: executionKey({
              workspace: executionWorkspace,
              type: action.type,
              targetId: outcome.target.id || stagedProductionId,
              params: action,
            }),
          }),
        })
      } else if (action.type === 'create_series_episode') {
        const outcome = await defaultApplicationAdapters.seriesLab.createEpisode(action)
        results.push({ action, ok: true, message: outcome.message, report: outcome.report })
      } else if (action.type === 'update_series_episode') {
        const outcome = await defaultApplicationAdapters.seriesLab.updateEpisode(action)
        results.push({ action, ok: true, message: outcome.message, report: outcome.report })
      } else if (action.type === 'generate_series_plan') {
        const outcome = await defaultApplicationAdapters.seriesLab.generatePlan(action)
        results.push({ action, ok: true, message: outcome.message, report: outcome.report })
      } else if (action.type === 'apply_series_plan') {
        const outcome = await defaultApplicationAdapters.seriesLab.applyPlan(action)
        results.push({ action, ok: true, message: outcome.message, report: outcome.report })
      } else if (action.type === 'render_series_shots') {
        const outcome = await defaultApplicationAdapters.seriesLab.renderShots(action)
        results.push({ action, ok: true, message: outcome.message, report: outcome.report })
      } else if (action.type === 'review_series_attempts') {
        const outcome = await defaultApplicationAdapters.seriesLab.reviewAttempts(action)
        results.push({ action, ok: true, message: outcome.message, report: outcome.report })
      } else if (action.type === 'assemble_series_episode') {
        const outcome = await defaultApplicationAdapters.seriesLab.assembleEpisode(action)
        results.push({ action, ok: true, message: outcome.message, report: outcome.report })
      } else if (action.type === 'commit_series_canon') {
        const outcome = await defaultApplicationAdapters.seriesLab.commitCanon(action)
        results.push({ action, ok: true, message: outcome.message, report: outcome.report })
      } else if (action.type === 'open_3d_scene') {
        await defaultApplicationAdapters.video3d.open()
        const { requestAgentSceneControl } = await import('./agentUiBus')
        results.push({ action, ok: true, message: await requestAgentSceneControl(action) })
      } else if (action.type === 'save_3d_scene') {
        await defaultApplicationAdapters.video3d.open()
        const { requestAgentSceneControl } = await import('./agentUiBus')
        results.push({ action, ok: true, message: await requestAgentSceneControl(action) })
      } else if (action.type === 'export_3d_scene') {
        await defaultApplicationAdapters.video3d.open()
        const { requestAgentSceneControl } = await import('./agentUiBus')
        results.push({ action, ok: true, message: await requestAgentSceneControl(action) })
      } else if (action.type === 'create_character_kit') {
        const outcome = await defaultApplicationAdapters.characterKit.create(action)
        results.push({ action, ok: true, message: outcome.message, report: outcome.report })
      } else if (action.type === 'open_character_kit') {
        const outcome = await defaultApplicationAdapters.characterKit.openKit(action)
        results.push({ action, ok: true, message: outcome.message, report: outcome.report })
      } else if (action.type === 'update_character_kit') {
        const outcome = await defaultApplicationAdapters.characterKit.update(action)
        results.push({ action, ok: true, message: outcome.message, report: outcome.report })
      } else if (action.type === 'attach_character_kit_references') {
        const outcome = await defaultApplicationAdapters.characterKit.attachReference(action)
        results.push({ action, ok: true, message: outcome.message, report: outcome.report })
      } else if (action.type === 'build_character_kit') {
        const outcome = await defaultApplicationAdapters.characterKit.build(action)
        results.push({ action, ok: true, message: outcome.message, report: outcome.report })
      } else if (action.type === 'open_character_kit_rig') {
        const outcome = await defaultApplicationAdapters.characterKit.openRig(action)
        results.push({ action, ok: true, message: outcome.message, report: outcome.report })
      } else if (action.type === 'apply_character_kit_preset') {
        const outcome = await defaultApplicationAdapters.characterKit.applyPreset(action)
        results.push({ action, ok: true, message: outcome.message, report: outcome.report })
      } else if (action.type === 'track_character_kit_job') {
        const outcome = await defaultApplicationAdapters.characterKit.trackJob(action)
        results.push({ action, ok: true, message: outcome.message, report: outcome.report })
      } else if (action.type === 'create_video_editor_project') {
        const outcome = await defaultApplicationAdapters.videoEditor.create(action)
        results.push({ action, ok: true, message: outcome.message, report: outcome.report })
      } else if (action.type === 'open_video_editor_project') {
        const outcome = await defaultApplicationAdapters.videoEditor.openProject(action)
        results.push({ action, ok: true, message: outcome.message, report: outcome.report })
      } else if (action.type === 'add_video_editor_clips') {
        const outcome = await defaultApplicationAdapters.videoEditor.addClips(action)
        results.push({ action, ok: true, message: outcome.message, report: outcome.report })
      } else if (action.type === 'order_video_editor_clips') {
        const outcome = await defaultApplicationAdapters.videoEditor.orderClips(action)
        results.push({ action, ok: true, message: outcome.message, report: outcome.report })
      } else if (action.type === 'trim_video_editor_clip') {
        const outcome = await defaultApplicationAdapters.videoEditor.trimClip(action)
        results.push({ action, ok: true, message: outcome.message, report: outcome.report })
      } else if (action.type === 'add_video_editor_audio') {
        const outcome = await defaultApplicationAdapters.videoEditor.addAudio(action)
        results.push({ action, ok: true, message: outcome.message, report: outcome.report })
      } else if (action.type === 'validate_video_editor_timeline') {
        const outcome = await defaultApplicationAdapters.videoEditor.validateTimeline()
        results.push({ action, ok: true, message: outcome.message, report: outcome.report })
      } else if (action.type === 'export_video_editor') {
        if (!action.confirm) throw new Error('Exportar Video Editor requiere confirm=true.')
        const outcome = await defaultApplicationAdapters.videoEditor.exportProject(action)
        results.push({ action, ok: true, message: outcome.message, report: outcome.report })
      } else if (action.type === 'track_video_editor_export') {
        const outcome = await defaultApplicationAdapters.videoEditor.trackExport()
        results.push({ action, ok: true, message: outcome.message, report: outcome.report })
      } else if (action.type === 'create_comic') {
        const outcome = await defaultApplicationAdapters.comic.create(action)
        results.push({ action, ok: true, message: outcome.message, report: outcome.report })
      } else if (action.type === 'generate_comic') {
        if (!action.confirm) throw new Error('Dibujar las viñetas requiere confirm=true.')
        const outcome = await defaultApplicationAdapters.comic.generate(action, createdComicId || undefined, onStep)
        results.push({
          action,
          ok: outcome.state !== 'failed',
          message: outcome.message,
          report: executionReport({
            state: outcome.state,
            message: outcome.message,
            recoverable: outcome.state === 'partial' || outcome.state === 'failed',
            target: outcome.target,
            executionKey: executionKey({
              workspace: executionWorkspace,
              type: action.type,
              targetId: outcome.target.id,
              params: action,
            }),
          }),
        })
      } else if (action.type === 'generate_comic_panel') {
        if (!action.confirm) throw new Error('Regenerar una viñeta requiere confirm=true.')
        const outcome = await defaultApplicationAdapters.comic.generatePanel(action.pageNumber, action.panelNumber, onStep)
        results.push({ action, ok: true, message: outcome.message, report: outcome.report })
      } else if (action.type === 'attach_studio_references') {
        const outcome = await defaultApplicationAdapters.studio.attachReferences(action)
        results.push({ action, ok: true, message: outcome.message, report: outcome.report })
      } else if (action.type === 'configure_studio_loras') {
        const outcome = await defaultApplicationAdapters.studio.configureLoras(action)
        results.push({ action, ok: true, message: outcome.message, report: outcome.report })
      } else if (action.type === 'inspect_queue') {
        const outcome = await defaultApplicationAdapters.queue.inspect(action.scope)
        results.push({ action, ok: true, message: outcome.message, report: outcome.report })
      } else if (action.type === 'cancel_task') {
        const { requestComicArtworkCancel } = await import('../comics/generateArtwork')
        const cancelledBatch = requestComicArtworkCancel()
        try {
          const outcome = await defaultApplicationAdapters.queue.cancel(action.taskId, action.confirm)
          results.push({
            action,
            ok: true,
            message: cancelledBatch
              ? `${outcome.message} También he pedido cancelar el lote de viñetas; las terminadas se conservan.`
              : outcome.message,
            report: outcome.report,
          })
        } catch (error) {
          if (!cancelledBatch) throw error
          results.push({
            action,
            ok: true,
            message: 'He pedido cancelar el lote de viñetas; las ilustraciones terminadas se conservan.',
          })
        }
      } else if (action.type === 'resume_task') {
        const outcome = await defaultApplicationAdapters.queue.resume(action.taskId, action.confirm)
        results.push({ action, ok: true, message: outcome.message, report: outcome.report })
      } else if (action.type === 'retry_task') {
        const outcome = await defaultApplicationAdapters.queue.retry(action.taskId, action.confirm)
        results.push({ action, ok: true, message: outcome.message, report: outcome.report })
      } else if (action.type === 'select_workspace') {
        const outcome = await defaultApplicationAdapters.workspace.select(action)
        results.push({ action, ok: true, message: outcome.message, report: outcome.report })
      } else if (action.type === 'create_workspace') {
        const outcome = await defaultApplicationAdapters.workspace.create(action)
        results.push({ action, ok: true, message: outcome.message, report: outcome.report })
      } else {
        throw new Error(`No hay ejecutor para ${action.type}.`)
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      results.push({ action, ok: false, message })
      failedActionTypes.add(action.type)
      if (action.type === 'prepare_video' || action.type === 'prepare_image' || action.type === 'prepare_audio' || action.type === 'prepare_3d') preparedStudio = false
    }
    const last = results.at(-1)
    if (last && last.action === action) {
      if (!last.ok) failedActionTypes.add(action.type)
      if (!last.report) {
        let target: AgentExecutionTarget | undefined
        if (action.type === 'create_comic' || action.type === 'generate_comic' || action.type === 'generate_comic_panel') {
          const { useComicStore } = await import('../comics/store')
          const project = useComicStore.getState().project
          target = { kind: 'comic', id: project.id, title: project.title }
          if (action.type === 'create_comic' && last.ok) createdComicId = project.id
        }
        last.report = executionReport({
          state: inferExecutionState(action.type, last.ok),
          message: last.message,
          target,
          recoverable: !last.ok,
          executionKey: executionKey({
            workspace: executionWorkspace,
            type: action.type,
            targetId: target?.id || createdComicId || stagedProductionId,
            params: action,
          }),
        })
      }
      if (actionExecutionKey && last.report) last.report.executionKey = actionExecutionKey
      if (last.ok && isExpensiveAction(action.type) && last.report.executionKey) {
        rememberExecution(last.report)
      }
    }
  }
  return results
}
