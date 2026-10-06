import { Euler, Object3D, Quaternion, Vector3 } from 'three'
import type { Vec3 } from './types.ts'

/** A prop carried in one whole hand. The offset is metres in that bone's local frame.
 *
 * `rotation` turns the prop in the hand: radians, Euler XYZ in the hand bone's frame, applied after the bone's own
 * rotation. Without it the prop takes the bone's rotation plus the slot's `rotationY` as a yaw (older documents). */
export type Scene3DHold = {
  carrier: string
  hand: 'left' | 'right'
  offset?: Vec3
  rotation?: Vec3
}

const HAND_BONE = { left: 'LeftHand', right: 'RightHand' } as const
const MAX_OFFSET = 2
export const MAX_HOLD_TURN = Math.PI * 2

export function parseHold(raw: unknown, slotId: string): Scene3DHold | undefined {
  if (!raw || typeof raw !== 'object') return undefined
  const value = raw as Partial<Scene3DHold>
  if (value.hand !== 'left' && value.hand !== 'right') return undefined
  if (typeof value.carrier !== 'string' || !value.carrier || value.carrier === slotId || value.carrier.length > 160) return undefined
  const offset = parseVec3(value.offset, MAX_OFFSET)
  const rotation = parseVec3(value.rotation, MAX_HOLD_TURN)
  return { carrier: value.carrier, hand: value.hand, ...(offset ? { offset } : {}), ...(rotation ? { rotation } : {}) }
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

const bonePosition = new Vector3()
const boneScale = new Vector3()

/** Put `prop` on the hand bone's world pose from this frame. The bone is read after it has been posed.
 * The bone's world matrix carries the carrier's scale, so its rotation is read by decomposing the matrix. */
export function followHand(prop: Object3D, bone: Object3D, offset: readonly [number, number, number], yaw: number,
  rotation?: readonly [number, number, number]) {
  bone.updateWorldMatrix(true, false)
  const point = new Vector3(offset[0], offset[1], offset[2]).applyMatrix4(bone.matrixWorld)
  const worldQuat = new Quaternion()
  bone.matrixWorld.decompose(bonePosition, worldQuat, boneScale)
  if (rotation) worldQuat.multiply(new Quaternion().setFromEuler(new Euler(rotation[0], rotation[1], rotation[2], 'XYZ')))
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
  if (yaw && !rotation) prop.rotateY(yaw)
  prop.updateMatrixWorld()
}

function isPrefixedHand(name: string, token: string) {
  return name.endsWith(`:${token}`) || name.endsWith(`_${token}`) || name === `mixamorig${token}`
}

function parseVec3(raw: unknown, limit: number): Vec3 | undefined {
  if (raw == null) return undefined
  if (!Array.isArray(raw) || raw.length !== 3 || !raw.every(item => typeof item === 'number' && Number.isFinite(item))) return undefined
  return raw.map(item => Math.min(limit, Math.max(-limit, item))) as unknown as Vec3
}
