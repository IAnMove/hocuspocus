import type { SeriesEpisode } from './types'

export async function registerEpisodeProduction(workspace: string, episode: SeriesEpisode): Promise<string> {
  const productionId = `series-${episode.id}`
  const response = await fetch('/api/v1/production-projects/resolve', {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ workspace, origin: 'ui', format: 'full_story',
      production_id: productionId, intent_id: `generation-${productionId}`,
      title: episode.title, project: { kind: 'episode', id: episode.id } }),
  })
  if (!response.ok) throw new Error(String(response.status))
  const result = await response.json() as { production_id: string }
  return result.production_id
}

export async function noteEpisodeProductionStatus(workspace: string, productionId: string, status: string): Promise<void> {
  const response = await fetch('/api/v1/production-projects/status', {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ workspace, production_id: productionId, status }),
  })
  if (!response.ok) throw new Error(String(response.status))
}
