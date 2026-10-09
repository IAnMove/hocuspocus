// A diorama set: house blocks standing in a ring around the action on a tiled ground, under a painted sky.
// The pieces come from app/services/diorama_set.py; this lays them out around one shot's camera and cast.
import { cameraEyeAtTime, cameraLookAtTime } from './camera'
import { framingPose } from './framing'
import { slotPoseAtTime } from './performance'
import type { Scene3DDocument, Scene3DSlot, Vec3 } from './types'

export interface DioramaHouse { source: string; width: number; height: number }
export interface DioramaGround { source: string; height: number; size: number }
export interface DioramaSet { houses: DioramaHouse[]; ground?: DioramaGround; layout?: 'plaza' | 'open' }

const MIN_RADIUS = 7          // the plaza is at least this wide around what the camera looks at
const CLEARANCE = 2.5         // metres between the furthest camera or cast position and the facades
const ALLEY = 1.8             // every third house leaves an alley this wide, so the sky shows between roofs
const OPEN_ARC = 0.85         // radians either side of the back where an 'open' plaza looks out to a distant skyline
const SKYLINE = 3.5           // the skyline stands this many times further away than the plaza's fronts
const SAMPLES = 12
const MAX_HOUSES = 32
const MODEL_HEIGHT = 1.7      // fitGltf scales a model to this height times its scale
const HOUSE_DEPTH = 3         // diorama_set.DEPTH
const GROUND_MARGIN = 6
const SETBACKS = [0, 1.1, 0.4, 1.6, 0.7]   // metres each house stands back from the ring, so the fronts do not form one wall

type Pose = { eye: Vec3; look: Vec3 }
type Spot = { house: DioramaHouse; angle: number; distance: number }

/** Where the camera is and looks over the shot. A framed camera is anchored at the target's middle. */
export function cameraPath(document: Scene3DDocument): Pose[] {
  const { camera, duration, slots } = document
  const framing = camera.family === 'fixed' ? undefined : camera.framing
  const target = framing ? slots.find(slot => slot.id === framing.targetSlot) : undefined
  return Array.from({ length: SAMPLES + 1 }, (_, index) => {
    const seconds = (duration * index) / SAMPLES
    if (framing && target) {
      const anchor: Vec3 = [target.position[0], target.position[1] + 0.9 * target.scale, target.position[2]]
      const pose = framingPose(framing, anchor, target, seconds, duration)
      return { eye: pose.eye, look: pose.look }
    }
    return { eye: cameraEyeAtTime(camera, seconds, duration, slots), look: cameraLookAtTime(camera, seconds, duration, slots) }
  })
}

/** Every place the cast and props stand during the shot. */
function castPoints(document: Scene3DDocument): Vec3[] {
  const moving = document.slots.filter(slot => slot.slot !== 'background' && (!slot.surface || slot.surface === 'cutout'))
  return moving.flatMap(slot => Array.from({ length: SAMPLES + 1 }, (_, index) =>
    slotPoseAtTime(slot, (document.duration * index) / SAMPLES, document.duration).position))
}

/** Houses along an arc of the given half-width round ``middle``, the first in the middle, then alternating left and
 * right until the arc is full. ``first`` offsets the house, alley and setback pattern. */
function arcSpots(houses: readonly DioramaHouse[], radius: number, middle: number, half: number, first = 0): Spot[] {
  const arc = (width: number) => 2 * Math.atan(width / (2 * radius))
  const spots: Spot[] = []
  let [left, right] = [middle, middle]
  for (let index = first; index < first + MAX_HOUSES; index++) {
    const house = houses[index % houses.length]
    const span = arc(house.width)
    const alley = index % 3 === 2 ? arc(ALLEY) : 0
    const distance = radius + SETBACKS[index % SETBACKS.length]
    if (index === first) {
      if (span > 2 * half) break
      spots.push({ house, angle: middle, distance })
      ;[left, right] = [middle + span / 2, middle - span / 2]
    } else if (left - right + span + alley > 2 * half) {
      break
    } else if ((index - first) % 2 === 1) {
      spots.push({ house, angle: left + alley + span / 2, distance })
      left += alley + span
    } else {
      spots.push({ house, angle: right - alley - span / 2, distance })
      right -= alley + span
    }
  }
  return spots
}

/** A plaza closes the whole ring, starting behind the cast (opposite the camera at mid-shot). An 'open' plaza leaves
 * that back arc to a skyline of the same houses far away, so the view runs out to a horizon with depth in it. */
export function ringSpots(houses: readonly DioramaHouse[], radius: number, back: number, open: boolean): Spot[] {
  if (!open) return arcSpots(houses, radius, back, Math.PI)
  const skyline = arcSpots(houses, radius * SKYLINE, back, OPEN_ARC)
  return [...skyline, ...arcSpots(houses, radius, back + Math.PI, Math.PI - OPEN_ARC, skyline.length)]
}

function houseSlot(spot: Spot, index: number, centre: [number, number]): Scene3DSlot {
  const [ux, uz] = [Math.sin(spot.angle), Math.cos(spot.angle)]
  const distance = spot.distance
  // A house's front is its +z; turned to face the middle of the plaza, its block reaches outwards.
  return {
    id: `set-house-${index + 1}`, slot: 'prop', media: 'model3d', sourceUrl: spot.house.source, clip: null,
    position: [centre[0] + ux * distance, 0, centre[1] + uz * distance], rotationY: Math.atan2(-ux, -uz),
    scale: spot.house.height / MODEL_HEIGHT, grounded: false,
  }
}

function groundSlot(ground: DioramaGround, centre: [number, number], reach: number): Scene3DSlot {
  // The slab's top stays at y = 0 whatever its scale, so a plaza wider than the slab stretches it.
  const stretch = Math.max(1, reach / (ground.size / 2))
  return {
    id: 'set-ground', slot: 'prop', media: 'model3d', sourceUrl: ground.source, clip: null,
    position: [centre[0], 0, centre[1]], rotationY: 0, scale: (ground.height * stretch) / MODEL_HEIGHT, grounded: false,
  }
}

/** The set's ground and a plaza of houses around what the camera looks at, outside where it and the cast go.
 * The whole ring is built, so a later edit can move the camera anywhere in the plaza. */
export function stageDioramaSet(document: Scene3DDocument, set: DioramaSet): Scene3DSlot[] {
  const path = cameraPath(document)
  const mid = path[Math.floor(path.length / 2)]
  const centre: [number, number] = [mid.look[0], mid.look[2]]
  const points = [...path.map(pose => pose.eye), ...castPoints(document)]
  const reach = Math.max(0, ...points.map(point => Math.hypot(point[0] - centre[0], point[2] - centre[1])))
  const radius = Math.max(MIN_RADIUS, reach + CLEARANCE)
  const back = Math.atan2(mid.look[0] - mid.eye[0], mid.look[2] - mid.eye[2])
  const spots = ringSpots(set.houses, radius, back, set.layout === 'open')
  const houses = spots.map((spot, index) => houseSlot(spot, index, centre))
  const far = Math.max(radius, ...spots.map(spot => spot.distance)) + HOUSE_DEPTH + GROUND_MARGIN
  return set.ground ? [groundSlot(set.ground, centre, far), ...houses] : houses
}
