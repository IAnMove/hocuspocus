import { DoubleSide, Mesh, MeshBasicMaterial, Object3D, PlaneGeometry } from 'three'
import type { MediaScreen } from './mediaScreen.ts'

export { pickScreenAnchor } from './mediaScreen.ts'

export const SCREEN_PLANE_NAME = 'HOCUS_SCREEN_PLANE'
const attachedPlanes = new WeakMap<Object3D, Mesh>()

export function namedSceneNodes(root: Object3D): string[] {
  const names: string[] = []
  root.traverse(child => { if (child.name) names.push(child.name) })
  return [...new Set(names)]
}

export function namedSceneMeshes(root: Object3D): string[] {
  const names: string[] = []
  root.traverse(child => { if (child instanceof Mesh && child.name) names.push(child.name) })
  return [...new Set(names)]
}

export function findNamedNode(root: Object3D, name: string): Object3D | undefined {
  if (!name) return undefined
  const hits: Object3D[] = []
  root.traverse(child => { if (child.name === name) hits.push(child) })
  if (hits.length > 1) throw new Error('screen-anchor-ambiguous')
  return hits[0]
}

export function screenPlaneOffset(screen: MediaScreen): [number, number, number] {
  const offset = screen.offset
  if (!offset || offset.length !== 3) return [0, 0, 0]
  return offset.map(value => Number.isFinite(value) ? value : 0) as [number, number, number]
}

/** Parent a content plane to a named bone/node so it follows GLB animation (TV heads, sprite faces). */
export function attachScreenPlane(root: Object3D, screen: MediaScreen): Mesh {
  detachScreenPlane(root)
  const parent = findNamedNode(root, screen.anchor || screen.targetMesh)
  if (!parent) throw new Error('screen-anchor-missing')
  const mesh = new Mesh(
    new PlaneGeometry(screen.width, screen.height),
    new MeshBasicMaterial({ color: 0x10202c, toneMapped: false, side: DoubleSide }),
  )
  mesh.name = SCREEN_PLANE_NAME
  mesh.userData.hocusGeneratedScreenPlane = true
  const [x, y, z] = screenPlaneOffset(screen)
  mesh.position.set(x, y, z)
  mesh.rotation.set(screen.pitch ?? 0, screen.yaw ?? 0, screen.roll ?? 0)
  parent.add(mesh)
  attachedPlanes.set(root, mesh)
  return mesh
}

export function detachScreenPlane(root: Object3D, expected = attachedPlanes.get(root)) {
  const existing = attachedPlanes.get(root)
  if (!existing || existing !== expected) return
  attachedPlanes.delete(root)
  existing.removeFromParent()
  existing.geometry.dispose()
  const material = existing.material
  if (Array.isArray(material)) material.forEach(item => item.dispose())
  else material.dispose()
}

export function screenUsesPlane(screen: MediaScreen, standalone: boolean) {
  return !standalone && screen.mode === 'plane'
}

/** Runtime plane only — a GLB mesh that happens to reuse the generated name stays in speech catalogs. */
export function isGeneratedScreenPlane(object: Object3D) {
  return object.userData.hocusGeneratedScreenPlane === true
}
