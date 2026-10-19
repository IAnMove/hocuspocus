// A painted set layer stands on the ground at the line of its lowest pieces, but most of its pieces end higher: a
// house's painted grass stops above where a fence post reaches, so under the house the floor shows through the key and
// the house seems to float. Settling the picture carries the ground up to each piece that stands just above the floor
// line: a band under it, in the floor's colour and grain (a ground style's) with the piece's shadow on it, down to the
// bottom edge; the part under the floor stays hidden by it. A piece far above the line (an arch's lintel, a tree's
// crown) is not standing on the floor there, so its gap stays; so does a sliver too narrow to be a piece.
import { CanvasTexture, type Texture } from 'three'
import type { ImageColorKey } from './imageColorKey'
import { groundColor, groundPixels, isGroundStyle, type GroundStyle } from './groundStyles'

const RUN = 4            // rows of solid paint a column needs at its foot: a lone speck or a key halo is not a piece
const SAMPLE = 10        // rows above the foot whose paint gives the band its first colour (the foot row itself is the halo)
const BLEND = 6          // columns either side whose colours are averaged, so the bands do not streak
const REACH = 0.55       // only pieces whose foot is in the lower part of the picture settle (not birds or clouds)
const SPILL = 28         // a pixel whose key channels stand this far above the others is key colour bled into the edge
const MAX_GAP = 0.12     // a foot further than this share of the picture above the floor line is not standing on it
const MIN_SPAN = 0.008   // a run of settling columns narrower than this share of the picture is a blade, not a piece
const CONTACT = 3        // rows under a piece over which the band turns from its own colour to the floor's
const SHADE = 0.72       // right under a piece the floor is this dark (its shadow), lightening to the floor line
const GRAIN = 128        // pixels across the ground style's tile whose grain the band carries
const SLIT = 0.006       // a gap between two settling runs this narrow (share of the picture) is bridged whatever it holds
const BRIDGE = 0.06      // ...and one this narrow too, unless a piece hangs far above its floor (an arch's opening)
const RIM = 0.025        // share of the picture over a band whose key colour is taken out (the painted fringe)
const TAPER = 0.025      // share of the picture over which a band's end slopes down to the floor line, not a cliff
const GRAIN_DEPTH = 0.6  // how much of the ground style's grain shows in the band

type Rgb = [number, number, number]
type Floor = { colour: Rgb; grain?: Float32Array }

const keyRgb = (hex: string): Rgb => [1, 3, 5].map(start => parseInt(hex.slice(start, start + 2), 16)) as Rgb

// floor: share of the picture under the floor line; color: the floor's (#rrggbb); ground: the ground style it stands on
export type SettleLook = { floor: number; color?: string; ground?: GroundStyle }

/** A settle look from a document, or undefined when malformed. */
export function parseSettleLook(raw: unknown): SettleLook | undefined {
  const value = raw as { floor?: unknown; color?: unknown; ground?: unknown } | undefined
  if (!value || typeof value !== 'object' || typeof value.floor !== 'number' || !Number.isFinite(value.floor)) return undefined
  const color = typeof value.color === 'string' && /^#[\da-f]{6}$/i.test(value.color) ? value.color : undefined
  return { floor: Math.max(0, Math.min(0.9, value.floor)), ...(color ? { color } : {}), ...(isGroundStyle(value.ground) ? { ground: value.ground } : {}) }
}

const hexRgb = (hex: string | undefined): Rgb | undefined => hex && /^#[\da-f]{6}$/i.test(hex) ? keyRgb(hex) : undefined
const smooth = (t: number) => { const c = Math.max(0, Math.min(1, t)); return c * c * (3 - 2 * c) }
const mix = (a: Rgb, b: Rgb, t: number): Rgb => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t]

type KeyTest = { solid: (x: number, y: number) => boolean; visible: (i: number) => boolean; excess: (i: number) => number; high: number[] }

/** Whether a pixel is paint (opaque, away from the key colour and not key bled into an edge) or merely shows, and how
 * far its key channels stand above the others (the key colour mixed into it). */
function keyTest(data: Uint8ClampedArray | Uint8Array, width: number, key?: ImageColorKey): KeyTest {
  const keyed = key ? keyRgb(key.color) : undefined
  const limit = key ? (key.tolerance + key.softness) * Math.sqrt(3) * 255 : 0
  const high = keyed ? [0, 1, 2].filter(c => keyed[c] > 127) : [], low = keyed ? [0, 1, 2].filter(c => keyed[c] <= 127) : []
  const excess = (i: number) => high.length > 0 && low.length > 0
    ? Math.min(...high.map(c => data[i + c])) - Math.max(...low.map(c => data[i + c])) : 0
  const visible = (i: number) => data[i + 3] >= 128
    && (!keyed || Math.hypot(data[i] - keyed[0], data[i + 1] - keyed[1], data[i + 2] - keyed[2]) > limit)
  const solid = (x: number, y: number) => { const i = (y * width + x) * 4; return visible(i) && excess(i) <= SPILL }
  return { solid, visible, excess, high }
}

/** Each column's lowest piece in the lower part of the picture (its foot row, or -1) and the colour of the paint
 * just above it. */
function findFeet(data: Uint8ClampedArray | Uint8Array, width: number, height: number, solid: (x: number, y: number) => boolean) {
  const feet: number[] = new Array(width).fill(-1)
  const colours: (Rgb | undefined)[] = new Array(width)
  const footOf = (x: number) => {
    for (let y = height - 1; y >= RUN; y--) {
      let run = 0
      while (run < RUN && solid(x, y - run)) run++
      if (run === RUN) return y
    }
    return -1
  }
  for (let x = 0; x < width; x++) {
    const y = footOf(x)
    if (y < 0 || y < height * (1 - REACH)) continue
    let r = 0, g = 0, b = 0, n = 0
    for (let k = 2; k < 2 + SAMPLE && y - k >= 0; k++) {
      if (!solid(x, y - k)) continue
      const i = ((y - k) * width + x) * 4; r += data[i]; g += data[i + 1]; b += data[i + 2]; n++
    }
    if (n) { feet[x] = y; colours[x] = [r / n, g / n, b / n] }
  }
  return { feet, colours }
}

/** Runs of equal values: [start, end) pairs. */
function runs<T>(values: T[]): [number, number][] {
  const found: [number, number][] = []
  for (let x = 0; x < values.length;) {
    let end = x
    while (end < values.length && values[end] === values[x]) end++
    found.push([x, end]); x = end
  }
  return found
}

/** The averaged colour of a column's piece and its neighbours'. */
function pieceColour(colours: (Rgb | undefined)[], feet: number[], x: number): Rgb {
  let r = 0, g = 0, b = 0, n = 0
  for (let dx = -BLEND; dx <= BLEND; dx++) {
    const c = colours[x + dx]
    if (feet[x + dx] >= 0 && c) { r += c[0]; g += c[1]; b += c[2]; n++ }
  }
  return [r / n, g / n, b / n]
}

type Bands = { top: number[]; tone: (Rgb | undefined)[] }

/** Where each column's band starts (-1: no band) and the colour it starts in. A piece just above the floor line
 * settles, in a run wide enough to be a piece; a gap between two settling runs is bridged, its band starting between
 * theirs, when it is a slit or holds no piece hanging far above the floor (the sky between two houses, not an arch's
 * opening). */
function bandTops(feet: number[], colours: (Rgb | undefined)[], line: number, width: number, height: number): Bands {
  const settles = feet.map(foot => foot >= 0 && foot < line - 1 && line - foot <= MAX_GAP * height)
  for (const [start, end] of runs(settles)) if (settles[start] && end - start < Math.max(2, Math.round(MIN_SPAN * width))) settles.fill(false, start, end)
  const top = feet.map((foot, x) => settles[x] ? foot : -1)
  const tone = top.map((foot, x) => foot >= 0 ? pieceColour(colours, feet, x) : undefined)
  for (const [start, end] of runs(settles)) {
    const left = start - 1, right = end
    if (settles[start] || left < 0 || right >= width) continue
    const opening = feet.slice(start, end).some(foot => foot >= 0 && line - foot > MAX_GAP * height)   // under a lintel
    if (end - start > Math.max(2, Math.round(SLIT * width)) && (opening || end - start > BRIDGE * width)) continue
    for (let x = start; x < end; x++) {
      const t = (x - left) / (right - left)
      top[x] = Math.round(top[left] + (top[right] - top[left]) * t)
      tone[x] = mix(tone[left] as Rgb, tone[right] as Rgb, t)
    }
  }
  taperEnds(top, tone, line, Math.max(2, Math.round(TAPER * width)))
  return { top, tone }
}

/** Slope each band's ends down to the floor line over ``reach`` columns, so it ends in a bank and not a cliff. */
function taperEnds(top: number[], tone: (Rgb | undefined)[], line: number, reach: number) {
  const from = top.slice()
  for (const [start, end] of runs(from.map(row => row >= 0))) {
    if (from[start] >= 0) continue
    for (const [edge, step] of [[start - 1, 1], [end, -1]] as const) {
      if (edge < 0 || edge >= from.length) continue
      for (let k = 1; k <= reach && edge + k * step >= start && edge + k * step < end; k++) {
        const x = edge + k * step, row = Math.round(from[edge] + (line - from[edge]) * smooth(k / reach))
        if (top[x] < 0 || row < top[x]) { top[x] = row; tone[x] = tone[edge] }
      }
    }
  }
}

/** The floor the bands turn into: its colour (given, or the ground style's) and, with a style, its grain. */
function floorOf(look: SettleLook): Floor | undefined {
  const colour = hexRgb(look.color) ?? (look.ground ? keyRgb(groundColor(look.ground)) : undefined)
  if (!colour) return undefined
  if (!look.ground) return { colour }
  const tile = groundPixels(look.ground, 1, GRAIN), grain = new Float32Array(GRAIN * GRAIN)
  let sum = 0
  for (let i = 0; i < grain.length; i++) { grain[i] = (tile[i * 4] + tile[i * 4 + 1] + tile[i * 4 + 2]) / 3; sum += grain[i] }
  const mean = sum / grain.length
  for (let i = 0; i < grain.length; i++) grain[i] = (grain[i] - mean) * GRAIN_DEPTH
  return { colour, grain }
}

/** One band pixel ``depth`` rows under the piece of a band ``span`` rows tall. */
function bandPixel(own: Rgb, floor: Floor | undefined, x: number, y: number, depth: number, span: number): Rgb {
  if (!floor) return mix(own, [own[0] * 0.62, own[1] * 0.62, own[2] * 0.62], smooth(depth / span))
  const shade = SHADE + (1 - SHADE) * smooth(depth / span)
  const grain = floor.grain ? floor.grain[(y % GRAIN) * GRAIN + (x % GRAIN)] : 0
  const ground: Rgb = [floor.colour[0] * shade + grain, floor.colour[1] * shade + grain, floor.colour[2] * shade + grain]
  return mix(own, ground, smooth((depth - 1) / CONTACT))
}

/** One column's band: the key colour taken out of the piece's rim just above it, then the band painted down to the
 * bottom edge over everything that is not paint. */
function paintColumn(data: Uint8ClampedArray | Uint8Array, width: number, height: number, x: number, top: number, own: Rgb, span: number, floor: Floor | undefined, test: KeyTest) {
  for (let y = Math.max(0, top - Math.round(RIM * height)); y <= top; y++) {
    const i = (y * width + x) * 4, excess = test.excess(i)
    if (excess > 0 && test.visible(i)) for (const c of test.high) data[i + c] = Math.max(0, data[i + c] - excess)
  }
  for (let y = top + 1; y < height; y++) {
    if (test.solid(x, y)) continue
    const i = (y * width + x) * 4, [r, g, b] = bandPixel(own, floor, x, y, y - top, span)
    data[i] = r; data[i + 1] = g; data[i + 2] = b; data[i + 3] = 255
  }
}

/** Fill under each piece standing just above the floor line, in place: the floor reaching up to it in its shadow, from
 * the piece's own colour at its foot (the floor's colour, or the piece's in shade, when no floor is known). Columns
 * already reaching the floor, far above it or too few to be a piece are left alone. Returns how many columns settled. */
export function settleColumns(data: Uint8ClampedArray | Uint8Array, width: number, height: number, key?: ImageColorKey, look: SettleLook = { floor: 0 }): number {
  const test = keyTest(data, width, key)
  const { feet, colours } = findFeet(data, width, height, test.solid)
  const line = Math.round(height * (1 - Math.max(0, Math.min(0.9, look.floor))))   // the floor line's row
  const { top, tone } = bandTops(feet, colours, line, width, height)
  const floor = floorOf(look)
  let settled = 0
  for (let x = 0; x < width; x++) {
    if (top[x] < 0) continue
    paintColumn(data, width, height, x, top[x], tone[x] as Rgb, Math.max(1, line - top[x]), floor, test)
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
