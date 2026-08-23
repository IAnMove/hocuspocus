export const LLM_ACTIVITY_PREVIEW_LIMIT = 400

/** One bounded, whitespace-normalized tail for live UI state only. */
export function llmActivityPreview(value: unknown, limit = LLM_ACTIVITY_PREVIEW_LIMIT): string {
  const normalized = String(value || '').replace(/\s+/g, ' ').trim()
  const maximum = Math.max(0, Math.floor(limit))
  if (normalized.length <= maximum) return normalized
  if (maximum <= 1) return maximum ? normalized.slice(-maximum) : ''
  return `…${normalized.slice(-(maximum - 1))}`
}
