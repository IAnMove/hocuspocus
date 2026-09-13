import { useEffect, useState } from 'react'
import { useUiTranslation } from '../../i18n'
import { useCharacterKitLibrary } from '../characters/useCharacterKitLibrary'
import { openSeriesCharacterEditor } from './seriesCharacterEditor'
import { seriesLipSyncIssues } from './nativeLipSync'
import { lipSyncCandidates } from './nativeTake'
import { seriesShotMethod } from './productionMethods'
import { useSeriesNativeBatch } from './nativeBatchState'
import { secondaryButton } from './styles'
import type { SeriesEpisode, SeriesProject } from './types'

export function SeriesLipSyncPreparation({ workspace, series, episode }: { workspace: string; series: SeriesProject; episode: SeriesEpisode }) {
  const { t } = useUiTranslation('seriesLab')
  const { kits, error: libraryError, reload } = useCharacterKitLibrary(workspace)
  const [error, setError] = useState('')
  const busy = useSeriesNativeBatch(state => state.running)
  useEffect(() => { window.addEventListener('focus', reload); return () => window.removeEventListener('focus', reload) }, [reload])
  const library = { version: 1 as const, revision: 0, activeId: '', kits: Object.fromEntries(kits.map(kit => [kit.id, kit])) }
  const shots = episode.shots.filter(shot => seriesShotMethod(series, shot) === 'animation_2d' && !shot.approvedAttemptId)
  const issues = seriesLipSyncIssues(workspace, series, shots, library)
  const updates = lipSyncCandidates(workspace, series, episode, library)
  if (!shots.some(shot => shot.dialogueBeats.length)) return null
  return <div className="space-y-2 border-t border-violet-500/20 pt-3">
    <p className="text-xs text-text-secondary">{t('native.lipsyncHint')}</p>
    <button className={secondaryButton} disabled={busy} onClick={reload}>{t('native.refreshCharacters')}</button>
    {issues.length > 0 && <ul className="space-y-2 text-xs text-amber-200">{issues.map(issue => <li key={issue.id}>
      <button className="underline underline-offset-2" disabled={busy} onClick={() => {
        void openSeriesCharacterEditor(workspace, series.id, issue.id).catch(reason => setError(reason.message))
      }}>{issue.name}</button>: {t(`native.lipsyncIssues.${issue.reason}`)}
    </li>)}</ul>}
    <button className={secondaryButton} disabled={busy || !updates.length || !!issues.length || !!libraryError} onClick={() => {
      void import('./nativeBatch').then(module => module.generateNativeDrafts(workspace, series.id, episode.id, true))
    }}>{t('native.updateLipsync', { count: updates.length })}</button>
    {(error || libraryError) && <p role="alert" className="text-xs text-red-300">{error || libraryError}</p>}
  </div>
}
