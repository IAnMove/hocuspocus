import { fxRandom } from '../../sceneFx/types'

/** Palette slots shared by the painter and the palette texture. Index 0 is
 *  transparent. Stars and glitter use several slots so the palette can make
 *  them twinkle by cycling, without repainting a single pixel. */
export const INDEX = {
  sky: 1, skySteps: 16,
  star: 20, starSteps: 8,
  moon: 30, moonShade: 31, haloInner: 32, haloOuter: 33,
  far: 40, farRim: 41, farShade: 42,
  near: 50, nearRim: 51,
  trees: 60,
} as const

export type IndexedLayer = { width: number; height: number; data: Uint8Array }

const BAYER = [0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5]
export const bayer = (x: number, y: number) => BAYER[(y & 3) * 4 + (x & 3)] / 16

function layer(width: number, height: number): IndexedLayer {
  return { width, height, data: new Uint8Array(width * height) }
}

function set(target: IndexedLayer, x: number, y: number, index: number) {
  if (x < 0 || y < 0 || x >= target.width || y >= target.height) return
  target.data[y * target.width + x] = index
}

/** A ridge line in rows from the top: fractal roughness, then a few peaks. */
export function ridge(seed: number, width: number, base: number, rough: number, peaks: number, peakLift = rough): number[] {
  const count = 2 ** Math.ceil(Math.log2(width)) + 1
  const heights = new Array<number>(count).fill(base)
  for (let step = count - 1, amp = rough; step > 1; step /= 2, amp *= .62) {
    for (let i = step / 2; i < count; i += step) {
      heights[i] = (heights[i - step / 2] + heights[i + step / 2]) / 2 + (fxRandom(seed, i * 7 + step) - .5) * amp
    }
  }
  for (let p = 0; p < peaks; p++) {
    // Spread across the middle of the range, where the camera looks.
    const at = (.14 + .72 * (p + .15 + fxRandom(seed, 900 + p) * .7) / peaks) * (width - 1), lift = (.45 + fxRandom(seed, 950 + p) * .55) * peakLift
    const reach = (count - 1) * (.08 + fxRandom(seed, 990 + p) * .1)
    for (let i = 0; i < count; i++) heights[i] -= lift * Math.pow(Math.max(0, 1 - Math.abs(i - at) / reach), 1.3)
  }
  return heights.slice(0, width).map(value => Math.max(2, Math.round(value)))
}

export type SkySpec = { seed: number; moon: { x: number; y: number; radius: number } | null; horizonRow: number; stars: number }

function paintStars(sky: IndexedLayer, spec: SkySpec) {
  for (let i = 0; i < spec.stars; i++) {
    const x = Math.floor(fxRandom(spec.seed, i * 2) * sky.width)
    const y = Math.floor(Math.pow(fxRandom(spec.seed, i * 2 + 1), 1.6) * spec.horizonRow * .85)
    const twinkle = INDEX.star + (i % INDEX.starSteps)
    set(sky, x, y, twinkle)
    if (fxRandom(spec.seed, i + 5000) > .94) for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) set(sky, x + dx, y + dy, twinkle)
  }
}

function moonPixel(seed: number, x: number, y: number, d: number, dx: number, r: number) {
  if (d <= r) {
    const crater = fxRandom(seed + 77, Math.floor(x / 3) * 131 + Math.floor(y / 3)) > .78 && d < r - 1.5
    return crater || dx > r * .45 ? INDEX.moonShade : INDEX.moon
  }
  if (d <= r * 1.7 && bayer(x, y) < 1 - (d - r) / (r * .7)) return INDEX.haloInner
  if (d <= r * 2.8 && bayer(x, y) < (1 - (d - r * 1.7) / (r * 1.1)) * .55) return INDEX.haloOuter
  return 0
}

function paintMoon(sky: IndexedLayer, seed: number, moon: NonNullable<SkySpec['moon']>) {
  const cx = moon.x * sky.width, cy = moon.y * sky.height, r = moon.radius
  for (let y = Math.floor(cy - r * 3); y <= cy + r * 3; y++) for (let x = Math.floor(cx - r * 3); x <= cx + r * 3; x++) {
    const index = moonPixel(seed, x, y, Math.hypot(x + .5 - cx, y + .5 - cy), x - cx, r)
    if (index) set(sky, x, y, index)
  }
}

/** Dithered bands from zenith to horizon, stars and a haloed moon. */
export function paintSky(width: number, height: number, spec: SkySpec): IndexedLayer {
  const sky = layer(width, height)
  for (let y = 0; y < height; y++) {
    const t = Math.min(1, y / spec.horizonRow) * (INDEX.skySteps - 1)
    for (let x = 0; x < width; x++) set(sky, x, y, INDEX.sky + Math.min(INDEX.skySteps - 1, Math.floor(t + bayer(x, y))))
  }
  paintStars(sky, spec)
  if (spec.moon) paintMoon(sky, spec.seed, spec.moon)
  return sky
}

export type RangeSpec = { seed: number; base: number; rough: number; peaks: number; peakLift?: number; snow?: number; body: number; rim: number; shade?: number; lightFrom: number; trees?: boolean; mist?: boolean }

/** How far each column rises above the valleys around it, in rows. */
function prominence(top: number[], reach: number) {
  return top.map((row, x) => {
    let valley = row
    for (let dx = -reach; dx <= reach; dx++) valley = Math.max(valley, top[Math.min(top.length - 1, Math.max(0, x + dx))])
    return valley - row
  })
}

/** Snow caps the peaks, deeper the higher they stand over their valleys,
 *  and frays into the rock below. */
function snowAt(spec: RangeSpec, top: number[], rise: number[], x: number, y: number) {
  if (!spec.snow) return false
  const depth = spec.snow * Math.max(0, rise[x] / Math.max(1, spec.peakLift ?? spec.rough) - .25), below = y - top[x]
  return below < depth && (below < depth * .6 || bayer(x, y) < (depth - below) / (depth * .4))
}

function rangePixel(spec: RangeSpec, top: number[], rise: number[], x: number, y: number, height: number) {
  if (spec.mist && y > height * .88 && bayer(x, y) < (y - height * .88) / (height * .12)) return INDEX.sky + INDEX.skySteps - 1
  if (snowAt(spec, top, rise, x, y)) return spec.rim
  const awayFromLight = x > 0 && top[x] > top[x - 1] === x / top.length > spec.lightFrom
  return spec.shade && awayFromLight && bayer(x, y) < .5 && y - top[x] < 14 ? spec.shade : spec.body
}

/** Rim light: the ridge itself, and slopes that face the moon. */
function paintRim(range: IndexedLayer, spec: RangeSpec, top: number[], x: number) {
  set(range, x, top[x], spec.rim)
  const facing = x / range.width < spec.lightFrom ? top[x + 1] < top[x] : top[x - 1] < top[x]
  if (facing && x > 0) for (let d = 1; d <= Math.abs(top[x] - top[x - 1] || 1); d++) set(range, x, top[x] + d, spec.rim)
}

/** Streaks of lit rock running down from the high ground. */
function paintStreaks(range: IndexedLayer, spec: RangeSpec, top: number[]) {
  for (let s = 0; s < Math.round(range.width / 18); s++) {
    let x = Math.floor(fxRandom(spec.seed, 300 + s) * range.width), y = top[x] + 2
    if (top[x] > spec.base - spec.rough * .6) continue
    const length = 3 + Math.floor(fxRandom(spec.seed, 400 + s) * 10)
    for (let i = 0; i < length; i++, y++) {
      set(range, x, y, spec.rim)
      if (fxRandom(spec.seed, 500 + s * 20 + i) > .6) x += fxRandom(spec.seed, 600 + s) > .5 ? 1 : -1
    }
  }
}

/** A mountain range cut out against the sky, with the ridges facing the
 *  light traced in a lighter rim, like moonlit pixel art. */
export function paintRange(width: number, height: number, spec: RangeSpec): IndexedLayer {
  const range = layer(width, height)
  const top = ridge(spec.seed, width, spec.base, spec.rough, spec.peaks, spec.peakLift)
  const rise = spec.snow ? prominence(top, Math.round(width / 10)) : []
  for (let x = 0; x < width; x++) {
    for (let y = Math.max(0, top[x]); y < height; y++) set(range, x, y, rangePixel(spec, top, rise, x, y, height))
    paintRim(range, spec, top, x)
  }
  if (spec.trees) paintPines(range, top, spec.seed)
  else paintStreaks(range, spec, top)
  return range
}

/** A dark line of conifers standing on the ridge. */
function paintPines(target: IndexedLayer, top: number[], seed: number) {
  for (let x = 0; x < target.width; x += 1 + Math.floor(fxRandom(seed, x + 7000) * 3)) {
    if (fxRandom(seed, x + 8000) < .18) continue
    const tall = 4 + Math.floor(fxRandom(seed, x + 9000) * 9)
    for (let row = 0; row < tall; row++) {
      const half = Math.floor((row / tall) * (tall * .32) + (row % 3 === 2 ? 1 : 0))
      for (let dx = -half; dx <= half; dx++) set(target, x + dx, top[x] - tall + row + 2, INDEX.trees)
    }
  }
}

/** Reeds and grass in the foreground corners. */
export function paintReeds(width: number, height: number, seed: number): IndexedLayer {
  const reeds = layer(width, height)
  for (let i = 0; i < 140; i++) {
    const side = i % 2 ? 1 : 0
    const x0 = side ? width - fxRandom(seed, i) * width * .22 : fxRandom(seed, i) * width * .22
    const tall = height * (.25 + fxRandom(seed, i + 300) * .7) * (1 - Math.abs(x0 / width - side) * 2.5)
    const lean = (fxRandom(seed, i + 600) - .5) * .6
    for (let y = 0; y < tall; y++) {
      const x = Math.round(x0 + lean * y * y / Math.max(1, tall))
      set(reeds, x, height - 1 - y, INDEX.trees)
      if (y < tall * .35) set(reeds, x + 1, height - 1 - y, INDEX.trees)
    }
  }
  return reeds
}
