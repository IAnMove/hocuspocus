import { Object3D, Quaternion, Vector3 } from 'three'
import type { Vec3 } from './types.ts'

/** A prop carried in one whole hand. The offset is metres in that bone's local frame. */
export type Scene3DHold = {
  carrier: string
  hand: 'left' | 'right'
  offset?: Vec3
}

const HAND_BONE = { left: 'LeftHand', right: 'RightHand' } as const
const MAX_OFFSET = 2

export function parseHold(raw: unknown, slotId: string): Scene3DHold | undefined {
  if (!raw || typeof raw !== 'object') return undefined
  const value = raw as Partial<Scene3DHold>
  if (value.hand !== 'left' && value.hand !== 'right') return undefined
  if (typeof value.carrier !== 'string' || !value.carrier || value.carrier === slotId || value.carrier.length > 160) return undefined
  const offset = parseOffset(value.offset)
  return offset ? { carrier: value.carrier, hand: value.hand, offset } : { carrier: value.carrier, hand: value.hand }
}

/** The whole hand bone. A finger such as LeftHandIndex1 is never a grip. */
export function findHandBone(root: Object3D, hand: 'left' | 'right'): Object3D | undefined {
  const token = HAND_BONE[hand]
  let exact: Object3D | undefined
  let prefixed: Object3D | undefined
  root.traverse(child => {
    if (child.name === token) exact = child
    else if (!prefixed && isPrefixedHand(child.name, token)) prefixed = child
  })
  return exact ?? prefixed
}

/** Put `prop` on the hand bone's world pose from this frame. The bone is read after it has been posed. */
export function followHand(prop: Object3D, bone: Object3D, offset: readonly [number, number, number], yaw: number) {
  bone.updateWorldMatrix(true, false)
  const point = new Vector3(offset[0], offset[1], offset[2]).applyMatrix4(bone.matrixWorld)
  const worldQuat = new Quaternion().setFromRotationMatrix(bone.matrixWorld)
  const parent = prop.parent
  if (parent) {
    parent.updateWorldMatrix(true, false)
    prop.position.copy(parent.worldToLocal(point))
    const parentQuat = parent.getWorldQuaternion(new Quaternion())
    prop.quaternion.copy(parentQuat.invert()).multiply(worldQuat)
  } else {
    prop.position.copy(point)
    prop.quaternion.copy(worldQuat)
  }
  if (yaw) prop.rotateY(yaw)
  prop.updateMatrixWorld()
}

function isPrefixedHand(name: string, token: string) {
  return name.endsWith(`:${token}`) || name.endsWith(`_${token}`) || name === `mixamorig${token}`
}

function parseOffset(raw: unknown): Vec3 | undefined {
  if (raw == null) return undefined
  if (!Array.isArray(raw) || raw.length !== 3 || !raw.every(item => typeof item === 'number' && Number.isFinite(item))) return undefined
  return raw.map(item => Math.min(MAX_OFFSET, Math.max(-MAX_OFFSET, item))) as unknown as Vec3
}
