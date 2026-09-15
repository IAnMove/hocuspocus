import { canApproveTake, tagFromDecision } from './status.ts'
import { findShot, findTake, replaceShot } from './takes.ts'
import type { PersistCommand, ReviewDesk, ReviewShot } from './types.ts'

export function setShotNotes(desk: ReviewDesk, shotId: string, notes: string): ReviewDesk {
  const shot = findShot(desk, shotId)
  return replaceShot(desk, { ...shot, notes })
}

export function approveShot(desk: ReviewDesk, shotId: string, takeId?: string): ReviewDesk {
  const shot = findShot(desk, shotId)
  const take = findTake(shot, takeId || shot.selectedTakeId || '')
  if (!canApproveTake(take)) {
    throw new Error(`Take ${take.id} is not completed and cannot be approved.`)
  }
  return replaceShot(desk, {
    ...shot,
    decision: 'approved',
    selectedTakeId: take.id,
    approvedTakeId: take.id,
  })
}

export function rejectShot(desk: ReviewDesk, shotId: string, takeId?: string): ReviewDesk {
  const shot = findShot(desk, shotId)
  const take = takeId ? findTake(shot, takeId) : shot.takes.find(item => item.id === shot.selectedTakeId)
  return replaceShot(desk, {
    ...shot,
    decision: 'rejected',
    selectedTakeId: take?.id || shot.selectedTakeId,
    approvedTakeId: null,
  })
}

function shotCommands(desk: ReviewDesk, shot: ReviewShot): PersistCommand[] {
  const take = shot.takes.find(item => item.id === shot.selectedTakeId)
  const commands: PersistCommand[] = []
  if (take?.filename) {
    commands.push({
      type: 'select_take',
      pipelineId: desk.pipelineId,
      clipIndex: shot.clipIndex,
      filename: take.filename,
      takeId: take.id,
    })
  }
  commands.push({
    type: 'tag_clip',
    pipelineId: desk.pipelineId,
    clipIndex: shot.clipIndex,
    tag: tagFromDecision(shot.decision),
  })
  commands.push({
    type: 'note_clip',
    pipelineId: desk.pipelineId,
    clipIndex: shot.clipIndex,
    notes: shot.notes,
  })
  return commands
}

export function persistCommandsFor(desk: ReviewDesk, shotIds?: Iterable<string>): PersistCommand[] {
  const allow = shotIds ? new Set(shotIds) : null
  return desk.shots
    .filter(shot => !allow || allow.has(shot.id))
    .flatMap(shot => shotCommands(desk, shot))
}
