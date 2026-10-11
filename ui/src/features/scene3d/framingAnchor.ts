import { Box3, Matrix4, Vector3, type Object3D } from 'three'
import type { Scene3DFraming, Vec3 } from './types'

/** The three points a camera may frame, in one space. */
type AnchorPoints = Record<Scene3DFraming['anchor'], Vector3>

const headBones = new WeakMap<Object3D, Object3D | null>()
/** Each mounted model's points at rest, in the model's own space. */
const restPoints = new WeakMap<Object3D, AnchorPoints>()

function headBone(root: Object3D) {
  if (!headBones.has(root)) {
    let head: Object3D | null = null
    root.traverse(node => {
      if (!head && 'isBone' in node && /head$/i.test(node.name)) head = node
    })
    headBones.set(root, head)
  }
  return headBones.get(root) ?? null
}

/** The points of the model as it stands now, in world space: the head bone when there is one, else its bounding box. */
function posedPoints(root: Object3D): AnchorPoints {
  const box = new Box3().setFromObject(root, true)
  const origin = root.getWorldPosition(new Vector3())
  const center = box.isEmpty() ? origin.clone() : box.getCenter(new Vector3())
  const feet = box.isEmpty() ? origin.clone() : new Vector3(center.x, box.min.y, center.z)
  const bone = headBone(root)
  const head = bone ? bone.getWorldPosition(new Vector3())
    : box.isEmpty() ? origin.clone() : new Vector3(center.x, box.min.y + (box.max.y - box.min.y) * .86, center.z)
  return { center, feet, head }
}

/** Measure the model as it stands now and keep the points in its own space. Called when a model mounts, before any
 * clip has moved it, so a camera that frames it later follows where the slot puts the model, not the pose of the
 * clip: a raised arm no longer lifts the shot. A root never marked is measured the first time a camera frames it. */
export function markRestPose(root: Object3D): AnchorPoints {
  root.updateMatrixWorld(true)
  const toLocal = new Matrix4().copy(root.matrixWorld).invert()
  const posed = posedPoints(root)
  const rest = { center: posed.center.applyMatrix4(toLocal), feet: posed.feet.applyMatrix4(toLocal), head: posed.head.applyMatrix4(toLocal) }
  restPoints.set(root, rest)
  return rest
}

/** Evaluate after animation/grounding. The default `track: 'rest'` places the rest-pose point where the model stands
 * now; `'pose'` reads the animated head bone or bounding box each frame, for a close-up that must stay on a moving face. */
export function framingAnchor(root: Object3D, anchor: Scene3DFraming['anchor'], track: Scene3DFraming['track'] = 'rest'): Vec3 {
  root.updateMatrixWorld(true)
  if (track === 'pose') return posedPoints(root)[anchor].toArray() as unknown as Vec3
  const rest = restPoints.get(root) ?? markRestPose(root)
  return rest[anchor].clone().applyMatrix4(root.matrixWorld).toArray() as unknown as Vec3
}
