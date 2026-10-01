import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { openEpisodeShots } from './openShots'

export function SeriesReviewLink({
  workspace, episodeId, productionIds,
}: {
  workspace: string
  episodeId: string
  productionIds: string[]
}) {
  const { t } = useTranslation('seriesLab')
  const [missing, setMissing] = useState(false)
  return <button type="button" className="rounded border border-border px-3 py-2 text-xs" data-episode={episodeId} data-workspace={workspace} onClick={() => {
    void openEpisodeShots(workspace, episodeId, productionIds).then(result => { if (result === 'missing') setMissing(true) }, () => setMissing(true))
  }}>
    {t('review.sharedShots')}{missing ? ` — ${t('review.sharedShotsMissing')}` : ''}
  </button>
}
