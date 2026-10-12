import { BoxGeometry, CylinderGeometry, Group, Mesh, MeshStandardMaterial, SphereGeometry, TorusGeometry, Vector3 } from 'three'
import { disposal } from './resources'
import type { MotionLabHandle } from './types'

export function musicMaterial(color: string, metalness = .4) {
  return new MeshStandardMaterial({ color, metalness, roughness: .28, emissive: color, emissiveIntensity: .02 })
}

export function musicMesh(parent: Group, name: string, geometry: BoxGeometry | CylinderGeometry | SphereGeometry | TorusGeometry,
  material: MeshStandardMaterial, position: [number, number, number]) {
  const mesh = new Mesh(geometry, material)
  mesh.name = name
  mesh.position.set(...position)
  mesh.castShadow = true
  mesh.receiveShadow = true
  parent.add(mesh)
  return mesh
}

export function musicBase(root: Group, radius: number) {
  const base = musicMesh(root, 'motion-music-plinth', new CylinderGeometry(radius, radius + .1, .24, 48),
    musicMaterial('#111b2c', .65), [0, -.12, 0])
  musicMesh(root, 'motion-music-base-ring', new TorusGeometry(radius - .12, .045, 8, 64),
    musicMaterial('#456179', .7), [0, .025, 0]).rotation.x = Math.PI / 2
  return base
}

const UP = new Vector3(0, 1, 0)
/** A thick connecting rod with endpoints supplied by the absolute mechanism clock. */
export function poseRod(rod: Mesh, start: Vector3, end: Vector3, direction: Vector3) {
  direction.subVectors(end, start)
  rod.position.copy(start).add(end).multiplyScalar(.5)
  rod.scale.y = direction.length()
  rod.quaternion.setFromUnitVectors(UP, direction.normalize())
}

export function musicHandle(root: Group, update: (seconds: number) => void): MotionLabHandle {
  const release = disposal(root)
  update(0)
  return { root, update, dispose: () => { root.removeFromParent(); release() } }
}
