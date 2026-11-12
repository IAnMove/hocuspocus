// CPU picture of a box room. The floor is the y = 0 plane, the door is a slab of its real height and each
// character is a flat quad from the floor to heightM. Projection is projectPoint, the same one the rest of the
// preview uses, so a foot at y = 0 lands on the floor the pixels already painted.
import { projectPoint, vecCross, vecLength, vecNormalize, vecScale, vecSub } from './camera'
import type { Scene3DDocument, Vec3 } from './types'

type SoftwareFrame = { width: number; height: number; pixels: Uint8Array }

export type RoomBoxPaint = {
  size: { w: number; d: number; h: number }
  /** A plate room has none: its door is in the picture. */
  door?: { wall: string; x: number; w: number; h: number }
  characters: { x: number; z: number; heightM: number; color: [number, number, number] }[]
}

const DOOR: [number, number, number] = [176, 78, 36]
const FLOOR_A: [number, number, number] = [196, 164, 112]
const FLOOR_B: [number, number, number] = [148, 108, 68]
const CHECK = 0.5

type Point = { x: number; y: number }

/** Paint the room over `frame` and return whether this document is a box room. */
export function paintRoomBox(frame: SoftwareFrame, document: Scene3DDocument, eye: Vec3, look: Vec3, fov: number, aspect: number): boolean {
  const box = document.roomBox
  if (!box) return false
  paintFloor(frame, box, eye, look, fov, aspect)
  if (box.door) fillWorldQuad(frame, doorCorners(box.door, box.size), DOOR, eye, look, fov, aspect)
  const people = [...box.characters].sort((a, b) => b.z - a.z)
  for (const person of people) fillWorldQuad(frame, characterCorners(person), person.color, eye, look, fov, aspect)
  return true
}

/** A frame of `width` pixels. The software preview stays at 160; the proof uses a wider frame of this same painter. */
export function renderRoomBoxFrame(document: Scene3DDocument, width = 960): SoftwareFrame {
  const height = Math.max(1, Math.round(width * document.height / Math.max(1, document.width)))
  const pixels = new Uint8Array(width * height * 4)
  pixels.fill(18)
  for (let i = 3; i < pixels.length; i += 4) pixels[i] = 255
  const frame = { width, height, pixels }
  paintRoomBox(frame, document, document.camera.eye, document.camera.look, document.camera.fov, width / height)
  return frame
}

function paintFloor(frame: SoftwareFrame, box: RoomBoxPaint, eye: Vec3, look: Vec3, fov: number, aspect: number) {
  const { forward, right, up } = basis(eye, look)
  const focal = 1 / Math.tan((fov * Math.PI) / 360)
  const { w, d } = box.size
  for (let y = 0; y < frame.height; y += 1) {
    for (let x = 0; x < frame.width; x += 1) {
      const ndcX = ((x + 0.5) / frame.width) * 2 - 1
      const ndcY = 1 - ((y + 0.5) / frame.height) * 2
      const dir = vecAdd(forward, vecAdd(vecScale(right, (ndcX * aspect) / focal), vecScale(up, ndcY / focal)))
      if (Math.abs(dir[1]) < 1e-8) continue
      const t = -eye[1] / dir[1]
      if (t <= 1e-4) continue
      const hitX = eye[0] + t * dir[0]
      const hitZ = eye[2] + t * dir[2]
      if (Math.abs(hitX) > w / 2 || Math.abs(hitZ) > d / 2) continue
      const check = (Math.floor((hitX + 100) / CHECK) + Math.floor((hitZ + 100) / CHECK)) & 1
      put(frame, x, y, check ? FLOOR_A : FLOOR_B)
    }
  }
}

function basis(eye: Vec3, look: Vec3) {
  const forward = vecNormalize(vecSub(look, eye))
  // right = forward × up. This camera looks toward +z, so right is world −x and a +x point lands on the left.
  const crossed = vecCross(forward, [0, 1, 0])
  const right = vecLength(crossed) < 1e-6 ? [1, 0, 0] as Vec3 : vecNormalize(crossed)
  const up = vecNormalize(vecCross(right, forward))
  return { forward, right, up }
}

function vecAdd(a: Vec3, b: Vec3): Vec3 {
  return [a[0] + b[0], a[1] + b[1], a[2] + b[2]]
}

function doorCorners(door: NonNullable<RoomBoxPaint['door']>, size: RoomBoxPaint['size']): Vec3[] {
  const { w, d } = size
  const half = door.w / 2
  if (door.wall === 'left' || door.wall === 'right') {
    const x = door.wall === 'left' ? -w / 2 + 0.02 : w / 2 - 0.02
    return [[x, 0, door.x - half], [x, 0, door.x + half], [x, door.h, door.x + half], [x, door.h, door.x - half]]
  }
  const z = d / 2 - 0.02
  return [[door.x - half, 0, z], [door.x + half, 0, z], [door.x + half, door.h, z], [door.x - half, door.h, z]]
}

function characterCorners(person: RoomBoxPaint['characters'][number]): Vec3[] {
  const half = Math.max(0.22, person.heightM * 0.18)
  return [
    [person.x - half, 0, person.z], [person.x + half, 0, person.z],
    [person.x + half, person.heightM, person.z], [person.x - half, person.heightM, person.z],
  ]
}

function fillWorldQuad(frame: SoftwareFrame, corners: Vec3[], rgb: [number, number, number], eye: Vec3, look: Vec3, fov: number, aspect: number) {
  const projected = corners.map(corner => projectPoint(corner, eye, look, fov, aspect))
  if (projected.some(point => !point)) return
  const points = projected.map(point => ({ x: point!.x * frame.width, y: point!.y * frame.height }))
  fillTriangle(frame, points[0], points[1], points[2], rgb)
  fillTriangle(frame, points[0], points[2], points[3], rgb)
}

function fillTriangle(frame: SoftwareFrame, a: Point, b: Point, c: Point, rgb: [number, number, number]) {
  const minX = Math.max(0, Math.floor(Math.min(a.x, b.x, c.x)))
  const maxX = Math.min(frame.width - 1, Math.ceil(Math.max(a.x, b.x, c.x)))
  const minY = Math.max(0, Math.floor(Math.min(a.y, b.y, c.y)))
  const maxY = Math.min(frame.height - 1, Math.ceil(Math.max(a.y, b.y, c.y)))
  for (let y = minY; y <= maxY; y += 1) {
    for (let x = minX; x <= maxX; x += 1) {
      if (inside(x + 0.5, y + 0.5, a, b, c)) put(frame, x, y, rgb)
    }
  }
}

function inside(px: number, py: number, a: Point, b: Point, c: Point): boolean {
  const sign = (p: Point, q: Point, r: Point) => (p.x - r.x) * (q.y - r.y) - (q.x - r.x) * (p.y - r.y)
  const here = { x: px, y: py }
  const d1 = sign(here, a, b)
  const d2 = sign(here, b, c)
  const d3 = sign(here, c, a)
  const hasNeg = d1 < 0 || d2 < 0 || d3 < 0
  const hasPos = d1 > 0 || d2 > 0 || d3 > 0
  return !(hasNeg && hasPos)
}

/** The paint object the CPU preview stores. A document that fails this is not a box room. */
export function validRoomBoxPaint(value: unknown): value is RoomBoxPaint {
  if (!value || typeof value !== 'object') return false
  const box = value as RoomBoxPaint
  const size = box.size
  const door = box.door
  if (!size || !Array.isArray(box.characters)) return false
  if (![size.w, size.d, size.h].every(item => typeof item === 'number' && item > 0)) return false
  if (door != null && !validDoor(door)) return false
  return box.characters.every(person => !!person
    && typeof person.x === 'number' && typeof person.z === 'number'
    && typeof person.heightM === 'number' && person.heightM > 0
    && Array.isArray(person.color) && person.color.length === 3
    && person.color.every(item => typeof item === 'number' && Number.isFinite(item)))
}

function validDoor(door: NonNullable<RoomBoxPaint['door']>): boolean {
  if (![door.w, door.h].every(item => typeof item === 'number' && item > 0)) return false
  return typeof door.wall === 'string' && typeof door.x === 'number' && Number.isFinite(door.x)
}

function put(frame: SoftwareFrame, x: number, y: number, rgb: [number, number, number]) {
  const i = (y * frame.width + x) * 4
  frame.pixels[i] = rgb[0]
  frame.pixels[i + 1] = rgb[1]
  frame.pixels[i + 2] = rgb[2]
  frame.pixels[i + 3] = 255
}
