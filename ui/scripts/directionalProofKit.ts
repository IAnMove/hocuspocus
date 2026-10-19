// A synthetic kit for the directional figures: five directions, a walk sheet and an idle sheet of each, one colour per direction.
// Nothing here calls a model. The PNGs are rasterised and encoded by hand, so the proof needs no image library.
import zlib from 'node:zlib'
import type { Direction } from '../src/features/scene3d/directionalSprite.ts'

export const CELL = { width: 200, height: 320 }
/** The catalog's contract with the sheets (app/shared/character_animations.json): boots on 96 % of the cell, figure 86 % high. */
export const FEET = 0.96
export const FIGURE = 0.86
export const DIRECTION_COLORS: Record<Direction, [number, number, number]> = {
  front: [229, 57, 53], front34: [251, 140, 0], side: [67, 160, 71], back34: [30, 136, 229], back: [142, 36, 170],
}
export const NOSE: [number, number, number] = [255, 235, 59]
/** The badge a figure wears on its right arm: seen on the sheets that look right, hidden on a sheet that really looks left. */
export const BADGE: [number, number, number] = [0, 200, 255]
/** The mouth drawings of the kit, one colour each, and where the mouth is on the sheets that have one (% of the longer edge of the cell). */
export const MOUTHS: Record<string, [number, number, number]> = { closed: [90, 40, 10], wide: [10, 255, 60], round: [255, 120, 200] }
export const COLUMN: [number, number, number] = [140, 120, 100]
/** The kit's blink drawing: one colour, so a pixel count says whether the eyes are shut. */
export const BLINK: [number, number, number] = [160, 32, 240]
export const BOOT: [number, number, number] = [20, 20, 20]
const SKIN: [number, number, number] = [255, 224, 189]
const WHITE: [number, number, number] = [255, 255, 255]

type Rgb = [number, number, number]
class Raster {
  readonly pixels: Uint8Array
  constructor(readonly width: number, readonly height: number) { this.pixels = new Uint8Array(width * height * 4) }
  dot(x: number, y: number, rgb: Rgb) {
    if (x < 0 || y < 0 || x >= this.width || y >= this.height) return
    const at = (y * this.width + x) * 4
    this.pixels[at] = rgb[0]; this.pixels[at + 1] = rgb[1]; this.pixels[at + 2] = rgb[2]; this.pixels[at + 3] = 255
  }
  rect(x0: number, y0: number, x1: number, y1: number, rgb: Rgb) {
    for (let y = Math.round(y0); y < Math.round(y1); y += 1) for (let x = Math.round(x0); x < Math.round(x1); x += 1) this.dot(x, y, rgb)
  }
  disc(cx: number, cy: number, radius: number, rgb: Rgb) {
    for (let y = Math.floor(cy - radius); y <= cy + radius; y += 1) for (let x = Math.floor(cx - radius); x <= cx + radius; x += 1) if ((x - cx) ** 2 + (y - cy) ** 2 <= radius ** 2) this.dot(x, y, rgb)
  }
}

const darker = (rgb: Rgb): Rgb => [rgb[0] * 0.65, rgb[1] * 0.65, rgb[2] * 0.65]
const paler = (rgb: Rgb): Rgb => [rgb[0] * 0.7 + WHITE[0] * 0.3, rgb[1] * 0.7 + WHITE[1] * 0.3, rgb[2] * 0.7 + WHITE[2] * 0.3]
/** The colour of the torso of a direction: full while it walks, paler while it stands. */
export const torsoColor = (dir: Direction, motion: 'walk' | 'idle'): Rgb => motion === 'walk' ? DIRECTION_COLORS[dir] : paler(DIRECTION_COLORS[dir])
/** The grey the pose picture is made of (posePng), and the pips that count the cells of a sheet: white lights the cell. */
export const POSE_TORSO: Rgb = [150, 150, 160]
export const PIP_ON: Rgb = [255, 255, 255]
export const PIP_OFF: Rgb = [255, 0, 255]
export const PIP = { pitch: 14, width: 10, left: 8, top: 6, height: 10 }

/** How far apart the feet are along the line the figure walks, as a share of the half step: a side view swings them most. */
const STRIDE: Record<Direction, number> = { front: 0.18, front34: 0.55, side: 1, back34: 0.55, back: 0.18 }

function drawLegs(image: Raster, cx: number, dir: Direction, swing: number, body: Rgb) {
  const feetY = CELL.height * FEET, legTop = 214
  const spread = 45 * STRIDE[dir] * swing
  for (const sign of [1, -1]) {
    const lift = dir === 'side' ? 0 : Math.max(0, sign * swing) * 10
    const x = cx + sign * (dir === 'side' ? spread : 17 + spread * 0.4)
    image.rect(x - 11, legTop, x + 11, feetY - 12 - lift, darker(body))
    image.rect(x - 14 + (dir === 'side' ? 6 : 0), feetY - 12 - lift, x + 14 + (dir === 'side' ? 14 : 0), feetY - lift, BOOT)
  }
}

function drawBadge(image: Raster, cx: number, dir: Direction, reversed: boolean) {
  if (dir === 'side' && !reversed) image.rect(cx - 12, 150, cx + 4, 166, BADGE)
  if (dir === 'front34' && !reversed) image.rect(cx - 30, 140, cx - 16, 154, BADGE)
}

/** The head of a direction. A reversed sheet is the kit's own drawing of the other side: it looks left, nose and ear included. */
function drawHead(image: Raster, cx: number, dir: Direction, body: Rgb, reversed: boolean) {
  const flip = reversed ? -1 : 1
  const shift = (dir === 'side' ? 6 : dir === 'front34' || dir === 'back34' ? 12 : 0) * flip
  const covered = dir === 'back' || dir === 'back34'
  image.disc(cx + shift, 80, 38, covered ? darker(body) : SKIN)
  const span = (from: number, to: number) => flip > 0 ? [cx + shift + from, cx + shift + to] : [cx + shift - to, cx + shift - from]
  if (dir === 'side') image.rect(span(36, 58)[0], 78, span(36, 58)[1], 92, NOSE)
  if (dir === 'front34') { image.rect(span(18, 36)[0], 76, span(18, 36)[1], 90, NOSE); image.rect(span(-6, 4)[0], 62, span(-6, 4)[1], 72, BOOT) }
  if (dir === 'front') { image.rect(cx - 20, 62, cx - 10, 74, BOOT); image.rect(cx + 10, 62, cx + 20, 74, BOOT) }
  if (dir === 'back34') image.rect(span(26, 38)[0], 72, span(26, 38)[1], 88, darker(body))
}

function drawPips(image: Raster, count: number, frame: number) {
  for (let pip = 0; pip < count; pip += 1) image.rect(PIP.left + pip * PIP.pitch, PIP.top, PIP.left + PIP.width + pip * PIP.pitch, PIP.top + PIP.height, pip === frame ? PIP_ON : PIP_OFF)
}

/** One cell: the figure of a direction at one instant of its cycle, with a pip row that lights the cell number. */
function drawCell(image: Raster, dir: Direction, motion: 'walk' | 'idle', frame: number, count: number, reversed: boolean) {
  const body = torsoColor(dir, motion)
  const cx = CELL.width / 2
  const swing = motion === 'walk' ? Math.sin(frame / count * Math.PI * 2) : 0
  const breath = motion === 'idle' ? (frame % 2) * 4 : 0
  drawLegs(image, cx, dir, swing, body)
  image.rect(cx - 38, 120 - breath, cx + 38, 218, body)
  const arm = dir === 'side' ? -swing * 30 : 0
  image.rect(cx - 52 + arm, 126, cx - 38 + arm, 200, darker(body)); image.rect(cx + 38 + arm, 126, cx + 52 + arm, 200, darker(body))
  drawHead(image, cx, dir, body, reversed)
  drawBadge(image, cx, dir, reversed)
  drawPips(image, count, frame)
}

export type SheetImage = { png: Buffer; columns: number; rows: number; count: number }

export function sheetPng(dir: Direction, motion: 'walk' | 'idle', count: number, reversed = false): SheetImage {
  const columns = Math.min(4, count), rows = Math.ceil(count / columns)
  const sheet = new Raster(columns * CELL.width, rows * CELL.height)
  for (let frame = 0; frame < count; frame += 1) {
    const cell = new Raster(CELL.width, CELL.height)
    drawCell(cell, dir, motion, frame, count, reversed)
    const left = (frame % columns) * CELL.width, top = Math.floor(frame / columns) * CELL.height
    for (let y = 0; y < CELL.height; y += 1) sheet.pixels.set(cell.pixels.subarray(y * CELL.width * 4, (y + 1) * CELL.width * 4), ((top + y) * sheet.width + left) * 4)
  }
  return { png: encodePng(sheet), columns, rows, count }
}

/** The base pose of the kit: a grey figure facing the camera with empty rows below its boots, like a Qwen pose. */
export function posePng(): Buffer {
  const image = new Raster(300, 480)
  image.rect(110, 330, 190, 440, [120, 120, 130])
  image.rect(95, 150, 205, 340, POSE_TORSO)
  image.disc(150, 100, 52, [190, 180, 170])
  image.rect(100, 440, 150, 450, BOOT); image.rect(150, 440, 200, 450, BOOT)
  return encodePng(image)
}

/** One mouth drawing: a flat colour, so a pixel count says which one is on a sheet. */
export function mouthPng(color: Rgb): Buffer {
  const image = new Raster(40, 24)
  image.rect(0, 0, 40, 24, color)
  return encodePng(image)
}

/** A box as a GLB (what GLTFLoader reads), base on y = 0 and 1.7 high so the scene's own scale sets its height. */
export function boxGlb(width: number, depth: number, color: Rgb): Buffer {
  const h = 1.7, x = width / 2, z = depth / 2
  const faces: [number[], number[]][] = [
    [[0, 0, 1], [-x, 0, z, x, 0, z, x, h, z, -x, h, z]], [[0, 0, -1], [x, 0, -z, -x, 0, -z, -x, h, -z, x, h, -z]],
    [[1, 0, 0], [x, 0, z, x, 0, -z, x, h, -z, x, h, z]], [[-1, 0, 0], [-x, 0, -z, -x, 0, z, -x, h, z, -x, h, -z]],
    [[0, 1, 0], [-x, h, z, x, h, z, x, h, -z, -x, h, -z]], [[0, -1, 0], [-x, 0, -z, x, 0, -z, x, 0, z, -x, 0, z]],
  ]
  const positions = new Float32Array(faces.flatMap(([, corners]) => corners))
  const normals = new Float32Array(faces.flatMap(([normal]) => [...normal, ...normal, ...normal, ...normal]))
  const indices = new Uint16Array(faces.flatMap((_face, index) => [0, 1, 2, 0, 2, 3].map(corner => index * 4 + corner)))
  const binary = Buffer.concat([Buffer.from(positions.buffer), Buffer.from(normals.buffer), Buffer.from(indices.buffer)])
  const json = Buffer.from(JSON.stringify({
    asset: { version: '2.0' }, scene: 0, scenes: [{ nodes: [0] }], nodes: [{ mesh: 0 }],
    meshes: [{ primitives: [{ attributes: { POSITION: 0, NORMAL: 1 }, indices: 2, material: 0 }] }],
    materials: [{ pbrMetallicRoughness: { baseColorFactor: [...color.map(value => value / 255), 1], metallicFactor: 0, roughnessFactor: 1 } }],
    buffers: [{ byteLength: binary.length }],
    bufferViews: [{ buffer: 0, byteOffset: 0, byteLength: positions.byteLength, target: 34962 }, { buffer: 0, byteOffset: positions.byteLength, byteLength: normals.byteLength, target: 34962 },
      { buffer: 0, byteOffset: positions.byteLength + normals.byteLength, byteLength: indices.byteLength, target: 34963 }],
    accessors: [{ bufferView: 0, componentType: 5126, count: 24, type: 'VEC3', min: [-x, 0, -z], max: [x, h, z] }, { bufferView: 1, componentType: 5126, count: 24, type: 'VEC3' },
      { bufferView: 2, componentType: 5123, count: 36, type: 'SCALAR' }],
  }))
  const pad = (data: Buffer, fill: number) => Buffer.concat([data, Buffer.alloc((4 - data.length % 4) % 4, fill)])
  const chunks = [[0x4e4f534a, pad(json, 0x20)], [0x004e4942, pad(binary, 0)]] as const
  const total = 12 + chunks.reduce((sum, [, data]) => sum + 8 + data.length, 0)
  const header = Buffer.alloc(12)
  header.writeUInt32LE(0x46546c67, 0); header.writeUInt32LE(2, 4); header.writeUInt32LE(total, 8)
  return Buffer.concat([header, ...chunks.flatMap(([type, data]) => { const head = Buffer.alloc(8); head.writeUInt32LE(data.length, 0); head.writeUInt32LE(type, 4); return [head, data] })])
}

/** The floor: 16 by 9 squares, so on a 16 by 9 m plane each one is a metre. */
export function floorPng(): Buffer {
  const image = new Raster(640, 360)
  for (let y = 0; y < 360; y += 1) for (let x = 0; x < 640; x += 1) image.dot(x, y, ((x / 40 | 0) + (y / 40 | 0)) % 2 ? [92, 98, 108] : [66, 70, 80])
  return encodePng(image)
}

function chunk(type: string, data: Buffer): Buffer {
  const head = Buffer.alloc(8)
  head.writeUInt32BE(data.length, 0); head.write(type, 4, 'latin1')
  const crc = Buffer.alloc(4)
  crc.writeUInt32BE(zlib.crc32(Buffer.concat([head.subarray(4), data])), 0)
  return Buffer.concat([head, data, crc])
}

function encodePng(image: Raster): Buffer {
  const rows = Buffer.alloc((image.width * 4 + 1) * image.height)
  for (let y = 0; y < image.height; y += 1) {
    rows[y * (image.width * 4 + 1)] = 0
    rows.set(image.pixels.subarray(y * image.width * 4, (y + 1) * image.width * 4), y * (image.width * 4 + 1) + 1)
  }
  const header = Buffer.alloc(13)
  header.writeUInt32BE(image.width, 0); header.writeUInt32BE(image.height, 4); header[8] = 8; header[9] = 6
  return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk('IHDR', header), chunk('IDAT', zlib.deflateSync(rows)), chunk('IEND', Buffer.alloc(0))])
}

/** The kit as the server hands it to a scene: one walk sheet and one idle sheet for each of the five directions. */
export const WALK_CELLS = 12
export const IDLE_CELLS = 2
export const DIRECTION_ORDER: Direction[] = ['front', 'front34', 'side', 'back34', 'back']
