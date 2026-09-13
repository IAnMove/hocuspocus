import { useUiTranslation } from '../../i18n'
import { useSeriesNativeBatch } from './nativeBatchState'
import { allowedSeriesMethods, seriesShotMethod, seriesTakeStage } from './productionMethods'
import type { SeriesEpisode, SeriesProject } from './types'
import { primaryButton } from './styles'

export function SeriesNativeDrafts({ workspace, series, episode }: { workspace: string; series: SeriesProject; episode: SeriesEpisode }) {
  const { t } = useUiTranslation('seriesLab')
  const job = useSeriesNativeBatch()
  if (!allowedSeriesMethods(series).includes('animation_2d')) return null
  const pending = episode.shots.filter(shot => seriesShotMethod(series, shot) === 'animation_2d' && seriesTakeStage(shot) === 'missing')
  const own = job.workspace === workspace && job.seriesId === series.id && job.episodeId === episode.id
  return <section aria-label={t('native.title')} className="space-y-3 rounded-xl border border-violet-500/40 bg-violet-500/10 p-4">
    <h3 className="text-sm font-semibold">{t('native.title')}</h3>
    <p className="text-xs text-text-secondary">{t('native.hint')}</p>
    <button className={primaryButton} disabled={job.running || !pending.length} onClick={() => {
      void import('./nativeBatch').then(module => module.generateNativeDrafts(workspace, series.id, episode.id))
    }}>{t('native.generate', { count: pending.length })}</button>
    {own && job.total > 0 && <p role="status" className="text-xs">{t('native.progress', { done: job.completed, total: job.total, order: job.order })}</p>}
    {own && job.error && <p role="alert" className="text-xs text-red-300">{job.error}</p>}
  </section>
}
