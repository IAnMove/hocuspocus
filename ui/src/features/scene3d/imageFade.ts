import type { Material, Object3D } from 'three'

/** An image layer's opacity over the shot: `from` until `start`, `to` after `end` (seconds), eased between.
 * A comic panel turns from the video frame into its printed twin as the camera pulls away, and back on the way in. */
export type ImageFade = { from: number; to: number; start: number; end: number }

const unit = (value: unknown, fallback: number) =>
  typeof value === 'number' && Number.isFinite(value) ? Math.max(0, Math.min(1, value)) : fallback
const seconds = (value: unknown) => typeof value === 'number' && Number.isFinite(value) ? Math.max(0, value) : null

export function parseImageFade(raw: unknown): ImageFade | undefined {
  if (!raw || typeof raw !== 'object') return undefined
  const value = raw as Partial<ImageFade>
  const start = seconds(value.start), end = seconds(value.end)
  if (start === null || end === null) return undefined
  return { from: unit(value.from, 1), to: unit(value.to, 1), start, end: Math.max(start, end) }
}

export function imageFadeAt(fade: ImageFade, at: number): number {
  if (at <= fade.start) return fade.from
  if (at >= fade.end) return fade.to
  const t = (at - fade.start) / (fade.end - fade.start)
  return fade.from + (fade.to - fade.from) * t * t * (3 - 2 * t)
}

type FadedSlot = { id: string; imageLook?: { fade?: ImageFade } }

/** Only textured materials fade, so a contact shadow under the picture keeps its own opacity. */
export function paintImageFades(gpus: ReadonlyMap<string, { root: Object3D }>, slots: readonly FadedSlot[], at: number) {
  for (const slot of slots) {
    const fade = slot.imageLook?.fade
    const root = fade ? gpus.get(slot.id)?.root : undefined
    if (!fade || !root) continue
    const opacity = imageFadeAt(fade, at)
    root.traverse(node => {
      const material = (node as { material?: Material | Material[] }).material
      for (const item of Array.isArray(material) ? material : material ? [material] : []) {
        if (!('map' in item) || !item.map) continue
        item.transparent = true
        item.opacity = opacity
      }
    })
  }
}
