import { interpolate, reviewCopy } from './copy.ts'
import { findShot, replaceShot } from './takes.ts'
import type { RegenOutcome, RegenPlan, ReviewDesk, ReviewShot, ReviewTake } from './types.ts'

export interface SubsetOptions {
  confirm?: boolean
  copy?: ReturnType<typeof reviewCopy>
}

function eligibleShot(shot: ReviewShot, requested: Set<string>): boolean {
  if (shot.decision === 'approved') return false
  return requested.has(shot.id)
}

export function planSubsetRegeneration(
  desk: ReviewDesk,
  shotIds: string[],
  options: SubsetOptions = {},
): RegenPlan {
  if (options.confirm !== true) {
    throw new Error('Regenerating a subset requires confirmation.')
  }
  const requested = new Set(shotIds)
  const keepShotIds: string[] = []
  const jobs: RegenPlan['jobs'] = []
  for (const shot of desk.shots) {
    if (!eligibleShot(shot, requested)) {
      keepShotIds.push(shot.id)
      continue
    }
    jobs.push({
      shotId: shot.id,
      clipIndex: shot.clipIndex,
      prompt: shot.prompt,
      refs: [...shot.refs],
      parentTakeId: shot.selectedTakeId,
    })
  }
  return { productionId: desk.productionId, keepShotIds, jobs }
}

export function queuedTakeFromJob(job: RegenPlan['jobs'][number], takeId: string): ReviewTake {
  return {
    id: takeId,
    generationId: takeId,
    filename: '',
    status: 'queued',
    durationSeconds: null,
    notes: '',
    source: 'regenerated',
    refs: [...job.refs],
    parentId: job.parentTakeId,
    prompt: job.prompt,
  }
}

function applyOutcome(shot: ReviewShot, outcome: RegenOutcome, copy: ReturnType<typeof reviewCopy>): ReviewShot {
  if (outcome.ok && outcome.take) {
    return { ...shot, takes: [...shot.takes, outcome.take], selectedTakeId: shot.selectedTakeId }
  }
  const message = outcome.error || 'unknown'
  const note = interpolate(copy.failureNote, { message })
  return { ...shot, notes: shot.notes ? `${shot.notes}\n${note}` : note }
}

export function applyRegenPlan(
  desk: ReviewDesk,
  plan: RegenPlan,
  outcomes: RegenOutcome[],
  options: { copy?: ReturnType<typeof reviewCopy> } = {},
): ReviewDesk {
  const copy = options.copy || reviewCopy('en')
  const byShot = new Map(outcomes.map(item => [item.shotId, item]))
  let next = desk
  for (const job of plan.jobs) {
    const shot = findShot(next, job.shotId)
    const outcome = byShot.get(job.shotId) || { shotId: job.shotId, ok: false, error: 'missing outcome' }
    next = replaceShot(next, applyOutcome(shot, outcome, copy))
  }
  return next
}

export function rerunCommands(desk: ReviewDesk, plan: RegenPlan) {
  return plan.jobs.map(job => ({
    type: 'rerun_clip' as const,
    pipelineId: desk.pipelineId,
    clipIndex: job.clipIndex,
    prompt: job.prompt,
    refs: job.refs,
    parentTakeId: job.parentTakeId,
  }))
}
