import type { SceneLayerType } from '../types'

export type NarrativeAssetRole = 'hero' | 'plate' | 'prop' | 'foreground'
export type AssetSuitability = {
  level: 'ok' | 'notice' | 'warning'
  message: string
}

const isRasterPreview = (name: string) => /\.preview\.(?:png|jpe?g|webp)$/i.test(name)
const isOpaqueRaster = (name: string) => /\.(?:jpe?g)$/i.test(name)
const isLoopHinted = (name: string) => /(loop|panorama|seamless|tile)/i.test(name)

/**
 * Give the scene author a truthful, lightweight suitability signal before a
 * template is mounted. It intentionally never guesses alpha or rigging from
 * pixels: those properties need a real asset inspection pass later.
 */
export function assessNarrativeAsset(role: NarrativeAssetRole, type: SceneLayerType | undefined, name = ''): AssetSuitability {
  if (!name) return { level: 'notice', message: 'Choose an existing asset for this slot.' }
  if (role === 'hero' && type === 'image' && (isOpaqueRaster(name) || isRasterPreview(name))) {
    return { level: 'warning', message: 'This is an opaque rendered image, so its baked background will travel with the character. Prefer a GLB, transparent PNG/WebP, or isolated video.' }
  }
  if (role === 'plate' && type === 'model3d') return { level: 'warning', message: 'A 3D model is not a full-frame plate. Use an image/video background and keep this model as a prop or hero.' }
  if (role === 'plate' && type === 'image' && !isLoopHinted(name)) {
    return { level: 'notice', message: 'This plate has no loop marker. For travel shots, review it in Fondo infinito or use a seam cover.' }
  }
  if (role === 'foreground' && type === 'image' && isOpaqueRaster(name)) {
    return { level: 'notice', message: 'An opaque foreground can reveal a rectangular edge while it scrolls; transparent PNG/WebP is safer.' }
  }
  if (role === 'hero' && type === 'model3d') return { level: 'ok', message: 'GLB selected. Use a verified rig clip when the action needs real limb animation.' }
  return { level: 'ok', message: 'Suitable for this template slot.' }
}
