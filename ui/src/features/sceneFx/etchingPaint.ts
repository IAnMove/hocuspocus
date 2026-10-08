/** Etching: luminance becomes cross-hatched sepia ink on paper. The same pixels always produce the same plate. */

const PAPER = [236, 220, 188] as const
const INK = [62, 38, 18] as const
const SPACING = [3, 4, 6, 10] as const

export function isEtching(kind: string): boolean {
  return kind === 'etching'
}

function clamp(value: number) {
  return value < 0 ? 0 : value > 255 ? 255 : value
}

function luma(r: number, g: number, b: number) {
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

/** 0–3 hatch densities, or 4 for bare paper. */
function band(value: number) {
  if (value < 64) return 0
  if (value < 120) return 1
  if (value < 180) return 2
  if (value < 220) return 3
  return 4
}

function grain(x: number, y: number) {
  let n = Math.imul(x, 374761393) + Math.imul(y, 668265263)
  n = Math.imul(n ^ (n >>> 13), 1274126177)
  return (n >>> 24) - 128
}

function hatched(x: number, y: number, density: number) {
  const spacing = SPACING[density]
  const down = (x + y) % spacing === 0
  if (density >= 2) return down
  return down || (x + spacing * 8 - y) % spacing === 0
}

/** Replace RGB in place. Alpha stays. Paper carries a fixed grain so two runs of one frame match. */
export function applyEtching(pixels: Uint8ClampedArray, width: number, height: number) {
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const i = (y * width + x) * 4
      const density = band(luma(pixels[i], pixels[i + 1], pixels[i + 2]))
      const ink = density < 4 && hatched(x, y, density)
      const speckle = ink ? 0 : grain(x, y) * 0.06
      const color = ink ? INK : PAPER
      pixels[i] = clamp(color[0] + speckle)
      pixels[i + 1] = clamp(color[1] + speckle)
      pixels[i + 2] = clamp(color[2] + speckle * 0.6)
    }
  }
}

export function applyEtchingLook(ctx: CanvasRenderingContext2D, width: number, height: number) {
  if (typeof ctx.getImageData !== 'function' || typeof ctx.putImageData !== 'function') return
  let image: ImageData
  try { image = ctx.getImageData(0, 0, width, height) } catch { return }
  applyEtching(image.data, width, height)
  ctx.putImageData(image, 0, 0)
}
