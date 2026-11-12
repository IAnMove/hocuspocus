import type { GenerationJob } from '../types'

const ACTIVE_GENERATION_JOB_STATUSES = new Set<GenerationJob['status']>([
  'queued',
  'waiting_resource',
  'running',
  'cancelling',
])

export function isGenerationJobActive(status: GenerationJob['status']): boolean {
  return ACTIVE_GENERATION_JOB_STATUSES.has(status)
}

/** Recovery leftovers are not running: a restart saved them for resume or discard. */
export function isGenerationJobInterrupted(status: GenerationJob['status']): boolean {
  return status === 'leftover' || status === 'interrupted'
}

/** Polling ends here and the tile stays visible with its outcome. */
export function isGenerationJobSettled(status: GenerationJob['status']): boolean {
  return status === 'failed' || status === 'cancelled' || isGenerationJobInterrupted(status)
}

/** The sole derivation for the app-wide busy flag. Terminal history is inert. */
export function deriveIsGenerating(
  jobs: ReadonlyArray<Pick<GenerationJob, 'status'>>,
): boolean {
  return jobs.some(job => isGenerationJobActive(job.status))
}
