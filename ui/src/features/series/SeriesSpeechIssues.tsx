import { useUiTranslation } from '../../i18n'
import { openSeriesCharacterEditor } from './seriesCharacterEditor'
import { seriesLipSyncIssues } from './nativeLipSync'
import type { SeriesProject } from './types'

export function SeriesSpeechIssues({ workspace, series, issues, disabled, onError }: {
  workspace: string; series: SeriesProject; issues: ReturnType<typeof seriesLipSyncIssues>; disabled: boolean; onError: (message: string) => void
}) {
  const { t } = useUiTranslation('seriesLab')
  return <ul className="space-y-2 text-xs text-text-secondary">{issues.map(issue => <li key={issue.id}>
    <button className="underline underline-offset-2" disabled={disabled} onClick={() => {
      void openSeriesCharacterEditor(workspace, series.id, issue.id).catch(reason => onError(reason.message))
    }}>{issue.name}</button>: {t(`native.lipsyncIssues.${issue.reason}`)}
  </li>)}</ul>
}
