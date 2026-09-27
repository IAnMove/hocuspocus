import type { ReactNode } from 'react'
import { useUiTranslation } from '../../i18n'
import { isSeriesGeneratedShot, seriesRenderCandidates, seriesShotMethod } from './productionMethods'
import type { SeriesEpisode, SeriesProject, SeriesShot } from './types'
import { primaryButton, secondaryButton } from './styles'

export function SeriesRenderActions({ series, episode, busy, onRender, onOpenShots }: {
  series: SeriesProject; episode: SeriesEpisode; busy: boolean
  onRender: (mode: 'missing' | 'failed') => void
  onOpenShots?: (shotId?: string) => void
}) {
  const { t } = useUiTranslation('seriesLab')
  const pending = seriesRenderCandidates(series, episode, 'missing').length
  const failed = seriesRenderCandidates(series, episode, 'failed').length
  return <div className="space-y-3">
    <p className="text-xs text-text-secondary">{t('renderActions.hint')}</p>
    <div className="flex flex-wrap gap-2">
      <button className={primaryButton} disabled={busy || !pending} onClick={() => onRender('missing')}>{t('renderActions.generate', { count: pending })}</button>
      <button className={secondaryButton} disabled={busy || !failed} onClick={() => onRender('failed')}>{t('renderActions.retry', { count: failed })}</button>
      {(['animation_2d', 'animation_3d', 'imported_video'] as const).map(method => {
        const shots = episode.shots.filter(shot => seriesShotMethod(series, shot) === method)
        return shots.length > 0 && <button key={method} className={secondaryButton} disabled={busy || !onOpenShots}
          onClick={() => onOpenShots?.(shots[0].id)}>{t(`renderActions.${method}`, { count: shots.length })}</button>
      })}
    </div>
    {!pending && <p role="status" className="text-xs text-text-muted">{t('renderActions.noCandidates')}</p>}
  </div>
}

export function SeriesReviewShotAction({ series, shot, onEdit, onOpenShots, children }: {
  series: SeriesProject; shot: SeriesShot; onEdit: (shot: SeriesShot) => void
  onOpenShots?: (shotId?: string) => void; children: ReactNode
}) {
  const { t } = useUiTranslation('seriesLab')
  if (isSeriesGeneratedShot(series, shot)) return <button className={secondaryButton} onClick={() => onEdit(shot)}>{children}</button>
  return <button className={secondaryButton} disabled={!onOpenShots} onClick={() => onOpenShots?.(shot.id)}>{t('renderActions.openShot', { order: shot.order })}</button>
}
