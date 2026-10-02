import { openLinkedProject } from '../production-catalog/projectLink'

type RegenerationTarget = {
  executor: 'http' | 'series_native'
  path?: string
  body?: Record<string, unknown>
  workspace?: string
  series_id?: string
  episode_id?: string
  shot_id?: string
}

export async function executeRegeneration(target: RegenerationTarget): Promise<void> {
  if (target.executor === 'http' && target.path?.startsWith('/api/v1/')) {
    const response = await fetch(target.path, {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify(target.body ?? {}),
    })
    if (!response.ok) throw new Error(String(response.status))
    return
  }
  if (target.executor !== 'series_native' || !target.workspace || !target.series_id || !target.episode_id || !target.shot_id) {
    throw new Error('The generation source is unavailable')
  }
  const { useSeriesNativeBatch } = await import('../series/nativeBatchState')
  if (useSeriesNativeBatch.getState().running) throw new Error('An episode generation is already running')
  const opened = await openLinkedProject(target.workspace, { kind: 'episode', id: target.episode_id, seriesId: target.series_id })
  if (opened === 'missing') throw new Error('The source episode is unavailable')
  const { generateNativeDrafts } = await import('../series/nativeBatch')
  await generateNativeDrafts(target.workspace, target.series_id, target.episode_id, 'regenerate', [target.shot_id])
  const error = useSeriesNativeBatch.getState().error
  if (error) throw new Error(error)
  if (useSeriesNativeBatch.getState().completed !== 1) throw new Error('The selected shot was not generated')
}
