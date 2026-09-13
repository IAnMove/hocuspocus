import { useEffect, useState } from 'react'
import { useUiTranslation } from '../../i18n'
import { useCharacterKitLibrary } from '../characters/useCharacterKitLibrary'
import { SeriesInitialSpeechPreparation, SeriesSpeechIssues } from './SeriesSpeechIssues'
import { lipSyncUpdatePlan } from './nativeTake'
import { useSeriesNativeBatch } from './nativeBatchState'
import { secondaryButton } from './styles'
import type { SeriesEpisode, SeriesProject, SeriesShot } from './types'

function LipSyncUpdateAction({ workspace, series, episode, plan, busy }: {
  workspace: string; series: SeriesProject; episode: SeriesEpisode; plan: ReturnType<typeof lipSyncUpdatePlan>; busy: boolean
}) {
  const { t } = useUiTranslation('seriesLab')
  if (plan.ready.length) return <button className={secondaryButton} disabled={busy} onClick={() => {
    void import('./nativeBatch').then(module => module.generateNativeDrafts(workspace, series.id, episode.id, true))
  }}>{t('native.updateLipsync', { count: plan.ready.length })}</button>
  if (!plan.candidates.length) return <p role="status" className="text-xs text-text-muted">{t('native.noUpdates')}</p>
  return null
}

export function SeriesLipSyncPreparation({ workspace, series, episode, initialShots = [], hasCompleted = true }: {
  workspace: string; series: SeriesProject; episode: SeriesEpisode; initialShots?: SeriesShot[]; hasCompleted?: boolean
}) {
  const { t } = useUiTranslation('seriesLab')
  const { kits, error: libraryError, reload, loading } = useCharacterKitLibrary(workspace)
  const [error, setError] = useState('')
  const busy = useSeriesNativeBatch(state => state.running)
  useEffect(() => { window.addEventListener('focus', reload); return () => window.removeEventListener('focus', reload) }, [reload])
  const library = { version: 1 as const, revision: 0, activeId: '', kits: Object.fromEntries(kits.map(kit => [kit.id, kit])) }
  const plan = lipSyncUpdatePlan(workspace, series, episode, library)
  return <>
    <SeriesInitialSpeechPreparation workspace={workspace} series={series} shots={initialShots} library={library}
      loading={loading} error={libraryError} disabled={busy} onError={setError} />
    {hasCompleted && <details className="rounded-lg border border-border px-3 py-2">
    <summary className="cursor-pointer text-sm text-text-secondary">{t('native.updateOptions')}
      {!loading && !libraryError && plan.candidates.length > 0 && <span className="ml-2 text-xs">{t('native.changedShots', { count: plan.candidates.length })}</span>}
    </summary>
    <div className="mt-3 space-y-3">
      <p className="text-xs text-text-secondary">{t('native.lipsyncHint')}</p>
      <button className={secondaryButton} disabled={busy || loading} onClick={reload}>{t('native.refreshCharacters')}</button>
      {loading ? <p role="status" className="text-xs">{t('speech.loading')}</p> : !libraryError && <>
        {plan.blocked.length > 0 && <div className="space-y-2 text-xs">
          <p className="text-amber-200">{t('native.blockedUpdates', { shots: plan.blocked.length, characters: plan.issues.length })}</p>
          <SeriesSpeechIssues workspace={workspace} series={series} issues={plan.issues} disabled={busy} onError={setError} />
        </div>}
        <LipSyncUpdateAction workspace={workspace} series={series} episode={episode} plan={plan} busy={busy} />
      </>}
      {libraryError && <p role="alert" className="text-xs text-red-300">{libraryError}</p>}
    </div>
  </details>}
  {error && <p role="alert" className="text-xs text-red-300">{error}</p>}
  </>
}
