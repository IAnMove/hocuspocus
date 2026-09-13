import { useEffect, useState } from 'react'
import { useUiTranslation } from '../../i18n'
import { useCharacterKitLibrary } from '../characters/useCharacterKitLibrary'
import { SeriesSpeechIssues } from './SeriesSpeechIssues'
import { nativeGenerationPlan } from './nativeGenerationPlan'
import { useSeriesNativeBatch } from './nativeBatchState'
import { primaryButton, secondaryButton } from './styles'
import { SeriesLipSyncStatus } from './SeriesLipSyncStatus'
import type { SeriesEpisode, SeriesProject, SeriesShot } from './types'

export function SeriesLipSyncPreparation({ workspace, series, episode, initialShots = [], hasCompleted = true }: {
  workspace: string; series: SeriesProject; episode: SeriesEpisode; initialShots?: SeriesShot[]; hasCompleted?: boolean
}) {
  const { t } = useUiTranslation('seriesLab')
  const { kits, error: libraryError, reload, loading } = useCharacterKitLibrary(workspace)
  const [error, setError] = useState('')
  const busy = useSeriesNativeBatch(state => state.running)
  useEffect(() => { window.addEventListener('focus', reload); return () => window.removeEventListener('focus', reload) }, [reload])
  const library = { version: 1 as const, revision: 0, activeId: '', kits: Object.fromEntries(kits.map(kit => [kit.id, kit])) }
  const mode = initialShots.length ? 'missing' : 'regenerate'
  const plan = nativeGenerationPlan(workspace, series, episode, library, mode)
  return <>
    <button className={primaryButton} disabled={busy || loading || Boolean(libraryError) || !plan.ready.length} onClick={() => {
      void import('./nativeBatch').then(module => module.generateNativeDrafts(workspace, series.id, episode.id, mode))
    }}>{t(mode === 'missing' ? 'native.generateAll' : 'native.regenerateAll', { count: plan.ready.length })}</button>
    <p className="text-xs text-text-secondary">{t('native.simpleHint')}</p>
    {hasCompleted && <SeriesLipSyncStatus series={series} episode={episode} />}
    {loading && <p role="status" className="text-xs">{t('speech.loading')}</p>}
    {plan.issues.length > 0 && !loading && <div className="space-y-2 text-xs">
      <p className="text-amber-200">{t('native.blockedUpdates', { shots: plan.blocked.length, characters: plan.issues.length })}</p>
      <SeriesSpeechIssues workspace={workspace} series={series} issues={plan.issues} disabled={busy} onError={setError} />
      <button className={secondaryButton} disabled={busy} onClick={reload}>{t('native.refreshCharacters')}</button>
    </div>}
    {libraryError && <p role="alert" className="text-xs text-red-300">{libraryError}<button className={`ml-2 ${secondaryButton}`} onClick={reload}>{t('native.refreshCharacters')}</button></p>}
    {error && <p role="alert" className="text-xs text-red-300">{error}</p>}
  </>
}
