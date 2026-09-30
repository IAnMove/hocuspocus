import { Mesh, PCFSoftShadowMap } from 'three'
import type { GpuWorld } from '../gpu.ts'
import type { AtmosHandle } from './sets/clearing.ts'

const SKIP = new Set(['atmos-grass', 'atmos-mote', 'atmos-leaf', 'atmos-sky'])

function shadeSlots(world: GpuWorld) {
  for (const gpu of world.slots.values()) {
    gpu.root.traverse(child => {
      if (!(child instanceof Mesh)) return
      child.castShadow = true
      child.receiveShadow = true
    })
    if (gpu.contactShadow) gpu.contactShadow.visible = false
  }
}

export function prepareAtmosShadows(world: GpuWorld) {
  const light = world.dir
  const high = world.renderer.shadowMap.enabled && light.shadow.mapSize.x >= 2048
  world.renderer.shadowMap.enabled = true
  world.renderer.shadowMap.type = PCFSoftShadowMap
  light.castShadow = true
  world.floor.receiveShadow = true
  if (!high && light.shadow.mapSize.x !== 1024) light.shadow.mapSize.set(1024, 1024)
  light.shadow.bias = -0.00045
  light.shadow.normalBias = 0.035
  const cam = light.shadow.camera
  cam.near = 0.4
  cam.far = 52
  cam.left = -16
  cam.right = 16
  cam.top = 16
  cam.bottom = -16
  cam.updateProjectionMatrix()
  if (!light.target.parent) world.scene.add(light.target)
  light.target.position.set(0, 1, -6)
  world.dressing?.traverse(child => {
    if (!(child instanceof Mesh) || SKIP.has(child.name)) return
    child.castShadow = child.name !== 'atmos-ground'
    child.receiveShadow = true
  })
  shadeSlots(world)
}

/** Preview-only shadows. Export keeps the 2048 map that setWorldExportQuality installed.
 *  Camera tests paint a partial world that has no directional light. */
export function releaseAtmosShadows(world: GpuWorld) {
  const light = world.dir
  const shadowMap = world.renderer?.shadowMap
  if (!light?.shadow || !shadowMap) return
  if (light.shadow.mapSize.x >= 2048 || !shadowMap.enabled) return
  shadowMap.enabled = false
  light.castShadow = false
  if (world.floor) world.floor.receiveShadow = false
}

export function atmosHandle(world: GpuWorld): AtmosHandle | undefined {
  return world.dressing?.userData.atmos as AtmosHandle | undefined
}
