import { useUiTranslation } from '../../i18n'
import { episodeReferenceIssues, type OpenSeriesReference } from './shotReferences'
import type { SeriesEpisode, SeriesProject } from './types'
import { seriesTakeStage } from './productionMethods'
import { secondaryButton } from './styles'

export function SeriesEpisodeProgress({ series, episode, onOpenReferences, onOpenShot, onReviewShot }: {
  series: SeriesProject; episode: SeriesEpisode; onOpenReferences?: OpenSeriesReference
  onOpenShot: (id: string) => void; onReviewShot?: (id: string) => void
}) {
  const { t } = useUiTranslation('seriesLab')
  const issues = episodeReferenceIssues(series, episode)
  const pending = episode.shots.filter(shot => seriesTakeStage(shot) !== 'approved')
  const missing = pending.filter(shot => seriesTakeStage(shot) === 'missing')
  const review = pending.filter(shot => seriesTakeStage(shot) === 'review')
  return <section aria-label={t('episodeProgress.title')} className="space-y-3 rounded-xl border border-border bg-bg-secondary p-4">
    <h3 className="text-sm font-semibold">{t('episodeProgress.title')}</h3>
    <p className={`text-xs ${issues.length ? 'text-amber-200' : 'text-emerald-300'}`}>{t(issues.length ? 'episodeProgress.referencesMissing' : 'episodeProgress.referencesReady', { count: issues.length })}</p>
    {issues.length > 0 && <ul className="space-y-2 text-xs">{issues.map(item => <li key={`${item.room}/${item.id}`}>
      <button className="text-violet-200 underline underline-offset-2" disabled={item.state !== 'missingEntity' && !onOpenReferences} onClick={() => {
        if (item.state === 'missingEntity') onOpenShot(item.shotId)
        else onOpenReferences?.(item.room, item.id)
      }}>{item.name}</button><span className="ml-2 text-text-secondary">{t(`production.assets.states.${item.state}`)}</span>
    </li>)}</ul>}
    <p className="text-xs text-text-secondary">{t('episodeProgress.takes', { missing: missing.length, review: review.length, approved: episode.shots.length - pending.length, total: episode.shots.length })}</p>
    {missing[0] && <button className={secondaryButton} onClick={() => onOpenShot(missing[0].id)}>{t('episodeProgress.nextShot', { order: missing[0].order })}</button>}
    {review[0] && <button className={secondaryButton} onClick={() => (onReviewShot ?? onOpenShot)(review[0].id)}>{t('episodeProgress.nextReview', { order: review[0].order })}</button>}
    {pending.length > 0 && <details><summary className="cursor-pointer text-xs text-violet-200">{t('episodeProgress.showPending', { count: pending.length })}</summary>
      <ul className="mt-2 max-h-56 space-y-2 overflow-y-auto text-xs">{pending.map(shot => <li key={shot.id}>
        <button className="text-violet-200 underline underline-offset-2" onClick={() => {
          if (seriesTakeStage(shot) === 'review' && onReviewShot) onReviewShot(shot.id)
          else onOpenShot(shot.id)
        }}>{t('review.shot', { order: shot.order })} · {shot.framing}</button><span className="ml-2 text-text-secondary">{t(`episodeProgress.${seriesTakeStage(shot)}`)}</span>
      </li>)}</ul>
    </details>}
    <p className="text-xs text-text-muted">{t('episodeProgress.hint')}</p>
  </section>
}
