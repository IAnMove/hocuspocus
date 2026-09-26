import type { ProjectCatalogItem, ProjectSource } from '../../api/client'
import { openSceneOutput } from '../../lib/sceneOutput'
import { useStore } from '../../stores/useStore'

export function resolveProjectSource(
  project: ProjectCatalogItem,
  preferredWorkspace: string,
): ProjectSource {
  const source = project.sources.find(item => item.workspace_id === preferredWorkspace)
    || project.sources[0]
  if (!source) throw new Error('The project has no persistent location.')
  return source
}

async function selectWorkspace(workspace: string) {
  const app = useStore.getState()
  if (app.activeWorkspace !== workspace || app.browsingUploads) {
    await app.switchWorkspace(workspace)
  }
  if (useStore.getState().activeWorkspace !== workspace || useStore.getState().browsingUploads) {
    throw new Error(`The workspace “${workspace}” could not be opened.`)
  }
}

export async function openProject(project: ProjectCatalogItem): Promise<void> {
  const preferred = useStore.getState().activeWorkspace || 'default'
  const source = resolveProjectSource(project, preferred)
  if (project.kind === 'comic') {
    const { useComicStore } = await import('../comics/store')
    if (useComicStore.getState().dirty && !window.confirm('Open this comic and discard unsaved changes?')) return
  }
  await selectWorkspace(source.workspace_id)

  if (project.kind === 'story') {
    const { useStoryStore } = await import('../stories/store')
    await useStoryStore.getState().loadWorkspace(source.workspace_id)
    if (!useStoryStore.getState().projects[project.id]) throw new Error('Story Lab does not contain that project.')
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
      throw new Error('Series Lab does not contain that project\'s series.')
    }
    await useSeriesStore.getState().openSeries(seriesId)
    if (useSeriesStore.getState().activeSeriesId !== seriesId) {
      throw new Error('Series Lab does not contain that project\'s series.')
    }
    if (project.kind === 'episode') {
      useSeriesStore.getState().openEpisode(project.id)
      if (useSeriesStore.getState().activeEpisodeId !== project.id) {
        throw new Error('Series Lab does not contain that episode.')
      }
    }
    useStore.getState().setMediaFilter('series')
    return
  }
  if (project.kind === 'comic') {
    const [{ loadComicProject }, { fetchSeriesLibrary }, { normalizeComicProject }, { resolveComicSource }, { useComicStore }] = await Promise.all([
      import('../../api/comics'), import('../../api/series'), import('../comics/model'),
      import('../comics/provenance'), import('../comics/store'),
    ])
    const loaded = normalizeComicProject(await loadComicProject(source.key))
    if (loaded.provenance) {
      const library = await fetchSeriesLibrary(loaded.provenance.workspaceId)
      resolveComicSource(loaded, library, loaded.provenance.workspaceId)
    }
    useComicStore.getState().setProject(loaded, source.key)
    useStore.getState().setMediaFilter('comics')
    return
  }
  if (project.kind === 'scene3d') {
    const query = new URLSearchParams({ workspace: source.workspace_id })
    await openSceneOutput({
      name: source.key,
      type: 'scene',
      url: `/api/v1/file/${encodeURIComponent(source.key)}?${query}`,
      mode: null,
      favorite: false,
      size: 0,
      created_at: 0,
    })
    return
  }
  if (project.kind === 'character_kit') {
    const { openKit } = await import('../characters/adapters')
    await openKit({ kitName: project.id })
    useStore.getState().setMediaFilter('characters')
    return
  }
  throw new Error('This project type has no durable storage to open yet.')
}
