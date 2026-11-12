import type { Object3D } from 'three'
import type { Scene3DSlot } from './types'

function angle(value: number | undefined) {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0
}

/** X and Z are optional. A scene that only stored a yaw stays a yaw. */
export function slotTilt(slot: Pick<Scene3DSlot, 'rotationY' | 'rotationX' | 'rotationZ'>): [number, number, number] {
  return [angle(slot.rotationX), slot.rotationY, angle(slot.rotationZ)]
}

export function applySlotTilt(root: Object3D, slot: Pick<Scene3DSlot, 'rotationY' | 'rotationX' | 'rotationZ'>) {
  root.rotation.set(...slotTilt(slot))
}
