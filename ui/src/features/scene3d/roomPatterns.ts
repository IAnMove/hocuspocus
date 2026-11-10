/** Materials a room paints for itself: a skin entry `{pattern: "leather", color: "#3a2a22", tile_m: 0.4}` needs no picture.
 *  Every pattern is a tileable greyscale 256 px canvas (mean about 0.8) that the surface's `color` tints, so one pattern serves any colour. */
import { CanvasTexture, SRGBColorSpace, type Texture } from 'three'
import { hash2, tileNoise } from './atmos/noise.ts'
import { canvasTexture } from './atmos/textures.ts'

/** Tiles repeat every `tile_m` metres. */
export const TILE_PATTERNS = ['leather', 'fabric', 'plastic', 'quilt', 'carpet', 'metal', 'wood', 'plaster', 'tile'] as const
/** Faces are painted once over the whole face they skin (an instrument cluster, a radio), so they ignore `tile_m`. */
export const FACE_PATTERNS = ['dials', 'radio', 'books'] as const
export const ROOM_PATTERNS = [...TILE_PATTERNS, ...FACE_PATTERNS] as const
export type TilePattern = (typeof TILE_PATTERNS)[number]
export type RoomPattern = (typeof ROOM_PATTERNS)[number]
/** The metres one repeat covers when a skin gives no `tile_m`. */
export const PATTERN_TILE_M: Record<TilePattern, number> = { leather: 0.35, fabric: 0.3, plastic: 0.5, quilt: 0.45, carpet: 0.3, metal: 0.8, wood: 0.9, plaster: 1.2, tile: 0.8 }
export const isFacePattern = (pattern: string): pattern is (typeof FACE_PATTERNS)[number] => (FACE_PATTERNS as readonly string[]).includes(pattern)

export const isRoomPattern = (value: unknown): value is RoomPattern => typeof value === 'string' && (ROOM_PATTERNS as readonly string[]).includes(value)

const SIZE = 256
const grey = (v: number) => Math.max(0, Math.min(255, Math.round(v * 255)))

/** One grey level in 0..1 for the pixel (x, y) of the tile. Pure, so the same pattern always paints the same pixels. */
export function patternLevel(pattern: TilePattern, x: number, y: number, seed: number): number {
  const grain = (scale: number, salt: number) => tileNoise(x / scale, y / scale, SIZE / scale, seed + salt)
  switch (pattern) {
    case 'leather': {
      const pores = hash2(x, y, seed) * 0.07
      const crease = (grain(32, 1) - 0.5) * 0.2 + (grain(8, 2) - 0.5) * 0.08
      const cell = Math.abs(grain(6, 3) - 0.5) < 0.035 ? -0.1 : 0
      return 0.84 + crease - pores + cell
    }
    case 'fabric': {
      const warp = ((x >> 1) + (y >> 1)) % 2 ? 0.07 : -0.05
      return 0.78 + warp + (hash2(x >> 1, y >> 1, seed) - 0.5) * 0.12 + (grain(48, 4) - 0.5) * 0.08
    }
    case 'plastic':
      return 0.86 + (hash2(x, y, seed) - 0.5) * 0.07 + (grain(64, 5) - 0.5) * 0.06
    case 'quilt': {
      const u = ((x + y) % 64) / 64, v = ((x - y + SIZE * 2) % 64) / 64
      const seam = Math.min(u, 1 - u, v, 1 - v)
      const puff = Math.sin(Math.PI * u) * Math.sin(Math.PI * v)
      return (seam < 0.035 ? 0.45 : 0.62 + 0.36 * puff) + (hash2(x, y, seed) - 0.5) * 0.04
    }
    case 'carpet':
      return 0.74 + (hash2(x, y, seed) - 0.5) * 0.26 + (grain(16, 6) - 0.5) * 0.1
    case 'metal': {
      const brush = (hash2(0, y, seed) - 0.5) * 0.1 + (hash2(x >> 3, y, seed + 2) - 0.5) * 0.05
      const seam = x % 128 < 2 || y % 128 < 2 ? -0.28 : 0
      const rivet = (x % 128 === 8 || x % 128 === 120) && (y % 64 === 10 || y % 64 === 54) ? 0.12 : 0
      return 0.8 + brush + seam + rivet
    }
    case 'wood': {
      const plank = Math.floor(x / 64), local = x % 64
      const tone = 0.74 + (hash2(plank, 1, seed) - 0.5) * 0.2
      const ring = Math.sin((y / SIZE) * Math.PI * 2 * (3 + plank % 3) + grain(48, plank) * 6) * 0.05
      return tone + ring + (local < 2 ? -0.3 : 0) + (Math.abs(((y + plank * 71) % SIZE) - 128) < 1 ? -0.2 : 0)
    }
    case 'plaster':
      return 0.9 + (grain(64, 7) - 0.5) * 0.1 + (grain(16, 8) - 0.5) * 0.05 + (hash2(x, y, seed) - 0.5) * 0.03
    case 'tile': {
      const gx = x % 64, gy = y % 64
      const cell = hash2(Math.floor(x / 64), Math.floor(y / 64), seed)
      return gx < 2 || gy < 2 ? 0.55 : 0.88 + (cell - 0.5) * 0.08 + (grain(32, 9) - 0.5) * 0.03
    }
  }
}

function gauge(ctx: CanvasRenderingContext2D, cx: number, cy: number, r: number, needle: number) {
  ctx.strokeStyle = '#cfd6e0'; ctx.lineWidth = 4; ctx.beginPath(); ctx.arc(cx, cy, r, 0, Math.PI * 2); ctx.stroke()
  ctx.lineWidth = 2
  for (let i = 0; i <= 12; i++) {
    const a = ((210 - i * 20) * Math.PI) / 180, long = i % 2 === 0
    ctx.strokeStyle = i > 9 ? '#ff6a5a' : '#e6ecf5'
    ctx.beginPath(); ctx.moveTo(cx + Math.cos(a) * r * (long ? 0.72 : 0.8), cy - Math.sin(a) * r * (long ? 0.72 : 0.8)); ctx.lineTo(cx + Math.cos(a) * r * 0.9, cy - Math.sin(a) * r * 0.9); ctx.stroke()
  }
  const a = ((210 - needle * 240) * Math.PI) / 180
  ctx.strokeStyle = '#ff5a3c'; ctx.lineWidth = 3; ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(cx + Math.cos(a) * r * 0.78, cy - Math.sin(a) * r * 0.78); ctx.stroke()
  ctx.fillStyle = '#2a2d33'; ctx.beginPath(); ctx.arc(cx, cy, 7, 0, Math.PI * 2); ctx.fill()
}

const BOOK_COLOURS = ['#7a2f2f', '#2f4a6b', '#3d5a3a', '#8a6a2f', '#5a3b5e', '#2b2b30', '#9a8b6a', '#4a6a70', '#6b3f2a', '#a05a3a']

/** Five shelves of book spines (a 3 x 2 m bookcase): widths, heights, colours and the odd leaning book come from a hash, so the same shelf is always the same. */
function paintBooks(ctx: CanvasRenderingContext2D, w: number, h: number) {
  ctx.fillStyle = '#1c1511'; ctx.fillRect(0, 0, w, h)
  const rows = 5, rowH = h / rows
  for (let r = 0; r < rows; r++) {
    let x = 6
    const floor = (r + 1) * rowH - 6
    for (let i = 0; x < w - 10; i++) {
      const bw = 9 + hash2(r, i, 41) * 16, bh = rowH * (0.55 + hash2(r, i, 42) * 0.38), colour = BOOK_COLOURS[Math.floor(hash2(r, i, 43) * BOOK_COLOURS.length)]
      if (hash2(r, i, 44) > 0.93) { x += 18 + hash2(r, i, 45) * 40; continue }                       // a gap
      ctx.fillStyle = colour; ctx.fillRect(x, floor - bh, bw, bh)
      ctx.fillStyle = 'rgba(255,255,255,0.14)'; ctx.fillRect(x + 1, floor - bh, 2, bh)
      ctx.fillStyle = 'rgba(0,0,0,0.3)'; ctx.fillRect(x + bw - 2, floor - bh, 2, bh)
      ctx.fillStyle = 'rgba(230,210,150,0.55)'; ctx.fillRect(x + 2, floor - bh + bh * 0.2, Math.max(2, bw - 4), 2); ctx.fillRect(x + 2, floor - bh * 0.3, Math.max(2, bw - 4), 2)
      x += bw + 1
    }
    ctx.fillStyle = '#4a3626'; ctx.fillRect(0, floor, w, 6)                                       // the board each row stands on
  }
}

/** An instrument cluster (two gauges and a small display, 0.52 x 0.2 m), a radio (display, two knobs, presets, a tape slot, 0.34 x 0.3 m) or a bookcase (3 x 2 m). */
export function faceTexture(name: (typeof FACE_PATTERNS)[number]): Texture | null {
  if (typeof document === 'undefined') return null
  const [w, h] = name === 'dials' ? [520, 200] : name === 'books' ? [600, 440] : [340, 300]
  const canvas = document.createElement('canvas'), ctx = canvas.getContext('2d')
  if (!ctx) return null
  canvas.width = w; canvas.height = h
  ctx.fillStyle = '#0d0f13'; ctx.fillRect(0, 0, w, h)
  if (name === 'books') paintBooks(ctx, w, h)
  else if (name === 'dials') {
    gauge(ctx, 130, 102, 78, 0.42); gauge(ctx, 390, 102, 78, 0.28)
    ctx.fillStyle = '#10251a'; ctx.fillRect(222, 62, 76, 56); ctx.fillStyle = '#6dff9a'
    for (let i = 0; i < 4; i++) ctx.fillRect(230 + i * 16, 74, 10, 14 + (i % 2) * 6)
    ctx.fillStyle = '#ffb347'; ctx.beginPath(); ctx.arc(236, 146, 7, 0, Math.PI * 2); ctx.fill(); ctx.fillStyle = '#5ad0ff'; ctx.beginPath(); ctx.arc(284, 146, 7, 0, Math.PI * 2); ctx.fill()
  } else {
    ctx.fillStyle = '#0c2418'; ctx.fillRect(34, 28, 272, 70); ctx.fillStyle = '#58ff9c'
    for (let i = 0; i < 5; i++) ctx.fillRect(52 + i * 48, 44, 26, 38 - (i % 3) * 8)
    for (const x of [84, 256]) { ctx.fillStyle = '#2b2e35'; ctx.beginPath(); ctx.arc(x, 168, 38, 0, Math.PI * 2); ctx.fill(); ctx.strokeStyle = '#8c93a0'; ctx.lineWidth = 3; ctx.stroke(); ctx.strokeStyle = '#e6ecf5'; ctx.beginPath(); ctx.moveTo(x, 168); ctx.lineTo(x + 14, 148); ctx.stroke() }
    for (let i = 0; i < 4; i++) { ctx.fillStyle = '#3a3e46'; ctx.fillRect(52 + i * 62, 226, 46, 16) }
    ctx.fillStyle = '#050607'; ctx.fillRect(60, 262, 220, 14)
  }
  const texture = new CanvasTexture(canvas); texture.colorSpace = SRGBColorSpace; texture.needsUpdate = true
  return texture
}

/** The tile as a repeating texture, or null where no canvas exists (a test without a DOM). */
export function patternTexture(pattern: RoomPattern, seed = 3): Texture | null {
  if (isFacePattern(pattern)) return faceTexture(pattern)
  return canvasTexture(SIZE, ctx => {
    const image = ctx.createImageData(SIZE, SIZE)
    for (let y = 0; y < SIZE; y++) for (let x = 0; x < SIZE; x++) {
      const v = grey(patternLevel(pattern, x, y, seed)), i = (y * SIZE + x) * 4
      image.data[i] = image.data[i + 1] = image.data[i + 2] = v
      image.data[i + 3] = 255
    }
    ctx.putImageData(image, 0, 0)
  }, true)
}
