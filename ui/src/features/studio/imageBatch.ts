import type { ApiOutput } from '../../api/outputs'

export type ImageBatchSettings = { enabled: boolean; perLine: boolean; sources: ApiOutput[] }
export const MAX_IMAGE_BATCH_JOBS = 100

export function imageBatchPrompts(prompt: string, perLine: boolean): string[] {
  return perLine ? prompt.split(/\r?\n/).map(line => line.trim()).filter(Boolean) : prompt.trim() ? [prompt] : []
}

/** Each source is a separate edit, never an additional reference to one edit. */
export function imageBatchPairs(prompt: string, settings: ImageBatchSettings | undefined, edit: boolean) {
  const prompts = imageBatchPrompts(prompt, settings?.perLine ?? false)
  const sources = edit && settings?.enabled ? settings.sources : [undefined]
  return sources.flatMap(source => prompts.map(text => ({ source, prompt: text })))
}

export type ImageReferenceRows = { primary?: readonly File[]; rows?: readonly (readonly File[])[] }

/** Filled rows, primary first. An empty extra row is a slot the user has not filled yet. */
export function filledReferenceRows(refs?: ImageReferenceRows): File[][] {
  const primary = [...(refs?.primary || [])]
  const extra = (refs?.rows || []).filter(row => row.length).map(row => [...row])
  return primary.length ? [primary, ...extra] : extra
}

/**
 * One job per prompt × reference row. A single row with a single prompt stays
 * on the normal generate path, so this returns an empty list.
 */
export function imageReferenceJobs(prompt: string, perLine: boolean, refs?: ImageReferenceRows): { prompt: string; refs: File[] }[] {
  const extra = (refs?.rows || []).some(row => row.length)
  const prompts = imageBatchPrompts(prompt, perLine)
  if (!extra && prompts.length <= 1) return []
  const rows = filledReferenceRows(refs)
  if (!prompts.length || !rows.length) return []
  return prompts.flatMap(text => rows.map(files => ({ prompt: text, refs: files })))
}

export function imageBatchEnabled(intent: string, settings?: ImageBatchSettings): boolean {
  return Boolean(settings?.perLine || imageBatchHasSources(intent, settings))
}

export function imageBatchHasSources(intent: string, settings?: ImageBatchSettings): boolean {
  return intent === 'edit' && Boolean(settings?.enabled)
}

export function imageBatchStatus(mode: string, intent: string, prompt: string, mask: unknown, settings?: ImageBatchSettings, refs?: ImageReferenceRows) {
  const separateEdits = imageBatchHasSources(intent, settings)
  const referenceJobs = mode === 'image' && !separateEdits
    ? imageReferenceJobs(prompt, settings?.perLine ?? false, refs)
    : []
  const batching = mode === 'image' && (imageBatchEnabled(intent, settings) || referenceJobs.length > 1)
  const count = separateEdits || !referenceJobs.length
    ? (batching ? imageBatchPairs(prompt, settings, intent === 'edit').length : 0)
    : referenceJobs.length
  const invalid = batching && (!count || count > MAX_IMAGE_BATCH_JOBS || (separateEdits && Boolean(mask)))
  return { batching, count, invalid }
}
