import type { ProjectCatalogItem, ProjectSource } from '../../api/client'
import { stageSceneForEditor } from '../../lib/sceneOutput'
import { useStore } from '../../stores/useStore'

export function resolveProjectSource(
  project: ProjectCatalogItem,
  preferredWorkspace: string,
): ProjectSource {
  const source = project.sources.find(item => item.workspace_id === preferredWorkspace)
    || project.sources[0]
  if (!source) throw new Error('El proyecto no tiene una ubicación persistente.')
  return source
}

async function selectWorkspace(workspace: string) {
  const app = useStore.getState()
  if (app.activeWorkspace !== workspace || app.browsingUploads) {
    await app.switchWorkspace(workspace)
  }
  if (useStore.getState().activeWorkspace !== workspace || useStore.getState().browsingUploads) {
    throw new Error(`No se pudo abrir el workspace “${workspace}”.`)
  }
}

export async function openProject(project: ProjectCatalogItem): Promise<void> {
  const preferred = useStore.getState().activeWorkspace || 'default'
  const source = resolveProjectSource(project, preferred)
  if (project.kind === 'comic') {
    const { useComicStore } = await import('../comics/store')
    if (useComicStore.getState().dirty && !window.confirm('¿Abrir este cómic y descartar los cambios sin guardar?')) return
  }
  await selectWorkspace(source.workspace_id)

  if (project.kind === 'story') {
    const { useStoryStore } = await import('../stories/store')
    await useStoryStore.getState().loadWorkspace(source.workspace_id)
    if (!useStoryStore.getState().projects[project.id]) throw new Error('Story Lab no contiene ese proyecto.')
    useStoryStore.getState().openProject(project.id)
    useStore.getState().setMediaFilter('stories')
    return
  }
  if (project.kind === 'series' || project.kind === 'episode') {
    const { useSeriesStore } = await import('../series/store')
    await useSeriesStore.getState().loadWorkspace(source.workspace_id)
    const seriesId = project.kind === 'series' ? project.id : project.parent?.id || ''
    if (
      useSeriesStore.getState().workspace !== source.workspace_id
      || !seriesId
      || !useSeriesStore.getState().library.seriesById[seriesId]
    ) {
      throw new Error('Series Lab no contiene la serie de ese proyecto.')
    }
    await useSeriesStore.getState().openSeries(seriesId)
    if (useSeriesStore.getState().activeSeriesId !== seriesId) {
      throw new Error('Series Lab no contiene la serie de ese proyecto.')
    }
    if (project.kind === 'episode') {
      useSeriesStore.getState().openEpisode(project.id)
      if (useSeriesStore.getState().activeEpisodeId !== project.id) {
        throw new Error('Series Lab no contiene ese episodio.')
      }
    }
    useStore.getState().setMediaFilter('series')
    return
  }
  if (project.kind === 'comic') {
    const [{ loadComicProject }, { useComicStore }] = await Promise.all([
      import('../../api/comics'), import('../comics/store'),
    ])
    useComicStore.getState().setProject(await loadComicProject(source.key), source.key)
    useStore.getState().setMediaFilter('comics')
    return
  }
  if (project.kind === 'scene3d') {
    const query = new URLSearchParams({ workspace: source.workspace_id })
    await stageSceneForEditor({
      name: source.key,
      type: 'scene',
      url: `/api/v1/file/${encodeURIComponent(source.key)}?${query}`,
      mode: null,
      favorite: false,
      size: 0,
      created_at: 0,
    })
    useStore.getState().setMediaFilter('scene3d')
    return
  }
  if (project.kind === 'character_kit') {
    const { openKit } = await import('../characters/adapters')
    await openKit({ kitName: project.id })
    useStore.getState().setMediaFilter('characters')
    return
  }
  throw new Error('Este tipo de proyecto todavía no tiene almacenamiento durable que abrir.')
}
