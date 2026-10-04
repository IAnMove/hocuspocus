import { Color, Fog, Material, Mesh, NearestFilter, Scene, Texture } from 'three'
import type { Scene3DDocument } from './types'
import { defaultPixelWorld } from './pixel/pixelWorld'

type ShadedMaterial = Material & { flatShading?: boolean; map?: Texture | null }
const shading = new WeakMap<Material, boolean>()
const filtering = new WeakMap<Texture, { min: Texture['minFilter']; mag: Texture['magFilter'] }>()
const fogs = new WeakMap<Scene, { original: Scene['fog']; retro: Fog }>()

/** Reuse the native whole-frame pixel pass at an effective 240-pixel height. */
export function withN64Look(document: Scene3DDocument): Scene3DDocument {
  if (document.renderLook !== 'n64') return document
  return {
    ...document,
    environment: { reflectiveFloor: false, platform: false, ...document.environment, bloom: 0 },
    pixelWorld: { ...defaultPixelWorld(), palettes: ['noon'], meteors: 0, screenGlow: 0,
      ...document.pixelWorld, pixelSize: 3, levels: 32, dither: 0 },
  }
}

function materialLook(material: ShadedMaterial, enabled: boolean) {
  if (typeof material.flatShading === 'boolean') {
    if (enabled && !shading.has(material)) shading.set(material, material.flatShading)
    const desired = enabled ? true : shading.get(material)
    if (desired !== undefined && desired !== material.flatShading) {
      material.flatShading = desired
      material.needsUpdate = true
    }
    if (!enabled) shading.delete(material)
  }
  const texture = material.map
  if (!texture) return
  if (enabled && !filtering.has(texture)) filtering.set(texture, { min: texture.minFilter, mag: texture.magFilter })
  const original = filtering.get(texture)
  if (enabled || original) {
    const min = enabled ? NearestFilter : original!.min
    const mag = enabled ? NearestFilter : original!.mag
    if (texture.minFilter !== min || texture.magFilter !== mag) {
      texture.minFilter = min
      texture.magFilter = mag
      texture.needsUpdate = true
    }
  }
  if (!enabled) filtering.delete(texture)
}

/** Apply after native scenery/atmosphere sync; preserve authored styles on disable. */
export function applyN64Look(scene: Scene, enabled: boolean) {
  if (!enabled && !fogs.has(scene)) return
  scene.traverse(object => {
    if (!(object instanceof Mesh)) return
    const materials = Array.isArray(object.material) ? object.material : [object.material]
    for (const material of materials) materialLook(material, enabled)
  })
  if (enabled) {
    let state = fogs.get(scene)
    if (!state) {
      state = { original: scene.fog, retro: new Fog('#a0bdca', 4, 28) }
      fogs.set(scene, state)
    }
    if (scene.fog !== state.retro) state.original = scene.fog
    if (scene.background instanceof Color) state.retro.color.copy(scene.background)
    scene.fog = state.retro
  } else {
    const state = fogs.get(scene)
    if (state && scene.fog === state.retro) scene.fog = state.original
    fogs.delete(scene)
  }
}
