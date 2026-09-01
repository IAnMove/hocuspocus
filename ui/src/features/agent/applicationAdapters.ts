import { useStore } from '../../stores/useStore'
import type { CommandResult } from '../../lib/commandContract'
import { rememberedCharacterKitLibrary } from '../characters/session'
import type { SeriesAssemblyJob } from '../series/assemblyContract'
import type { SeriesJobStatus } from '../series/types'
import type { MediaFilter } from '../../types'
import type { AgentApply3dRhythmAction, AgentApplySeriesPlanAction, AgentApplyStoryProposalAction, AgentApproveStorySectionAction, AgentApproveStoryVisualsAction, AgentAssembleSeriesEpisodeAction, AgentCommitSeriesCanonAction, AgentConfigureStorySongAction, AgentCreateComicAction, AgentCreateSeriesEpisodeAction, AgentCreateStoryAction, AgentGenerateComicAction, AgentGenerateSeriesPlanAction, AgentGenerateStorySectionAction, AgentGenerateStorySongAction, AgentGenerateStoryVisualsAction, AgentRenderSeriesShotsAction, AgentReviewSeriesAttemptsAction, AgentStageStoryComicAction, AgentStartDirectorProductionAction, AgentStageStoryMusicVideoAction, AgentStageStoryVideoAction, AgentUpdateSeriesEpisodeAction, AgentUpdateStoryAction } from './agentActions'
import {
  executionKey,
  executionReport,
  rememberExecution,
  reuseExecution,
  type AgentExecutionReport,
  type AgentExecutionTarget,
} from './agentContract'
import { openAgentActivityDetails, requestAgentSceneControl, requestAgentSceneRhythm, requestAgentSceneWorkflow, requestAgentStoryVisualGeneration, type AgentSceneControlRequest, type AgentSceneWorkflowRequest } from './agentUiBus'
import type { AgentRhythmGrid } from './agentUiBus'
import { queueMusic } from './audioActions'
import type { AgentPrepareAudioAction } from './agentActions'
import type { AgentTab } from './capabilityRegistry'
import type {
  AgentAddVideoEditorAudioAction,
  AgentAddVideoEditorClipsAction,
  AgentCreateVideoEditorProjectAction,
  AgentExportVideoEditorAction,
  AgentOpenVideoEditorProjectAction,
  AgentOrderVideoEditorClipsAction,
  AgentTrimVideoEditorClipAction,
} from './videoEditorActions'
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

export interface AdapterOutcome {
  message: string
  target: AgentExecutionTarget
  taskId?: string
  pipelineId?: string
  outputNames?: string[]
  assetIds?: string[]
  sceneId?: string
  layerIds?: string[]
  audioTrackId?: string
  analysisId?: string
  bpm?: number
  beatCount?: number
  downbeatCount?: number
  rhythmGrid?: AgentRhythmGrid
  report?: AgentExecutionReport
}

export interface StudioAdapter {
  open(tab?: 'studio' | 'images' | 'videos' | 'audio' | '3d'): Promise<AdapterOutcome>
  queueMusic(action: AgentPrepareAudioAction): Promise<AdapterOutcome>
}

export interface StoryLabAdapter {
  open(): Promise<AdapterOutcome>
  create(action: AgentCreateStoryAction): Promise<AdapterOutcome>
  update(action: AgentUpdateStoryAction): Promise<AdapterOutcome>
  generateProposal(action: AgentGenerateStorySectionAction, onStep?: (message: string) => void): Promise<AdapterOutcome>
  applyProposal(action: AgentApplyStoryProposalAction): Promise<AdapterOutcome>
  approveSection(action: AgentApproveStorySectionAction): Promise<AdapterOutcome>
  approveVisuals(action: AgentApproveStoryVisualsAction): Promise<AdapterOutcome>
  generateVisuals(action: AgentGenerateStoryVisualsAction): Promise<AdapterOutcome>
  configureSong(action: AgentConfigureStorySongAction): Promise<AdapterOutcome>
  generateSong(action: AgentGenerateStorySongAction): Promise<AdapterOutcome>
  stageComic(action: AgentStageStoryComicAction): Promise<AdapterOutcome>
  stageVideo(action: AgentStageStoryVideoAction): Promise<AdapterOutcome>
  stageMusicVideo(action: AgentStageStoryMusicVideoAction): Promise<AdapterOutcome>
  startDirectorProduction(action: AgentStartDirectorProductionAction, expectedProductionId?: string): Promise<AdapterOutcome>
}
export interface SeriesLabAdapter {
  open(): Promise<AdapterOutcome>
  createEpisode(action: AgentCreateSeriesEpisodeAction): Promise<AdapterOutcome>
  updateEpisode(action: AgentUpdateSeriesEpisodeAction): Promise<AdapterOutcome>
  generatePlan(action: AgentGenerateSeriesPlanAction): Promise<AdapterOutcome>
  applyPlan(action: AgentApplySeriesPlanAction): Promise<AdapterOutcome>
  renderShots(action: AgentRenderSeriesShotsAction): Promise<AdapterOutcome>
  reviewAttempts(action: AgentReviewSeriesAttemptsAction): Promise<AdapterOutcome>
  commitCanon(action: AgentCommitSeriesCanonAction): Promise<AdapterOutcome>
  assembleEpisode(action: AgentAssembleSeriesEpisodeAction): Promise<AdapterOutcome>
}
export interface ComicAdapter {
  open(): Promise<AdapterOutcome>
  create(action: AgentCreateComicAction): Promise<AdapterOutcome>
  generate(action: AgentGenerateComicAction, expectedProjectId?: string, onStep?: (message: string) => void): Promise<AdapterOutcome & { state: 'completed' | 'partial' | 'failed' }>
  generatePanel(pageNumber: number, panelNumber: number, onStep?: (message: string) => void): Promise<AdapterOutcome>
}
export interface VideoEditorAdapter {
  open(): Promise<AdapterOutcome>
  create(action: AgentCreateVideoEditorProjectAction): Promise<AdapterOutcome>
  openProject(action: AgentOpenVideoEditorProjectAction): Promise<AdapterOutcome>
  addClips(action: AgentAddVideoEditorClipsAction): Promise<AdapterOutcome>
  orderClips(action: AgentOrderVideoEditorClipsAction): Promise<AdapterOutcome>
  trimClip(action: AgentTrimVideoEditorClipAction): Promise<AdapterOutcome>
  addAudio(action: AgentAddVideoEditorAudioAction): Promise<AdapterOutcome>
  validateTimeline(): Promise<AdapterOutcome>
  exportProject(action: AgentExportVideoEditorAction): Promise<AdapterOutcome>
  trackExport(): Promise<AdapterOutcome>
}
export interface CharacterKitAdapter {
  open(creator?: boolean): Promise<AdapterOutcome>
  create(action: AgentCreateCharacterKitAction): Promise<AdapterOutcome>
  openKit(action: AgentOpenCharacterKitAction): Promise<AdapterOutcome>
  update(action: AgentUpdateCharacterKitAction): Promise<AdapterOutcome>
  attachReference(action: AgentAttachCharacterKitReferencesAction): Promise<AdapterOutcome>
  build(action: AgentBuildCharacterKitAction): Promise<AdapterOutcome>
  openRig(action: AgentOpenCharacterKitRigAction): Promise<AdapterOutcome>
  applyPreset(action: AgentApplyCharacterKitPresetAction): Promise<AdapterOutcome>
  trackJob(action: AgentTrackCharacterKitJobAction): Promise<AdapterOutcome>
}
export interface QueueAdapter { openActivity(): Promise<AdapterOutcome> }

export interface Video3DAdapter {
  open(animate?: boolean): Promise<AdapterOutcome>
  applyRhythm(action: AgentApply3dRhythmAction): Promise<AdapterOutcome>
  run(request: AgentSceneWorkflowRequest): Promise<AdapterOutcome>
  control(request: AgentSceneControlRequest): Promise<AdapterOutcome>
}

export interface WizardApplicationAdapters {
  studio: StudioAdapter
  storyLab: StoryLabAdapter
  seriesLab: SeriesLabAdapter
  comic: ComicAdapter
  video3d: Video3DAdapter
  videoEditor: VideoEditorAdapter
  characterKit: CharacterKitAdapter
  queue: QueueAdapter
  openTab(tab: AgentTab): Promise<AdapterOutcome>
}

const TAB_TARGETS: Partial<Record<AgentTab, MediaFilter>> = {
  images: 'images', videos: 'videos', audio: 'audio', '3d': 'model3d',
  story_lab: 'stories', series_lab: 'series', comics: 'comics',
  video_editor: 'videoeditor', video_3d: 'scene3d', animate_3d: 'animate3d',
  character_creator: 'characters', character_kit: 'characters', workspaces: 'workspaces',
}

const TAB_LABELS: Record<AgentTab, string> = {
  studio: 'Studio', director: 'Director', productions: 'Productions', images: 'Images',
  videos: 'Videos', audio: 'Audio', '3d': '3D', story_lab: 'Story Lab',
  series_lab: 'Series Lab', comics: 'Comics', video_editor: 'Video Editor',
  video_3d: '3D Video', animate_3d: 'Animate 3D', character_creator: 'Character Creator',
  character_kit: 'CharacterKit', workspaces: 'Workspaces', settings: 'Settings',
}

function target(tab: AgentTab): AgentExecutionTarget {
  return { kind: 'application_section', id: tab, title: TAB_LABELS[tab] }
}

function isTabOpen(tab: AgentTab): boolean {
  const state = useStore.getState()
  if (tab === 'settings') return state.settingsOpen && !state.dashboardOpen
  if (tab === 'productions') return state.dashboardOpen && !state.settingsOpen
  if (tab === 'director') {
    return state.sidebarMode === 'director' && state.sidebarOpen
      && !state.settingsOpen && !state.dashboardOpen
  }
  if (tab === 'studio') {
    return state.sidebarMode === 'studio' && state.sidebarOpen
      && !state.settingsOpen && !state.dashboardOpen
  }
  const mediaFilter = TAB_TARGETS[tab]
  return Boolean(mediaFilter && state.mediaFilter === mediaFilter
    && !state.settingsOpen && !state.dashboardOpen)
}

async function navigate(tab: AgentTab): Promise<AdapterOutcome> {
  const state = useStore.getState()
  const alreadyVisible = isTabOpen(tab)
  if (tab === 'settings') {
    state.setDashboardOpen(false)
    state.setSidebarOpen(false)
    state.setSettingsOpen(true)
  } else if (tab === 'productions') {
    state.setSettingsOpen(false)
    state.setSidebarOpen(false)
    state.setDashboardOpen(true)
  } else if (tab === 'director') {
    state.setSettingsOpen(false)
    state.setDashboardOpen(false)
    state.setSidebarMode('director')
    state.setSidebarOpen(true)
    window.dispatchEvent(new Event('maestro:director-open'))
  } else if (tab === 'studio') {
    state.setSettingsOpen(false)
    state.setDashboardOpen(false)
    state.setSidebarMode('studio')
    state.setSidebarOpen(true)
  } else {
    const mediaFilter = TAB_TARGETS[tab]
    state.setSettingsOpen(false)
    state.setDashboardOpen(false)
    if (mediaFilter) state.setMediaFilter(mediaFilter)
    state.setSidebarOpen(false)
  }
  if (!isTabOpen(tab)) throw new Error(`HocusPocus no confirmó la navegación a ${TAB_LABELS[tab]}.`)
  return {
    message: alreadyVisible ? `${TAB_LABELS[tab]} ya estaba visible.` : `He abierto ${TAB_LABELS[tab]}.`,
    target: target(tab),
  }
}

const SLICE_TABS: Record<string, AgentTab> = {
  character_kit: 'character_kit',
  character_creator: 'character_creator',
  video_editor: 'video_editor',
}

async function applySliceNavigation(result: CommandResult): Promise<void> {
  const destination = result.navigationTarget?.destination
  const tab = destination ? SLICE_TABS[destination] : undefined
  if (tab) await navigate(tab)
}

function kitNameFromResult(result: CommandResult): string {
  const id = result.entities[0]?.id
  const library = rememberedCharacterKitLibrary()
  return (id && library?.kits[id]?.name) || id || 'Character Kit'
}

function entityTarget(result: CommandResult, title: string, fallbackKind = 'application_section'): AgentExecutionTarget {
  const entity = result.entities[0]
  return {
    kind: entity?.kind || fallbackKind,
    id: entity?.id || title,
    title,
  }
}

async function kitOutcome(result: CommandResult, message: string): Promise<AdapterOutcome> {
  await applySliceNavigation(result)
  return {
    message,
    target: entityTarget(result, kitNameFromResult(result), 'character_kit'),
    taskId: result.taskIds[0],
    pipelineId: result.pipelineIds[0],
  }
}

async function editorOutcome(result: CommandResult, message: string, extra: Partial<AdapterOutcome> = {}): Promise<AdapterOutcome> {
  await applySliceNavigation(result)
  const id = result.entities[0]?.id || 'video_editor'
  return {
    message,
    target: { kind: 'video_editor', id, title: id },
    taskId: result.taskIds[0],
    pipelineId: result.pipelineIds[0],
    outputNames: result.artifacts.map(item => item.id),
    ...extra,
  }
}

export function createDefaultApplicationAdapters(): WizardApplicationAdapters {
  const adapters = {} as WizardApplicationAdapters
  adapters.studio = {
    open: tab => navigate(tab || 'studio'),
    async queueMusic(action) {
      const result = await queueMusic(action)
      return { ...result, target: { kind: 'queue_task', id: result.taskId, title: 'Song generation' } }
    },
  }
  adapters.storyLab = {
    open: () => navigate('story_lab'),
    async create(action) {
      const { create } = await import('../stories/adapters')
      return presentStorySliceResult(await create(action))
    },
    async update(action) {
      const { update } = await import('../stories/adapters')
      return presentStorySliceResult(await update(action))
    },
    async generateProposal(action, onStep) {
      const { generateProposal } = await import('../stories/adapters')
      return presentStorySliceResult(await generateProposal(action, onStep))
    },
    async applyProposal(action) {
      const { applyProposal } = await import('../stories/adapters')
      return presentStorySliceResult(await applyProposal(action))
    },
    async approveSection(action) {
      const { approveSection } = await import('../stories/adapters')
      return presentStorySliceResult(await approveSection(action))
    },
    async approveVisuals(action) {
      const { approveVisuals } = await import('../stories/adapters')
      return presentStorySliceResult(await approveVisuals(action))
    },
    async generateVisuals(action) {
      const { generateVisuals } = await import('../stories/adapters')
      const result = await generateVisuals(action)
      const presented = await presentStorySliceResult(result)
      const request = result.artifacts[0]?.metadata?.visualRequest as {
        projectId?: string
        scope?: 'world' | 'locations' | 'characters' | 'all'
        targetNames?: string[]
      } | undefined
      if (!request?.projectId || !request.scope) return presented
      const visual = await requestAgentStoryVisualGeneration({
        projectId: request.projectId,
        scope: request.scope,
        targetNames: request.targetNames || [],
      })
      return { ...presented, message: visual.message, assetIds: visual.assetIds }
    },
    async configureSong(action) {
      const { configureSong } = await import('../stories/adapters')
      const result = await configureSong(action)
      const presented = await presentStorySliceResult(result)
      const cueId = String(result.artifacts[0]?.metadata?.cueId || presented.target.id)
      const cueTitle = String(result.artifacts[0]?.metadata?.cueTitle || presented.target.title)
      return { ...presented, target: { kind: 'story_song', id: cueId, title: cueTitle } }
    },
    async generateSong(action) {
      const { generateSong } = await import('../stories/adapters')
      const result = await generateSong(action)
      const presented = await presentStorySliceResult(result)
      const meta = result.artifacts[0]?.metadata || {}
      const candidateId = String(meta.candidateId || presented.target.id)
      const cueTitle = String(meta.cueTitle || presented.target.title)
      const outputName = typeof meta.outputName === 'string' ? meta.outputName : ''
      return {
        ...presented,
        target: { kind: 'story_song', id: candidateId, title: cueTitle },
        outputNames: outputName ? [outputName] : presented.outputNames,
      }
    },
    async stageComic(action) {
      const { stageComic } = await import('../stories/adapters')
      const result = await stageComic(action)
      const presented = await presentStorySliceResult(result)
      const comicId = String(result.artifacts[0]?.metadata?.comicId || '')
      const comicTitle = String(result.artifacts[0]?.metadata?.comicTitle || '')
      if (!comicId) throw new Error('Story Lab no correlacionó la producción de cómic con su proyecto editable.')
      return { ...presented, target: { kind: 'comic', id: comicId, title: comicTitle } }
    },
    async stageVideo(action) {
      const { stageVideo } = await import('../stories/adapters')
      const result = await stageVideo(action)
      const presented = await presentStorySliceResult(result)
      return stagedDirectorOutcome(presented.message)
    },
    async stageMusicVideo(action) {
      const { stageMusicVideo } = await import('../stories/adapters')
      const result = await stageMusicVideo(action)
      const presented = await presentStorySliceResult(result)
      return stagedDirectorOutcome(presented.message)
    },
    async startDirectorProduction(action, expectedProductionId) {
      const { bindDirectorProductionTarget } = await import('./agentContract')
      const { useStoryStore } = await import('../stories/store')
      await useStoryStore.getState().loadWorkspace(useStore.getState().activeWorkspace || 'default')
      const handoff = useStore.getState().directorStoryProductionHandoff
      const stories = useStoryStore.getState()
      const project = handoff ? stories.projects[handoff.projectId] || stories.project : stories.project
      const production = project?.productions.find(item => item.id === handoff?.productionId)
      if (!production) throw new Error('Director no devolvió el destino de producción verificado.')
      bindDirectorProductionTarget(expectedProductionId, production.id, production.title)
      const { startProduction } = await import('../stories/adapters')
      const result = await startProduction(action)
      const presented = await presentStorySliceResult(result)
      const productionId = String(result.artifacts[0]?.metadata?.productionId || production.id)
      const productionTitle = String(result.artifacts[0]?.metadata?.productionTitle || production.title)
      return {
        ...presented,
        target: { kind: 'director_production', id: productionId, title: productionTitle },
        pipelineId: result.pipelineIds[0],
      }
    },
  }
  adapters.seriesLab = {
    open: () => navigate('series_lab'),
    async createEpisode(action) {
      const { createEpisode } = await import('../series/adapters')
      return presentSeriesSliceResult(await createEpisode(action))
    },
    async updateEpisode(action) {
      const { updateEpisode } = await import('../series/adapters')
      return presentSeriesSliceResult(await updateEpisode(action))
    },
    async generatePlan(action) {
      const { generatePlan } = await import('../series/adapters')
      const outcome = await presentSeriesSliceResult(await generatePlan(action))
      if (!outcome.taskId) throw new Error('Series Lab no devolvió el job de planificación iniciado.')
      return outcome
    },
    async applyPlan(action) {
      const { applyPlan } = await import('../series/adapters')
      return presentSeriesSliceResult(await applyPlan(action))
    },
    async renderShots(action) {
      const { renderShots } = await import('../series/adapters')
      const outcome = await presentSeriesSliceResult(await renderShots(action))
      if (!outcome.taskId) throw new Error('Series Lab no devolvió el job de render iniciado.')
      return outcome
    },
    async reviewAttempts(action) {
      const { reviewAttempts } = await import('../series/adapters')
      return presentSeriesSliceResult(await reviewAttempts(action))
    },
    async commitCanon(action) {
      const { commitCanon } = await import('../series/adapters')
      return presentSeriesSliceResult(await commitCanon(action))
    },
    async assembleEpisode(action) {
      const { assembleEpisode } = await import('../series/adapters')
      const outcome = await presentSeriesSliceResult(await assembleEpisode(action))
      if (!outcome.taskId) throw new Error('Series Lab no devolvió el job de ensamblado iniciado.')
      return outcome
    },
  }
  adapters.comic = {
    open: () => navigate('comics'),
    async create(action) {
      const { create } = await import('../comics/adapters')
      return presentComicSliceResult(await create(action))
    },
    async generate(action, expectedProjectId, onStep) {
      const { bindGenerateComicTarget } = await import('./agentContract')
      const { useComicStore } = await import('../comics/store')
      const current = useComicStore.getState().project
      bindGenerateComicTarget(expectedProjectId, current.id, current.title)
      const { generate } = await import('../comics/adapters')
      return presentComicSliceResult(await generate(action, onStep))
    },
    async generatePanel(pageNumber, panelNumber, onStep) {
      const { generatePanel } = await import('../comics/adapters')
      return presentComicSliceResult(await generatePanel(pageNumber, panelNumber, onStep))
    },
  }
  adapters.videoEditor = {
    open: () => navigate('video_editor'),
    async create(action) {
      const { createProject } = await import('../video-editor/adapters')
      const result = await createProject({ projectName: action.projectName })
      const name = result.entities[0]?.id || action.projectName.trim() || 'my_video'
      return editorOutcome(result, `He creado el proyecto de Video Editor “${name}”.`)
    },
    async openProject(action) {
      const { openProject } = await import('../video-editor/adapters')
      const result = await openProject({ projectName: action.projectName })
      const { loadEditorDraft } = await import('../video-editor/editorDraft')
      const draft = loadEditorDraft(useStore.getState().activeWorkspace || 'default')
      return editorOutcome(result, `He abierto Video Editor “${draft.projectName}” con ${draft.clips.length} clips.`)
    },
    async addClips(action) {
      const { addClips } = await import('../video-editor/adapters')
      const result = await addClips({ outputNames: action.outputNames })
      const name = result.entities[0]?.id || 'Video Editor'
      return editorOutcome(result, `He añadido ${action.outputNames.length} clips exactos a “${name}”.`)
    },
    async orderClips(action) {
      const { orderClips } = await import('../video-editor/adapters')
      const result = await orderClips({ clipNames: action.clipNames })
      return editorOutcome(result, `He reordenado ${action.clipNames.length} clips.`)
    },
    async trimClip(action) {
      const { trimClip } = await import('../video-editor/adapters')
      const result = await trimClip({
        clipName: action.clipName,
        trimStart: action.trimStart,
        trimEnd: action.trimEnd,
      })
      return editorOutcome(result, `He recortado “${action.clipName}” a ${action.trimStart}-${action.trimEnd}s.`)
    },
    async addAudio(action) {
      const { addAudio } = await import('../video-editor/adapters')
      const result = await addAudio({ clipName: action.clipName, outputName: action.outputName })
      const name = result.entities[0]?.id || 'Video Editor'
      return editorOutcome(result, `He configurado “${action.outputName}” como banda sonora de “${name}”.`)
    },
    async validateTimeline() {
      const { validateTimeline } = await import('../video-editor/adapters')
      const result = await validateTimeline()
      const { loadEditorDraft } = await import('../video-editor/editorDraft')
      const { sequenceTotalDuration } = await import('../video-editor/editorTimeline')
      const draft = loadEditorDraft(useStore.getState().activeWorkspace || 'default')
      const duration = sequenceTotalDuration(draft.clips)
      return editorOutcome(result, `Línea de tiempo válida: ${draft.clips.length} clips, ${duration.toFixed(1)}s.`)
    },
    async exportProject(action) {
      if (!action.confirm) throw new Error('Exportar requiere confirm=true.')
      const { loadEditorDraft } = await import('../video-editor/editorDraft')
      const { sequenceTotalDuration } = await import('../video-editor/editorTimeline')
      const workspace = useStore.getState().activeWorkspace || 'default'
      const draft = loadEditorDraft(workspace)
      const key = executionKey({
        workspace,
        type: 'export_video_editor',
        targetId: draft.projectName,
        params: {
          clips: draft.clips.map(clip => clip.name),
          duration: sequenceTotalDuration(draft.clips),
          soundtrack: draft.soundtrack ? {
            name: draft.soundtrack.name,
            source: draft.soundtrack.source,
            trimStart: draft.soundtrack.trimStart,
            trimEnd: draft.soundtrack.trimEnd,
            volume: draft.soundtrack.volume,
            loop: draft.soundtrack.loop,
          } : null,
        },
      })
      const reused = reuseExecution(key)
      if (reused) {
        return {
          message: `Reutilizo la ejecución anterior (${reused.state}). ${reused.message}`,
          target: reused.target || { kind: 'video_editor', id: draft.projectName, title: draft.projectName },
          taskId: reused.taskId,
          outputNames: reused.outputNames,
          report: reused,
        }
      }
      const { exportProject } = await import('../video-editor/adapters')
      const result = await exportProject({ confirm: true })
      const jobId = result.taskIds[0]
      const message = `He encolado la exportación de “${draft.projectName}” (${jobId}).`
      const report = executionReport({
        state: 'queued',
        message,
        recoverable: true,
        target: { kind: 'video_editor', id: draft.projectName, title: draft.projectName },
        taskId: jobId,
        executionKey: key,
      })
      rememberExecution(report)
      return editorOutcome(result, message, { report })
    },
    async trackExport() {
      const { trackExport } = await import('../video-editor/adapters')
      const result = await trackExport()
      const jobId = result.taskIds[0]
      const artifact = result.artifacts[0]
      const jobMessage = typeof artifact?.metadata?.message === 'string' ? artifact.metadata.message : ''
      const jobStatus = typeof artifact?.metadata?.status === 'string' ? artifact.metadata.status : result.status
      const state = jobStatus === 'completed' || result.status === 'completed' ? 'completed'
        : jobStatus === 'failed' || jobStatus === 'cancelled' || result.status === 'failed' ? 'failed'
          : jobStatus === 'queued' || jobStatus === 'waiting_resource' ? 'queued'
            : 'running'
      const message = `Exportación ${jobId}: ${jobStatus}. ${jobMessage}`.trim()
      const outputNames = result.artifacts.filter(item => item.kind === 'video').map(item => item.id)
      const report = executionReport({
        state,
        message,
        recoverable: state === 'failed',
        target: { kind: 'video_editor', id: result.entities[0]?.id || 'video_editor', title: result.entities[0]?.id || 'video_editor' },
        taskId: jobId,
        outputNames,
      })
      return editorOutcome(result, message, { report, outputNames })
    },
  }
  adapters.characterKit = {
    open: creator => navigate(creator ? 'character_creator' : 'character_kit'),
    async create(action) {
      const { createKit } = await import('../characters/adapters')
      const result = await createKit({ name: action.name, style: action.style })
      const name = kitNameFromResult(result)
      const message = result.navigationTarget?.section === 'existing'
        ? `He abierto el Character Kit existente “${name}”.`
        : `He creado el Character Kit “${name}”. Todavía no he generado poses.`
      return kitOutcome(result, message)
    },
    async openKit(action) {
      const { openKit } = await import('../characters/adapters')
      const result = await openKit({ kitName: action.kitName })
      return kitOutcome(result, `He abierto Character Kit “${kitNameFromResult(result)}”.`)
    },
    async update(action) {
      const { updateKit } = await import('../characters/adapters')
      const result = await updateKit({
        kitName: action.kitName,
        name: action.name,
        lookNotes: action.lookNotes,
        style: action.style,
      })
      return kitOutcome(result, `He actualizado la identidad de “${kitNameFromResult(result)}”.`)
    },
    async attachReference(action) {
      const { attachReference } = await import('../characters/adapters')
      const result = await attachReference({ kitName: action.kitName, outputNames: action.outputNames })
      return kitOutcome(
        result,
        `He adjuntado “${action.outputNames[0]}” como referencia de identidad de “${kitNameFromResult(result)}”.`,
      )
    },
    async build(action) {
      const { buildKit } = await import('../characters/adapters')
      const result = await buildKit({ kitName: action.kitName })
      return kitOutcome(result, `He montado el kit “${kitNameFromResult(result)}” con la pose base. No he lanzado generación.`)
    },
    async openRig(action) {
      const { openRig } = await import('../characters/adapters')
      const result = await openRig({ kitName: action.kitName })
      return kitOutcome(result, `He abierto el Face Rig de “${kitNameFromResult(result)}”.`)
    },
    async applyPreset(action) {
      const { applyPreset } = await import('../characters/adapters')
      const result = await applyPreset({ kitName: action.kitName, presetId: action.presetId })
      return kitOutcome(result, `He aplicado el preset “${action.presetId}” al Face Rig de “${kitNameFromResult(result)}”.`)
    },
    async trackJob(action) {
      const { trackJob } = await import('../characters/adapters')
      const result = await trackJob({ kitName: action.kitName })
      const { inspectCanonicalQueue } = await import('./queueActions')
      const inspected: unknown = await inspectCanonicalQueue('active')
      const queue = typeof inspected === 'string'
        ? inspected
        : (inspected && typeof inspected === 'object' && 'artifacts' in inspected
          ? String((inspected as CommandResult).artifacts[0]?.metadata?.summary || '')
          : '')
      openAgentActivityDetails()
      const name = kitNameFromResult(result)
      const message = `Sigo el trabajo de “${name}”. ${queue}`
      const target = entityTarget(result, name, 'character_kit')
      return {
        message,
        target,
        report: executionReport({
          state: 'running',
          message,
          target,
          recoverable: false,
        }),
      }
    },
  }
  adapters.queue = {
    async openActivity() {
      openAgentActivityDetails()
      return {
        message: 'He abierto Activity.',
        target: { kind: 'activity', id: 'activity', title: 'Activity' },
      }
    },
  }
  adapters.video3d = {
    open: animate => navigate(animate ? 'animate_3d' : 'video_3d'),
    async applyRhythm(action) {
      const navigation = await navigate('video_3d')
      const message = await requestAgentSceneRhythm(action)
      return { ...navigation, message }
    },
    async run(request) {
      const navigation = await navigate('video_3d')
      const outcome = await requestAgentSceneWorkflow(request)
      return { ...navigation, ...outcome, outputNames: outcome.outputNames }
    },
    async control(request) {
      const navigation = await navigate('video_3d')
      return { ...navigation, message: await requestAgentSceneControl(request) }
    },
  }
  adapters.openTab = tab => {
    if (tab === 'studio' || tab === 'images' || tab === 'videos' || tab === 'audio' || tab === '3d') {
      return adapters.studio.open(tab)
    }
    if (tab === 'story_lab') return adapters.storyLab.open()
    if (tab === 'series_lab') return adapters.seriesLab.open()
    if (tab === 'comics') return adapters.comic.open()
    if (tab === 'video_editor') return adapters.videoEditor.open()
    if (tab === 'video_3d') return adapters.video3d.open()
    if (tab === 'animate_3d') return adapters.video3d.open(true)
    if (tab === 'character_creator') return adapters.characterKit.open(true)
    if (tab === 'character_kit') return adapters.characterKit.open(false)
    return navigate(tab)
  }
  return adapters
}

async function stagedDirectorOutcome(message: string): Promise<AdapterOutcome> {
  const handoff = useStore.getState().directorStoryProductionHandoff
  if (!handoff?.productionId) throw new Error('Story Lab no devolvió el destino de producción preparado.')
  const { useStoryStore } = await import('../stories/store')
  const project = useStoryStore.getState().projects[handoff.projectId] || useStoryStore.getState().project
  const production = project?.productions.find(item => item.id === handoff.productionId)
  if (!production) throw new Error('La producción preparada no está en el estado canónico de Story Lab.')
  return { message, target: { kind: 'director_production', id: production.id, title: production.title } }
}

async function storyOutcome(message: string): Promise<AdapterOutcome> {
  const { useStoryStore } = await import('../stories/store')
  const project = useStoryStore.getState().project
  if (!project?.id) throw new Error('Story Lab no devolvió la historia canónica creada o actualizada.')
  return { message, target: { kind: 'story', id: project.id, title: project.title } }
}

async function presentStorySliceResult(result: CommandResult): Promise<AdapterOutcome> {
  const destination = result.navigationTarget?.destination
  if (destination === 'director') await navigate('director')
  else if (destination === 'comics') await navigate('director')
  else await navigate('story_lab')
  const {
    notifyAgentStoryDraft,
    openAgentStorySection,
  } = await import('./agentUiBus')
  const section = result.navigationTarget?.section
  if (
    section === 'overview'
    || section === 'world'
    || section === 'characters'
    || section === 'relationships'
    || section === 'structure'
    || section === 'assets'
    || section === 'music'
  ) {
    openAgentStorySection(section)
  }
  const meta = result.artifacts[0]?.metadata || {}
  if (meta.notifyDraft === true && result.entities[0]?.id) notifyAgentStoryDraft(result.entities[0].id)
  const summary = typeof meta.summary === 'string' ? meta.summary : 'Story Lab listo.'
  if (destination === 'director' || destination === 'comics') {
    const title = typeof meta.title === 'string' ? meta.title : (result.entities[0]?.id || 'story')
    return {
      message: summary,
      target: { kind: result.entities[0]?.kind || 'story', id: result.entities[0]?.id || title, title },
      pipelineId: result.pipelineIds[0],
    }
  }
  return { ...await storyOutcome(summary), pipelineId: result.pipelineIds[0] }
}

async function seriesEpisodeOutcome(message: string): Promise<AdapterOutcome> {
  const { useSeriesStore } = await import('../series/store')
  const state = useSeriesStore.getState()
  const series = state.library.seriesById[state.activeSeriesId]
  const episode = series?.episodesById[state.activeEpisodeId]
  if (!series?.id || !episode?.id) throw new Error('Series Lab no devolvió el episodio canónico creado o actualizado.')
  return { message, target: { kind: 'series_episode', id: episode.id, title: `${series.title} · ${episode.title}` } }
}

async function presentSeriesSliceResult(result: CommandResult): Promise<AdapterOutcome> {
  await navigate('series_lab')
  const {
    clearAgentSeriesPlanJob,
    notifyAgentSeriesAssemblyJob,
    notifyAgentSeriesPlanJob,
    notifyAgentSeriesRenderJob,
    openAgentSeriesReviewView,
    openAgentSeriesSection,
  } = await import('./agentUiBus')
  const section = result.navigationTarget?.section
  if (section === 'setup' || section === 'canon' || section === 'episode' || section === 'shots' || section === 'review') {
    openAgentSeriesSection(section)
  }
  if (result.navigationTarget?.anchor === 'finish') openAgentSeriesReviewView('finish')
  const meta = result.artifacts[0]?.metadata || {}
  const channel = typeof meta.channel === 'string' ? meta.channel : ''
  const job = meta.job && typeof meta.job === 'object' ? meta.job as Record<string, unknown> : null
  if (channel === 'series_plan' && job) notifyAgentSeriesPlanJob(job as unknown as SeriesJobStatus)
  if (channel === 'series_render' && job) notifyAgentSeriesRenderJob(job as unknown as SeriesJobStatus)
  if (channel === 'series_assembly' && job) notifyAgentSeriesAssemblyJob(job as unknown as SeriesAssemblyJob)
  if (channel === 'series_plan_clear') clearAgentSeriesPlanJob(result.entities[0]?.id || '')
  const summary = typeof meta.summary === 'string' ? meta.summary : 'Series Lab listo.'
  const outcome = await seriesEpisodeOutcome(summary)
  if (channel === 'series_plan' || channel === 'series_render' || channel === 'series_assembly') {
    const jobEpisodeId = typeof job?.episodeId === 'string' ? job.episodeId : ''
    if (jobEpisodeId && jobEpisodeId !== outcome.target.id) {
      throw new Error('El job de Series Lab no pertenece al episodio canónico abierto.')
    }
  }
  return { ...outcome, taskId: result.taskIds[0] }
}

async function presentComicSliceResult(result: CommandResult): Promise<AdapterOutcome & { state: 'completed' | 'partial' | 'failed' }> {
  await navigate('comics')
  const meta = result.artifacts[0]?.metadata || {}
  const summary = typeof meta.summary === 'string' ? meta.summary : 'Comics listo.'
  const title = typeof meta.title === 'string' ? meta.title : (result.entities[0]?.id || 'comic')
  const state = result.status === 'partial' ? 'partial' : result.status === 'failed' ? 'failed' : 'completed'
  return {
    message: summary,
    target: { kind: 'comic', id: result.entities[0]?.id || title, title },
    state,
  }
}

export const defaultApplicationAdapters = createDefaultApplicationAdapters()
