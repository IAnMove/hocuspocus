// A metric box room: the camera and the cast share app/shared/room_box_camera.json with app/services/room_box.py.
// The open side is z = -depth/2. The camera sits at adult eye height just outside it and looks in. fitGltf scales a
// model by 1.7 / bbox height about the origin, so the room slot's scale is ceiling/1.7 and it is not grounded.
import frame from '../../../../app/shared/room_box_camera.json' with { type: 'json' }
import type { RoomBoxPaint } from './roomBoxRaster'
import { applyNamedLight } from './modifiers'
import type { Scene3DDocument, Scene3DSlot, Vec3 } from './types'

const MODEL_HEIGHT = 1.7
const PALETTE: [number, number, number][] = [[40, 110, 190], [190, 60, 70], [60, 150, 90], [160, 120, 40]]

export interface RoomBoxCharacter {
  x: number
  z: number
  heightM?: number
  color?: [number, number, number]
  source?: string
  id?: string
}

/** The camera of a plate room (`plate.camera` of the spec): the plate's own viewpoint and its lens shift. */
export interface RoomPlateCamera {
  eye: Vec3
  look: Vec3
  fov: number
  lensShift: number
}

export interface RoomBoxSpec {
  size: { w: number; d: number; h: number }
  door?: { wall: string; x: number; w: number; h: number } | null
  /** A plate room: the painted back wall, seen from this camera. */
  plate?: { camera: RoomPlateCamera }
  file?: string
  framing?: 'wide' | 'medium'
  characters?: RoomBoxCharacter[]
}

/** The same pose `room_box.camera_pose` returns. `wide` is the interior full-body frame. */
export function roomBoxCamera(depth: number, wide = true): { eye: Vec3; look: Vec3; fov: number } {
  const back = wide ? frame.wideBack : frame.mediumBack
  return {
    eye: [0, frame.eyeHeight, round4(-depth / 2 - back)],
    look: [0, frame.lookY, round4(depth * frame.lookZShare)],
    fov: wide ? frame.fovWide : frame.fovMedium,
  }
}

function round4(value: number): number {
  return Math.round(value * 10000) / 10000
}

/** Place the room and its cast. A document without this call is left alone. */
export function stageRoomBox(document: Scene3DDocument, spec: RoomBoxSpec): Scene3DDocument {
  const plate = spec.plate?.camera
  const pose = plate ?? roomBoxCamera(spec.size.d, spec.framing !== 'medium')
  const camera = { ...document.camera }
  delete camera.framing
  delete camera.lensShift
  document.camera = { ...camera, family: 'fixed', eye: [...pose.eye], look: [...pose.look], fov: pose.fov, ...(plate ? { lensShift: plate.lensShift } : {}) }
  applyNamedLight(document, 'soft')
  const characters = (spec.characters ?? []).map((person, index) => ({
    x: person.x,
    z: person.z,
    heightM: person.heightM ?? frame.defaultHeight,
    color: person.color ?? PALETTE[index % PALETTE.length],
  }))
  const paint: RoomBoxPaint = { size: { ...spec.size }, ...(spec.door ? { door: { ...spec.door } } : {}), characters }
  document.roomBox = paint
  if (spec.file) document.slots = [...document.slots.filter(slot => slot.id !== 'room-box'), roomSlot(spec.file, spec.size.h)]
  spec.characters?.forEach((person, index) => {
    if (person.source) document.slots = [...document.slots, characterSlot(person, index)]
  })
  // The room is its own floor: a cinema template with no environment must not fall back to the studio/backdrop floor.
  document.environment = { platform: false, bloom: 0, ...document.environment, reflectiveFloor: false, floorStyle: 'none' }
  return document
}

function roomSlot(file: string, height: number): Scene3DSlot {
  return {
    id: 'room-box', slot: 'prop', position: [0, 0, 0], rotationY: 0, scale: height / MODEL_HEIGHT,
    sourceUrl: file, media: 'model3d', clip: null, grounded: false,
  }
}

function characterSlot(person: RoomBoxCharacter, index: number): Scene3DSlot {
  const height = person.heightM ?? frame.defaultHeight
  const image = !person.source || /\.(png|webp|jpe?g)(\?|$)/i.test(person.source)
  return {
    id: person.id || `room-cast-${index + 1}`, slot: 'prop', position: [person.x, 0, person.z], rotationY: 0,
    scale: image ? height / 2 : height / MODEL_HEIGHT, sourceUrl: person.source || '', media: image ? 'image' : 'model3d',
    clip: null, grounded: true, imageLook: { grounded: true, shadow: 0.45 },
  }
}
