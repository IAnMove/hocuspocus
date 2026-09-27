import type { CharacterKitLibrary } from '../../lib/characterKit'
import { allowedSeriesMethods, seriesShotMethod, seriesTakeStage } from './productionMethods'
import { seriesLipSyncIssues } from './nativeLipSync'
import { lipSyncUpdatePlan } from './nativeTake'
import type { SeriesEpisode, SeriesProject } from './types'

export type NativeGenerationMode = 'missing' | 'regenerate' | 'changed'

function nativeShots(series: SeriesProject, episode: SeriesEpisode) {
  if (!allowedSeriesMethods(series).includes('animation_2d')) return []
  return episode.shots.filter(shot => seriesShotMethod(series, shot) === 'animation_2d'
    && !shot.attempts.some(attempt => ['queued', 'running', 'cancelling'].includes(attempt.status)))
}

export function nativeDraftCandidates(series: SeriesProject, episode: SeriesEpisode) {
  return nativeShots(series, episode).filter(shot => seriesTakeStage(shot) === 'missing')
}

/** Explicit regeneration includes current, approved and silent shots; individual requests stay scoped. */
export function nativeGenerationPlan(workspace: string, series: SeriesProject, episode: SeriesEpisode,
  kits: CharacterKitLibrary, mode: NativeGenerationMode, shotIds?: string[]) {
  if (mode === 'changed') return lipSyncUpdatePlan(workspace, series,
    { ...episode, shots: episode.shots.filter(shot => !shotIds || shotIds.includes(shot.id)) }, kits, 'saved-draft')
  const candidates = (mode === 'missing' ? nativeDraftCandidates(series, episode) : nativeShots(series, episode))
    .filter(shot => !shotIds || shotIds.includes(shot.id))
  const policy = mode === 'missing' ? 'approved' : 'saved-draft'
  const ready = candidates.filter(shot => !seriesLipSyncIssues(workspace, series, [shot], kits, policy).length)
  const blocked = candidates.filter(shot => !ready.includes(shot))
  return { candidates, ready, blocked, issues: seriesLipSyncIssues(workspace, series, blocked, kits, policy) }
}
