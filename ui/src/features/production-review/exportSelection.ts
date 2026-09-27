import { canApproveTake, isTakeQueued } from './status.ts'
import type { ExportOmission, ExportSelection, ReviewDesk, ReviewShot, ReviewTake } from './types.ts'

function selectedTakeOf(shot: ReviewShot): ReviewTake | undefined {
  return shot.takes.find(take => take.id === shot.selectedTakeId)
    || shot.takes.find(take => take.id === shot.approvedTakeId)
}

function omit(shot: ReviewShot, reason: ExportOmission['reason']): ExportOmission {
  return { shotId: shot.id, reason }
}

function omissionFor(shot: ReviewShot, take: ReviewTake | undefined): ExportOmission | null {
  if (shot.decision !== 'approved' || !shot.approvedTakeId) return omit(shot, 'not_approved')
  if (!take) return omit(shot, 'not_completed')
  if (isTakeQueued(take)) return omit(shot, 'queued')
  if (!canApproveTake(take)) return omit(shot, 'not_completed')
  if (!take.filename) return omit(shot, 'missing_filename')
  return null
}

export function exportApprovedSelection(desk: ReviewDesk): ExportSelection {
  const clips: ExportSelection['clips'] = []
  const omitted: ExportOmission[] = []
  for (const shot of desk.shots) {
    const take = selectedTakeOf(shot)
    const skip = omissionFor(shot, take)
    if (skip || !take) {
      omitted.push(skip || omit(shot, 'not_approved'))
      continue
    }
    clips.push({
      shotId: shot.id,
      takeId: take.id,
      filename: take.filename,
      durationSeconds: take.durationSeconds ?? shot.durationSeconds,
    })
  }
  return { productionId: desk.productionId, clips, omitted }
}
