import { Material, Mesh, type Object3D } from 'three'
import type { Scene3DSlot } from './types'

/** Metres: keep the automatic ground below authored surfaces at Y=0. */
export const GROUND_DEPTH_GAP = .002

/** Depth bias resolves grazing-angle ties without thickening or moving assets. */
export function biasSurfaceDepth(material: Material, layer: number) {
  material.polygonOffset = true
  material.polygonOffsetFactor = layer > 0 ? -1 : 1
  material.polygonOffsetUnits = layer > 0 ? -layer : 2
}

export function stabilizeGroundDepth(ground: Mesh) {
  ground.position.y = -GROUND_DEPTH_GAP
  const materials = Array.isArray(ground.material) ? ground.material : [ground.material]
  for (const material of materials) biasSurfaceDepth(material, 0)
}

/** Document order breaks coplanar surface ties identically in preview/export. */
export function stabilizeSurfaceDepth(root: Object3D, layer: number) {
  root.traverse(child => {
    if (!(child instanceof Mesh)) return
    const materials = Array.isArray(child.material) ? child.material : [child.material]
    for (const material of materials) biasSurfaceDepth(material, layer)
  })
}

export function stabilizeSceneSurfaces(slots: readonly Scene3DSlot[], roots: ReadonlyMap<string, { root: Object3D }>) {
  let layer = 0
  for (const slot of slots) {
    if (slot.media !== 'image' || (slot.surface !== 'floor' && slot.surface !== 'wall')) continue
    layer += 1
    const root = roots.get(slot.id)?.root
    if (root) stabilizeSurfaceDepth(root, layer)
  }
}
