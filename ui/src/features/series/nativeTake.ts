import type { CharacterKitLibrary } from '../../lib/characterKit'
import type { CharacterKitReviewPolicy } from '../../lib/characterKitReview'
import type { SeriesAsset, SeriesEpisode, SeriesProject, SeriesShot } from './types'
import { allowedSeriesMethods, seriesShotMethod } from './productionMethods'
import { seriesLipSyncFingerprint, seriesLipSyncIssues } from './nativeLipSync'

export function latestNativeTake(series: SeriesProject, shot: SeriesShot) {
  const attempt = [...shot.attempts].reverse().find(item => item.status === 'completed' && item.reviewDecision !== 'rejected')
  return attempt?.outputAssetIds.map(id => series.assets[id]).find(asset => asset?.metadata.productionMethod === 'animation_2d'
    && typeof asset.metadata.sceneFilename === 'string')
}

export function lipSyncCandidates(workspace: string, series: SeriesProject, episode: SeriesEpisode, kits: CharacterKitLibrary,
  policy: CharacterKitReviewPolicy = 'approved') {
  if (!allowedSeriesMethods(series).includes('animation_2d')) return []
  return episode.shots.filter(shot => {
    if (seriesShotMethod(series, shot) !== 'animation_2d' || (policy === 'approved' && shot.approvedAttemptId) || !shot.dialogueBeats.length
      || shot.attempts.some(attempt => ['queued', 'running', 'cancelling'].includes(attempt.status))) return false
    const take = latestNativeTake(series, shot)
    return take && take.metadata.lipSyncFingerprint !== seriesLipSyncFingerprint(workspace, series, shot, kits)
  })
}

/** The UI and batch use the same eligible subset; unfinished characters do not block other shots. */
export function lipSyncUpdatePlan(workspace: string, series: SeriesProject, episode: SeriesEpisode, kits: CharacterKitLibrary,
  policy: CharacterKitReviewPolicy = 'approved') {
  const candidates = lipSyncCandidates(workspace, series, episode, kits, policy)
  const ready: SeriesShot[] = [], blocked: SeriesShot[] = []
  for (const shot of candidates) {
    if (seriesLipSyncIssues(workspace, series, [shot], kits, policy).length) blocked.push(shot)
    else ready.push(shot)
  }
  return { candidates, ready, blocked, issues: seriesLipSyncIssues(workspace, series, blocked, kits, policy) }
}

/** Persisted receipts survive reloads and keep approved originals distinct from newer drafts. */
export function isRegeneratedSeriesAsset(asset?: SeriesAsset) {
  return asset?.metadata.nativeRegeneration === true || asset?.metadata.lipSyncUpdate === true
}

export function lipSyncDraftsToReview(series: SeriesProject, episode: SeriesEpisode) {
  return episode.shots.filter(shot => {
    const approvedIndex = shot.attempts.findIndex(attempt => attempt.id === shot.approvedAttemptId)
    return shot.attempts.slice(approvedIndex + 1).some(attempt => attempt.status === 'completed' && attempt.reviewDecision !== 'rejected'
      && attempt.outputAssetIds.some(id => isRegeneratedSeriesAsset(series.assets[id])))
  })
}
