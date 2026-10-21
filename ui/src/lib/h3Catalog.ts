/** Observations from the paired 2026-09-06 benchmark, not hardware minima.
 * Source: docs/development/H3_BENCHMARK_2026-09-06.md.
 * GPU includes allocator reservations; PSS includes server children.
 */
export interface H3CatalogEntry {
  variant: 'pruned' | 'full' | 'fast' | 'distilled' | 'legacy'
  workflow: 'frames' | 'references'
  measured?: { ram: number; vram: number; profile: number; warmOnly?: boolean }
}

const entries: Record<string, H3CatalogEntry> = {
  minimax_h3: { variant: 'pruned', workflow: 'frames', measured: { ram: 34.4, vram: 21.5, profile: 3 } },
  minimax_h3_full: { variant: 'full', workflow: 'frames', measured: { ram: 37.1, vram: 21.2, profile: 3 } },
  minimax_h3_ref2va: { variant: 'pruned', workflow: 'references', measured: { ram: 38.3, vram: 21.6, profile: 3 } },
  minimax_h3_ref2va_full: { variant: 'full', workflow: 'references', measured: { ram: 42.1, vram: 21.3, profile: 3.5 } },
  // Cold process RAM sample was inconsistent and is excluded, not silently repaired.
  minimax_h3_fused_turbo: { variant: 'fast', workflow: 'frames', measured: { ram: 40.6, vram: 21.1, profile: 3, warmOnly: true } },
  minimax_h3_ref2va_fused_turbo: { variant: 'fast', workflow: 'references', measured: { ram: 39.9, vram: 21.4, profile: 3 } },
  minimax_h3_legacy: { variant: 'legacy', workflow: 'frames' },
  // Official FastVideo FastH3 (8-step DMD2, text to video). Not measured on this GPU yet.
  minimax_h3_fasth3_v2: { variant: 'distilled', workflow: 'frames' },
  minimax_h3_fasth3_trim: { variant: 'distilled', workflow: 'frames' },
}

export function h3CatalogEntry(modelType: string): H3CatalogEntry | undefined {
  return Object.hasOwn(entries, modelType) ? entries[modelType] : undefined
}

/** Frames-workflow ID for a variant. Series stores this and L1 maps strategy. */
export function h3FramesModelId(modelType: string): string {
  const entry = h3CatalogEntry(modelType)
  if (!entry || entry.variant === 'distilled') return modelType
  const match = Object.entries(entries).find(([, item]) => (
    item.variant === entry.variant && item.workflow === 'frames'
  ))
  return match?.[0] || modelType
}

export function h3FusedStepRange(modelType: string): { min: number; max: number; fallback: number } | null {
  const variant = h3CatalogEntry(modelType)?.variant
  if (variant === 'distilled') return { min: 8, max: 8, fallback: 8 }
  return variant === 'fast' ? { min: 4, max: 8, fallback: 4 } : null
}

export const SERIES_SETUP_VIDEO_MODELS = [
  { id: 'minimax_h3_legacy', labelKey: 'providers.h3Legacy' as const },
  { id: 'minimax_h3', labelKey: 'providers.h3Pruned' as const },
  { id: 'minimax_h3_full', labelKey: 'providers.h3Full' as const },
  { id: 'minimax_h3_fused_turbo', labelKey: 'providers.h3Fused' as const },
] as const

export function seriesSetupVideoUnavailableReason(modelType: string): string | null {
  if (h3CatalogEntry(modelType) || SERIES_SETUP_VIDEO_MODELS.some(item => item.id === modelType)) {
    return null
  }
  return 'unknown_model'
}

export function seriesStepsForVideoModel(modelType: string, currentSteps: number): number {
  const range = h3FusedStepRange(modelType)
  if (!range) return currentSteps
  return currentSteps < range.min || currentSteps > range.max ? range.fallback : currentSteps
}
