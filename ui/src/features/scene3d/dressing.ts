import { workshopGroup } from './workshopSet.ts'
import { mediaSet } from './mediaSet.ts'
import { chaseGroup } from './chaseSet.ts'
import {
  BoxGeometry,
  Color,
  Group,
  IcosahedronGeometry,
  Mesh,
  MeshStandardMaterial,
  type Object3D,
} from 'three'
import { cafeGroup, type CafeMaps } from './cafeSet.ts'
import { citadelGroup } from './citadelSet.ts'
import { driveGroup, isDriveDressing, type DriveMaps } from './driveSet.ts'
import { actionGroup, applyActionAtmosphere, isActionDressing } from './actionSets.ts'
import { clearDrive } from './driveMotion.ts'
import type { GpuWorld } from './gpu.ts'
import type { Scene3DDressing } from './types.ts'

export function dropDressing(world: GpuWorld) {
  if (!world.dressing) return
  world.scene.remove(world.dressing)
  world.dressing.traverse(child => {
    if (!(child instanceof Mesh)) return
    child.geometry.dispose()
    const materials = Array.isArray(child.material) ? child.material : [child.material]
    for (const material of materials) {
      const mapped = material as MeshStandardMaterial
      mapped.map?.dispose()
      mapped.map = null
      material.dispose()
    }
  })
  world.dressing = null
}

function streetGroup(): Object3D {
  const root = new Group()
  const brick = new MeshStandardMaterial({ color: 0x3a3340, roughness: 0.88 })
  const glass = new MeshStandardMaterial({ color: 0x1a2438, roughness: 0.28, metalness: 0.55 })
  const blocks = [
    [-5.4, 2.2, -4.2, 1.6, 4.4, 1.6],
    [5.8, 3.1, -3.6, 1.8, 6.2, 1.8],
    [-6.2, 1.6, 3.4, 1.4, 3.2, 1.5],
    [6.4, 2.4, 4.1, 1.7, 4.8, 1.7],
    [0.4, 1.2, -7.2, 3.2, 2.4, 1.2],
    [-2.8, 0.9, 6.8, 2.2, 1.8, 1.1],
  ]
  for (const [x, y, z, w, h, d] of blocks) {
    const mesh = new Mesh(new BoxGeometry(w, h, d), Math.abs(x) > 5 ? glass : brick)
    mesh.position.set(x, y, z)
    root.add(mesh)
  }
  return root
}

function spaceGroup(): Object3D {
  const root = new Group()
  const rock = new MeshStandardMaterial({ color: new Color(0x2a2030), roughness: 0.95, emissive: 0x140818, emissiveIntensity: 0.35 })
  const spots = [[-3.2, 0.4, -2.4, 0.7], [3.6, 0.8, -1.6, 0.9], [1.2, 0.2, 3.1, 0.5], [-2.1, 1.4, 2.6, 0.4]]
  for (const [x, y, z, r] of spots) {
    const mesh = new Mesh(new IcosahedronGeometry(r, 0), rock)
    mesh.position.set(x, y, z)
    root.add(mesh)
  }
  return root
}

export function syncDressing(
  world: GpuWorld,
  kind: Scene3DDressing | undefined,
  maps?: { cafe?: CafeMaps; drive?: DriveMaps },
) {
  dropDressing(world)
  clearDrive(world)
  applyActionAtmosphere(world.scene, kind)
  world.floor.visible = kind !== 'space' && kind !== 'treadmill' && kind !== 'cafe' && !isDriveDressing(kind) && !isActionDressing(kind)
  world.floor.position.y = world.floor.visible ? 0 : -80
  if (kind === 'street') world.dressing = streetGroup()
  if (kind === 'retro-lab' || kind === 'observatory' || kind === 'broadcast-plaza') world.dressing = mediaSet(kind)
  if (kind === 'workshop') world.dressing = workshopGroup()
  if (kind === 'chase-street') world.dressing = chaseGroup()
  if (kind === 'citadel') world.dressing = citadelGroup()
  if (kind === 'space') world.dressing = spaceGroup()
  if (isActionDressing(kind)) world.dressing = actionGroup(kind)
  if (kind === 'cafe') world.dressing = cafeGroup(maps?.cafe ?? { facade: null, floor: null, back: null })
  if (isDriveDressing(kind)) {
    const built = driveGroup(kind, maps?.drive ?? { paint: null, glass: null, front: null, rear: null, road: null, building: null })
    world.dressing = built.root
    world.driveWheels = built.wheels
    world.driveRoad = built.roadMap
    world.driveMovers = built.movers
    world.driveSpeed = 0.2
  }
  if (world.dressing) world.scene.add(world.dressing)
}
