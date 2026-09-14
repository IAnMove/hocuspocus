import { DoubleSide, Mesh, MeshStandardMaterial, PlaneGeometry, type Object3D, type Texture } from 'three'
import type { Scene3DSlot } from './types'

/** A bottom-anchored image plane with real alpha occlusion and scene lighting. */
export function imageCutoutMesh(slot: Scene3DSlot, texture: Texture | null) {
  const image = texture?.image as { width?: number; height?: number } | undefined
  const aspect = image?.width && image.height ? image.width / image.height : 1
  const mesh = new Mesh(new PlaneGeometry(2 * aspect, 2), new MeshStandardMaterial({
    map: texture, color: texture ? 0xffffff : 0x243044, side: DoubleSide,
    transparent: true, alphaTest: .05, depthWrite: true, roughness: .9,
  }))
  poseImageCutout(mesh, slot)
  return mesh
}

export function poseImageCutout(root: Object3D, slot: Scene3DSlot) {
  const scale = Math.max(.05, slot.scale)
  root.position.set(slot.position[0], slot.position[1] + scale, slot.position[2])
  root.rotation.set(0, slot.rotationY, 0)
  root.scale.setScalar(scale)
}
