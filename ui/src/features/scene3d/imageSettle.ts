// A painted set layer stands on the ground at the line of its lowest pieces, but most of its pieces end higher: a
// house's painted grass stops above where a fence post reaches, so under the house the floor shows through the key and
// the house seems to float. Settling the picture carries each column's lowest painted colour down to the bottom edge,
// so every piece stands on a band of its own ground that meets the floor; the part under the floor stays hidden by it.
import { CanvasTexture, type Texture } from 'three'
import type { ImageColorKey } from './imageColorKey'

const RUN = 4            // rows of solid paint a column needs at its foot: a lone speck or a key halo is not a piece
const SAMPLE = 10        // rows above the foot whose paint gives the band its colour (the foot row itself is the halo)
const BLEND = 6          // columns either side whose band colours are averaged, so the bands do not streak
const REACH = 0.55       // only pieces whose foot is in the lower part of the picture settle (not birds or clouds)
const SPILL = 28         // a pixel whose key channels stand this far above the others is key colour bled into the edge

const keyRgb = (hex: string): [number, number, number] => [1, 3, 5].map(start => parseInt(hex.slice(start, start + 2), 16)) as [number, number, number]

export type SettleLook = { floor: number; color?: string }   // floor: share of the picture under the floor line; color: the floor's

const hexRgb = (hex: string | undefined): [number, number, number] | undefined =>
  hex && /^#[\da-f]{6}$/i.test(hex) ? keyRgb(hex) : undefined
const smooth = (t: number) => t * t * (3 - 2 * t)

/** Fill under each column's lowest piece down to the floor line, in place: from the piece's own colour at its foot to
 * the floor's colour at the line (the piece's colour in shade when the floor's is unknown), so the ground seems to
 * climb to every piece. Columns already reaching the floor are left alone. Returns how many columns settled. */
export function settleColumns(data: Uint8ClampedArray | Uint8Array, width: number, height: number, key?: ImageColorKey, look: SettleLook = { floor: 0 }): number {
  const keyed = key ? keyRgb(key.color) : undefined
  const limit = key ? (key.tolerance + key.softness) * Math.sqrt(3) * 255 : 0
  const high = keyed ? [0, 1, 2].filter(c => keyed[c] > 127) : [], low = keyed ? [0, 1, 2].filter(c => keyed[c] <= 127) : []
  const spill = (i: number) => high.length > 0 && low.length > 0
    && Math.min(...high.map(c => data[i + c])) - Math.max(...low.map(c => data[i + c])) > SPILL
  const solid = (x: number, y: number) => {
    const i = (y * width + x) * 4
    if (data[i + 3] < 128) return false
    if (!keyed) return true
    return Math.hypot(data[i] - keyed[0], data[i + 1] - keyed[1], data[i + 2] - keyed[2]) > limit && !spill(i)
  }
  const feet: number[] = new Array(width).fill(-1)
  const colours: [number, number, number][] = new Array(width)
  for (let x = 0; x < width; x++) {
    for (let y = height - 1; y >= RUN; y--) {
      let run = 0
      while (run < RUN && solid(x, y - run)) run++
      if (run < RUN) continue
      if (y >= height * (1 - REACH)) {
        feet[x] = y
        let r = 0, g = 0, b = 0, n = 0
        for (let k = 2; k < 2 + SAMPLE && y - k >= 0; k++) {
          if (!solid(x, y - k)) continue
          const i = ((y - k) * width + x) * 4; r += data[i]; g += data[i + 1]; b += data[i + 2]; n++
        }
        if (n) colours[x] = [r / n, g / n, b / n]
        else feet[x] = -1
      }
      break
    }
  }
  const line = Math.round(height * (1 - Math.max(0, Math.min(0.9, look.floor))))   // the floor line's row
  const floorColour = hexRgb(look.color)
  let settled = 0
  for (let x = 0; x < width; x++) {
    if (feet[x] < 0 || feet[x] >= line - 1) continue
    let r = 0, g = 0, b = 0, n = 0
    for (let dx = -BLEND; dx <= BLEND; dx++) {
      const c = colours[x + dx]
      if (feet[x + dx] >= 0 && c) { r += c[0]; g += c[1]; b += c[2]; n++ }
    }
    const own: [number, number, number] = [r / n, g / n, b / n]
    const end = floorColour ?? [own[0] * 0.62, own[1] * 0.62, own[2] * 0.62]
    const span = Math.max(1, line - feet[x])
    for (let y = feet[x] + 1; y < height; y++) {
      const t = smooth(Math.min(1, (y - feet[x]) / span)), i = (y * width + x) * 4
      data[i] = own[0] + (end[0] - own[0]) * t; data[i + 1] = own[1] + (end[1] - own[1]) * t; data[i + 2] = own[2] + (end[2] - own[2]) * t
      data[i + 3] = 255
    }
    settled++
  }
  return settled
}

/** A copy of the layer's texture with its pieces settled, or the texture itself where pixels cannot be read. */
export function settledTexture(texture: Texture, key?: ImageColorKey, look?: SettleLook): Texture {
  const image = texture.image as (CanvasImageSource & { width?: number; height?: number }) | undefined
  const width = image?.width ?? 0, height = image?.height ?? 0
  if (!image || !width || !height || typeof document === 'undefined') return texture
  const canvas = document.createElement('canvas')
  canvas.width = width; canvas.height = height
  const context = canvas.getContext('2d', { willReadFrequently: true })
  if (!context) return texture
  try {
    context.drawImage(image, 0, 0)
    const pixels = context.getImageData(0, 0, width, height)
    if (!settleColumns(pixels.data, width, height, key, look)) return texture
    context.putImageData(pixels, 0, 0)
  } catch {
    return texture        // a picture from another origin cannot be read back
  }
  const settled = new CanvasTexture(canvas)
  settled.colorSpace = texture.colorSpace
  settled.wrapS = texture.wrapS; settled.wrapT = texture.wrapT
  settled.minFilter = texture.minFilter; settled.magFilter = texture.magFilter
  settled.anisotropy = texture.anisotropy; settled.flipY = texture.flipY
  settled.needsUpdate = true
  return settled
}
