import { fxRandom, type SceneFx } from './types'

export const RETRO_LOOK_IDS = [
  'psx', 'n64', 'nes', 'snes', 'gameboy', 'gameboy_color', 'genesis', 'vhs', 'crt', 'c64',
] as const

export type RetroLookId = (typeof RETRO_LOOK_IDS)[number]

export function isRetroLook(kind: string): kind is RetroLookId {
  return (RETRO_LOOK_IDS as readonly string[]).includes(kind)
}

const BAYER = [0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5]

const GB: RGB[] = [[15, 56, 15], [48, 98, 48], [139, 172, 15], [155, 188, 15]]
const C64: RGB[] = [
  [0, 0, 0], [255, 255, 255], [136, 0, 0], [170, 255, 238], [204, 68, 204], [0, 204, 85], [0, 0, 170], [238, 238, 119],
  [221, 136, 85], [102, 68, 0], [255, 119, 119], [51, 51, 51], [119, 119, 119], [170, 255, 102], [0, 136, 255], [187, 187, 187],
]
const NES: RGB[] = [
  [84, 84, 84], [0, 30, 116], [8, 16, 144], [48, 0, 136], [68, 0, 100], [92, 0, 48], [84, 4, 0], [60, 24, 0],
  [32, 42, 0], [8, 58, 0], [0, 64, 0], [0, 60, 0], [0, 50, 60], [0, 0, 0], [152, 150, 152], [8, 76, 196],
  [48, 50, 236], [92, 30, 228], [136, 20, 176], [160, 20, 100], [152, 34, 32], [120, 60, 0], [84, 90, 0], [40, 114, 0],
  [8, 124, 0], [0, 118, 40], [0, 102, 120], [0, 0, 0], [236, 238, 236], [76, 154, 236], [120, 124, 236], [176, 98, 236],
  [228, 84, 236], [236, 88, 180], [236, 106, 88], [212, 136, 32], [160, 170, 0], [116, 196, 0], [76, 208, 32], [56, 204, 108],
  [56, 180, 204], [60, 60, 60], [236, 238, 236], [168, 204, 236], [188, 188, 236], [212, 178, 236], [236, 174, 236],
  [236, 174, 212], [236, 180, 176], [228, 196, 144], [204, 210, 120], [180, 222, 120], [168, 226, 144], [152, 226, 180],
  [160, 214, 228], [160, 162, 160],
]
type RGB = [number, number, number]

function clamp(value: number) {
  return value < 0 ? 0 : value > 255 ? 255 : value
}

function bayer(x: number, y: number) {
  return BAYER[(y & 3) * 4 + (x & 3)] / 16 - 0.5
}

function quantize(value: number, steps: number, dither: number) {
  const q = 255 / Math.max(1, steps - 1)
  return clamp(Math.round(clamp(value + dither) / q) * q)
}

function nearest(r: number, g: number, b: number, palette: readonly RGB[]): RGB {
  let best = palette[0], bestD = Infinity
  for (const color of palette) {
    const d = (r - color[0]) ** 2 + (g - color[1]) ** 2 + (b - color[2]) ** 2
    if (d < bestD) { bestD = d; best = color }
  }
  return best
}

function luma(r: number, g: number, b: number) {
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

function colsFor(width: number, height: number, columns: number, intensity: number) {
  const cols = Math.max(48, Math.round(columns / Math.max(0.7, intensity)))
  return { cols, rows: Math.max(36, Math.round(cols * height / Math.max(1, width))) }
}

function read(src: Uint8ClampedArray, width: number, height: number, x: number, y: number): RGB {
  const sx = Math.max(0, Math.min(width - 1, x | 0))
  const sy = Math.max(0, Math.min(height - 1, y | 0))
  const i = (sy * width + sx) * 4
  return [src[i], src[i + 1], src[i + 2]]
}

function pixelate(src: Uint8ClampedArray, width: number, height: number, cols: number, rows: number, map: (r: number, g: number, b: number, x: number, y: number) => RGB) {
  const out = new Uint8ClampedArray(src.length)
  for (let y = 0; y < height; y++) {
    const cy = Math.min(rows - 1, Math.floor(y * rows / height))
    for (let x = 0; x < width; x++) {
      const cx = Math.min(cols - 1, Math.floor(x * cols / width))
      const sx = Math.floor((cx + 0.5) * width / cols)
      const sy = Math.floor((cy + 0.5) * height / rows)
      const [r, g, b] = map(...read(src, width, height, sx, sy), cx, cy)
      const i = (y * width + x) * 4
      out[i] = r; out[i + 1] = g; out[i + 2] = b; out[i + 3] = src[i + 3]
    }
  }
  src.set(out)
}

function bitcrush(src: Uint8ClampedArray, width: number, height: number, cols: number, bits: number, dither: number) {
  const steps = 1 << bits
  const rows = Math.max(36, Math.round(cols * height / Math.max(1, width)))
  pixelate(src, width, height, cols, rows, (r, g, b, x, y) => {
    const t = bayer(x, y) * dither
    return [quantize(r, steps, t), quantize(g, steps, t), quantize(b, steps, t)]
  })
}

function palettize(src: Uint8ClampedArray, width: number, height: number, cols: number, palette: readonly RGB[], dither: number) {
  const rows = Math.max(36, Math.round(cols * height / Math.max(1, width)))
  pixelate(src, width, height, cols, rows, (r, g, b, x, y) => {
    const t = bayer(x, y) * dither
    return nearest(clamp(r + t), clamp(g + t), clamp(b + t), palette)
  })
}

function vhs(src: Uint8ClampedArray, width: number, height: number, intensity: number, seed: number, time: number) {
  const copy = new Uint8ClampedArray(src)
  const shift = Math.max(1, Math.round(2 * intensity))
  const tracking = Math.sin(time * 7.3) * intensity * 2
  for (let y = 0; y < height; y++) {
    const rowJitter = Math.round((fxRandom(seed, y + Math.floor(time * 30)) - 0.5) * 6 * intensity + tracking)
    const wobble = Math.round(Math.sin(y * 0.18 + time * 11) * shift)
    for (let x = 0; x < width; x++) {
      const i = (y * width + x) * 4
      const [r] = read(copy, width, height, x + rowJitter - shift, y)
      const g = read(copy, width, height, x + rowJitter, y)[1]
      const b = read(copy, width, height, x + rowJitter + shift + wobble, y)[2]
      const noise = (fxRandom(seed, x + y * 997 + Math.floor(time * 12) * 13) - 0.5) * 28 * intensity
      const scan = (y & 1) ? 1 - 0.18 * intensity : 1
      src[i] = clamp((r + noise) * scan)
      src[i + 1] = clamp((g + noise * 0.6) * scan)
      src[i + 2] = clamp((b + noise) * scan)
    }
  }
  const bar = Math.max(2, Math.round(height * 0.03 * intensity))
  const barY = height - bar - Math.round((time * 17 % 1) * 6)
  for (let y = barY; y < Math.min(height, barY + bar); y++) {
    for (let x = 0; x < width; x++) {
      const i = (y * width + x) * 4
      const n = fxRandom(seed, x * 3 + y + Math.floor(time * 40)) * 255
      src[i] = n; src[i + 1] = n * 0.85; src[i + 2] = n * 0.7
    }
  }
}

function crt(src: Uint8ClampedArray, width: number, height: number, intensity: number) {
  const copy = new Uint8ClampedArray(src)
  const cx = width / 2, cy = height / 2, maxD = Math.hypot(cx, cy)
  for (let y = 0; y < height; y++) {
    const scan = (y & 1) ? 1 - 0.28 * intensity : 1
    for (let x = 0; x < width; x++) {
      const i = (y * width + x) * 4
      const [r, g, b] = read(copy, width, height, x, y)
      const mask = x % 3
      const mr = mask === 0 ? 1.18 : 0.82
      const mg = mask === 1 ? 1.18 : 0.82
      const mb = mask === 2 ? 1.18 : 0.82
      const vig = 1 - Math.pow(Math.hypot(x - cx, y - cy) / maxD, 2) * 0.45 * intensity
      src[i] = clamp(r * mr * scan * vig)
      src[i + 1] = clamp(g * mg * scan * vig)
      src[i + 2] = clamp(b * mb * scan * vig)
    }
  }
}

function psxJitter(src: Uint8ClampedArray, width: number, height: number, cols: number, intensity: number, time: number) {
  const rows = Math.max(36, Math.round(cols * height / Math.max(1, width)))
  pixelate(src, width, height, cols, rows, (r, g, b, x, y) => {
    const t = bayer(x, y) * (18 * intensity)
    const wobble = Math.sin((y + time * 9) * 0.7) * intensity
    return [
      quantize(r + wobble * 4, 32, t),
      quantize(g, 32, t),
      quantize(b - wobble * 3, 32, t),
    ]
  })
}

export function applyRetroPixels(
  pixels: Uint8ClampedArray,
  width: number,
  height: number,
  kind: RetroLookId,
  intensity: number,
  seed: number,
  time: number,
) {
  const amount = Math.max(0.1, Math.min(2, intensity))
  if (kind === 'vhs') { vhs(pixels, width, height, amount, seed, time); return }
  if (kind === 'crt') { crt(pixels, width, height, amount); return }
  if (kind === 'psx') {
    psxJitter(pixels, width, height, colsFor(width, height, 320, amount).cols, amount, time)
    return
  }
  if (kind === 'n64') {
    const { cols } = colsFor(width, height, 320, amount)
    bitcrush(pixels, width, height, cols, 5, 10 * amount)
    const copy = new Uint8ClampedArray(pixels)
    for (let i = 0; i < pixels.length; i += 4) {
      const x = (i / 4) % width
      const mix = 0.35 * amount
      const [r, g, b] = read(copy, width, height, x + 1, Math.floor(i / 4 / width))
      pixels[i] = clamp(pixels[i] * (1 - mix) + r * mix)
      pixels[i + 1] = clamp(pixels[i + 1] * (1 - mix) + g * mix)
      pixels[i + 2] = clamp(pixels[i + 2] * (1 - mix) + b * mix)
    }
    return
  }
  if (kind === 'nes') { palettize(pixels, width, height, colsFor(width, height, 256, amount).cols, NES, 22 * amount); return }
  if (kind === 'snes') { bitcrush(pixels, width, height, colsFor(width, height, 256, amount).cols, 5, 8 * amount); return }
  if (kind === 'genesis') { bitcrush(pixels, width, height, colsFor(width, height, 320, amount).cols, 3, 28 * amount); return }
  if (kind === 'c64') { palettize(pixels, width, height, colsFor(width, height, 160, amount).cols, C64, 16 * amount); return }
  if (kind === 'gameboy') {
    const { cols, rows } = { cols: Math.max(80, Math.round(160 / amount)), rows: Math.max(72, Math.round(144 / amount)) }
    pixelate(pixels, width, height, cols, rows, (r, g, b) => GB[Math.max(0, Math.min(3, Math.round(luma(r, g, b) / 255 * 3)))])
    return
  }
  const { cols, rows } = { cols: Math.max(80, Math.round(160 / amount)), rows: Math.max(72, Math.round(144 / amount)) }
  pixelate(pixels, width, height, cols, rows, (r, g, b, x, y) => {
    const t = bayer(x, y) * 14 * amount
    return [quantize(r, 8, t), quantize(g, 8, t), quantize(b, 8, t)]
  })
}

export function applyRetroLook(
  ctx: CanvasRenderingContext2D,
  width: number,
  height: number,
  cue: SceneFx,
  seconds: number,
) {
  if (typeof ctx.getImageData !== 'function' || typeof ctx.putImageData !== 'function') return
  if (!isRetroLook(cue.kind)) return
  let image: ImageData
  try { image = ctx.getImageData(0, 0, width, height) } catch { return }
  applyRetroPixels(image.data, width, height, cue.kind, cue.intensity, cue.seed, seconds - cue.start)
  ctx.putImageData(image, 0, 0)
}
