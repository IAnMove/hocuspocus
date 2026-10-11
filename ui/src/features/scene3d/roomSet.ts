/** Interior geometry, authored in metres; surfaces retain wall UVs across opening cuts. */
import type { Scene3DDocument, Scene3DSlot, Vec3 } from './types'

export type RoomMaterial = { color?: string; image?: { asset: string }; texture?: { asset: string }; video?: { asset: string }; tile_m?: number }
export type RoomOpening = { wall: string; kind: string; x: number; width: number; height: number; sill?: number; surface?: string }
export type RoomMold = {
  id: string; size: string; dimensions: Vec3; walls: string[]; surfaces: string[]
  openings: RoomOpening[]; blocks: { id: string; box: [number, number, number, number, number, number]; surfaces: string[] }[]
  marks: { id: string; pose: string; position: Vec3; facing: number }[]
  propAnchors: { id: string; on: string; position: Vec3; maxHeight: number }[]
  cameras: { id: string; position: Vec3; lookAt: Vec3; fov: number }[]
  defaultSkin: Record<string, RoomMaterial>; lights: string
}
export type RoomSet = { mold: RoomMold; skin?: Record<string, RoomMaterial>; camera?: string }
export type RoomPanel = { id: string; surface: string; position: Vec3; rotation: Vec3; size: [number, number]; uv: [number, number, number, number]; fullSize: [number, number]; material: RoomMaterial }
const LIGHTS: Record<string, { color: string; intensity: number; direction: Vec3 }> = {
  office_day: { color: '#fff6e5', intensity: 1.1, direction: [-0.6, -1, -0.4] },
  bar_warm: { color: '#ffd6a2', intensity: 0.85, direction: [0.3, -1, -0.4] },
  studio: { color: '#ffffff', intensity: 1.3, direction: [-0.3, -1, -0.7] },
  clinical: { color: '#eaf3ff', intensity: 1.1, direction: [-0.2, -1, 0.2] },
}

export function roomLightPreset(room: RoomSet) {
  return LIGHTS[room.mold.lights] ?? LIGHTS.office_day
}

function roomImage(slot: Scene3DSlot): Scene3DSlot {
  if (slot.media !== 'image') return slot
  const surface = slot.surface ?? 'cutout'
  return { ...slot, surface, ...(surface === 'cutout' ? { imageLook: { grounded: true, ...slot.imageLook } } : {}) }
}

export function validRoomSet(value: unknown): value is RoomSet {
  if (!value || typeof value !== 'object') return false
  const room = value as RoomSet, mold = room.mold
  const vector = (p: unknown) => Array.isArray(p) && p.length === 3 && p.every(n => typeof n === 'number' && Number.isFinite(n))
  if (!mold || !vector(mold.dimensions) || !mold.dimensions.every(n => n >= 0.5 && n <= 30)) return false
  if (![mold.walls, mold.openings, mold.blocks, mold.cameras, mold.surfaces, mold.marks, mold.propAnchors].every(Array.isArray)) return false
  if (mold.blocks.length > 128 || mold.openings.length > 64 || !mold.defaultSkin) return false
  if (!mold.cameras.every(c => vector(c.position) && vector(c.lookAt) && c.fov > 0 && c.fov < 180)) return false
  return mold.blocks.every(b => Array.isArray(b.box) && b.box.length === 6 && b.box.every(Number.isFinite) && b.box.slice(3).every(n => n > 0))
}

/** A no-room request is a strict no-op, including object identity. */
export function stageRoomSet(document: Scene3DDocument, room?: RoomSet): Scene3DDocument {
  if (!room) return document
  if (!validRoomSet(room)) throw new Error('invalid_room_set')
  const named = room.mold.cameras.find(camera => camera.id === (room.camera ?? 'two_shot'))
  if (!named) throw new Error(`unknown_room_camera:${room.camera}`)
  document.room = structuredClone(room)
  document.dressing = 'none'
  document.slots = document.slots.filter(slot => slot.slot !== 'background').map(roomImage)
  document.environment = { reflectiveFloor: false, platform: false, bloom: 0, floorStyle: 'none' }
  document.camera = { family: 'fixed', eye: [...named.position], look: [...named.lookAt], fov: named.fov }
  document.light = { kind: 'directional', ...roomLightPreset(room) }
  return document
}

export function roomPanels(room: RoomSet): RoomPanel[] {
  const { mold } = room, [w, d, h] = mold.dimensions
  const panels: RoomPanel[] = []
  const skin = { ...mold.defaultSkin, ...room.skin }
  const add = (surface: string, position: Vec3, rotation: Vec3, size: [number, number], uv: RoomPanel['uv'] = [0, 0, 1, 1], fullSize = size) => {
    panels.push({ id: `room-${surface}-${panels.length}`, surface, position, rotation, size, uv, fullSize, material: skin[surface] ?? { color: '#d8d2c4' } })
  }
  add('floor', [0, 0, 0], [-Math.PI / 2, 0, 0], [w, d])
  add('ceiling', [0, h, 0], [Math.PI / 2, 0, 0], [w, d])
  for (const wall of mold.walls) {
    const side = wall === 'left' || wall === 'right', span = side ? d : w
    const openings = mold.openings.filter(o => o.wall === wall)
    const rects = openings.map(o => ({ ...o, a: o.x * span - o.width / 2, b: o.x * span + o.width / 2, low: o.sill ?? 0, high: (o.sill ?? 0) + o.height }))
    const xs = [...new Set([0, span, ...rects.flatMap(o => [o.a, o.b])])].sort((a, b) => a - b)
    const ys = [...new Set([0, h, ...rects.flatMap(o => [o.low, o.high])])].sort((a, b) => a - b)
    const yaw = wall === 'left' ? Math.PI / 2 : wall === 'right' ? -Math.PI / 2 : wall === 'front' ? Math.PI : 0
    const at = (u: number, y: number, offset = 0): Vec3 => side ? [wall === 'left' ? -w/2-offset : w/2+offset, y, u-span/2] : [u-span/2, y, wall === 'back' ? -d/2-offset : d/2+offset]
    for (let i = 1; i < xs.length; i++) for (let j = 1; j < ys.length; j++) {
      const x = (xs[i-1]+xs[i])/2, y = (ys[j-1]+ys[j])/2
      if (rects.some(o => x > o.a && x < o.b && y > o.low && y < o.high)) continue
      add(`wall_${wall}`, at(x, y), [0, yaw, 0], [xs[i]-xs[i-1], ys[j]-ys[j-1]], [xs[i-1]/span, ys[j-1]/h, xs[i]/span, ys[j]/h], [span, h])
    }
    for (const o of rects) add(o.surface ?? (o.kind === 'window' ? 'window_view' : 'door'), at(o.x*span, o.low+o.height/2, 0.015), [0, yaw, 0], [o.width, o.height])
  }
  for (const block of mold.blocks) {
    const [x, y, z, bw, bh, bd] = block.box
    const front = block.surfaces.find(s => s.endsWith('_front')) ?? block.surfaces[0]
    const top = block.surfaces.find(s => s.endsWith('_top')) ?? front
    add(front, [x,y+bh/2,z+bd/2], [0,0,0], [bw,bh])
    add(front, [x,y+bh/2,z-bd/2], [0,Math.PI,0], [bw,bh])
    add(front, [x-bw/2,y+bh/2,z], [0,-Math.PI/2,0], [bd,bh])
    add(front, [x+bw/2,y+bh/2,z], [0,Math.PI/2,0], [bd,bh])
    add(top, [x,y+bh,z], [-Math.PI/2,0,0], [bw,bd])
    add(front, [x,y,z], [Math.PI/2,0,0], [bw,bd])
  }
  return panels
}
