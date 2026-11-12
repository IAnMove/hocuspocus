import { BufferGeometry, Material, Mesh, Points, type Object3D } from 'three'

/** Own sets can share geometry/materials: release each resource exactly once, including Points. */
export function disposal(root: Object3D) {
  let disposed = false
  return () => {
    if (disposed) return
    disposed = true
    const geometries = new Set<BufferGeometry>(), materials = new Set<Material>()
    root.traverse(object => {
      if (!(object instanceof Mesh) && !(object instanceof Points)) return
      geometries.add(object.geometry)
      for (const material of Array.isArray(object.material) ? object.material : [object.material]) materials.add(material)
    })
    geometries.forEach(geometry => geometry.dispose())
    materials.forEach(material => material.dispose())
    root.clear()
  }
}

/** Index-addressed noise has the same result for a frame sampled out of order. */
export function seeded(seed: number, index: number): number {
  let hash = Math.imul(seed ^ (index + 1), 0x45d9f3b)
  hash = Math.imul(hash ^ (hash >>> 16), 0x45d9f3b)
  return ((hash ^ (hash >>> 16)) >>> 0) / 4294967296
}
