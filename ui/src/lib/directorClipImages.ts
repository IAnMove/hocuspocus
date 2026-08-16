import type { DirectorClipImage } from '../types'

export type DirectorClipImageEntry = string | null | undefined | {
  filename?: string | null
  clipIndex?: number | null
  index?: number | null
  shot_id?: string | null
  shotId?: string | null
  prompt?: string | null
  image_prompt?: string | null
}

export type DirectorClipImagePlan = {
  image_prompt?: string | null
  shot_id?: string | null
  shotId?: string | null
  index?: number | null
}

/**
 * Rehydrate Director images without letting missing entries shift their slot.
 * The source array is intentionally mapped before filtering so a failed image
 * at slot 0 cannot make the image for slot 1 appear in slot 0.
 */
export function mapDirectorClipImages(
  entries: DirectorClipImageEntry[],
  plans: DirectorClipImagePlan[] = [],
): DirectorClipImage[] {
  const planIndexByShotId = new Map<string, number>()
  const planByShotId = new Map<string, DirectorClipImagePlan>()
  plans.forEach((plan, index) => {
    const shotId = String(plan.shot_id || plan.shotId || '').trim()
    const planIndex = Number.isInteger(plan.index) && Number(plan.index) >= 0
      ? Number(plan.index)
      : index
    if (shotId && !planIndexByShotId.has(shotId)) {
      planIndexByShotId.set(shotId, planIndex)
      planByShotId.set(shotId, plan)
    }
  })

  return entries
    .map<DirectorClipImage | null>((raw, originalIndex) => {
      const source = typeof raw === 'string' ? { filename: raw } : (raw || {})
      const filename = typeof source.filename === 'string' ? source.filename.trim() : ''
      if (!filename) return null

      const shotId = String(source.shot_id || source.shotId || '').trim()
      const explicitIndex = Number.isInteger(source.clipIndex) && Number(source.clipIndex) >= 0
        ? Number(source.clipIndex)
        : Number.isInteger(source.index) && Number(source.index) >= 0
          ? Number(source.index)
          : null
      const stableShotIndex = shotId ? planIndexByShotId.get(shotId) : undefined
      const clipIndex = stableShotIndex
        ?? explicitIndex
        ?? originalIndex
      const plan = (shotId && planByShotId.get(shotId)) || plans[clipIndex]
      return {
        clipIndex,
        ...(shotId ? { shotId } : {}),
        prompt: source.prompt || source.image_prompt || plan?.image_prompt || '',
        file: null,
        filename,
      }
    })
    .filter((image): image is DirectorClipImage => image !== null)
}
