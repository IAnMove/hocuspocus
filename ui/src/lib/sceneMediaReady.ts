import type { SceneLayer } from '../types'

/** Frame export must wait for image layers too, including the first React paint. */
export async function waitForSceneImages(root: HTMLElement | null, layers: SceneLayer[]) {
  const expected = layers.filter(layer => layer.visible && ['image', 'overlay'].includes(layer.type) && layer.source)
  if (!expected.length) return
  const deadline = Date.now() + 25000
  while (Date.now() < deadline) {
    const images = Array.from(root?.querySelectorAll<HTMLImageElement>('img[data-layer-id]') || [])
    const ready = expected.every(layer => images.some(img => img.dataset.layerId === layer.id && img.complete && img.naturalWidth > 0))
    if (ready) return
    await new Promise(resolve => setTimeout(resolve, 100))
  }
  throw new Error('Scene images did not load. Check their source files before exporting.')
}
