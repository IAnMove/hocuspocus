import { imageReferenceJobs } from './imageBatch'
import { snapshotStudioImageIntent, type StudioImageIntent, type StudioImageIntentSource } from './prepareGeneration'

export type ReferenceJob = ReturnType<typeof imageReferenceJobs>[number]

/** Edit sources are their own jobs, so reference rows do not apply there. */
export function usesSeparateEdits(source: StudioImageIntentSource): boolean {
  return source.imageStudioIntent === 'edit' && Boolean(source.imageBatch?.enabled)
}

/** Prompt × reference-row jobs for the form as it is now. Empty when the normal path is enough. */
export function referenceJobsOf(source: StudioImageIntentSource): ReferenceJob[] {
  if (usesSeparateEdits(source)) return []
  return imageReferenceJobs(String(source.params?.prompt || ''), Boolean(source.imageBatch?.perLine), {
    primary: source.imageRefs, rows: source.imageRefRows,
  })
}

/** Params of one job in a batch: its own prompt and one image per prompt. */
export function batchJobParams(source: StudioImageIntentSource, prompt: string) {
  return {
    ...source.params, prompt, repeat_generation: 1, multi_prompts_gen_type: 2,
    // Layer count lives in batch_size for Qwen Layered. Only pin it to 1
    // when the model uses that field as extra images per prompt.
    ...(source.modelOptions?.image_layer_count ? {} : { batch_size: 1 }),
  }
}

/** Freeze every job before the first await: later form edits must not alter a submitted batch. */
export function referenceRowIntents(source: StudioImageIntentSource, jobs: ReferenceJob[]): StudioImageIntent[] {
  return jobs.map(job => snapshotStudioImageIntent({
    ...source, imageRefs: job.refs, params: batchJobParams(source, job.prompt),
  }))
}

/**
 * With one job left (first row empty, one extra row filled) the normal path
 * would read only the first row and send no references. Use the job's pictures.
 */
export function withSingleReferenceJob(source: StudioImageIntentSource, jobs: ReferenceJob[]): StudioImageIntentSource {
  return jobs.length === 1 ? { ...source, imageRefs: jobs[0].refs } : source
}
