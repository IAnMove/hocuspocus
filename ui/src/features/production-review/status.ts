import type { ClipTag, ReviewDecision, ReviewTake, TakeStatus } from './types.ts'

const LIVE: ReadonlySet<TakeStatus> = new Set(['queued', 'running'])
const TERMINAL_FAILURE: ReadonlySet<TakeStatus> = new Set(['failed', 'cancelled'])

export function isTakeCompleted(take: Pick<ReviewTake, 'status'> | TakeStatus): boolean {
  const status = typeof take === 'string' ? take : take.status
  return status === 'completed'
}

export function isTakeQueued(take: Pick<ReviewTake, 'status'> | TakeStatus): boolean {
  const status = typeof take === 'string' ? take : take.status
  return LIVE.has(status)
}

export function canApproveTake(take: Pick<ReviewTake, 'status' | 'filename'> | undefined): boolean {
  if (!take) return false
  return isTakeCompleted(take) && Boolean(take.filename)
}

export function decisionFromTag(tag: ClipTag | undefined): ReviewDecision {
  if (tag === 'good') return 'approved'
  if (tag === 'needs_work') return 'rejected'
  return 'pending'
}

export function tagFromDecision(decision: ReviewDecision): ClipTag {
  if (decision === 'approved') return 'good'
  if (decision === 'rejected') return 'needs_work'
  return null
}

export function livePipelineStatus(status: string | undefined): boolean {
  const token = (status || '').toLowerCase()
  return token === 'queued' || token === 'running' || token === 'planning' || token === 'resuming'
}

export function failedTake(status: TakeStatus): boolean {
  return TERMINAL_FAILURE.has(status)
}
