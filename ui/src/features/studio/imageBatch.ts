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

export function imageBatchEnabled(intent: string, settings?: ImageBatchSettings): boolean {
  return Boolean(settings?.perLine || imageBatchHasSources(intent, settings))
}

export function imageBatchHasSources(intent: string, settings?: ImageBatchSettings): boolean {
  return intent === 'edit' && Boolean(settings?.enabled)
}

export function imageBatchStatus(mode: string, intent: string, prompt: string, mask: unknown, settings?: ImageBatchSettings) {
  const batching = mode === 'image' && imageBatchEnabled(intent, settings)
  const count = batching ? imageBatchPairs(prompt, settings, intent === 'edit').length : 0
  const invalid = batching && (!count || count > MAX_IMAGE_BATCH_JOBS || (imageBatchHasSources(intent, settings) && Boolean(mask)))
  return { batching, count, invalid }
}
