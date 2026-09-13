import type { CharacterKitLibrary } from '../../lib/characterKit'
import type { SeriesEpisode, SeriesProject, SeriesShot } from './types'
import { allowedSeriesMethods, seriesShotMethod } from './productionMethods'
import { seriesLipSyncFingerprint, seriesLipSyncIssues } from './nativeLipSync'

export function latestNativeTake(series: SeriesProject, shot: SeriesShot) {
  const attempt = [...shot.attempts].reverse().find(item => item.status === 'completed')
  return attempt?.outputAssetIds.map(id => series.assets[id]).find(asset => asset?.metadata.productionMethod === 'animation_2d'
    && typeof asset.metadata.sceneFilename === 'string')
}

export function lipSyncCandidates(workspace: string, series: SeriesProject, episode: SeriesEpisode, kits: CharacterKitLibrary) {
  if (!allowedSeriesMethods(series).includes('animation_2d')) return []
  return episode.shots.filter(shot => {
    if (seriesShotMethod(series, shot) !== 'animation_2d' || shot.approvedAttemptId || !shot.dialogueBeats.length
      || shot.attempts.some(attempt => ['queued', 'running', 'cancelling'].includes(attempt.status))) return false
    const take = latestNativeTake(series, shot)
    return take && take.metadata.lipSyncFingerprint !== seriesLipSyncFingerprint(workspace, series, shot, kits)
  })
}

/** The UI and batch use the same eligible subset; unfinished characters do not block other shots. */
export function lipSyncUpdatePlan(workspace: string, series: SeriesProject, episode: SeriesEpisode, kits: CharacterKitLibrary) {
  const candidates = lipSyncCandidates(workspace, series, episode, kits)
  const ready: SeriesShot[] = [], blocked: SeriesShot[] = []
  for (const shot of candidates) {
    if (seriesLipSyncIssues(workspace, series, [shot], kits).length) blocked.push(shot)
    else ready.push(shot)
  }
  return { candidates, ready, blocked, issues: seriesLipSyncIssues(workspace, series, blocked, kits) }
}
