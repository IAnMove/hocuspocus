import { CanvasTexture, NoColorSpace, RepeatWrapping, SRGBColorSpace, type Texture } from 'three'
import { hash2 } from './noise.ts'

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

const COBBLE_REPEAT = 16

/** Same voronoi as the albedo, in world metres. Low values are the joints. */
export function cobbleJoint(x: number, z: number, seed: number): number {
  const span = COBBLE_REPEAT * 256
  const px = ((x + 24) / 48) * span
  const py = ((-z + 24) / 48) * span
  const cell = nearest(px, py, 28, seed)
  return Math.min(1, Math.max(0, (cell.d2 - cell.d1) / 5))
}

export function cobbleTextures(stone: string, seed: number): { albedo: Texture | null; normal: Texture | null } {
  const albedo = canvasTexture(256, (ctx, size) => {
    const img = ctx.createImageData(size, size)
    const rgb = Number.parseInt(stone.slice(1), 16)
    for (let y = 0; y < size; y += 1) {
      for (let x = 0; x < size; x += 1) {
        const cell = nearest(x, y, 28, seed)
        const joint = Math.min(1, Math.max(0, (cell.d2 - cell.d1) / 5))
        const moss = joint < 0.35 ? (0.35 - joint) * 2 : 0
        const tint = 0.82 + cell.id * 0.28
        const i = (y * size + x) * 4
        img.data[i] = Math.min(255, ((rgb >> 16) & 255) * tint * (0.55 + joint * 0.45))
        img.data[i + 1] = Math.min(255, ((rgb >> 8) & 255) * tint * (0.55 + joint * 0.45) + moss * 70)
        img.data[i + 2] = Math.min(255, (rgb & 255) * tint * (0.5 + joint * 0.4))
        img.data[i + 3] = 255
      }
    }
    ctx.putImageData(img, 0, 0)
  }, true)
  const normal = canvasTexture(128, (ctx, size) => {
    const img = ctx.createImageData(size, size)
    for (let y = 0; y < size; y += 1) {
      for (let x = 0; x < size; x += 1) {
        const scale = 256 / size
        const here = nearest(x * scale, y * scale, 28, seed)
        const right = nearest((x + 1) * scale, y * scale, 28, seed)
        const up = nearest(x * scale, (y + 1) * scale, 28, seed)
        const dx = (right.d1 - here.d1) * 8
        const dy = (up.d1 - here.d1) * 8
        const i = (y * size + x) * 4
        img.data[i] = Math.max(0, Math.min(255, 128 - dx * 40))
        img.data[i + 1] = Math.max(0, Math.min(255, 128 - dy * 40))
        img.data[i + 2] = 200
        img.data[i + 3] = 255
      }
    }
    ctx.putImageData(img, 0, 0)
  }, true)
  if (albedo) albedo.repeat.set(COBBLE_REPEAT, COBBLE_REPEAT)
  if (normal) {
    normal.colorSpace = NoColorSpace
    normal.repeat.set(COBBLE_REPEAT, COBBLE_REPEAT)
  }
  return { albedo, normal }
}

export function barkTexture(seed: number): Texture | null {
  return canvasTexture(128, (ctx, size) => {
    ctx.fillStyle = '#6a5344'
    ctx.fillRect(0, 0, size, size)
    for (let i = 0; i < 80; i += 1) {
      const x = hash2(i, 1, seed) * size
      ctx.fillStyle = `rgba(40,28,20,${0.25 + hash2(i, 2, seed) * 0.4})`
      ctx.fillRect(x, 0, 1 + (i % 3), size)
    }
  })
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
