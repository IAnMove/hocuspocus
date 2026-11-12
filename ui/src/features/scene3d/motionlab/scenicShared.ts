import { BoxGeometry, CylinderGeometry, Group, Mesh, MeshStandardMaterial, SphereGeometry, TorusGeometry, Vector3,
  type BufferGeometry, type Material, type MeshStandardMaterialParameters } from 'three'
import { disposal } from './resources'

type Triple = [number, number, number]
const UP = new Vector3(0, 1, 0)

/** Each set owns its resources. Repeated solid primitives share geometry only inside this builder. */
export class ScenicBuilder {
  readonly root = new Group()
  private geometries = new Map<string, BufferGeometry>()
  private release = disposal(this.root)
  constructor(name: string) { this.root.name = name }
  dispose = () => { this.release(); this.geometries.clear() }
  group(name: string, parent = this.root): Group {
    const group = new Group(); group.name = name; parent.add(group); return group
  }
  material(color: string | number, options: MeshStandardMaterialParameters = {}): MeshStandardMaterial {
    return new MeshStandardMaterial({ color, roughness: .62, metalness: .08, ...options })
  }
  private geometry(key: string, create: () => BufferGeometry) {
    if (!this.geometries.has(key)) this.geometries.set(key, create())
    return this.geometries.get(key)!
  }
  private mesh(name: string, geometry: BufferGeometry, position: Triple, material: Material, parent: Group): Mesh {
    const mesh = new Mesh(geometry, material)
    mesh.name = name; mesh.position.set(...position); mesh.castShadow = true; mesh.receiveShadow = true
    parent.add(mesh); return mesh
  }
  box(name: string, size: Triple, position: Triple, material: Material, parent = this.root): Mesh {
    const mesh = this.mesh(name, this.geometry('box', () => new BoxGeometry(1, 1, 1)), position, material, parent)
    mesh.scale.set(...size); return mesh
  }
  ellipsoid(name: string, size: Triple, position: Triple, material: Material, parent = this.root): Mesh {
    const mesh = this.mesh(name, this.geometry('sphere', () => new SphereGeometry(.5, 16, 10)), position, material, parent)
    mesh.scale.set(...size); return mesh
  }
  cylinder(name: string, top: number, bottom: number, height: number, position: Triple, material: Material, parent = this.root): Mesh {
    return this.mesh(name, this.geometry(`cylinder:${top}:${bottom}:${height}`, () => new CylinderGeometry(top, bottom, height, 20)), position, material, parent)
  }
  torus(name: string, radius: number, tube: number, position: Triple, material: Material, parent = this.root): Mesh {
    return this.mesh(name, this.geometry(`torus:${radius}:${tube}`, () => new TorusGeometry(radius, tube, 8, 32)), position, material, parent)
  }
  beam(name: string, from: Triple, to: Triple, radius: number, material: Material, parent = this.root): Mesh {
    const a = new Vector3(...from), b = new Vector3(...to), direction = b.clone().sub(a)
    const midpoint = a.clone().add(b).multiplyScalar(.5).toArray() as Triple
    const beam = this.cylinder(name, radius, radius, direction.length(), midpoint, material, parent)
    beam.quaternion.setFromUnitVectors(UP, direction.normalize()); return beam
  }
}

export const wrap = (value: number, length: number): number => ((value % length) + length) % length
export const smooth = (value: number): number => { const x = Math.max(0, Math.min(1, value)); return x * x * (3 - 2 * x) }
export const clock = (seconds: number, speed: number): number => (Number.isFinite(seconds) ? Math.max(0, seconds) : 0) * speed
