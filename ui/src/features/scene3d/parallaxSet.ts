// A parallax set: painted cutout layers stood across the camera's line of sight, behind and in front of the cast,
// so a camera that moves sees the place shift in depth. The far picture is the sky; the ground is a slab.
import type { Scene3DDocument, Scene3DSlot, Vec3 } from './types'
import { cameraPath, castPoints, type DioramaGround } from './dioramaSet.ts'

export interface ParallaxLayer { source: string; depth: 'mid' | 'near' }
export interface ParallaxSet { layers: ParallaxLayer[]; ground?: DioramaGround; key?: string }

const PLANE_HEIGHT = 1.125     // an image slot is a 2 x 1.125 m plane at scale 1 (gpu.ts), raised 2.2 m
const PLANE_LIFT = 2.2
const MODEL_HEIGHT = 1.7       // the ground slab is a model: fitGltf scales it to this height times its scale
const MID_BEHIND = 9           // metres the mid layer stands behind the furthest the cast goes from the camera
const NEAR_ALONG = 0.3         // the near layer stands this share of the way from the camera to what it looks at
const NEAR_CLEARANCE = 0.7     // a camera that comes closer than this to the near layer's plane would cross it
const SPREAD = 1.5             // layers are this much wider than the view at their distance, for the move
const KEY_TOLERANCE = 0.12
const KEY_SOFTNESS = 0.08
const GROUND_MARGIN = 8

type Pose = { eye: Vec3; look: Vec3 }

/** The set's ground and its layers for this shot's camera. */
export function stageParallaxSet(document: Scene3DDocument, set: ParallaxSet): Scene3DSlot[] {
  const path = cameraPath(document)
  const mid = path[Math.floor(path.length / 2)]
  const ahead = heading(mid)
  const centre: Vec3 = [mid.look[0], 0, mid.look[2]]
  const slots: Scene3DSlot[] = []
  const reach = Math.max(MID_BEHIND, ...castPoints(document).map(point => along(point, centre, ahead))) + MID_BEHIND
  for (const layer of set.layers) {
    const slot = layer.depth === 'near' ? nearSlot(layer, document, path, mid, ahead, set.key) : midSlot(layer, document, mid, centre, ahead, reach, set.key)
    if (slot) slots.push(slot)
  }
  if (set.ground) slots.unshift(groundSlot(set.ground, centre, reach + GROUND_MARGIN))
  return slots
}

/** The horizontal direction the camera looks along. */
function heading(pose: Pose): Vec3 {
  const dx = pose.look[0] - pose.eye[0]
  const dz = pose.look[2] - pose.eye[2]
  const length = Math.hypot(dx, dz) || 1
  return [dx / length, 0, dz / length]
}

/** How far a point lies from ``origin`` along ``direction``. */
function along(point: Vec3, origin: Vec3, direction: Vec3): number {
  return (point[0] - origin[0]) * direction[0] + (point[2] - origin[2]) * direction[2]
}

/** The height of the view at ``distance`` from the eye, widened for the move. */
function viewHeight(document: Scene3DDocument, distance: number): number {
  return 2 * distance * Math.tan((document.camera.fov * Math.PI) / 360) * SPREAD
}

/** A layer facing the camera, ``scale`` from the view height it must cover, its bottom on the floor unless ``centreY``
 * puts its middle on the line of sight. */
function layerSlot(layer: ParallaxLayer, at: Vec3, ahead: Vec3, scale: number, key: string | undefined, centreY?: number): Scene3DSlot {
  const middle = centreY ?? (PLANE_HEIGHT * scale) / 2
  return {
    id: `set-layer-${layer.depth}`, slot: 'prop', media: 'image', surface: 'cutout', sourceUrl: layer.source, clip: null,
    position: [at[0], middle - PLANE_LIFT, at[2]], rotationY: Math.atan2(-ahead[0], -ahead[2]), scale, grounded: false,
    imageLook: { unlit: true, colorKey: { color: key ?? '#00ff00', tolerance: KEY_TOLERANCE, softness: KEY_SOFTNESS } },
  } as Scene3DSlot
}

function midSlot(layer: ParallaxLayer, document: Scene3DDocument, pose: Pose, centre: Vec3, ahead: Vec3, reach: number, key?: string): Scene3DSlot {
  const at: Vec3 = [centre[0] + ahead[0] * reach, 0, centre[2] + ahead[2] * reach]
  const distance = Math.hypot(at[0] - pose.eye[0], at[2] - pose.eye[2])
  return layerSlot(layer, at, ahead, viewHeight(document, distance) / PLANE_HEIGHT, key)
}

/** The near layer stands a short way in front of the camera, centred on its line of sight; none when the camera
 * would cross it during the shot (an orbit, a crash zoom). */
function nearSlot(layer: ParallaxLayer, document: Scene3DDocument, path: Pose[], pose: Pose, ahead: Vec3, key?: string): Scene3DSlot | null {
  const toLook = Math.hypot(pose.look[0] - pose.eye[0], pose.look[2] - pose.eye[2])
  const distance = toLook * NEAR_ALONG
  const at: Vec3 = [pose.eye[0] + ahead[0] * distance, 0, pose.eye[2] + ahead[2] * distance]
  if (path.some(step => along(step.eye, at, ahead) > -NEAR_CLEARANCE || along(step.look, at, ahead) < NEAR_CLEARANCE)) return null
  const centreY = pose.eye[1] + (pose.look[1] - pose.eye[1]) * NEAR_ALONG
  return layerSlot(layer, at, ahead, viewHeight(document, distance) / PLANE_HEIGHT, key, centreY)
}

function groundSlot(ground: DioramaGround, centre: Vec3, reach: number): Scene3DSlot {
  const stretch = Math.max(1, reach / (ground.size / 2))
  return {
    id: 'set-ground', slot: 'prop', media: 'model3d', sourceUrl: ground.source, clip: null,
    position: [centre[0], 0, centre[2]], rotationY: 0, scale: (ground.height * stretch) / MODEL_HEIGHT, grounded: false,
  }
}
