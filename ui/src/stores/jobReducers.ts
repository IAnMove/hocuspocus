import type { GenerationJob } from '../types'
import { deriveIsGenerating, isGenerationJobActive } from '../lib/generationJobState'

export type JobState = {
  jobs: GenerationJob[]
  isGenerating: boolean
}
/** Build the public queue state from one immutable job collection. */
export function withJobs(jobs: readonly GenerationJob[]): JobState {
  const nextJobs = [...jobs]
  return { jobs: nextJobs, isGenerating: deriveIsGenerating(nextJobs) }
}

/** Add a new foreground job while preserving the existing display order. */
export function prependJob(jobs: readonly GenerationJob[], job: GenerationJob): JobState {
  return withJobs([job, ...jobs])
}

/** Replace a job by object identity, which is stable before the server ID exists. */
export function updateJob(
  jobs: readonly GenerationJob[],
  predicate: (job: GenerationJob) => boolean,
  update: (job: GenerationJob) => GenerationJob,
): JobState {
  return withJobs(jobs.map(job => predicate(job) ? update(job) : job))
}

/** Remove one job from the visible queue. */
export function removeJob(
  jobs: readonly GenerationJob[],
  predicate: (job: GenerationJob) => boolean,
): JobState {
  return withJobs(jobs.filter(job => !predicate(job)))
}

/** Mark active jobs as cancelling without removing their progress tile. */
export function markJobsCancelling(
  jobs: readonly GenerationJob[],
  ids: ReadonlySet<string>,
): JobState {
  return updateJob(jobs, job => !!job.id && ids.has(job.id) && isGenerationJobActive(job.status), job => ({
    ...job,
    status: 'cancelling',
    message: 'Cancelling…',
    phase: 'Cancelling',
  }))
}
