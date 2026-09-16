import { DoubleSide, Mesh, MeshBasicMaterial, MeshStandardMaterial, type Object3D, type Texture } from 'three'
import { applyPsxImageMaterial } from './imageLook'
import { applyImageColorKey } from './imageColorKey'
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
  if (texture && slot.imageLook?.colorKey) applyImageColorKey(material, slot.imageLook.colorKey)
  const mesh = new Mesh(imageWindowGeometry(aspect, slot.imageLook?.windows), material)
  groundImageCutout(mesh, slot, texture, aspect)
  poseImageCutout(mesh, slot)
  return mesh
}

function groundImageCutout(mesh: Mesh, slot: Scene3DSlot, texture: Texture | null, aspect: number) {
  if (slot.imageLook?.grounded) {
    const foot = textureFootprint(texture)
    if (foot) {
      // Trim only the empty rows below the feet and retain original pixel scale.
      if (slot.screen?.sourceUrl && !slot.screen.poseSequence) {
        // A moving matte needs the complete video canvas. Keep its UVs and
        // scale, translating the reference footline onto the ground instead.
        mesh.geometry.translate(0, -2 * foot.bottom, 0)
      } else if (!slot.screen?.poseSequence) {
        mesh.geometry.scale(1, 1 - foot.bottom, 1).translate(0, -foot.bottom, 0)
        const uv = mesh.geometry.getAttribute('uv')
        for (let i = 0; i < uv.count; i++) uv.setY(i, foot.bottom + uv.getY(i) * (1 - foot.bottom))
      }
      if (slot.imageLook.shadow) mesh.add(imageContactShadow(foot, aspect, slot.imageLook.shadow))
    }
  }
}

export function poseImageCutout(root: Object3D, slot: Scene3DSlot) {
  const scale = Math.max(.05, slot.scale)
  const roll = (slot.imageLook?.roll ?? 0) * Math.PI / 180
  root.rotation.set(0, slot.rotationY, roll, 'YXZ')
  // Rotate around the foot anchor, so tilting a cutout cannot lift its board/feet.
  root.position.set(0, scale, 0).applyEuler(root.rotation)
  root.position.x += slot.position[0]; root.position.y += slot.position[1]; root.position.z += slot.position[2]
  root.scale.setScalar(scale)
}
