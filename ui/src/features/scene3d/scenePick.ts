import { Object3D, Raycaster, Vector2 } from 'three'
import { worldSfxIdFromObject } from '../sceneFx/worldRuntime'
import type { GpuWorld } from './gpu'

export const WORLD_SFX_SELECT_PREFIX = 'wsfx:'

const raycaster = new Raycaster()
const pointer = new Vector2()

/** The slot or world effect under the pointer. An empty string is empty space. */
export function pickSceneId(world: GpuWorld, clientX: number, clientY: number): string {
  const canvas = world.renderer.domElement
  const rect = canvas.getBoundingClientRect()
  if (rect.width <= 0 || rect.height <= 0) return ''
  pointer.set((clientX - rect.left) / rect.width * 2 - 1, -(clientY - rect.top) / rect.height * 2 + 1)
  raycaster.setFromCamera(pointer, world.camera)
  const slotTargets = [...world.slots.entries()].filter(([, slot]) => slot.root.visible)
  const worldTargets = [...(world.worldSfx?.values() ?? [])].filter(item => item.root.visible).map(item => item.root)
  const hit = raycaster.intersectObjects([...worldTargets, ...slotTargets.map(([, slot]) => slot.root)], true)[0]
  if (!hit) return ''
  const worldId = worldSfxIdFromObject(hit.object)
  if (worldId) return WORLD_SFX_SELECT_PREFIX + worldId
  const selected = slotTargets.find(([, slot]) => contains(slot.root, hit.object))
  return selected?.[0] ?? ''
}

function contains(root: Object3D, object: Object3D) {
  let current: Object3D | null = object
  while (current) {
    if (current === root) return true
    current = current.parent
  }
  return false
}
