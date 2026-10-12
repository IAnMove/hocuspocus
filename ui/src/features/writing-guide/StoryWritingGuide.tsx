import { useStore } from '../../stores/useStore'
import { useStoryStore } from '../stories/store'
import { resolveStoryWritingProvider } from '../stories/provider'
import { readGuide, guideContext, type GuideUpdate } from './model'
import { targetEntity, targetKey, updateTarget, type GuideTarget } from './bindings'
import { WritingGuide } from './WritingGuide'

export function StoryWritingGuide({ projectId, scope, targetId }: {
  projectId: string; scope: 'story' | 'world' | 'character' | 'relationship' | 'beat'; targetId?: string
}) {
  const project = useStoryStore(state => state.project)
  const workspace = useStore(state => state.activeWorkspace)
  const profile = useStore(state => state.productionProfile)
  const target: GuideTarget = { scope, id: targetId || projectId }
  if (project.id !== projectId) return null
  const entity = targetEntity(project, target)
  if (!entity) return null
  const data = readGuide(entity, project.writingGuide, scope, targetKey(target))
  const update = (change: GuideUpdate) => {
    const store = useStoryStore.getState()
    if (useStore.getState().activeWorkspace !== workspace || store.project.id !== projectId) return
    store.updateProject(current => updateTarget(current, target, change))
  }
  return <WritingGuide key={`${workspace}/${projectId}/${scope}/${target.id}`}
    scope={scope} data={data} language={project.language} onChange={update}
    context={guideContext(project as unknown as Record<string, unknown>, entity, project.writingGuide)}
    provider={resolveStoryWritingProvider(profile, project)} />
}
