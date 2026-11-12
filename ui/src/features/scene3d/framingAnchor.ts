import { Box3, Matrix4, Vector3, type Object3D, type SkinnedMesh } from 'three'
import type { Scene3DFraming, Vec3 } from './types'

/** The three points a camera may frame, in one space. */
type AnchorPoints = Record<Scene3DFraming['anchor'], Vector3>

const headBones = new WeakMap<Object3D, Object3D | null>()
const crownMarks = new WeakMap<Object3D, Object3D | null>()
/** Each mounted model's points at rest, in the model's own space. */
const restPoints = new WeakMap<Object3D, AnchorPoints>()
/** Where a rig marks its crown (HeadTop_End), the head point is at most this share of the figure's height below it.
 * A realistic rig's head bone already sits there (1.53 m under a 1.70 m crown); an auto-rig that put the bone at the
 * chest of a doll in a dress, or a big-headed figure, would otherwise frame the chest and cut the face at the top. */
export const HEAD_BELOW_CROWN = .15

/** The first bone whose name matches, preferring one a skin moves. A rigged rip keeps its former skeleton next to the
 * new one (`previous:head`), loose and still: framing that one aimed the camera beside the character. A loose bone is
 * used only when no skin has one. */
function skinnedFirst(cache: WeakMap<Object3D, Object3D | null>, root: Object3D, wanted: (node: Object3D) => boolean) {
  if (!cache.has(root)) {
    const skinned = new Set<Object3D>()
    root.traverse(node => {
      if ((node as SkinnedMesh).isSkinnedMesh) for (const bone of (node as SkinnedMesh).skeleton.bones) skinned.add(bone)
    })
    let moved: Object3D | null = null
    let loose: Object3D | null = null
    root.traverse(node => {
      if (!wanted(node)) return
      if (skinned.has(node)) moved ??= node
      else loose ??= node
    })
    cache.set(root, moved ?? loose)
  }
  return cache.get(root) ?? null
}

const headBone = (root: Object3D) => skinnedFirst(headBones, root, node => 'isBone' in node && /head$/i.test(node.name))
const crownMark = (root: Object3D) => skinnedFirst(crownMarks, root, node => /headtop(_end)?$/i.test(node.name))

/** The points of the model as it stands now, in world space: the head bone when there is one (raised toward a crown
 * mark far above it), else its bounding box. */
function posedPoints(root: Object3D): AnchorPoints {
  const box = new Box3().setFromObject(root, true)
  const origin = root.getWorldPosition(new Vector3())
  const center = box.isEmpty() ? origin.clone() : box.getCenter(new Vector3())
  const feet = box.isEmpty() ? origin.clone() : new Vector3(center.x, box.min.y, center.z)
  const bone = headBone(root)
  const head = bone ? bone.getWorldPosition(new Vector3())
    : box.isEmpty() ? origin.clone() : new Vector3(center.x, box.min.y + (box.max.y - box.min.y) * .86, center.z)
  const crown = bone && !box.isEmpty() ? crownMark(root) : null
  if (crown) head.y = Math.max(head.y, crown.getWorldPosition(new Vector3()).y - HEAD_BELOW_CROWN * (box.max.y - box.min.y))
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
