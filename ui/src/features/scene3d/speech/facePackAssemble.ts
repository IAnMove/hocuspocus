import { EXPRESSIONS, VISEMES, type Expression, type Viseme } from './types'
import { VISEME_ALIASES } from './facePackPrompts'

export const FACE_PACK_TILE = 128

function luma(r: number, g: number, b: number) {
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

function borderMean(data: Uint8ClampedArray) {
  let sr = 0, sg = 0, sb = 0, n = 0
  for (let y = 0; y < FACE_PACK_TILE; y++) {
    for (let x = 0; x < FACE_PACK_TILE; x++) {
      if (x >= 10 && x < FACE_PACK_TILE - 10 && y >= 10 && y < FACE_PACK_TILE - 10) continue
      const i = (y * FACE_PACK_TILE + x) * 4
      const r = data[i], g = data[i + 1], b = data[i + 2]
      if (luma(r, g, b) < 28) continue
      sr += r; sg += g; sb += b; n++
    }
  }
  return n < 16 ? [1, 1, 1] : [sr / n, sg / n, sb / n]
}

export function rasterFaceTile(image: CanvasImageSource): ImageData {
  const canvas = document.createElement('canvas')
  canvas.width = FACE_PACK_TILE
  canvas.height = FACE_PACK_TILE
  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error('no 2d context')
  ctx.drawImage(image, 0, 0, FACE_PACK_TILE, FACE_PACK_TILE)
  return ctx.getImageData(0, 0, FACE_PACK_TILE, FACE_PACK_TILE)
}

export function matchFaceSkin(tile: ImageData, ref: ImageData): ImageData {
  const [tr, tg, tb] = borderMean(tile.data)
  const [rr, rg, rb] = borderMean(ref.data)
  const kr = rr / tr, kg = rg / tg, kb = rb / tb
  const out = new ImageData(new Uint8ClampedArray(tile.data), FACE_PACK_TILE, FACE_PACK_TILE)
  for (let i = 0; i < out.data.length; i += 4) {
    const r = out.data[i], g = out.data[i + 1], b = out.data[i + 2]
    if (luma(r, g, b) < 28) continue
    out.data[i] = Math.max(0, Math.min(255, Math.round(r * kr)))
    out.data[i + 1] = Math.max(0, Math.min(255, Math.round(g * kg)))
    out.data[i + 2] = Math.max(0, Math.min(255, Math.round(b * kb)))
  }
  return out
}

export function pasteFaceMouth(base: ImageData, viseme: ImageData, cx = 64, cy = 92, rx = 30, ry = 18): ImageData {
  const out = new ImageData(new Uint8ClampedArray(base.data), FACE_PACK_TILE, FACE_PACK_TILE)
  for (let y = 0; y < FACE_PACK_TILE; y++) {
    const ny = (y + 0.5 - cy) / ry
    for (let x = 0; x < FACE_PACK_TILE; x++) {
      const nx = (x + 0.5 - cx) / rx
      const d = nx * nx + ny * ny
      if (d > 1.2) continue
      const a = d <= 0.92 ? 1 : Math.max(0, 1 - (d - 0.92) / 0.28)
      const i = (y * FACE_PACK_TILE + x) * 4
      for (let c = 0; c < 3; c++) {
        out.data[i + c] = Math.round(out.data[i + c] * (1 - a) + viseme.data[i + c] * a)
      }
    }
  }
  return out
}

export type FacePackStills = {
  rest: CanvasImageSource
  visemes?: Partial<Record<Viseme, CanvasImageSource>>
  expressions?: Partial<Record<Expression, CanvasImageSource>>
}

function completeTiles<K extends string>(keys: readonly K[], fill: (key: K) => ImageData): Record<K, ImageData> {
  const tiles = {} as Record<K, ImageData>
  for (const key of keys) tiles[key] = fill(key)
  return tiles
}

export function composeFacePack(stills: FacePackStills): HTMLCanvasElement {
  const rest = matchFaceSkin(rasterFaceTile(stills.rest), rasterFaceTile(stills.rest))
  const visemes = completeTiles(VISEMES, (viseme) => {
    if (viseme === 'rest') return rest
    const source = stills.visemes?.[viseme] ?? stills.visemes?.[VISEME_ALIASES[viseme] ?? viseme] ?? stills.rest
    return matchFaceSkin(rasterFaceTile(source), rest)
  })
  const expressions = completeTiles(EXPRESSIONS, (expression) => {
    if (expression === 'neutral') return rest
    const source = stills.expressions?.[expression] ?? stills.rest
    return matchFaceSkin(rasterFaceTile(source), rest)
  })
  const canvas = document.createElement('canvas')
  canvas.width = FACE_PACK_TILE * VISEMES.length
  canvas.height = FACE_PACK_TILE * EXPRESSIONS.length
  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error('no 2d context')
  const scratch = document.createElement('canvas')
  scratch.width = FACE_PACK_TILE
  scratch.height = FACE_PACK_TILE
  const sctx = scratch.getContext('2d')
  if (!sctx) throw new Error('no 2d context')
  EXPRESSIONS.forEach((expression, row) => {
    const base = expressions[expression]
    VISEMES.forEach((viseme, col) => {
      const tile = viseme === 'rest' ? base : pasteFaceMouth(base, visemes[viseme])
      sctx.putImageData(tile, 0, 0)
      ctx.drawImage(scratch, col * FACE_PACK_TILE, row * FACE_PACK_TILE)
    })
  })
  return canvas
}
