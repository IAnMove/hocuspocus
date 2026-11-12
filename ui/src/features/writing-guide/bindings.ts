import type { StoryProject } from '../stories/types'
import type { SeriesProject } from '../series/types'
import { editGuide, type GuideScope, type GuideUpdate } from './model'

type Project = StoryProject | SeriesProject
type Entity = Record<string, unknown>
const record = (value: unknown): Entity => value as Entity
const rows = (value: unknown): Entity[] => Array.isArray(value) ? value as Entity[] : []
export type GuideTarget = { scope: GuideScope; id: string; episodeId?: string }
export const targetKey = (target: GuideTarget) => ['story', 'world', 'series', 'seriesWorld'].includes(target.scope)
  ? 'root' : target.scope === 'scene' ? `${target.episodeId}/${target.id}` : target.id

export function targetEntity(project: Project, target: GuideTarget): Entity | undefined {
  const source = record(project)
  const { scope, id } = target
  if (scope === 'story' || scope === 'series') return id === project.id ? source : undefined
  if (scope === 'world') return record(source.world)
  if (scope === 'seriesWorld') return record(source.canon)
  if (scope === 'episode' || scope === 'scene') {
    const episode = record(source.episodesById)?.[scope === 'episode' ? id : target.episodeId || '']
    return scope === 'episode' ? record(episode) : rows(record(episode)?.script).find(item => item.id === id)
  }
  const collection = { character: 'characters', seriesCharacter: 'characters', relationship: 'relationships',
    beat: 'beats', season: 'seasons' }[scope]
  return rows(source[collection]).find(item => item.id === id)
}

/** Re-resolve stable IDs inside the store's latest mutation, including when the collection was reordered. */
export function updateTarget<P extends Project>(project: P, target: GuideTarget, update: GuideUpdate): P {
  const next = structuredClone(project)
  const entity = targetEntity(next, target)
  if (!entity) return project
  const result = editGuide(entity, next.writingGuide, target.scope, targetKey(target), update)
  Object.assign(entity, result.entity)
  next.writingGuide = result.guide
  if (result.changed && 'approval' in entity && target.scope !== 'seriesWorld') entity.approval = 'draft'
  if (result.changed && 'canon' in next && !['season', 'episode', 'scene'].includes(target.scope)) {
    next.canon = { ...next.canon, approval: 'draft', approvedAt: '' }
  }
  return next
}
