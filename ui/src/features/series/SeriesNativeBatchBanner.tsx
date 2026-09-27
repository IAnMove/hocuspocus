import { useUiTranslation } from '../../i18n'
import { useSeriesNativeBatch } from './nativeBatchState'

export function SeriesNativeBatchBanner() {
  const { t } = useUiTranslation('seriesLab')
  const job = useSeriesNativeBatch()
  if (!job.running) return null
  return <div role="status" className="z-50 flex shrink-0 flex-wrap items-center gap-3 border-b border-violet-500/40 bg-bg-secondary p-3 text-sm">
    <strong>{t('native.progress', { done: job.completed, total: job.total, order: job.order })}</strong>
    <span>{t(`native.${job.phase}`, { defaultValue: job.phase })}</span>
    <button className="ml-auto rounded border border-border px-3 py-1" disabled={job.stopping} onClick={() => useSeriesNativeBatch.setState({ stopping: true })}>{t(job.stopping ? 'native.stopping' : 'native.stop')}</button>
  </div>
}
