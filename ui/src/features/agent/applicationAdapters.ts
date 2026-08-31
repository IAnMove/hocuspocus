import { useStore } from '../../stores/useStore'
import type { MediaFilter } from '../../types'
import type { AgentApply3dRhythmAction } from './agentActions'
import type { AgentExecutionTarget } from './agentContract'
import { openAgentActivityDetails, requestAgentSceneControl, requestAgentSceneRhythm, requestAgentSceneWorkflow, type AgentSceneControlRequest, type AgentSceneWorkflowRequest } from './agentUiBus'
import type { AgentRhythmGrid } from './agentUiBus'
import { queueMusic } from './audioActions'
import type { AgentPrepareAudioAction } from './agentActions'
import type { AgentTab } from './capabilityRegistry'

export interface AdapterOutcome {
  message: string
  target: AgentExecutionTarget
  taskId?: string
  pipelineId?: string
  outputNames?: string[]
  sceneId?: string
  layerIds?: string[]
  audioTrackId?: string
  analysisId?: string
  bpm?: number
  beatCount?: number
  downbeatCount?: number
  rhythmGrid?: AgentRhythmGrid
}

export interface StudioAdapter {
  open(tab?: 'studio' | 'images' | 'videos' | 'audio' | '3d'): Promise<AdapterOutcome>
  queueMusic(action: AgentPrepareAudioAction): Promise<AdapterOutcome>
}

export interface StoryLabAdapter { open(): Promise<AdapterOutcome> }
export interface SeriesLabAdapter { open(): Promise<AdapterOutcome> }
export interface ComicAdapter { open(): Promise<AdapterOutcome> }
export interface VideoEditorAdapter { open(): Promise<AdapterOutcome> }
export interface CharacterKitAdapter { open(creator?: boolean): Promise<AdapterOutcome> }
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

export function createDefaultApplicationAdapters(): WizardApplicationAdapters {
  const adapters = {} as WizardApplicationAdapters
  adapters.studio = {
    open: tab => navigate(tab || 'studio'),
    async queueMusic(action) {
      const result = await queueMusic(action)
      return { ...result, target: { kind: 'queue_task', id: result.taskId, title: 'Song generation' } }
    },
  }
  adapters.storyLab = { open: () => navigate('story_lab') }
  adapters.seriesLab = { open: () => navigate('series_lab') }
  adapters.comic = { open: () => navigate('comics') }
  adapters.videoEditor = { open: () => navigate('video_editor') }
  adapters.characterKit = { open: creator => navigate(creator ? 'character_creator' : 'character_kit') }
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

export const defaultApplicationAdapters = createDefaultApplicationAdapters()
