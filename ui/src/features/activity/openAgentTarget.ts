import { fetchCharacterKitLibrary } from '../../api/characters'
import { getWorld3DWorkingScene, getWorld3DWorkspaceTemplate } from '../../api/world3dWorkspace'
import { queueFaceRigHandoff } from '../../lib/characterKitHandoff'
import { openSceneOutput } from '../../lib/sceneOutput'
import { useStore } from '../../stores/useStore'
import type { OutputFile } from '../../types'
import type { AgentTarget } from './agentOrigin'
import { openActivityArtifact } from './openTargets'

function fileUrl(name: string, workspace: string): string {
  return `/api/v1/file/${encodeURIComponent(name)}?workspace=${encodeURIComponent(workspace)}`
}

async function openWorld3DDocument(document: unknown): Promise<void> {
  const app = useStore.getState()
  app.setDashboardOpen(false)
  app.setMediaFilter('world3d')
  const { presentSceneDocument } = await import('../sceneFx/handoff')
  await presentSceneDocument('3d', document)
}

async function openSeriesTarget(target: AgentTarget): Promise<void> {
  const app = useStore.getState()
  app.setDashboardOpen(false)
  app.setMediaFilter('series')
  const { useSeriesStore } = await import('../series/store')
  const series = useSeriesStore.getState()
  const seriesId = target.kind === 'series' ? target.id : target.series
  if (seriesId) await series.openSeries(seriesId)
  if (target.kind === 'series_episode') useSeriesStore.getState().openEpisode(target.id)
}

/** The kit library lives in the Video 2.5D editor; its Face Rig handoff opens an existing kit by its base pose. */
async function openKit(target: AgentTarget, workspace: string): Promise<void> {
  const library = await fetchCharacterKitLibrary(workspace)
  const kit = library.kits[target.id]
  const source = kit?.base?.source || kit?.identityReference?.source
  if (!kit || !source) throw new Error(`Character Kit “${target.title || target.id}” has no saved base pose to open.`)
  queueFaceRigHandoff({ name: kit.name, source, workspace })
  openTab('scene3d')
}

/** Story Lab with that project open (the Wizard's stories are saved in the workspace's story library). */
async function openStory(id: string, workspace: string): Promise<void> {
  openTab('stories')
  const { useStoryStore } = await import('../stories/store')
  if (useStoryStore.getState().workspace !== workspace || !useStoryStore.getState().hydrated) {
    await useStoryStore.getState().loadWorkspace(workspace)
  }
  const stories = useStoryStore.getState()
  if (!stories.projects[id]) throw new Error(`Story “${id}” is not in this workspace.`)
  stories.openProject(id)
}

function openTab(filter: Parameters<ReturnType<typeof useStore.getState>['setMediaFilter']>[0]): void {
  const app = useStore.getState()
  app.setDashboardOpen(false)
  app.setMediaFilter(filter)
}

/** Open what an agent made in the editor a user would have used to make it. Rejects with a readable reason. */
export async function openAgentTarget(target: AgentTarget, workspace: string): Promise<void> {
  switch (target.kind) {
    case 'scene_file': {
      const name = target.file || target.id
      await openSceneOutput({ name, url: fileUrl(name, workspace), type: 'scene' } as OutputFile)
      return
    }
    case 'world3d_scene':
      await openWorld3DDocument(await getWorld3DWorkingScene(workspace, target.id))
      return
    case 'world3d_template':
      await openWorld3DDocument((await getWorld3DWorkspaceTemplate(workspace, target.id)).document)
      return
    case 'series':
    case 'series_episode':
      await openSeriesTarget(target)
      return
    case 'character_kit':
      await openKit(target, workspace)
      return
    case 'workspace_collection':
      openTab('runs')
      return
    case 'story':
      await openStory(target.id, workspace)
      return
    case 'montage': {
      const file = [target.file, target.id].find(name => name?.endsWith('.montage.json'))
      if (!file) { openTab('videoeditor'); return }
      const { requestOpenMontage } = await import('../music-productions/useOpenProductionMontage')
      requestOpenMontage(workspace, file)
      return
    }
    default:
      openActivityArtifact(target.file || target.id)
  }
}
