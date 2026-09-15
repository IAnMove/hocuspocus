import { DoubleSide, Mesh, MeshBasicMaterial, MeshStandardMaterial, type Object3D, type Texture } from 'three'
import { applyPsxImageMaterial } from './imageLook'
import { imageWindowGeometry } from './imageWindows'
import { imageContactShadow, textureFootprint } from './imageGrounding'
import type { Scene3DSlot } from './types'

/** A bottom-anchored image plane with real alpha occlusion and scene lighting. */
export function imageCutoutMesh(slot: Scene3DSlot, texture: Texture | null) {
  const image = texture?.image as { width?: number; height?: number } | undefined
  const aspect = image?.width && image.height ? image.width / image.height : 1
  const options = { map: texture, color: slot.imageLook?.tint ?? (texture ? 0xffffff : 0x243044), side: DoubleSide,
    transparent: true, alphaTest: .05, depthWrite: true }
  const material = slot.imageLook?.unlit ? new MeshBasicMaterial(options) : new MeshStandardMaterial({ ...options, roughness: .9 })
  if (texture && slot.imageLook?.psx) applyPsxImageMaterial(material, texture, slot.imageLook.psx)
  const mesh = new Mesh(imageWindowGeometry(aspect, slot.imageLook?.windows), material)
  if (slot.imageLook?.grounded) {
    const foot = textureFootprint(texture)
    if (foot) {
      // Trim only the empty rows below the feet and retain original pixel scale.
      if (!slot.screen?.poseSequence) {
        mesh.geometry.scale(1, 1 - foot.bottom, 1).translate(0, -foot.bottom, 0)
        const uv = mesh.geometry.getAttribute('uv')
        for (let i = 0; i < uv.count; i++) uv.setY(i, foot.bottom + uv.getY(i) * (1 - foot.bottom))
      }
      if (slot.imageLook.shadow) mesh.add(imageContactShadow(foot, aspect, slot.imageLook.shadow))
    }
  }
  poseImageCutout(mesh, slot)
  return mesh
}

export function poseImageCutout(root: Object3D, slot: Scene3DSlot) {
  const scale = Math.max(.05, slot.scale)
  root.position.set(slot.position[0], slot.position[1] + scale, slot.position[2])
  root.rotation.set(0, slot.rotationY, 0)
  root.scale.setScalar(scale)
}
