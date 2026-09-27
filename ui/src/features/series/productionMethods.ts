import type { SeriesEpisode, SeriesProductionMethod, SeriesProject, SeriesShot } from './types'

export const SERIES_PRODUCTION_METHODS: SeriesProductionMethod[] = ['generated_video', 'animation_2d', 'animation_3d', 'imported_video']
export function allowedSeriesMethods(series: Pick<SeriesProject, 'allowedProductionMethods'>): SeriesProductionMethod[] {
  return series.allowedProductionMethods?.length ? series.allowedProductionMethods : ['generated_video']
}
export function seriesShotMethod(series: Pick<SeriesProject, 'allowedProductionMethods'>, shot: Pick<SeriesShot, 'productionMethod'>): SeriesProductionMethod {
  return shot.productionMethod || allowedSeriesMethods(series)[0]
}

export type SeriesRenderMode = 'selected' | 'missing' | 'failed' | 'all'

export function isSeriesGeneratedShot(series: Pick<SeriesProject, 'allowedProductionMethods'>, shot: Pick<SeriesShot, 'productionMethod'>) {
  return allowedSeriesMethods(series).includes('generated_video') && seriesShotMethod(series, shot) === 'generated_video'
}

/** Match the render endpoint: selected shots may append alternatives to an approved take. */
export function seriesRenderCandidates(series: Pick<SeriesProject, 'allowedProductionMethods'>,
  episode: Pick<SeriesEpisode, 'shots'>, mode: SeriesRenderMode, shotIds: string[] = []) {
  return episode.shots.filter(shot => {
    if (!isSeriesGeneratedShot(series, shot)) return false
    if (mode === 'selected') return shotIds.includes(shot.id)
    if (shot.approvedAttemptId) return false
    return mode !== 'failed' || shot.attempts.at(-1)?.status === 'failed'
  })
}

export function canBatchAssignSeriesShot(shot: SeriesShot): boolean {
  return !shot.approvedAttemptId && !shot.attempts.some(attempt => ['queued', 'running', 'cancelling', 'completed'].includes(attempt.status))
}

export function assignSeriesEpisodeMethod(series: Pick<SeriesProject, 'allowedProductionMethods'>,
  episode: SeriesEpisode, method: SeriesProductionMethod): SeriesEpisode {
  if (!allowedSeriesMethods(series).includes(method)) return episode
  return { ...episode, shots: episode.shots.map(shot => canBatchAssignSeriesShot(shot) && seriesShotMethod(series, shot) !== method
    ? { ...shot, productionMethod: method, referenceManifest: undefined,
      dialogueDuration: method === 'generated_video' ? shot.dialogueDuration : undefined }
    : shot) }
}

export function seriesTakeStage(shot: SeriesShot) {
  if (shot.approvedAttemptId) return 'approved'
  if (shot.attempts.some(attempt => attempt.status === 'completed' && attempt.reviewDecision !== 'rejected')) return 'review'
  return 'missing'
}
