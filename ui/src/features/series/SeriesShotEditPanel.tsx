import { useUiTranslation } from '../../i18n'
import { SeriesShotDraftFields } from './SeriesShotDraftFields'
import { SeriesShotPlanEditor } from './SeriesShotPlanEditor'
import { SeriesShotProduction } from './SeriesShotProduction'
import type { SeriesEpisode, SeriesProject, SeriesShot } from './types'

/** Edit a shot in place from the review: its plan, lines and production. Saving it sends its approvals back to pending. */
export function SeriesShotEditPanel({ workspace, series, episode, shot, onChange, saveNow }: {
  workspace: string; series: SeriesProject; episode: SeriesEpisode; shot: SeriesShot
  onChange: (shot: SeriesShot) => void; saveNow: () => Promise<unknown>
}) {
  const { t } = useUiTranslation('seriesLab')
  return <div className="space-y-3 rounded-lg border border-violet-500/30 bg-bg-secondary p-3" data-testid={`series-approval-edit-${shot.id}`}>
    <p className="text-[11px] text-amber-200">{t('approval.edit.resetHint')}</p>
    <SeriesShotDraftFields shot={shot} series={series} workspace={workspace} onChange={onChange} />
    <SeriesShotPlanEditor workspace={workspace} series={series} shot={shot} onChange={onChange} />
    <SeriesShotProduction workspace={workspace} series={series} episode={episode} shot={shot} onChange={onChange} saveNow={saveNow} />
  </div>
}
