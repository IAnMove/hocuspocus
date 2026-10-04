// Optional risograph press. Paint runs it only when `finish.riso` is set.
// The working grid is half the frame (nearest-neighbor back) so a 1080p pass stays near 40ms.
import { getSceneLayerTiming } from '../sceneTimeline'
import type { SceneLayer } from '../../types'

export type SceneRiso = {
  paper: string
  sepPaper: string
  inks: string[]
  angles: number[]
  cells: number[]
  solids: number[]
  misreg: number
  cutKick: number
  beatKick: number
  gamma: number
  gain: number
  kLo: number
  kHi: number
  lift: number
  grain: number
  fibre: number
  inkTex: number
  vignette: number
}

export type RisoCutLayer = {
  type: string
  visible?: boolean
  animation: SceneLayer['animation']
}

export type RisoPressTime = { seconds: number; envelope: number; cut: number }

const HEX = /^#[0-9a-fA-F]{6}$/
const ANGLES = [15, 75, 45, 105]
const CELLS = [7, 7, 7, 6]
const SOLIDS = [0.88, 0.88, 0.88, 0.5]
const DIR_X = [1, -0.64, 0.26, -0.83]
const DIR_Y = [0.24, 0.77, -0.97, -0.56]
const TILE = 64
const TILE_MASK = TILE - 1

const clamp = (value: number, min: number, max: number) => Math.max(min, Math.min(max, value))
const num = (value: unknown, fallback: number, min: number, max: number) =>
  typeof value === 'number' && Number.isFinite(value) ? clamp(value, min, max) : fallback

function hexColor(value: unknown, fallback: string) {
  return typeof value === 'string' && HEX.test(value) ? value : fallback
}

function inksOf(raw: unknown): string[] | undefined {
  if (!Array.isArray(raw) || raw.length < 1 || raw.length > 4) return undefined
  const inks: string[] = []
  for (const item of raw) {
    if (typeof item !== 'string' || !HEX.test(item)) return undefined
    inks.push(item)
  }
  return inks
}

function series(raw: unknown, count: number, fallback: readonly number[], low: number, high: number) {
  const out: number[] = []
  for (let index = 0; index < count; index += 1) {
    const item = Array.isArray(raw) ? raw[index] : undefined
    out.push(num(item, fallback[Math.min(index, fallback.length - 1)], low, high))
  }
  return out
}

export function takeRiso(raw: unknown): SceneRiso | undefined {
  if (!raw || typeof raw !== 'object') return undefined
  const value = raw as Partial<SceneRiso>
  const inks = inksOf(value.inks)
  if (!inks) return undefined
  return {
    paper: hexColor(value.paper, '#EFE6D2'),
    sepPaper: hexColor(value.sepPaper, '#F4EEE2'),
    inks,
    angles: series(value.angles, inks.length, ANGLES, 0, 180),
    cells: series(value.cells, inks.length, CELLS, 2, 24),
    solids: series(value.solids, inks.length, SOLIDS, 0, 1),
    misreg: num(value.misreg, 1.2, 0, 8),
    cutKick: num(value.cutKick, 16, 0, 48),
    beatKick: num(value.beatKick, 4, 0, 24),
    gamma: num(value.gamma, 1.25, 0.2, 3),
    gain: num(value.gain, 1, 0, 2),
    kLo: num(value.kLo, 0.5, 0, 1),
    kHi: num(value.kHi, 0.72, 0, 1),
    lift: num(value.lift, 0, -0.2, 0.2),
    grain: num(value.grain, 0.022, 0, 0.2),
    fibre: num(value.fibre, 1, 0, 2),
    inkTex: num(value.inkTex, 0.22, 0, 1),
    vignette: num(value.vignette, 0.35, 0, 1),
  }
}

function rgb01(hex: string): [number, number, number] {
  const parsed = Number.parseInt(hex.slice(1), 16)
  return [(parsed >> 16) / 255, ((parsed >> 8) & 255) / 255, (parsed & 255) / 255]
}

function matInv(source: number[][]) {
  const n = source.length
  const matrix = source.map((row, index) => [...row, ...Array.from({ length: n }, (_, column) => (index === column ? 1 : 0))])
  for (let column = 0; column < n; column += 1) {
    let pivot = column
    for (let row = column + 1; row < n; row += 1) if (Math.abs(matrix[row][column]) > Math.abs(matrix[pivot][column])) pivot = row
    const swap = matrix[column]
    matrix[column] = matrix[pivot]
    matrix[pivot] = swap
    const diag = matrix[column][column] || 1e-9
    for (let index = 0; index < n * 2; index += 1) matrix[column][index] /= diag
    for (let row = 0; row < n; row += 1) {
      if (row === column) continue
      const factor = matrix[row][column]
      for (let index = 0; index < n * 2; index += 1) matrix[row][index] -= factor * matrix[column][index]
    }
  }
  return matrix.map(row => row.slice(n))
}

function densityMatrix(paper: [number, number, number], inks: Array<[number, number, number]>) {
  const rows = inks.map(ink => [0, 1, 2].map(channel => Math.max(-Math.log(Math.max(ink[channel], 0.02) / paper[channel]), 0)))
  const n = rows.length
  const gram = Array.from({ length: n }, (_, row) => Array.from({ length: n }, (_, column) =>
    rows[row][0] * rows[column][0] + rows[row][1] * rows[column][1] + rows[row][2] * rows[column][2]))
  for (let index = 0; index < n; index += 1) gram[index][index] += 1e-3
  const inverse = n ? matInv(gram) : []
  const packed = new Float32Array(9)
  for (let row = 0; row < n; row += 1) {
    for (let column = 0; column < 3; column += 1) {
      let sum = 0
      for (let other = 0; other < n; other += 1) sum += inverse[row][other] * rows[other][column]
      packed[column * 3 + row] = sum
    }
  }
  return packed
}

type Prepared = {
  count: number
  chromatic: number
  useK: boolean
  matrix: Float32Array
  dLut: [Float32Array, Float32Array, Float32Array]
  gLut: Uint8Array
  kLut: Uint8Array
  paper: [number, number, number]
  ink: Array<[number, number, number]>
  cells: number[]
  solids: number[]
  cos: Float64Array
  sin: Float64Array
  dirX: Float64Array
  dirY: Float64Array
  misreg: number
  cutKick: number
  beatKick: number
  grain: number
  fibre: number
  inkTex: number
  vignette: number
}

function densityLut(channelPaper: number, lift: number) {
  const lut = new Float32Array(256)
  for (let index = 0; index < 256; index += 1) {
    const lifted = Math.min(1, Math.max(0.004, index / 255 + lift))
    lut[index] = Math.max(-Math.log(lifted / channelPaper), 0)
  }
  return lut
}

function gammaLut(gamma: number, gain: number) {
  const lut = new Uint8Array(1024)
  for (let index = 0; index < 1024; index += 1) {
    lut[index] = clamp(Math.pow(index / 1023, gamma) * gain * 255, 0, 255) | 0
  }
  return lut
}

function blackLut(kLo: number, kHi: number) {
  const lut = new Uint8Array(256)
  const span = Math.max(0.001, kHi - kLo)
  for (let index = 0; index < 256; index += 1) {
    const t = clamp((1 - index / 255 - kLo) / span, 0, 1)
    lut[index] = (t * t * (3 - 2 * t) * 255) | 0
  }
  return lut
}

function unitDirection(index: number): [number, number] {
  const x = DIR_X[index] ?? 1
  const y = DIR_Y[index] ?? 0
  const length = Math.hypot(x, y) || 1
  return [x / length, y / length]
}

function prepare(riso: SceneRiso): Prepared {
  const useK = riso.inks.length === 4
  const chromatic = useK ? 3 : riso.inks.length
  const sep = rgb01(riso.sepPaper)
  const colors = riso.inks.map(rgb01)
  const cos = new Float64Array(riso.inks.length)
  const sin = new Float64Array(riso.inks.length)
  const dirX = new Float64Array(riso.inks.length)
  const dirY = new Float64Array(riso.inks.length)
  for (let index = 0; index < riso.inks.length; index += 1) {
    const radians = (riso.angles[index] ?? ANGLES[index]) * Math.PI / 180
    cos[index] = Math.cos(radians)
    sin[index] = Math.sin(radians)
    const [x, y] = unitDirection(index)
    dirX[index] = x
    dirY[index] = y
  }
  return {
    count: riso.inks.length,
    chromatic,
    useK,
    matrix: densityMatrix(sep, colors.slice(0, chromatic)),
    dLut: [densityLut(sep[0], riso.lift), densityLut(sep[1], riso.lift), densityLut(sep[2], riso.lift)],
    gLut: gammaLut(riso.gamma, riso.gain),
    kLut: blackLut(riso.kLo, Math.max(riso.kHi, riso.kLo)),
    paper: rgb01(riso.paper),
    ink: colors,
    cells: riso.cells,
    solids: riso.solids,
    cos, sin, dirX, dirY,
    misreg: riso.misreg,
    cutKick: riso.cutKick,
    beatKick: riso.beatKick,
    grain: riso.grain,
    fibre: riso.fibre,
    inkTex: riso.inkTex,
    vignette: riso.vignette,
  }
}

let preparedKey = ''
let preparedCache: Prepared | undefined

function preparedFor(riso: SceneRiso) {
  const key = JSON.stringify(riso)
  if (preparedCache && key === preparedKey) return preparedCache
  preparedCache = prepare(riso)
  preparedKey = key
  return preparedCache
}

function hash01(x: number, y: number) {
  let n = Math.imul(x | 0, 374761393) + Math.imul(y | 0, 668265263)
  n = Math.imul(n ^ (n >>> 13), 1274126177)
  return (n >>> 0) / 4294967296
}

function valueNoise(x: number, y: number) {
  const ix = Math.floor(x)
  const iy = Math.floor(y)
  const fx = x - ix
  const fy = y - iy
  const ux = fx * fx * (3 - 2 * fx)
  const uy = fy * fy * (3 - 2 * fy)
  const a = hash01(ix, iy)
  const b = hash01(ix + 1, iy)
  const c = hash01(ix, iy + 1)
  const d = hash01(ix + 1, iy + 1)
  return a + (b - a) * ux + (c - a) * uy + (a - b - c + d) * ux * uy
}

function fbm(x: number, y: number) {
  let amplitude = 0.5
  let sum = 0
  let px = x
  let py = y
  for (let octave = 0; octave < 4; octave += 1) {
    sum += amplitude * valueNoise(px, py)
    px = px * 2.03 + 1.7
    py = py * 2.03 + 1.7
    amplitude *= 0.5
  }
  return sum
}

type TextureTile = { key: string; paper: Float32Array; ink: Float32Array; grain: Float32Array }

function buildTexture(seed: number, fibre: number, inkTex: number, grain: number): TextureTile {
  const paper = new Float32Array(TILE * TILE)
  const ink = new Float32Array(TILE * TILE)
  const grainTile = new Float32Array(TILE * TILE)
  for (let y = 0; y < TILE; y += 1) {
    for (let x = 0; x < TILE; x += 1) {
      const index = y * TILE + x
      const thread = fbm((x + seed) * 0.22, y * 0.03) - 0.5
      const tooth = fbm(x * 0.37 + 3.1, y * 0.37 + seed) - 0.5
      paper[index] = 1 + fibre * (0.06 * thread + 0.05 * tooth)
      const mottling = fbm(x * 0.09 + seed, y * 0.09)
      const speck = hash01(x + seed, y * 3 + 2) > 0.985 ? 1 : 0
      ink[index] = 1 - inkTex * (0.55 * mottling + 0.45 * speck)
      grainTile[index] = grain * (hash01(x + seed * 3, y + 11) - 0.5)
    }
  }
  return { key: '', paper, ink, grain: grainTile }
}

let textureCache: TextureTile | undefined

function textureFor(prep: Prepared, seed: number) {
  const key = `${seed}|${prep.fibre}|${prep.inkTex}|${prep.grain}`
  if (textureCache?.key === key) return textureCache
  textureCache = { ...buildTexture(seed, prep.fibre, prep.inkTex, prep.grain), key }
  return textureCache
}

let poolW = 0
let poolH = 0
let poolPlates: Uint8Array[] = []
let poolOut: Uint8ClampedArray | undefined

function buffers(width: number, height: number) {
  if (poolW !== width || poolH !== height) {
    poolW = width
    poolH = height
    poolPlates = [0, 1, 2, 3].map(() => new Uint8Array(width * height))
    poolOut = new Uint8ClampedArray(width * height * 4)
  }
  return { plates: poolPlates, out: poolOut as Uint8ClampedArray }
}

function writeSeparation(src: Uint8ClampedArray, srcW: number, scale: number, width: number, height: number, plates: Uint8Array[], prep: Prepared) {
  const matrix = prep.matrix
  const d0 = prep.dLut[0]
  const d1 = prep.dLut[1]
  const d2 = prep.dLut[2]
  const gLut = prep.gLut
  const kLut = prep.kLut
  const chromatic = prep.chromatic
  for (let y = 0; y < height; y += 1) {
    const sy = y * scale
    for (let x = 0; x < width; x += 1) {
      const source = (sy * srcW + x * scale) << 2
      const r = src[source]
      const g = src[source + 1]
      const b = src[source + 2]
      const alpha = src[source + 3] / 255
      const lum = (r * 77 + g * 150 + b * 29) >>> 8
      const k = prep.useK ? kLut[lum] : 0
      const removed = k * (2.2 / 255)
      let dr = d0[r] - removed
      let dg = d1[g] - removed
      let db = d2[b] - removed
      if (dr < 0) dr = 0
      if (dg < 0) dg = 0
      if (db < 0) db = 0
      const pixel = y * width + x
      for (let row = 0; row < chromatic; row += 1) {
        let coverage = matrix[row] * dr + matrix[3 + row] * dg + matrix[6 + row] * db
        if (coverage < 0) coverage = 0
        else if (coverage > 1) coverage = 1
        plates[row][pixel] = (gLut[(coverage * 1023) | 0] * alpha) | 0
      }
      if (prep.useK) plates[chromatic][pixel] = (gLut[((k / 255) * 1023) | 0] * alpha) | 0
    }
  }
}

/** Separate `pixels` into planar coverages (plate-major, 0–255). One plate per ink. */
export function separateRiso(pixels: Uint8ClampedArray, width: number, height: number, riso: SceneRiso) {
  const prep = preparedFor(riso)
  const count = prep.count
  const plates = Array.from({ length: count }, () => new Uint8Array(width * height))
  writeSeparation(pixels, width, 1, width, height, plates, prep)
  const packed = new Uint8Array(count * width * height)
  for (let plate = 0; plate < count; plate += 1) packed.set(plates[plate], plate * width * height)
  return packed
}

function clamp8(value: number) {
  if (value <= 0) return 0
  if (value >= 255) return 255
  return value | 0
}

function shiftsFor(prep: Prepared, cut: number, envelope: number, scale: number) {
  const ox = new Float64Array(prep.count)
  const oy = new Float64Array(prep.count)
  const magnitude = prep.misreg + prep.cutKick * cut + prep.beatKick * envelope
  for (let index = 0; index < prep.count; index += 1) {
    ox[index] = prep.dirX[index] * magnitude / scale
    oy[index] = prep.dirY[index] * magnitude / scale
  }
  return { ox, oy }
}

function printPlates(out: Uint8ClampedArray, width: number, height: number, plates: Uint8Array[], prep: Prepared, shifts: { ox: Float64Array; oy: Float64Array }, seed: number, scale: number) {
  const texture = textureFor(prep, seed)
  const cell = new Float64Array(prep.count)
  const rScale = new Float64Array(prep.count)
  const solid = new Float64Array(prep.count)
  const rowCos = new Float64Array(prep.count)
  const rowSin = new Float64Array(prep.count)
  for (let ink = 0; ink < prep.count; ink += 1) {
    cell[ink] = Math.max(1.25, prep.cells[ink] / scale)
    rScale[ink] = (cell[ink] * 0.72) ** 2
    solid[ink] = prep.solids[ink] * 255
  }
  for (let y = 0; y < height; y += 1) {
    const vignetteY = prep.vignette * (((y + 0.5) / height - 0.5) ** 2) * 1.6
    for (let ink = 0; ink < prep.count; ink += 1) {
      rowCos[ink] = prep.cos[ink] * y
      rowSin[ink] = prep.sin[ink] * y
    }
    const yMask = (y & TILE_MASK) * TILE
    for (let x = 0; x < width; x += 1) {
      const fibre = texture.paper[yMask + (x & TILE_MASK)]
      let red = prep.paper[0] * fibre
      let green = prep.paper[1] * fibre
      let blue = prep.paper[2] * fibre
      for (let ink = 0; ink < prep.count; ink += 1) {
        const plane = plates[ink]
        const inkCell = cell[ink]
        let localX = Math.round(x - shifts.ox[ink])
        let localY = Math.round(y - shifts.oy[ink])
        if (localX < 0) localX = 0
        else if (localX >= width) localX = width - 1
        if (localY < 0) localY = 0
        else if (localY >= height) localY = height - 1
        const local = plane[localY * width + localX]
        let amount = 0
        if (local >= solid[ink]) amount = 1
        else if (local > 5) {
          const cosine = prep.cos[ink]
          const sine = prep.sin[ink]
          const qx = cosine * x - rowSin[ink]
          const qy = sine * x + rowCos[ink]
          const ccx = (Math.floor(qx / inkCell) + 0.5) * inkCell
          const ccy = (Math.floor(qy / inkCell) + 0.5) * inkCell
          let centerX = Math.round(cosine * ccx + sine * ccy - shifts.ox[ink])
          let centerY = Math.round(-sine * ccx + cosine * ccy - shifts.oy[ink])
          if (centerX < 0) centerX = 0
          else if (centerX >= width) centerX = width - 1
          if (centerY < 0) centerY = 0
          else if (centerY >= height) centerY = height - 1
          const center = plane[centerY * width + centerX]
          if (center > 5 && (qx - ccx) ** 2 + (qy - ccy) ** 2 <= (center / 255) * rScale[ink]) amount = 1
        }
        const printed = amount * texture.ink[yMask + ((x + ink * 13) & TILE_MASK)]
        if (printed <= 0) continue
        const color = prep.ink[ink]
        red *= 1 - printed + printed * color[0]
        green *= 1 - printed + printed * color[1]
        blue *= 1 - printed + printed * color[2]
      }
      const vignette = 1 - vignetteY - prep.vignette * (((x + 0.5) / width - 0.5) ** 2) * 1.6
      const grain = texture.grain[(y & TILE_MASK) * TILE + (x & TILE_MASK)]
      const offset = (y * width + x) << 2
      out[offset] = clamp8((red * vignette + grain) * 255)
      out[offset + 1] = clamp8((green * vignette + grain) * 255)
      out[offset + 2] = clamp8((blue * vignette + grain) * 255)
      out[offset + 3] = 255
    }
  }
}

function blitNearest(small: Uint8ClampedArray, smallW: number, smallH: number, dest: Uint8ClampedArray, width: number, height: number) {
  if (smallW === width && smallH === height) {
    dest.set(small)
    return
  }
  for (let y = 0; y < height; y += 1) {
    const sourceRow = Math.min(smallH - 1, y >> 1) * smallW
    const destRow = y * width
    for (let x = 0; x < width; x += 1) {
      const source = (sourceRow + Math.min(smallW - 1, x >> 1)) << 2
      const offset = (destRow + x) << 2
      dest[offset] = small[source]
      dest[offset + 1] = small[source + 1]
      dest[offset + 2] = small[source + 2]
      dest[offset + 3] = 255
    }
  }
}

/** Reprint `pixels` in place. `frameScale` 2 means the buffer is already half a frame. */
export function pressRiso(pixels: Uint8ClampedArray, width: number, height: number, riso: SceneRiso, time: RisoPressTime, frameScale = 0) {
  if (width < 1 || height < 1) return
  const prep = preparedFor(riso)
  const scale = frameScale > 0 ? 1 : (width >= 4 && height >= 4 ? 2 : 1)
  const pitch = frameScale > 0 ? frameScale : scale
  const workW = scale === 2 ? width >> 1 : width
  const workH = scale === 2 ? height >> 1 : height
  const { plates, out } = buffers(workW, workH)
  writeSeparation(pixels, width, scale, workW, workH, plates, prep)
  const seed = Math.round(time.seconds * 12) % 97
  printPlates(out, workW, workH, plates, prep, shiftsFor(prep, time.cut, time.envelope, pitch), seed, pitch)
  if (scale === 2) blitNearest(out, workW, workH, pixels, width, height)
  else pixels.set(out)
}

export function risoPlateShift(riso: SceneRiso, cut: number, envelope: number) {
  const prep = preparedFor(riso)
  const magnitude = prep.misreg + prep.cutKick * cut + prep.beatKick * envelope
  const shifts: Array<[number, number]> = []
  for (let index = 0; index < prep.count; index += 1) shifts.push([prep.dirX[index] * magnitude, prep.dirY[index] * magnitude])
  return shifts
}

function rememberCut(since: number, seconds: number, mark: number, accept: boolean) {
  if (!accept || seconds < mark) return since
  return Math.min(since, seconds - mark)
}

/** 1 on an image/video cut, then an exponential settle. 0 when the document has no interior cut. */
export function risoCutEnvelope(seconds: number, layers: readonly RisoCutLayer[] | undefined, duration: number) {
  if (!layers?.length || !(duration > 0)) return 0
  let since = 99
  for (const layer of layers) {
    if (layer.visible === false || (layer.type !== 'image' && layer.type !== 'video')) continue
    const timing = getSceneLayerTiming(layer as SceneLayer)
    const start = timing.offset
    const end = timing.loop ? duration : start + timing.span / timing.speed
    since = rememberCut(since, seconds, start, start > 0.04 && start < duration)
    since = rememberCut(since, seconds, end, !timing.loop && end > 0.04 && end < duration - 0.04)
  }
  return since > 1.5 ? 0 : Math.exp(-since * 9)
}

let scratch: HTMLCanvasElement | undefined

function halfCanvas(width: number, height: number) {
  if (typeof document === 'undefined') return undefined
  if (!scratch) scratch = document.createElement('canvas')
  if (scratch.width !== width || scratch.height !== height) {
    scratch.width = width
    scratch.height = height
  }
  return scratch
}

export function paintRisoPress(ctx: CanvasRenderingContext2D, width: number, height: number, seconds: number, riso: SceneRiso, envelope = 0, layers?: readonly RisoCutLayer[], duration = 0) {
  const time = { seconds, envelope, cut: risoCutEnvelope(seconds, layers, duration) }
  const work = width >= 4 && height >= 4 ? halfCanvas(width >> 1, height >> 1) : undefined
  const small = work?.getContext('2d')
  if (work && small) {
    small.drawImage(ctx.canvas, 0, 0, work.width, work.height)
    const frame = small.getImageData(0, 0, work.width, work.height)
    pressRiso(frame.data, work.width, work.height, riso, time, 2)
    small.putImageData(frame, 0, 0)
    const smooth = ctx.imageSmoothingEnabled
    ctx.imageSmoothingEnabled = false
    ctx.drawImage(work, 0, 0, width, height)
    ctx.imageSmoothingEnabled = smooth
    return
  }
  const frame = ctx.getImageData(0, 0, width, height)
  pressRiso(frame.data, width, height, riso, time)
  ctx.putImageData(frame, 0, 0)
}
