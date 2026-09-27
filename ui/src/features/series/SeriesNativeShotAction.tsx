import { useUiTranslation } from '../../i18n'
import { useSeriesNativeBatch } from './nativeBatchState'
import { allowedSeriesMethods, seriesShotMethod, seriesTakeStage } from './productionMethods'
import { secondaryButton } from './styles'
import type { SeriesEpisode, SeriesProject, SeriesShot } from './types'

export function SeriesNativeShotAction({ workspace, series, episode, shot }: {
  workspace: string; series: SeriesProject; episode: SeriesEpisode; shot: SeriesShot
}) {
  const { t } = useUiTranslation('seriesLab')
  const running = useSeriesNativeBatch(state => state.running)
  if (!allowedSeriesMethods(series).includes('animation_2d') || seriesShotMethod(series, shot) !== 'animation_2d') return null
  const mode = seriesTakeStage(shot) === 'missing' ? 'missing' : 'regenerate'
  const active = shot.attempts.some(attempt => ['queued', 'running', 'cancelling'].includes(attempt.status))
  return <button className={secondaryButton} disabled={running || active} onClick={() => {
    void import('./nativeBatch').then(module => module.generateNativeDrafts(workspace, series.id, episode.id, mode, [shot.id]))
  }}>{t(mode === 'missing' ? 'native.generateOne' : 'native.regenerateOne')}</button>
}
