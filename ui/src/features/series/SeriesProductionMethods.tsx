import { useState } from 'react'
import { useUiTranslation } from '../../i18n'
import { SectionCard } from './components'
import { allowedSeriesMethods, assignSeriesEpisodeMethod, canBatchAssignSeriesShot, SERIES_PRODUCTION_METHODS, seriesShotMethod } from './productionMethods'
import type { SeriesEpisode, SeriesProductionMethod, SeriesProject } from './types'
import { seriesEntityImage, type SeriesReferenceRoom } from './shotReferences'
import { primaryButton, secondaryButton, selectClass } from './styles'

export function SeriesProductionMethods({ series, update, onOpenReferences, episode, updateEpisode }: {
  series: SeriesProject; update: (updater: (series: SeriesProject) => SeriesProject) => void
  onOpenReferences?: (room: SeriesReferenceRoom) => void
  episode?: SeriesEpisode; updateEpisode?: (updater: (episode: SeriesEpisode) => SeriesEpisode) => void
}) {
  const { t } = useUiTranslation('seriesLab')
  const allowed = allowedSeriesMethods(series)
  const [chosenMethod, setChosenMethod] = useState<SeriesProductionMethod | ''>('')
  const method = chosenMethod && allowed.includes(chosenMethod) ? chosenMethod : ''
  const pendingCount = episode?.shots.filter(shot => canBatchAssignSeriesShot(shot) && seriesShotMethod(series, shot) !== method).length || 0
  return <SectionCard title={t('production.title')} description={t('production.description')}>
    <div className="grid gap-2 sm:grid-cols-2">{SERIES_PRODUCTION_METHODS.map(method => <label key={method} className="flex items-start gap-3 rounded-lg border border-border p-3">
      <input type="checkbox" className="mt-1 accent-violet-500" checked={allowed.includes(method)} disabled={allowed.length === 1 && allowed.includes(method)}
        onChange={event => update(current => ({ ...current, allowedProductionMethods: event.target.checked
          ? [...allowedSeriesMethods(current), method] : allowedSeriesMethods(current).filter(item => item !== method) }))} />
      <span><span className="block text-xs font-semibold text-text-primary">{t(`production.methods.${method}`)}</span><span className="mt-1 block text-[11px] text-text-muted">{t(`production.hints.${method}`)}</span></span>
    </label>)}</div>
    <p className="mt-2 text-xs text-violet-200">{t(allowed.length > 1 ? 'production.mixed' : 'production.single')}</p>
    {episode && updateEpisode && <div className="mt-3 space-y-2 rounded-lg border border-border p-3">
      <p className="text-xs text-text-secondary">{t('production.bulkHint')}</p>
      <div className="flex flex-wrap items-end gap-2">
        <label className="min-w-0 flex-1 text-xs text-text-secondary">{t('production.bulkMethod')}
          <select className={`${selectClass} mt-1`} value={method} onChange={event => setChosenMethod(event.target.value as SeriesProductionMethod | '')}>
            <option value="">{t('production.bulkChoose')}</option>
            {allowed.map(value => <option key={value} value={value}>{t(`production.methods.${value}`)}</option>)}
          </select>
        </label>
        <button type="button" className={primaryButton} disabled={!method || !pendingCount} onClick={() => {
          if (method) updateEpisode(current => assignSeriesEpisodeMethod(series, current, method))
        }}>{t('production.bulkApply', { count: pendingCount })}</button>
      </div>
    </div>}
    {allowed.some(method => method === 'animation_2d' || method === 'animation_3d') && <div className="mt-4 space-y-3 rounded-lg border border-violet-500/25 p-3">
      <p className="text-xs font-semibold text-text-primary">{t('production.assets.title')}</p>
      <p className="text-xs text-text-secondary">{t('production.assets.setupHint')}</p>
      <div className="grid gap-3 sm:grid-cols-2">{(['locations', 'characters'] as const).map(room => <div key={room} className="space-y-2">
        <p className="text-xs text-text-secondary">{t(`production.assets.${room}Count`, {
          ready: series[room].filter(entity => entity.approval === 'approved' && seriesEntityImage(entity, series.assets)).length,
          total: series[room].length,
        })}</p>
        {onOpenReferences && <button type="button" className={secondaryButton} onClick={() => onOpenReferences(room)}>{t(room === 'locations' ? 'production.assets.prepareLocations' : 'production.assets.prepareCharacters')}</button>}
      </div>)}</div>
    </div>}
  </SectionCard>
}
