export interface TimelineAttemptLike {
  id: string
  status: string
  reviewDecision?: 'approved' | 'rejected'
  outputAssetIds: string[]
}

export interface TimelineShotLike<TAttempt extends TimelineAttemptLike = TimelineAttemptLike> {
  id: string
  order: number
  approvedAttemptId?: string
  attempts: TAttempt[]
}

export interface PlaybackSlotLike {
  shotId: string
}

export interface PlaybackCursor {
  index: number
  shotId: string | null
  outcome: 'start' | 'keep' | 'stop'
}

/** Reconcile ordered playback by stable slot identity, never array position. */
export function reconcilePlaybackCursor(
  previousShotId: string | null | undefined,
  playable: ReadonlyArray<PlaybackSlotLike>,
): PlaybackCursor {
  if (!playable.length) return { index: -1, shotId: null, outcome: 'stop' }
  if (!previousShotId) {
    return { index: 0, shotId: playable[0].shotId, outcome: 'start' }
  }
  const index = playable.findIndex(item => item.shotId === previousShotId)
  return index >= 0
    ? { index, shotId: previousShotId, outcome: 'keep' }
    : { index: -1, shotId: null, outcome: 'stop' }
}

export function orderedTimelineShots<T extends { id: string; order: number }>(shots: T[]): T[] {
  return [...shots].sort((left, right) => left.order - right.order || left.id.localeCompare(right.id))
}

export function safeTimelineAttempt<T extends TimelineAttemptLike>(
  shot: TimelineShotLike<T>,
  hasAsset: (assetId: string) => boolean,
): T | undefined {
  // The ordered review cut is a live working cut: a completed regeneration
  // replaces the visible slot immediately while the previous approved take
  // remains available as a safe fallback and immutable history.
  return [...shot.attempts].reverse().find(attempt => attempt.status === 'completed'
      && attempt.reviewDecision !== 'rejected' && attempt.outputAssetIds.some(hasAsset))
    || shot.attempts.find(attempt => attempt.id === shot.approvedAttemptId
      && attempt.status === 'completed' && attempt.outputAssetIds.some(hasAsset))
}

export function seriesEditorCanvas(
  rawQuality: unknown,
  orientation: unknown,
): { label: string; width: number; height: number } {
  const quality = String(rawQuality || '480p')
  const dimensions: Record<string, [number, number]> = {
    '480p': [864, 480], '540p': [960, 544], '720p': [1280, 704], '768p': [1344, 768],
  }
  const [landscapeWidth, landscapeHeight] = dimensions[quality] || dimensions['480p']
  const portrait = orientation === 'portrait'
  return {
    label: `${portrait ? 'Portrait' : 'Landscape'} ${quality}`,
    width: portrait ? landscapeHeight : landscapeWidth,
    height: portrait ? landscapeWidth : landscapeHeight,
  }
}
