import { useUiTranslation } from '../../i18n'
import { useSeriesNativeBatch } from './nativeBatchState'
import { allowedSeriesMethods, seriesShotMethod, seriesTakeStage } from './productionMethods'
import type { SeriesEpisode, SeriesProject } from './types'
import { SeriesLipSyncPreparation } from './SeriesLipSyncPreparation'

export function SeriesNativeDrafts({ workspace, series, episode }: { workspace: string; series: SeriesProject; episode: SeriesEpisode }) {
  const { t } = useUiTranslation('seriesLab')
  const job = useSeriesNativeBatch()
  if (!allowedSeriesMethods(series).includes('animation_2d')) return null
  const shots = episode.shots.filter(shot => seriesShotMethod(series, shot) === 'animation_2d')
  const pending = shots.filter(shot => seriesTakeStage(shot) === 'missing' && !shot.attempts.some(attempt => ['queued', 'running', 'cancelling'].includes(attempt.status)))
  const completed = shots.filter(shot => seriesTakeStage(shot) !== 'missing').length
  if (!shots.length) return null
  const own = job.workspace === workspace && job.seriesId === series.id && job.episodeId === episode.id
  return <section aria-label={t('native.title')} className="space-y-3 rounded-lg border border-border p-3">
    <h3 className="text-sm font-semibold">{t('native.title')}</h3>
    {completed > 0 && <p className="text-xs text-text-secondary">{t('native.completedShots', { count: completed })}</p>}
    <SeriesLipSyncPreparation key={`${workspace}/${series.id}/${episode.id}`} workspace={workspace} series={series} episode={episode}
      initialShots={pending} hasCompleted={completed > 0} />
    {own && job.total > 0 && <p role="status" className="text-xs">{t('native.progress', { done: job.completed, total: job.total, order: job.order })}</p>}
    {own && job.error && <p role="alert" className="text-xs text-red-300">{job.error}</p>}
  </section>
}
