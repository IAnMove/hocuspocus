import type { SeriesEpisode, SeriesProductionMethod, SeriesProject, SeriesShot } from './types'

export const SERIES_PRODUCTION_METHODS: SeriesProductionMethod[] = ['generated_video', 'animation_2d', 'animation_3d', 'imported_video']
export function allowedSeriesMethods(series: Pick<SeriesProject, 'allowedProductionMethods'>): SeriesProductionMethod[] {
  return series.allowedProductionMethods?.length ? series.allowedProductionMethods : ['generated_video']
}
export function seriesShotMethod(series: Pick<SeriesProject, 'allowedProductionMethods'>, shot: Pick<SeriesShot, 'productionMethod'>): SeriesProductionMethod {
  return shot.productionMethod || allowedSeriesMethods(series)[0]
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
