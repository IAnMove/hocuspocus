/** Render settings of a server export quality level (draft, final, master).

The server freezes them in the export plan. Draft is today's export: no supersampling
and no multisampled composer, so its frames stay byte-identical.
*/
export type ExportRenderQuality = { supersample: number; samples: number }

export const DRAFT_RENDER: ExportRenderQuality = { supersample: 1, samples: 0 }

/** WebGL2 guarantees at least 4096; the long side of a supersampled frame stays within 8192. */
export const MAX_SUPERSAMPLED_SIDE = 8192
/** The server plans 1.5x (final) or 2x (master); 4x is accepted for reference renders. */
export const MAX_SUPERSAMPLE = 4

/** The plan's render fields. Anything missing, invalid or out of range falls back to draft. */
export function renderQualityOf(plan: { supersample?: unknown; samples?: unknown } | null | undefined): ExportRenderQuality {
  const supersample = Number(plan?.supersample)
  const samples = Number(plan?.samples)
  return {
    supersample: Number.isFinite(supersample) ? Math.min(MAX_SUPERSAMPLE, Math.max(1, supersample)) : 1,
    samples: Number.isInteger(samples) && samples > 0 ? Math.min(8, samples) : 0,
  }
}

function even(value: number): number {
  const rounded = Math.max(2, Math.round(value))
  return rounded - (rounded % 2)
}

/** The size the stage renders at before the frame is scaled down to the output size. */
export function supersampledSize(size: { width: number; height: number }, supersample: number, maxSide = MAX_SUPERSAMPLED_SIDE) {
  const longest = Math.max(size.width, size.height, 1)
  const factor = Math.max(1, Math.min(supersample, maxSide / longest))
  if (factor === 1) return { width: size.width, height: size.height }
  return { width: even(size.width * factor), height: even(size.height * factor) }
}
