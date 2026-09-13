import { useUiTranslation } from '../../i18n'
import { openSeriesCharacterEditor } from './seriesCharacterEditor'
import { seriesLipSyncIssues } from './nativeLipSync'
import type { CharacterKitLibrary } from '../../lib/characterKit'
import type { SeriesProject, SeriesShot } from './types'

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

/** Initial generation keeps direct setup links, independently of optional updates to existing takes. */
export function SeriesInitialSpeechPreparation({ workspace, series, shots, library, loading, error, disabled, onError }: {
  workspace: string; series: SeriesProject; shots: SeriesShot[]; library: CharacterKitLibrary
  loading: boolean; error?: string; disabled: boolean; onError: (message: string) => void
}) {
  const { t } = useUiTranslation('seriesLab')
  if (!shots.length) return null
  if (loading) return <p role="status" className="text-xs">{t('speech.loading')}</p>
  if (error) return <p role="alert" className="text-xs text-red-300">{error}</p>
  const issues = seriesLipSyncIssues(workspace, series, shots, library)
  if (!issues.length) return null
  return <div className="space-y-2">
    <p className="text-xs text-amber-200">{t('native.initialSpeechSetup')}</p>
    <SeriesSpeechIssues workspace={workspace} series={series} issues={issues} disabled={disabled} onError={onError} />
  </div>
}
