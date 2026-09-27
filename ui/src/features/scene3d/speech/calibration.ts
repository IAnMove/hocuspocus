import { Bone, Box3, Color, Mesh, MeshStandardMaterial, Raycaster, Vector3, type Object3D } from 'three'
import type { FacePlacement } from './types'
import { restFaceHit } from './faceCoordinates'
import { isGeneratedScreenPlane } from '../screenPlane'

export const FACE_PROFILES = ['generic', 'human_mira', 'elf_seren', 'orc_grog', 'goblin_zik'] as const
export type FaceProfile = typeof FACE_PROFILES[number]
export type PlacementMode = FaceProfile | 'bounds'
const PROFILES = {
  generic: [0, .27, .19, .21, .12, .8],
  human_mira: [-.22, .33, .19, .225, .12, .8],
  elf_seren: [.12, .24, .19, .205, .115, .8],
  orc_grog: [.055, .245, .22, .20, .115, 1.1],
  goblin_zik: [.02, .23, .20, .21, .13, .95],
} satisfies Record<FaceProfile, number[]>
export function faceMeshes(root: Object3D): Mesh[] {
  const meshes: Mesh[] = []
  root.traverse(node => { if (node instanceof Mesh && !isGeneratedScreenPlane(node)) meshes.push(node) })
  return meshes
}
/** Editable starting point in ORIGINAL vertex coordinates, also for GLBs without a rig. */
export function manualFace(root: Object3D): FacePlacement | undefined {
  const meshes = faceMeshes(root)
  const supported = meshes.filter(m => !Array.isArray(m.material) && m.material instanceof MeshStandardMaterial && m.geometry.attributes.position)
  const mesh = supported.find(m => /head|face/i.test(m.name)) ?? supported.sort((a, b) => b.geometry.attributes.position.count - a.geometry.attributes.position.count)[0]
  if (!mesh) return undefined
  mesh.geometry.computeBoundingBox()
  const box = mesh.geometry.boundingBox!
  const size = box.getSize(new Vector3()), mid = box.getCenter(new Vector3())
  if (box.isEmpty() || size.y <= 0 || size.x <= 0) return undefined
  const headOnly = /head|face/i.test(mesh.name), width = Math.max(.0001, size.x * (headOnly ? .3 : .12))
  const height = Math.max(.0001, size.y * (headOnly ? .16 : .045)), y = box.min.y + size.y * (headOnly ? .35 : .85)
  const skin = (mesh.material as MeshStandardMaterial).color.toArray() as [number, number, number]
  return { meshIndex: meshes.indexOf(mesh), center: [mid.x, y, box.max.z], size: [width, height], skin,
    eyes: { left: [mid.x - width, y + height * 2, box.max.z], right: [mid.x + width, y + height * 2, box.max.z],
      size: [width * .6, height * .6], skinLeft: [...skin], skinRight: [...skin] } }
}
/** Called once on the original GLTF before the scene normalizes or animates it. */
export function estimateFace(root: Object3D, profile: FaceProfile): FacePlacement | undefined {
  root.updateMatrixWorld(true)
  const meshes = faceMeshes(root)
  const mesh = [...meshes].filter(m => !Array.isArray(m.material) && m.material instanceof MeshStandardMaterial && m.geometry.attributes.uv)
    .sort((a, b) => b.geometry.attributes.position.count - a.geometry.attributes.position.count)[0]
  if (!mesh) return undefined
  const material = mesh.material as MeshStandardMaterial
  const head = root.getObjectByName('Head') ?? root.getObjectByName('mixamorigHead')
  // Generic placement is deliberately opt-in; a head landmark is needed.
  if (!(head instanceof Bone)) return undefined
  const box = new Box3().setFromObject(root), size = box.getSize(new Vector3())
  const headPos = head.getWorldPosition(new Vector3())
  const headEnd = root.getObjectByName('head_end') ?? root.getObjectByName('Head_end')
  const hh = Math.max(size.y * .12, (headEnd?.getWorldPosition(new Vector3()).y ?? box.max.y) - headPos.y)
  const [factor, rise, spacing, ew, eh, widthScale] = PROFILES[profile]
  const ray = new Raycaster()
  const hit = (x: number, y: number) => {
    ray.set(new Vector3(x, y, box.max.z + size.z + 1), new Vector3(0, 0, -1))
    return ray.intersectObject(mesh, false)[0]
  }
  let pixels: ImageData | undefined
  try {
    const map = material.map, img = map?.image as CanvasImageSource & { width: number; height: number } | undefined
    if (img) {
      const canvas = document.createElement('canvas')
      canvas.width = img.width; canvas.height = img.height
      const ctx = canvas.getContext('2d')!
      ctx.drawImage(img, 0, 0); pixels = ctx.getImageData(0, 0, canvas.width, canvas.height)
    }
  } catch { /* Cross-origin texture: leave an editable neutral skin color. */ }
  const skinAt = (x: number, y: number): [number, number, number] => {
    const uv = hit(x, y)?.uv
    if (!uv || !pixels || !material.map) return new Color('#c49378').toArray() as [number, number, number]
    material.map.transformUv(uv)
    const at = (Math.min(pixels.height - 1, Math.floor(uv.y * pixels.height)) * pixels.width + Math.min(pixels.width - 1, Math.floor(uv.x * pixels.width))) * 4
    return new Color().setRGB(pixels.data[at] / 255, pixels.data[at + 1] / 255, pixels.data[at + 2] / 255, 'srgb').toArray() as [number, number, number]
  }
  const y = headPos.y + hh * factor, x = headPos.x, centerHit = hit(x, y)
  const center = centerHit && restFaceHit(centerHit)
  if (!center) return undefined
  const point = (px: number, py: number) => {
    const intersection = hit(px, py), rest = intersection && restFaceHit(intersection)
    return (rest?.point ?? center.point.clone().add(new Vector3((px - x) * center.scale, (py - y) * center.scale, 0))).toArray()
  }
  const localHeight = hh * center.scale
  const eyeY = y + hh * rise, eyeX = hh * spacing
  return { meshIndex: meshes.indexOf(mesh), center: center.point.toArray(), size: [localHeight * .49 * widthScale, localHeight * .36 * .85],
    skin: skinAt(x + hh * .49 * .48, y + hh * .36 * .3),
    eyes: { left: point(x - eyeX, eyeY), right: point(x + eyeX, eyeY), size: [localHeight * ew, localHeight * eh],
      skinLeft: skinAt(x - eyeX + hh * ew * .85, eyeY - hh * eh * 1.05),
      skinRight: skinAt(x + eyeX + hh * ew * .85, eyeY - hh * eh * 1.05) } }
}
