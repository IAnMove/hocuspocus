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

/** The sole derivation for the app-wide busy flag. Terminal history is inert. */
export function deriveIsGenerating(
  jobs: ReadonlyArray<Pick<GenerationJob, 'status'>>,
): boolean {
  return jobs.some(job => isGenerationJobActive(job.status))
}
