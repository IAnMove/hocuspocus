import type { LinkedTarget } from './target'

export async function openLinkedProject(workspace: string, target: LinkedTarget): Promise<'story' | 'episode' | 'missing'> {
  const { useStore } = await import('../../stores/useStore')
  if (target.kind === 'story') {
    const { useStoryStore } = await import('../stories/store')
    await useStoryStore.getState().loadWorkspace(workspace)
    if (!useStoryStore.getState().projects[target.id]) return 'missing'
    useStoryStore.getState().openProject(target.id)
    useStore.getState().setMediaFilter('stories')
    return 'story'
  }
  if (!target.seriesId) return 'missing'
  const { useSeriesStore } = await import('../series/store')
  await useSeriesStore.getState().loadWorkspace(workspace)
  if (!useSeriesStore.getState().library.seriesById[target.seriesId]) return 'missing'
  await useSeriesStore.getState().openSeries(target.seriesId)
  useSeriesStore.getState().openEpisode(target.id)
  useStore.getState().setMediaFilter('series')
  return 'episode'
}
