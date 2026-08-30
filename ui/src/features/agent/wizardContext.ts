import { useStore } from '../../stores/useStore'
import { emptyCharacterKitLibrary } from '../../lib/characterKit'
import { comicArtworkInventory } from '../comics/generateArtwork'
import { useComicStore } from '../comics/store'
import { loadEditorDraft } from '../video-editor/editorDraft'
import { sequenceTotalDuration } from '../video-editor/editorTimeline'
import { useSeriesStore } from '../series/store'
import { useStoryStore } from '../stories/store'
import { rememberedCharacterKitLibrary, rememberedVideo3dScene } from './wizardLabSession'

export interface WizardLabSnapshots {
  story: {
    project_id: string
    title: string
    project_type: string
    characters: number
    productions: number
    visual_jobs: number
    state: string
  }
  series: {
    series_id: string
    title: string
    episode_id: string
    episode_title: string
    shots: number
    approved: number
    failed: number
    state: string
  }
  video_3d: {
    scene_id: string
    title: string
    layers: number
    state: string
  }
  character_kit: {
    kit_id: string
    title: string
    poses: number
    mouth: number
    eyes: number
    state: string
  }
  video_editor: {
    project_id: string
    title: string
    clips: number
    duration: number
    export_job: string
    state: string
  }
}

function storySnapshot(): WizardLabSnapshots['story'] {
  const { project } = useStoryStore.getState()
  const visualJobs = project.visualJobs ? Object.keys(project.visualJobs).length : 0
  const running = Object.values(project.visualJobs || {}).some(status => /run|queue/i.test(String(status)))
  return {
    project_id: project.id || '',
    title: project.title || '',
    project_type: project.projectType || '',
    characters: project.characters?.length || 0,
    productions: project.productions?.length || 0,
    visual_jobs: visualJobs,
    state: running ? 'running' : project.title && project.title !== 'Untitled story' ? 'ready' : 'empty',
  }
}

function seriesSnapshot(): WizardLabSnapshots['series'] {
  const state = useSeriesStore.getState()
  const series = state.library.seriesById[state.activeSeriesId]
  const episode = series?.episodesById[state.activeEpisodeId]
  const shots = episode?.shots || []
  const approved = shots.filter(shot => Boolean(shot.approvedAttemptId)).length
  const failed = shots.filter(shot => shot.attempts?.some(attempt => attempt.status === 'failed')).length
  return {
    series_id: series?.id || '',
    title: series?.title || '',
    episode_id: episode?.id || '',
    episode_title: episode?.title || '',
    shots: shots.length,
    approved,
    failed,
    state: state.renderRecovery.length ? 'running' : episode ? 'ready' : 'empty',
  }
}

function video3dSnapshot(): WizardLabSnapshots['video_3d'] {
  const remembered = rememberedVideo3dScene()
  if (remembered) return remembered
  const latest = useStore.getState().outputs.find(output => output.type === 'scene')
  return {
    scene_id: latest?.name || '',
    title: latest?.name || '',
    layers: 0,
    state: latest ? 'saved' : 'empty',
  }
}

function characterKitSnapshot(): WizardLabSnapshots['character_kit'] {
  const library = rememberedCharacterKitLibrary() || emptyCharacterKitLibrary()
  const kit = library.kits[library.activeId] || Object.values(library.kits)[0]
  if (!kit) {
    return { kit_id: '', title: '', poses: 0, mouth: 0, eyes: 0, state: 'empty' }
  }
  const poses = Number(Boolean(kit.base)) + Object.keys(kit.poses || {}).length
  return {
    kit_id: kit.id,
    title: kit.name,
    poses,
    mouth: Object.keys(kit.mouth || {}).length,
    eyes: Object.keys(kit.eyes || {}).length,
    state: kit.base?.reviewState === 'approved' ? 'ready' : 'draft',
  }
}

function videoEditorSnapshot(): WizardLabSnapshots['video_editor'] {
  const workspace = useStore.getState().activeWorkspace || 'default'
  const draft = loadEditorDraft(workspace)
  let exportJob = ''
  try {
    exportJob = window.localStorage.getItem(`maestro-video-editor-export-v1:${encodeURIComponent(workspace)}`) || ''
  } catch {
    exportJob = ''
  }
  return {
    project_id: draft.projectName || 'my_video',
    title: draft.projectName || 'my_video',
    clips: draft.clips.length,
    duration: Math.round(sequenceTotalDuration(draft.clips) * 10) / 10,
    export_job: exportJob,
    state: exportJob ? 'exporting' : draft.clips.length ? 'ready' : 'empty',
  }
}

export function buildWizardLabSnapshots(): WizardLabSnapshots {
  return {
    story: storySnapshot(),
    series: seriesSnapshot(),
    video_3d: video3dSnapshot(),
    character_kit: characterKitSnapshot(),
    video_editor: videoEditorSnapshot(),
  }
}

export function comicLabSnapshot() {
  const inventory = comicArtworkInventory(useComicStore.getState().project)
  return {
    project_id: inventory.projectId,
    title: inventory.title,
    pages: inventory.pages,
    panels: inventory.panels,
    completed: inventory.completed,
    failed: inventory.failed,
    provider: inventory.provider,
    active_page: inventory.activePage,
  }
}
