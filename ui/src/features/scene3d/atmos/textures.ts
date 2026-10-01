import { CanvasTexture, RepeatWrapping, SRGBColorSpace, type Texture } from 'three'
import { hash2, tileNoise } from './noise.ts'

type Paint = (ctx: CanvasRenderingContext2D, size: number) => void

export function canvasTexture(size: number, paint: Paint, repeat = false): Texture | null {
  if (typeof document === 'undefined') return null
  const el = document.createElement('canvas')
  el.width = size
  el.height = size
  const ctx = el.getContext('2d')
  if (!ctx) return null
  paint(ctx, size)
  const texture = new CanvasTexture(el)
  texture.colorSpace = SRGBColorSpace
  if (repeat) {
    texture.wrapS = RepeatWrapping
    texture.wrapT = RepeatWrapping
    texture.repeat.set(7, 7)
  }
  texture.needsUpdate = true
  return texture
}

function nearest(px: number, py: number, cells: number, seed: number): { d1: number; d2: number; id: number } {
  const gx = Math.floor(px / cells)
  const gy = Math.floor(py / cells)
  let d1 = 1e9
  let d2 = 1e9
  let id = 0
  for (let y = gy - 1; y <= gy + 1; y += 1) {
    for (let x = gx - 1; x <= gx + 1; x += 1) {
      const jx = (x + hash2(x, y, seed)) * cells
      const jy = (y + hash2(x, y, seed + 3)) * cells
      const dist = Math.hypot(px - jx, py - jy)
      if (dist < d1) { d2 = d1; d1 = dist; id = hash2(x, y, seed + 8) }
      else if (dist < d2) d2 = dist
    }
  }
  return { d1, d2, id }
}

const FLOOR_SIZE = 512

function channels(hex: string): [number, number, number] {
  const rgb = Number.parseInt(hex.slice(1), 16)
  return [(rgb >> 16) & 255, (rgb >> 8) & 255, rgb & 255]
}

function smooth(edge0: number, edge1: number, x: number): number {
  const t = Math.min(1, Math.max(0, (x - edge0) / (edge1 - edge0)))
  return t * t * (3 - 2 * t)
}

/** Painterly forest floor: mossy grass with worn dirt, dark pockets and fallen leaves. Tiles without a seam. */
export function floorTexture(grass: string, dirt: string, seed: number): Texture | null {
  const moss = channels(grass)
  const soil = channels(dirt).map((v, i) => v * 0.42 + [64, 44, 26][i] * 0.58)
  const leaf = [214, 150, 58]
  const texture = canvasTexture(FLOOR_SIZE, (ctx, size) => {
    const img = ctx.createImageData(size, size)
    for (let y = 0; y < size; y += 1) {
      for (let x = 0; x < size; x += 1) {
        const u = x / size
        const v = y / size
        const patch = tileNoise(u * 4, v * 4, 4, seed)
        const mid = tileNoise(u * 16, v * 16, 16, seed + 1)
        const fine = tileNoise(u * 128, v * 128, 128, seed + 2)
        const worn = smooth(0.56, 0.74, patch)
        const shade = 0.78 + mid * 0.42 + (fine - 0.5) * 0.16
        const leafy = fine > 0.86 && mid > 0.4 ? 0.8 : 0
        const pocket = fine < 0.12 ? 0.8 : 1
        const i = (y * size + x) * 4
        for (let c = 0; c < 3; c += 1) {
          const base = moss[c] * shade * (1 - worn) + soil[c] * (0.78 + mid * 0.4) * worn
          img.data[i + c] = Math.min(255, (base * (1 - leafy) + leaf[c] * (0.7 + mid * 0.4) * leafy) * pocket)
        }
        img.data[i + 3] = 255
      }
    }
    ctx.putImageData(img, 0, 0)
  }, true)
  if (texture) texture.repeat.set(8, 8)
  return texture
}

export type TerrainPaint = { base: string; alt: string; fleck: string; seed: number; fleckAbove?: number; patches?: number }

/** Painterly ground for any terrain: two soils in soft patches, fine flecks and dark pockets. Tiles without a seam. */
export function terrainTexture(paint: TerrainPaint): Texture | null {
  const base = channels(paint.base)
  const alt = channels(paint.alt)
  const fleck = channels(paint.fleck)
  const cells = paint.patches ?? 4
  const above = paint.fleckAbove ?? 0.9
  const texture = canvasTexture(FLOOR_SIZE, (ctx, size) => {
    const img = ctx.createImageData(size, size)
    for (let y = 0; y < size; y += 1) {
      for (let x = 0; x < size; x += 1) {
        const u = x / size
        const v = y / size
        const patch = smooth(0.38, 0.66, tileNoise(u * cells, v * cells, cells, paint.seed))
        const mid = tileNoise(u * 16, v * 16, 16, paint.seed + 1)
        const fine = tileNoise(u * 128, v * 128, 128, paint.seed + 2)
        const shade = 0.82 + mid * 0.36 + (fine - 0.5) * 0.14
        const speck = fine > above ? 0.8 : 0
        const pocket = fine < 0.1 ? 0.78 : 1
        const i = (y * size + x) * 4
        for (let c = 0; c < 3; c += 1) {
          const soil = (base[c] * (1 - patch) + alt[c] * patch) * shade
          img.data[i + c] = Math.min(255, (soil * (1 - speck) + fleck[c] * speck) * pocket)
        }
        img.data[i + 3] = 255
      }
    }
    ctx.putImageData(img, 0, 0)
  }, true)
  if (texture) texture.repeat.set(8, 8)
  return texture
}

/** Vertical bark ridges with dark crevices, lichen flecks and a few knots. Tiles around the trunk. */
export function barkTexture(seed: number): Texture | null {
  const texture = canvasTexture(256, (ctx, size) => {
    ctx.fillStyle = '#7a5d44'
    ctx.fillRect(0, 0, size, size)
    const stroke = (x: number, y: number, w: number, h: number, color: string) => {
      ctx.fillStyle = color
      for (const dx of [-size, 0, size]) for (const dy of [-size, 0, size]) ctx.fillRect(x + dx, y + dy, w, h)
    }
    for (let i = 0; i < 340; i += 1) {
      const x = hash2(i, 1, seed) * size
      const y = hash2(i, 2, seed) * size
      const w = 1 + Math.floor(hash2(i, 3, seed) * 4)
      const h = 30 + hash2(i, 4, seed) * 130
      const dark = hash2(i, 5, seed) < 0.55
      stroke(x, y, w, h, dark ? `rgba(24,15,9,${0.5 + hash2(i, 6, seed) * 0.4})` : `rgba(190,150,108,${0.28 + hash2(i, 6, seed) * 0.3})`)
    }
    for (let i = 0; i < 46; i += 1) stroke(hash2(i, 7, seed) * size, hash2(i, 8, seed) * size, 3, 3, 'rgba(150,170,110,0.35)')
    for (let i = 0; i < 4; i += 1) {
      ctx.fillStyle = 'rgba(24,16,10,0.55)'
      ctx.beginPath()
      ctx.ellipse(hash2(i, 9, seed) * size, hash2(i, 10, seed) * size, 9, 16, 0, 0, Math.PI * 2)
      ctx.fill()
    }
  }, true)
  if (texture) texture.repeat.set(3, 1)
  return texture
}

/** White where the sun passes, dark where a leaf blocks it. */
export function leafCookie(seed: number): Texture | null {
  const texture = canvasTexture(256, (ctx, size) => {
    const img = ctx.createImageData(size, size)
    for (let y = 0; y < size; y += 1) {
      for (let x = 0; x < size; x += 1) {
        const cell = nearest(x, y, 18, seed + 40)
        const gap = cell.d1 > 8.0 && cell.id > 0.62
        const v = gap ? 255 : 22
        const i = (y * size + x) * 4
        img.data[i] = v
        img.data[i + 1] = v
        img.data[i + 2] = v
        img.data[i + 3] = 255
      }
    }
    ctx.putImageData(img, 0, 0)
  })
  if (texture) {
    texture.wrapS = RepeatWrapping
    texture.wrapT = RepeatWrapping
    texture.repeat.set(3, 3)
  }
  return texture
}

export function leafSprite(color: string): Texture | null {
  return canvasTexture(64, (ctx, size) => {
    ctx.clearRect(0, 0, size, size)
    ctx.fillStyle = color
    ctx.beginPath()
    ctx.ellipse(size / 2, size / 2, size * 0.42, size * 0.22, 0.6, 0, Math.PI * 2)
    ctx.fill()
  })
}
