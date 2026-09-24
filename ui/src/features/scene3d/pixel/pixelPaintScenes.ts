import { fxRandom } from '../../sceneFx/types'
import { bayer, INDEX, layer, paintPines, ridge, set, type IndexedLayer } from './pixelPaint'
import type { Tone } from './pixelPaintWorlds'

/** Painters for interiors, travel, the seasons and the later pixel worlds. */

type Pane = { x0: number; x1: number; y0: number; y1: number }

function paintRoomWall(room: IndexedLayer, pane: Pane) {
  const lightX = (pane.x0 + pane.x1) / 2, lightY = pane.y1
  for (let y = 0; y < room.height; y++) for (let x = 0; x < room.width; x++) {
    if (x > pane.x0 && x < pane.x1 && y > pane.y0 && y < pane.y1) continue
    // Candlelight from the sill warms the wall around the window.
    const glow = 1 - Math.hypot((x - lightX) / room.width, (y - lightY) / room.height) * 3.2
    set(room, x, y, glow > .45 || (glow > 0 && bayer(x, y) < glow * 2.2) ? INDEX.room + 1 : INDEX.room)
  }
}

function paintWindowFrame(room: IndexedLayer, pane: Pane) {
  const midX = Math.round((pane.x0 + pane.x1) / 2), midY = Math.round((pane.y0 + pane.y1) / 2)
  for (let y = pane.y0 - 3; y <= pane.y1 + 3; y++) for (let x = pane.x0 - 3; x <= pane.x1 + 3; x++) {
    const onFrame = x <= pane.x0 || x >= pane.x1 || y <= pane.y0 || y >= pane.y1 || Math.abs(x - midX) < 2 || Math.abs(y - midY) < 2
    if (onFrame) set(room, x, y, INDEX.room + 2)
  }
  for (let x = pane.x0 - 8; x <= pane.x1 + 8; x++) for (let y = pane.y1 + 3; y < pane.y1 + 8; y++) set(room, x, y, y === pane.y1 + 3 ? INDEX.room + 1 : INDEX.room + 2)
}

function paintCurtains(room: IndexedLayer, pane: Pane) {
  for (const side of [-1, 1]) {
    const edge = side < 0 ? pane.x0 - 10 : pane.x1 + 10
    for (let y = 0; y < pane.y1 + 20 && y < room.height; y++) {
      const drape = 14 + Math.round(Math.sin(y * .05) * 3) + (y > pane.y1 - 10 ? Math.round((y - pane.y1 + 10) * .4) : 0)
      for (let d = 0; d < drape; d++) set(room, edge + side * (d - drape + 8), y, (d + Math.round(y * .1)) % 5 === 0 ? INDEX.room + 2 : INDEX.room + 3)
    }
  }
}

function paintSill(room: IndexedLayer, pane: Pane) {
  const sill = pane.y1 + 3, plant = pane.x0 + 8, candle = pane.x1 - 12
  for (let y = sill - 6; y < sill; y++) for (let dx = -3; dx <= 3; dx++) if (Math.abs(dx) <= 3 - (sill - y > 4 ? 1 : 0)) set(room, plant + dx, y, INDEX.room + 2)
  for (let leaf = 0; leaf < 7; leaf++) {
    const angle = -Math.PI / 2 + (leaf - 3) * .38, length = 6 + (leaf % 3) * 3
    for (let d = 0; d < length; d++) for (const w of [0, 1]) set(room, Math.round(plant + Math.cos(angle) * d) + w, Math.round(sill - 6 + Math.sin(angle) * d), INDEX.room + 4)
  }
  for (let y = sill - 9; y < sill; y++) for (let dx = -2; dx <= 2; dx++) set(room, candle + dx, y, INDEX.room + 5)
  for (let y = sill - 14; y < sill - 9; y++) for (let dx = -1; dx <= 1; dx++) if (Math.abs(dx) < 1 || y > sill - 12) set(room, candle + dx, y, INDEX.flame)
}

/** Rain running down the glass: short trails whose bright slot walks down. */
function paintRainOnGlass(room: IndexedLayer, pane: Pane, seed: number) {
  for (let d = 0; d < (pane.x1 - pane.x0) * .7; d++) {
    const x = pane.x0 + 2 + Math.floor(fxRandom(seed, d) * (pane.x1 - pane.x0 - 4)), y0 = pane.y0 + Math.floor(fxRandom(seed, d + 99) * (pane.y1 - pane.y0) * .8)
    const length = 3 + Math.floor(fxRandom(seed, d + 199) * 10)
    for (let y = y0; y < Math.min(pane.y1 - 1, y0 + length); y++) set(room, x, y, INDEX.drop + ((y + d * 3) % INDEX.dropSteps))
  }
}

/** A cosy room seen from inside: warm wall, a window with a cross frame
 *  whose panes stay open onto the world behind, curtains, a sill with a
 *  plant and a candle, and rain running down the glass. */
export function paintRoom(width: number, height: number, seed: number): IndexedLayer {
  const room = layer(width, height)
  const pane = { x0: Math.round(width * .24), x1: Math.round(width * .76), y0: Math.round(height * .12), y1: Math.round(height * .66) }
  paintRoomWall(room, pane)
  paintWindowFrame(room, pane)
  paintCurtains(room, pane)
  paintSill(room, pane)
  paintRainOnGlass(room, pane, seed)
  return room
}

/** A ridge that wraps: its outline is a sum of whole waves across the
 *  width (plus noise on a grid that divides it), so a scrolling layer has
 *  no seam where it comes round. */
export function paintLoopRange(width: number, height: number, spec: Tone & { seed: number; base: number; amp: number; trees: number }): IndexedLayer {
  const range = layer(width, height)
  const waves = [1, 2, 3, 5, 8, 13].map((k, i) => ({ k, a: 1 / (i + 1.4), phase: fxRandom(spec.seed, i) * Math.PI * 2 }))
  const top = Array.from({ length: width }, (_, x) => Math.round(spec.base - spec.amp * waves.reduce((sum, w) => sum + w.a * Math.sin(w.k * Math.PI * 2 * x / width + w.phase), 0) + (fxRandom(spec.seed, x >> 2) - .5) * 2))
  for (let x = 0; x < width; x++) {
    for (let y = Math.max(0, top[x]); y < height; y++) set(range, x, y, spec.body)
    set(range, x, top[x], spec.rim)
  }
  if (spec.trees > 0) paintPines(range, top, spec.seed, spec.trees)
  return range
}

/** Telegraph poles with sagging wires, spaced to wrap seamlessly. */
export function paintPoles(width: number, height: number, spacing: number): IndexedLayer {
  const poles = layer(width, height)
  const top = Math.round(height * .12)
  for (let x = 0; x < width; x += spacing) {
    for (let y = top; y < height; y++) { set(poles, x, y, INDEX.trees); set(poles, x + 1, y, INDEX.trees) }
    for (let dx = -5; dx <= 6; dx++) set(poles, x + dx, top + 3, INDEX.trees)
    for (const wire of [top + 3, top + 9]) for (let dx = 0; dx < spacing; dx++) {
      const t = dx / spacing
      set(poles, (x + dx) % width, Math.round(wire + 7 * (1 - (2 * t - 1) ** 2)), INDEX.trees)
    }
  }
  return poles
}

/** A carriage wall with a round-cornered window open onto the world, a
 *  lit rim, and a little table with a cup under it. */
export function paintCarriage(width: number, height: number): IndexedLayer {
  const wall = layer(width, height)
  const x0 = Math.round(width * .14), x1 = Math.round(width * .86), y0 = Math.round(height * .1), y1 = Math.round(height * .68), r = 14
  const inside = (x: number, y: number) => {
    const cx = Math.min(Math.max(x, x0 + r), x1 - r), cy = Math.min(Math.max(y, y0 + r), y1 - r)
    return Math.hypot(x - cx, y - cy) <= r && x > x0 && x < x1 && y > y0 && y < y1
  }
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
    if (inside(x, y)) continue
    const rim = inside(x - 3, y) || inside(x + 3, y) || inside(x, y - 3) || inside(x, y + 3)
    set(wall, x, y, rim ? INDEX.room + 2 : y > y1 + 10 ? INDEX.room + 1 : INDEX.room)
  }
  for (let x = x0 + 30; x < x1 - 30; x++) for (let y = y1 + 10; y < y1 + 14; y++) set(wall, x, y, INDEX.room + 2)
  const cup = Math.round(width * .6)
  for (let y = y1 + 3; y < y1 + 10; y++) for (let dx = -3; dx <= 3; dx++) set(wall, cup + dx, y, INDEX.room + 5)
  for (let y = y1 + 5; y < y1 + 8; y++) set(wall, cup + 5, y, INDEX.room + 5)
  return wall
}

/** Snow waiting to fall: a band under each column's top edge painted in
 *  four levels, first ones on the heights. As winter deepens the levels
 *  turn white in order, so snow piles up without repainting. */
export function dustSnow(target: IndexedLayer, depth: number, slot: number, seed: number) {
  const tops = Array.from({ length: target.width }, (_, x) => {
    let top = 0
    while (top < target.height && target.data[top * target.width + x] === 0) top++
    return top
  })
  const high = Math.min(...tops), low = Math.max(...tops.filter(top => top < target.height))
  for (let x = 0; x < target.width; x++) {
    // Deepest on the heights, thin in the hollows, with a ragged lower edge.
    const reach = depth * (.25 + 1.1 * (1 - (tops[x] - high) / Math.max(1, low - high))) * (.75 + fxRandom(seed, x >> 2) * .5)
    for (let y = tops[x]; y < Math.min(target.height, tops[x] + reach); y++) {
      const level = Math.floor(Math.max(0, Math.min(.99, (y - tops[x]) / reach + (fxRandom(seed, x * 53 + y) - .5) * .5)) * 4)
      set(target, x, y, slot + level)
    }
  }
  return target
}

/** A round deciduous tree: canopy in the seasonal leaf slots (shade, body,
 *  light), lit on the side facing the sun. */
function paintLeafTree(target: IndexedLayer, x: number, ground: number, size: number, seed: number, lightFrom: number) {
  for (let y = 0; y < size * .9; y++) { set(target, x, ground - y, INDEX.trees); set(target, x + 1, ground - y, INDEX.trees) }
  const litSide = x / target.width < lightFrom ? 1 : -1, cy = ground - size * 1.3
  for (let y = Math.floor(cy - size); y <= cy + size * .8; y++) for (let px = Math.floor(x - size); px <= x + size; px++) {
    const d = Math.hypot(px - x, (y - cy) * 1.15) / size + (fxRandom(seed, px * 7 + y) - .5) * .25
    if (d > 1) continue
    const light = ((px - x) * litSide - (y - cy)) / size
    set(target, px, y, INDEX.leaf + (light > .45 ? 2 : light < -.3 ? 0 : 1))
  }
}

/** Rolling hills dotted with round trees, snow waiting on the crests. */
export function paintOrchard(width: number, height: number, spec: Tone & { seed: number; trees: number }): IndexedLayer {
  const hills = layer(width, height)
  const ground = ridge(spec.seed, width, height * .6, height * .12, 3, height * .2)
  for (let x = 0; x < width; x++) for (let y = ground[x]; y < height; y++) set(hills, x, y, y === ground[x] ? spec.rim : spec.body)
  dustSnow(hills, 6, INDEX.snowNear, spec.seed)
  for (let t = 0; t < spec.trees; t++) {
    const x = Math.round(width * (.03 + .94 * (t + fxRandom(spec.seed, t) * .7) / spec.trees))
    paintLeafTree(hills, x, ground[x] + 2, 5 + fxRandom(spec.seed, t + 50) * 5, spec.seed + t, spec.lightFrom)
  }
  return hills
}

/** A rose window: glass in six hues by ring and petal, held by lead. */
function paintRose(target: IndexedLayer, cx: number, cy: number, r: number) {
  for (let y = Math.floor(cy - r); y <= cy + r; y++) for (let x = Math.floor(cx - r); x <= cx + r; x++) {
    const d = Math.hypot(x - cx, y - cy) / r, a = Math.atan2(y - cy, x - cx)
    if (d > 1) continue
    const petal = Math.floor(((a / (Math.PI * 2) + 1) % 1) * 12), ring = d < .3 ? 0 : d < .68 ? 1 : 2
    const lead = d > .96 || Math.abs(d - .3) < .03 || Math.abs(d - .68) < .025 || (ring > 0 && Math.abs(((a / (Math.PI * 2) + 1) % 1) * 12 - Math.round(((a / (Math.PI * 2) + 1) % 1) * 12)) < .06 / Math.max(.3, d))
    set(target, x, y, lead ? INDEX.trees : INDEX.glass + (ring === 0 ? 3 : (petal + ring * 2) % INDEX.glassSteps))
  }
}

/** A tall pointed lancet window with a grid of glass. */
function paintLancet(target: IndexedLayer, cx: number, top: number, bottom: number, half: number, hue: number) {
  for (let y = top; y < bottom; y++) {
    const arch = y < top + half * 1.6 ? Math.sqrt(Math.max(0, 1 - ((top + half * 1.6 - y) / (half * 1.6)) ** 2)) * half : half
    for (let x = Math.round(cx - arch); x <= cx + arch; x++) {
      const lead = (y - top) % 9 === 0 || x === Math.round(cx) || Math.abs(Math.abs(x - cx) - arch) < 1
      set(target, x, y, lead ? INDEX.trees : INDEX.glass + ((hue + Math.floor((y - top) / 9)) % INDEX.glassSteps))
    }
  }
}

/** The nave's far wall: dressed stone, a rose window and two lancets. */
export function paintNaveWall(width: number, height: number): IndexedLayer {
  const wall = layer(width, height)
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
    const course = y % 8 === 0 || (x + (Math.floor(y / 8) % 2) * 6) % 12 === 0
    set(wall, x, y, course ? INDEX.far : INDEX.near)
  }
  paintRose(wall, width / 2, height * .3, height * .2)
  paintLancet(wall, width * .36, Math.round(height * .52), Math.round(height * .9), 9, 1)
  paintLancet(wall, width * .64, Math.round(height * .52), Math.round(height * .9), 9, 4)
  return wall
}

/** A side of the nave: a row of piers and pointed arches in shadow. */
export function paintArcade(width: number, height: number): IndexedLayer {
  const side = layer(width, height)
  const bay = 48
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
    const along = x % bay, pier = along < 8
    const archTop = height * .3 + Math.pow(Math.abs(along - bay / 2 - 4) / (bay / 2 - 4), 2) * height * .18
    set(side, x, y, pier || y < archTop ? (pier && along < 2 ? INDEX.farRim : INDEX.far) : INDEX.trees)
  }
  return side
}

/** A stone floor of large slabs, laid on the ground. */
export function paintFlagstones(width: number, height: number, seed: number): IndexedLayer {
  const floor = layer(width, height)
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
    const joint = y % 14 === 0 || (x + (Math.floor(y / 14) % 2) * 10) % 20 === 0
    set(floor, x, y, joint ? INDEX.trees : fxRandom(seed, (x >> 3) * 97 + (y >> 3)) > .5 ? INDEX.near : INDEX.far)
  }
  return floor
}

/** The pond's radius as a share of its plane, so lilies can stay inside. */
const POND = .236

/** A garden pond seen from above: grass, a rim of stones, then water whose
 *  floor carries a net of caustics in the shimmer slots. */
export function paintPond(width: number, height: number, seed: number): IndexedLayer {
  const pond = layer(width, height)
  const cx = width / 2, cy = height / 2
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
    const a = Math.atan2(y - cy, x - cx), wobble = 1 + Math.sin(a * 3 + seed) * .06 + Math.sin(a * 7) * .03
    const d = Math.hypot((x - cx) / (width * POND), (y - cy) / (height * POND)) / wobble
    if (d > 1.08) { set(pond, x, y, INDEX.pad + (fxRandom(seed, x * 31 + y) > .85 ? 1 : 0)); continue }
    if (d > .97) { set(pond, x, y, fxRandom(seed, (x >> 2) * 7 + (y >> 2)) > .5 ? INDEX.farRim : INDEX.far); continue }
    const net = Math.abs(Math.sin(x * .12 + Math.sin(y * .08) * 2) + Math.sin(y * .11 + Math.sin(x * .07) * 2))
    set(pond, x, y, net < .1 ? INDEX.ray + ((x + y) >> 3) % INDEX.raySteps : d > .8 ? INDEX.pond : INDEX.pond + 1)
  }
  return pond
}

/** Lily pads, each a disc with a notch, some carrying a lotus flower. */
export function paintLilies(width: number, height: number, seed: number, count: number): IndexedLayer {
  const lilies = layer(width, height)
  for (let l = 0; l < count; l++) {
    // Scattered over the water, away from the rim.
    const a = fxRandom(seed, l) * Math.PI * 2, reach = Math.sqrt(fxRandom(seed, l + 60)) * .8 * POND
    const cx = width / 2 + Math.cos(a) * reach * width, cy = height / 2 + Math.sin(a) * reach * height, r = 6 + fxRandom(seed, l + 120) * 5, notch = fxRandom(seed, l + 180) * Math.PI * 2
    for (let y = Math.floor(cy - r); y <= cy + r; y++) for (let x = Math.floor(cx - r); x <= cx + r; x++) {
      const d = Math.hypot(x - cx, y - cy), a = Math.atan2(y - cy, x - cx)
      if (d > r || Math.abs(Math.atan2(Math.sin(a - notch), Math.cos(a - notch))) < .35) continue
      set(lilies, x, y, d > r - 1 || (x - cx) * (y - cy) > 0 && d < r * .3 ? INDEX.pad + 1 : INDEX.pad)
    }
    if (fxRandom(seed, l + 240) > .55) for (let dy = -2; dy <= 2; dy++) for (let dx = -2; dx <= 2; dx++) if (Math.abs(dx) + Math.abs(dy) <= 3) set(lilies, Math.round(cx) + dx, Math.round(cy) + dy, (dx + dy) % 2 ? INDEX.pad + 2 : INDEX.balloon + 3)
  }
  return lilies
}

/** A koi seen from above, facing +x: a cream body with red or gold
 *  patches, fins and a forked tail. */
export function paintKoi(width: number, height: number, variant: number): IndexedLayer {
  const koi = layer(width, height)
  const cy = (height - 1) / 2, patch = INDEX.balloon + (variant % 2)
  for (let x = 0; x < width; x++) {
    const t = x / (width - 1), half = t < .25 ? t / .25 * .55 : Math.sin(Math.PI * Math.min(1, (t - .1) / .9)) * cy
    for (let y = 0; y < height; y++) {
      const dy = Math.abs(y - cy)
      if (t < .22 ? dy > (.22 - t) * 10 + .5 : dy > half + .3) continue
      const spot = ((x * 3 + variant * 5) % 11 < 5 && t > .3 && t < .85) || (t > .8 && variant % 3 !== 2)
      set(koi, x, y, t < .22 ? patch : spot ? patch : INDEX.balloon + 3)
    }
  }
  for (const dy of [-1, 1]) set(koi, Math.round(width * .6), Math.round(cy + dy * (cy + .5)), patch)
  return koi
}

function blob(target: IndexedLayer, cx: number, cy: number, rx: number, ry: number) {
  for (let y = Math.floor(cy - ry); y <= cy + ry; y++) for (let x = Math.floor(cx - rx); x <= cx + rx; x++) {
    if (((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1) set(target, x, y, INDEX.trees)
  }
}

function stroke(target: IndexedLayer, x0: number, y0: number, x1: number, y1: number, width: number) {
  const steps = Math.ceil(Math.hypot(x1 - x0, y1 - y0))
  for (let i = 0; i <= steps; i++) {
    const t = i / Math.max(1, steps)
    for (let w = 0; w < width; w++) set(target, Math.round(x0 + (x1 - x0) * t) + w, Math.round(y0 + (y1 - y0) * t), INDEX.trees)
  }
}

/** One camel facing right, mid-stride for `phase` (0..1). */
function paintCamel(target: IndexedLayer, cx: number, ground: number, phase: number, rider: boolean) {
  const back = ground - 24
  blob(target, cx, back + 6, 13, 7)
  blob(target, cx - 2, back - 1, 6, 6)
  stroke(target, cx + 10, back + 4, cx + 18, back - 7, 3)
  blob(target, cx + 21, back - 8, 4, 2.5)
  stroke(target, cx - 13, back + 3, cx - 15, back + 12, 1)
  ;[-9, -5, 5, 9].forEach((x, leg) => {
    const swing = Math.sin((phase + leg * .25 + (leg > 1 ? .5 : 0)) * Math.PI * 2) * 3
    stroke(target, cx + x, back + 11, cx + x + swing * .4, ground - 8, 2)
    stroke(target, cx + x + swing * .4, ground - 8, cx + x + swing, ground, 2)
  })
  if (rider) { blob(target, cx - 2, back - 11, 3, 5); blob(target, cx - 2, back - 17, 2.2, 2.2) }
}

/** A person walking ahead, leading the caravan. */
function paintWalker(target: IndexedLayer, cx: number, ground: number, phase: number) {
  blob(target, cx, ground - 26, 2.4, 2.4)
  stroke(target, cx, ground - 23, cx, ground - 12, 3)
  const swing = Math.sin(phase * Math.PI * 2) * 4
  stroke(target, cx + 1, ground - 12, cx + 1 + swing, ground, 2)
  stroke(target, cx + 1, ground - 12, cx + 1 - swing, ground, 2)
  stroke(target, cx + 1, ground - 21, cx + 6, ground - 16, 1)
}

/** A camel caravan in silhouette, one frame of its walk. */
export function paintCaravan(width: number, height: number, frame: number, frames: number): IndexedLayer {
  const caravan = layer(width, height)
  const phase = frame / frames, ground = height - 1
  paintWalker(caravan, width - 16, ground, phase)
  ;[0, 1, 2].forEach(i => paintCamel(caravan, width - 60 - i * 62, ground, phase + i * .33, i === 1))
  return caravan
}

/** A neon grid floor that tiles both ways: bright lines in the beat slot
 *  with a dithered glow either side, on near-black ground. */
export function paintGrid(width: number, height: number, cell: number): IndexedLayer {
  const grid = layer(width, height)
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
    const dx = Math.min(x % cell, cell - x % cell), dy = Math.min(y % cell, cell - y % cell), d = Math.min(dx, dy)
    set(grid, x, y, d === 0 ? INDEX.grid : d === 1 && bayer(x, y) < .5 ? INDEX.grid + 1 : INDEX.trees)
  }
  return grid
}

/** Palm silhouettes leaning in from both edges. */
export function paintPalms(width: number, height: number, seed: number): IndexedLayer {
  const palms = layer(width, height)
  ;[[.06, 1], [.14, .75], [.9, -1], [.97, -.8]].forEach(([at, lean], p) => {
    const base = Math.round(width * at), tall = height * (.6 + fxRandom(seed, p) * .3)
    let x = base, y = height - 1
    for (let s = 0; s < tall; s++, y--) {
      x = base + lean * (s / tall) ** 2 * tall * .35
      for (let w = -2; w <= 2; w++) set(palms, Math.round(x) + w, y, INDEX.trees)
    }
    for (let f = 0; f < 7; f++) {
      const angle = Math.PI * (1.05 + f * .15) + lean * .2, length = height * (.16 + fxRandom(seed, p * 9 + f) * .08)
      for (let d = 0; d < length; d++) {
        const droop = (d / length) ** 2 * length * .5
        const thick = Math.max(1, Math.round(4 * (1 - d / length)))
        for (let k = 0; k < thick; k++) set(palms, Math.round(x + Math.cos(angle) * d), Math.round(y + Math.sin(angle) * d * .6 + droop + k), INDEX.trees)
      }
    }
  })
  return palms
}

/** One frame of a starling murmuration: every bird holds a place in the
 *  flock, and the flock's shape swells, folds and twists around a loop, so
 *  frame `frames` meets frame 0 again. */
export function paintMurmuration(width: number, height: number, frame: number, frames: number, seed: number, birds: number): IndexedLayer {
  const flock = layer(width, height)
  const phase = frame / frames * Math.PI * 2
  for (let b = 0; b < birds; b++) {
    const angle = fxRandom(seed, b) * Math.PI * 2, reach = Math.sqrt(fxRandom(seed, b + 5000))
    let u = Math.cos(angle) * reach, v = Math.sin(angle) * reach
    // Swell and squeeze, a travelling fold, and a slow twist.
    u *= 1 + .35 * Math.sin(phase + v * 2.2)
    v *= .55 + .25 * Math.cos(phase * 2 + u * 1.7)
    v += .35 * Math.sin(u * 2.6 + phase) * (1 - Math.abs(u) * .4)
    const twist = .5 * Math.sin(phase + reach * 3)
    const x = u * Math.cos(twist) - v * Math.sin(twist), y = u * Math.sin(twist) + v * Math.cos(twist)
    const px = Math.round(width / 2 + x * width * .4), py = Math.round(height / 2 + y * height * .7)
    set(flock, px, py, INDEX.trees)
    if (fxRandom(seed, b + 9000) > .7) set(flock, px + 1, py, INDEX.trees)
  }
  return flock
}

/** A launch tower: an open lattice with crossbeams, arms and blinking lights. */
export function paintLaunchTower(width: number, height: number): IndexedLayer {
  const tower = layer(width, height)
  const x0 = Math.round(width * .15), x1 = Math.round(width * .45)
  for (let y = Math.round(height * .08); y < height; y++) {
    set(tower, x0, y, INDEX.farRim); set(tower, x1, y, INDEX.farRim)
    const bay = (y % 16) / 16
    set(tower, Math.round(x0 + (x1 - x0) * bay), y, INDEX.farRim); set(tower, Math.round(x1 - (x1 - x0) * bay), y, INDEX.farRim)
    if (y % 16 === 0) for (let x = x0; x <= x1; x++) set(tower, x, y, INDEX.farRim)
    if (y % 48 === 20) { for (let x = x1; x < width * .62; x++) set(tower, x, y, INDEX.farRim); set(tower, x0, y - 1, INDEX.window + (y & 7)) }
  }
  for (let x = 0; x < width; x++) for (let y = height - 6; y < height; y++) set(tower, x, y, INDEX.near)
  set(tower, Math.round((x0 + x1) / 2), Math.round(height * .07), INDEX.tail)
  return tower
}

/** A rocket standing on its pad: stages, fins and a red nose. */
export function paintRocket(width: number, height: number): IndexedLayer {
  const rocket = layer(width, height)
  const cx = (width - 1) / 2, half = width * .22, nose = height * .16
  for (let y = 0; y < height; y++) {
    const w = y < nose ? half * Math.sqrt(y / nose) : half
    for (let x = Math.round(cx - w); x <= cx + w; x++) {
      const stage = y > nose && (Math.round(y - nose) % Math.round(height * .28)) < 2
      const lit = x > cx + w * .35
      set(rocket, x, y, y < nose * .7 ? INDEX.balloon : stage ? INDEX.trees : lit ? INDEX.moon : INDEX.balloon + 3)
    }
  }
  for (const side of [-1, 1]) for (let y = Math.round(height * .8); y < height; y++) {
    const spread = (y - height * .8) / (height * .2) * width * .26
    for (let d = 0; d <= spread; d++) set(rocket, Math.round(cx + side * (half + d)), y, INDEX.balloon)
  }
  return rocket
}

/** The engines' flame: a flickering cone in the flame slots over a white core. */
export function paintExhaust(width: number, height: number, seed: number): IndexedLayer {
  const flame = layer(width, height)
  const cx = (width - 1) / 2
  for (let y = 0; y < height; y++) {
    const t = y / height, w = width * .5 * (.35 + t * .65) * (1 - t * .3)
    for (let x = Math.round(cx - w); x <= cx + w; x++) {
      const core = Math.abs(x - cx) < w * .35 && t < .55
      if (!core && bayer(x, y) > 1.05 - t) continue
      set(flame, x, y, core ? INDEX.lamp : INDEX.flame + ((x + y + seed) & 3))
    }
  }
  return flame
}
