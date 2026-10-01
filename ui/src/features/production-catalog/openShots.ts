import { listWorks } from './api'
import { REVIEW_EVENT } from './reviewEvent'
import { reviewDetail } from './target'

export function openSharedShots(workspace: string, productionId: string): boolean {
  const detail = reviewDetail(workspace, productionId)
  if (!detail || typeof window === 'undefined') return false
  window.dispatchEvent(new CustomEvent(REVIEW_EVENT, { detail }))
  return true
}

export async function openEpisodeShots(workspace: string, episodeId: string, productionIds: string[]): Promise<'opened' | 'missing'> {
  const known = productionIds.find(id => reviewDetail(workspace, id))
  if (known && openSharedShots(workspace, known)) return 'opened'
  const listed = await listWorks(workspace, '', '')
  const match = listed.works.find(item => item.project?.kind === 'episode' && item.project.id === episodeId)
  if (match && openSharedShots(workspace, match.production_id)) return 'opened'
  return 'missing'
}
