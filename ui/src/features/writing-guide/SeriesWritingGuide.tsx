import { useStore } from '../../stores/useStore'
import { useSeriesStore } from '../series/store'
import { resolveStoryWritingProvider } from '../stories/provider'
import { readGuide, type GuideScope, type GuideUpdate } from './model'
import { seriesGuideContext } from './seriesContext'
import { targetEntity, targetKey, updateTarget, type GuideTarget } from './bindings'
import { WritingGuide } from './WritingGuide'

export function SeriesWritingGuide({ seriesId, scope, targetId, episodeId }: {
  seriesId: string; scope: GuideScope; targetId?: string; episodeId?: string
}) {
  const project = useSeriesStore(state => state.library.seriesById[seriesId])
  const workspace = useSeriesStore(state => state.workspace)
  const profile = useStore(state => state.productionProfile)
  const target: GuideTarget = { scope, id: targetId || seriesId, episodeId }
  if (!project) return null
  const entity = targetEntity(project, target)
  if (!entity) return null
  const data = readGuide(entity, project.writingGuide, scope, targetKey(target))
  const update = (change: GuideUpdate) => {
    const store = useSeriesStore.getState()
    if (store.workspace !== workspace || store.activeSeriesId !== seriesId) return
    store.updateSeries(current => updateTarget(current, target, change))
  }
  const provider = resolveStoryWritingProvider(profile, {
    provider: { ...project.provider, writingBaseUrl: project.provider.writingBaseUrl || '', imageProvider: 'maestro' },
  })
  return <WritingGuide key={`${workspace}/${seriesId}/${scope}/${targetKey(target)}`}
    scope={scope} data={data} language={project.language} provider={provider} onChange={update}
    context={seriesGuideContext(project, target, entity)} />
}
