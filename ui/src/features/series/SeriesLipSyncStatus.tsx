import { useUiTranslation } from '../../i18n'
import { openAgentSeriesReviewView, openAgentSeriesSection } from '../../lib/uiBus'
import { lipSyncDraftsToReview } from './nativeTake'
import { secondaryButton } from './styles'
import type { SeriesEpisode, SeriesProject } from './types'

export function SeriesLipSyncStatus({ series, episode }: { series: SeriesProject; episode: SeriesEpisode }) {
  const { t } = useUiTranslation('seriesLab')
  const drafts = lipSyncDraftsToReview(series, episode)
  if (!drafts.length) return null
  return <div className="space-y-2 rounded-lg border border-green-500/30 p-3">
    <p role="status" className="text-sm text-green-200">{t('native.newVersions', { count: drafts.length })}</p>
    <p className="text-xs text-text-secondary">{t('native.reviewVersionsHint')}</p>
    <button className={secondaryButton} onClick={() => {
      openAgentSeriesSection('review'); openAgentSeriesReviewView('history')
    }}>{t('native.reviewVersions')}</button>
  </div>
}
