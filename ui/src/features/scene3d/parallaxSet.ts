// A parallax set: painted cutout layers stood across the camera's line of sight, behind and in front of the cast,
// so a camera that moves sees the place shift in depth. The far picture is the sky; the ground is a slab.
// A layer is tiled with mirrored copies of itself until it covers everything the camera sweeps over during the
// shot, so a turn never shows its edge; every layer sinks a little into the ground, so its pieces stand on it
// rather than float; the near layer stands on the floor too, so nothing is seen under it, and stays under the cast's
// feet. With ``scroll`` the mid layer and the ground slide past the cast at that speed (no near layer: it would
// flicker past): a character running on the spot runs through the place.
import type { Scene3DDocument, Scene3DSlot, Vec3 } from './types'
import { cameraPath, castPoints, type DioramaGround, type StyledGround } from './dioramaSet.ts'
import { groundColor, type GroundStyle } from './groundStyles.ts'

export interface ParallaxLayer { source: string; depth: 'mid' | 'near'; foot?: number }   // foot: share of the picture's height that is empty under its pieces
export interface ParallaxSet { layers: ParallaxLayer[]; ground?: DioramaGround | StyledGround; key?: string }
// scroll: metres per second the place slides to the camera's left (the cast runs to its right).
// groundStyle: the shot draws this ground style (groundStyles.ts), so the set's own ground slab is left out and the
// layers' pieces settle onto that floor, in its colour and grain.
export interface ParallaxOptions { scroll?: number; groundStyle?: GroundStyle }

const CUTOUT_HEIGHT = 2        // an image cutout is 2 m tall at scale 1 and stands on its position (imageCutout.ts)
const MODEL_HEIGHT = 1.7       // the ground slab is a model: fitGltf scales it to this height times its scale
const MID_BEHIND = 9           // metres the mid layer stands behind the furthest the cast goes from the camera
const NEAR_ALONG = 0.3         // the near layer stands this share of the way from the camera to what it looks at
const NEAR_CLEARANCE = 0.7     // a camera that comes closer than this to the near layer's plane would cross it
const SPREAD = 1.5             // layers are this much taller than the view at their distance, for the move
const NEAR_REACH = 0.4          // the near layer's picture reaches this share of the frame up from its bottom edge
const UNDER_FEET = 0.7          // ...and at most this share of the way from the frame's bottom up to the cast's feet
const SINK = 0.05              // share of a layer's height sunk under the ground, so its pieces stand on it
const LAYER_ASPECT = 1664 / 928   // the layers are drawn at this size (production_parallax.py)
const TILE_MARGIN = 1.1        // tiles cover this much more than the camera sweeps
const MAX_TILES = 9
const KEY_TOLERANCE = 0.2
const KEY_SOFTNESS = 0.12
const GROUND_MARGIN = 8
const GROUND_TILE = 3          // metres the ground picture covers before it repeats (diorama_set.GROUND_TILE)

type Pose = { eye: Vec3; look: Vec3 }

/** The set's ground and its layers for this shot's camera. */
export function stageParallaxSet(document: Scene3DDocument, set: ParallaxSet, options: ParallaxOptions = {}): Scene3DSlot[] {
  const path = cameraPath(document)
  const mid = path[Math.floor(path.length / 2)]
  const ahead = heading(mid)
  const centre: Vec3 = [mid.look[0], 0, mid.look[2]]
  const scroll = Number.isFinite(options.scroll) ? (options.scroll as number) : 0
  const slots: Scene3DSlot[] = []
  const reach = Math.max(MID_BEHIND, ...castPoints(document).map(point => along(point, centre, ahead))) + MID_BEHIND
  for (const layer of set.layers) {
    const slot = layer.depth === 'near' ? nearSlot(layer, document, path, mid, ahead, set.key, scroll, options.groundStyle)
      : midSlot(layer, document, path, mid, centre, ahead, reach, set.key, scroll, options.groundStyle)
    if (slot) slots.push(slot)
  }
  if (set.ground && 'source' in set.ground && !options.groundStyle) slots.unshift(groundSlot(set.ground, centre, ahead, reach + GROUND_MARGIN, scroll))
  return slots
}

/** Where the place slides on a scrolled shot, as a horizontal direction: to the camera's left at mid-shot. */
export function scrollDirection(document: Scene3DDocument): [number, number] {
  const path = cameraPath(document)
  const ahead = heading(path[Math.floor(path.length / 2)])
  return [ahead[2], -ahead[0]]
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

/** Half the width of the view at ``distance``, from the lens and the frame's shape. */
function halfViewWidth(document: Scene3DDocument, distance: number): number {
  const shape = document.width > 0 && document.height > 0 ? document.width / document.height : 16 / 9
  return distance * Math.tan((document.camera.fov * Math.PI) / 360) * shape
}

/** How many mirrored copies of a layer, side by side on its plane, cover every look the camera takes during the
 * shot: each step's line of sight is carried to the plane and widened by the view there. */
function tilesFor(document: Scene3DDocument, path: Pose[], at: Vec3, ahead: Vec3, height: number): number {
  const side: Vec3 = [-ahead[2], 0, ahead[0]]
  let span = 0
  for (const step of path) {
    const dx = step.look[0] - step.eye[0], dz = step.look[2] - step.eye[2]
    const closing = dx * ahead[0] + dz * ahead[2]
    const distance = -along(step.eye, at, ahead)
    if (!(closing > 1e-6) || !(distance > 0)) continue
    const t = distance / closing
    const hit: Vec3 = [step.eye[0] + dx * t, 0, step.eye[2] + dz * t]
    span = Math.max(span, Math.abs(along(hit, at, side)) + halfViewWidth(document, distance))
  }
  const tile = height * LAYER_ASPECT
  return Math.max(1, Math.min(MAX_TILES, Math.ceil((2 * span * TILE_MARGIN) / tile)))
}

/** A layer facing the camera, scaled to the view height it must cover, standing on the floor lowered by the
 * empty key colour under its pieces (``foot``) and sunk a little more, so the pieces stand on the ground. */
function layerSlot(layer: ParallaxLayer, at: Vec3, ahead: Vec3, height: number, key: string | undefined, tiles: number, scroll: number, ground?: GroundStyle): Scene3DSlot {
  const scale = height / CUTOUT_HEIGHT
  const bottom = -((layer.foot ?? 0) + SINK) * height
  const slot = {
    id: `set-layer-${layer.depth}`, slot: 'prop', media: 'image', surface: 'cutout', sourceUrl: layer.source, clip: null,
    position: [at[0], bottom, at[2]], rotationY: Math.atan2(-ahead[0], -ahead[2]), scale, grounded: false,
    imageLook: { unlit: true, colorKey: { color: key ?? '#ff00ff', tolerance: KEY_TOLERANCE, softness: KEY_SOFTNESS },
      settle: { floor: round((layer.foot ?? 0) + SINK), ...(ground ? { color: groundColor(ground), ground } : {}) }, ...(tiles > 1 ? { tiles } : {}) },
  } as Scene3DSlot
  if (scroll) slot.drift = round(scroll / (height * LAYER_ASPECT))
  return slot
}

function midSlot(layer: ParallaxLayer, document: Scene3DDocument, path: Pose[], pose: Pose, centre: Vec3, ahead: Vec3, reach: number, key: string | undefined, scroll: number, ground?: GroundStyle): Scene3DSlot {
  const at: Vec3 = [centre[0] + ahead[0] * reach, 0, centre[2] + ahead[2] * reach]
  const distance = Math.hypot(at[0] - pose.eye[0], at[2] - pose.eye[2])
  const height = viewHeight(document, distance)
  return layerSlot(layer, at, ahead, height, key, tilesFor(document, path, at, ahead, height), scroll, ground)
}

/** The near layer stands on the floor a short way in front of the camera, its picture reaching only the lower part of
 * the frame and staying under the cast's feet, so its pieces frame the bottom and the sides and never hide the cast.
 * None when the camera would cross it during the shot (an orbit, a crash zoom), when the cast's feet are out of the
 * frame (a close shot: any near piece would cover the body), or on a scrolled shot: a picture this close slides past
 * several times a second and its mirrored copies flicker. */
function nearSlot(layer: ParallaxLayer, document: Scene3DDocument, path: Pose[], pose: Pose, ahead: Vec3, key: string | undefined, scroll: number, ground?: GroundStyle): Scene3DSlot | null {
  if (scroll) return null
  const toLook = Math.hypot(pose.look[0] - pose.eye[0], pose.look[2] - pose.eye[2])
  const distance = toLook * NEAR_ALONG
  const at: Vec3 = [pose.eye[0] + ahead[0] * distance, 0, pose.eye[2] + ahead[2] * distance]
  if (path.some(step => along(step.eye, at, ahead) > -NEAR_CLEARANCE || along(step.look, at, ahead) < NEAR_CLEARANCE)) return null
  const half = distance * Math.tan((document.camera.fov * Math.PI) / 360)
  const sight = pose.eye[1] + (pose.look[1] - pose.eye[1]) * NEAR_ALONG
  const base = Math.max(0, sight - half)                          // the lowest the frame shows at the layer's plane
  const feet = feetLine(document, pose, ahead, distance)
  if (feet <= base) return null
  const reach = Math.min(sight + (2 * NEAR_REACH - 1) * half, base + (feet - base) * UNDER_FEET)   // its picture's top
  if (!(reach > 0.05)) return null                                // a camera this low sees nothing of a floor layer
  const height = reach / (1 - (layer.foot ?? 0) - SINK)
  return layerSlot(layer, at, ahead, height, key, tilesFor(document, path, at, ahead, height), scroll, ground)
}

/** The height at which the cast's lowest point (its feet) is seen through a plane ``distance`` ahead of the camera;
 * a cast member nearer than the plane is in front of the layer and cannot be hidden by it. */
function feetLine(document: Scene3DDocument, pose: Pose, ahead: Vec3, distance: number): number {
  let lowest = Infinity
  for (const point of castPoints(document)) {
    const away = along(point, pose.eye, ahead)
    if (away <= distance) continue
    lowest = Math.min(lowest, pose.eye[1] + (point[1] - pose.eye[1]) * (distance / away))
  }
  return lowest
}

/** The ground slab, turned to the camera's heading so a scroll runs along the view. */
function groundSlot(ground: DioramaGround, centre: Vec3, ahead: Vec3, reach: number, scroll: number): Scene3DSlot {
  const stretch = Math.max(1, reach / (ground.size / 2))
  const slot: Scene3DSlot = {
    id: 'set-ground', slot: 'prop', media: 'model3d', sourceUrl: ground.source, clip: null,
    position: [centre[0], 0, centre[2]], rotationY: scroll ? Math.atan2(-ahead[0], -ahead[2]) : 0, scale: (ground.height * stretch) / MODEL_HEIGHT, grounded: false,
  }
  if (scroll) slot.drift = round(scroll / ((ground.tile ?? GROUND_TILE) * stretch))   // the slab is stretched with its picture
  return slot
}

function round(value: number): number {
  return Math.round(value * 1e6) / 1e6
}
