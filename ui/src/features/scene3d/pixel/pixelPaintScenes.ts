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

/** A walker holding a lantern out ahead, one frame of the walk; the lamp
 *  sways a pixel with each step. */
export function paintLanternBearer(width: number, height: number, frame: number, frames: number): IndexedLayer {
  const bearer = layer(width, height)
  const phase = frame / frames, ground = height - 1, cx = Math.round(width * .4)
  paintWalker(bearer, cx, ground, phase)
  const hx = cx + 6 + Math.round(Math.sin(phase * Math.PI * 2)), hy = ground - 12
  for (let y = ground - 16; y < hy; y++) set(bearer, hx, y, INDEX.trees)
  for (let y = hy; y < hy + 3; y++) for (let x = hx - 1; x <= hx + 1; x++) set(bearer, x, y, INDEX.lamp)
  return bearer
}

/** A flat-roofed house in the sun: one long wall, a band of glass
 *  reflecting the sky and a slim overhang. */
export function paintModernHouse(width: number, height: number): IndexedLayer {
  const house = layer(width, height)
  const top = Math.round(height * .14)
  for (let y = top; y < height; y++) for (let x = 0; x < width; x++) set(house, x, y, INDEX.far)
  for (let x = 0; x < width; x++) for (let y = top - 3; y < top; y++) set(house, x, y, INDEX.farRim)
  for (let x = 0; x < width; x++) set(house, x, top, INDEX.farShade)
  const glassTop = Math.round(height * .36), glassBottom = Math.round(height * .82), left = Math.round(width * .3), right = Math.round(width * .92)
  for (let y = glassTop; y < glassBottom; y++) for (let x = left; x < right; x++) {
    const mullion = (x - left) % 22 === 0 || x === right - 1 || y === glassTop || y === glassBottom - 1
    set(house, x, y, mullion ? INDEX.farRim : INDEX.sky + 4 + Math.round(((y - glassTop) / (glassBottom - glassTop)) * 8))
  }
  for (let y = glassTop + 4; y < height; y++) for (let x = Math.round(width * .1); x < width * .18; x++) set(house, x, y, INDEX.farShade)
  return house
}

/** A pool on a pale stone deck, seen from above: blue deepening toward the
 *  far end, the coping and a diving board. */
export function paintPool(width: number, height: number): IndexedLayer {
  const pool = layer(width, height)
  const box = { left: Math.round(width * .3), right: Math.round(width * .7), far: Math.round(height * .12), near: Math.round(height * .62) }
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) set(pool, x, y, poolTexel(x, y, box))
  const board = Math.round((box.left + box.right) / 2)
  for (let y = box.near - 16; y < box.near + 10; y++) for (let x = board - 3; x <= board + 3; x++) set(pool, x, y, x === board + 3 ? INDEX.farShade : INDEX.coping)
  return pool
}

/** Water deepening toward the far end, the coping round it, deck beyond. */
function poolTexel(x: number, y: number, { left, right, far, near }: Record<'left' | 'right' | 'far' | 'near', number>) {
  if (x >= left && x < right && y >= far && y < near) return INDEX.pool + 3 - Math.min(3, Math.floor((near - y) / (near - far) * 3 + bayer(x, y)))
  if (x >= left - 3 && x < right + 3 && y >= far - 3 && y < near + 3) return INDEX.coping
  return bayer(x, y) < .25 ? INDEX.sand + 1 : INDEX.sand
}

/** A band of ripe wheat: stalks from the bottom, ears catching the light
 *  at the top, a ragged skyline of heads and the odd poppy. */
export function paintWheat(width: number, height: number, seed: number, poppies: number): IndexedLayer {
  const wheat = layer(width, height)
  for (let x = 0; x < width; x++) {
    const top = Math.round(height * (.08 + .22 * fxRandom(seed, x) + .1 * Math.sin(x * .02 + seed)))
    for (let y = Math.max(0, top); y < height; y++) {
      const depth = (y - top) / (height - top), ear = y - top < height * .14
      const tone = ear ? (bayer(x, y) < .6 ? 3 : 2) : depth < .5 ? (bayer(x, y) < .7 - depth ? 2 : 1) : (bayer(x, y) < 1.2 - depth * 1.2 ? 1 : 0)
      set(wheat, x, y, INDEX.wheat + tone)
    }
    if (fxRandom(seed, x + 5000) < poppies) for (let d = 0; d < 3; d++) set(wheat, x + (d % 2), top + 1 + (d >> 1), INDEX.tulip)
  }
  return wheat
}

/** Star trails round a pole at (`poleX`, `poleY`) as fractions of the
 *  sky: every star sweeps the same angle, and `order` says when each
 *  texel of its arc is traced, so the exposure builds up over the shot. */
export function paintStarTrails(width: number, height: number, seed: number, poleX: number, poleY: number, count: number): IndexedLayer {
  const trails = layer(width, height)
  trails.order = new Uint8Array(width * height)
  const cx = width * poleX, cy = height * poleY, reach = Math.hypot(width, height), sweep = Math.PI * .55
  for (let s = 0; s < count; s++) {
    const radius = 3 + Math.sqrt(fxRandom(seed, s)) * reach * .8, start = fxRandom(seed, s + 900) * Math.PI * 2
    const slot = INDEX.star + Math.floor(fxRandom(seed, s + 1800) * 8)
    for (let step = 0, steps = Math.ceil(sweep * radius * 1.4); step <= steps; step++) {
      const angle = start + sweep * step / steps
      const x = Math.round(cx + Math.cos(angle) * radius), y = Math.round(cy - Math.sin(angle) * radius)
      if (x < 0 || y < 0 || x >= width || y >= height) continue
      const at = y * width + x, when = 1 + Math.round(step / steps * 254)
      if (!trails.data[at] || when < trails.order[at]) { trails.data[at] = slot; trails.order[at] = when }
    }
  }
  set(trails, Math.round(cx), Math.round(cy), INDEX.moon)
  trails.order[Math.round(cy) * width + Math.round(cx)] = 1
  return trails
}

/** A small ridge tent glowing from inside, its door flap open. */
export function paintGlowTent(width: number, height: number): IndexedLayer {
  const tent = layer(width, height)
  const mid = width / 2
  for (let y = 1; y < height; y++) {
    const half = (y / height) * mid
    for (let x = Math.round(mid - half); x <= Math.round(mid + half); x++) {
      const edge = x <= Math.round(mid - half) || x >= Math.round(mid + half) || y === height - 1
      const door = y > height * .45 && Math.abs(x - mid - 1) < (y - height * .45) * .45
      set(tent, x, y, edge ? INDEX.trees : door ? INDEX.lamp : INDEX.window)
    }
  }
  for (let x = Math.round(mid) - 1; x <= Math.round(mid) + 1; x++) set(tent, x, 0, INDEX.trees)
  return tent
}

/** A tall house front: a steep roof with a chimney, rows of shuttered
 *  windows (some lit) and a door, grey against the trees. */
export function paintHouse(width: number, height: number, seed: number): IndexedLayer {
  const house = layer(width, height)
  const left = Math.round(width * .08), right = Math.round(width * .92), eaves = Math.round(height * .3), mid = width / 2
  for (let y = 0; y < height; y++) for (let x = left - 2; x <= right + 2; x++) {
    const reach = (y / eaves) * (mid - left + 2), roof = y < eaves && Math.abs(x - mid) <= reach
    if (roof) set(house, x, y, Math.abs(x - mid) >= reach - 1 ? INDEX.farRim : INDEX.far)
    else if (y >= eaves && x >= left && x <= right) set(house, x, y, INDEX.far)
  }
  for (let y = Math.round(eaves * .2); y < eaves * .6; y++) for (let x = Math.round(width * .68); x < width * .76; x++) set(house, x, y, INDEX.far)
  paintHouseWindows(house, left, right, eaves, seed)
  const door = Math.round(left + (right - left) * 1.5 / 4)
  for (let y = height - Math.round(height * .2); y < height; y++) for (let x = door - 3; x <= door + 3; x++) set(house, x, y, INDEX.trees)
  return house
}

/** Two rows of shuttered windows, about half of them lit. */
function paintHouseWindows(house: IndexedLayer, left: number, right: number, eaves: number, seed: number) {
  const cols = 4, ww = Math.round(house.width * .09), wh = Math.round(house.height * .13)
  for (let r = 0; r < 2; r++) for (let c = 0; c < cols; c++) {
    if (r === 1 && c === 1) continue
    const x0 = Math.round(left + (right - left) * (c + .5) / cols - ww / 2), y0 = Math.round(eaves + house.height * (.1 + r * .26))
    const pane = fxRandom(seed, r * 5 + c) < .6 ? INDEX.window + (r * cols + c) % 8 : INDEX.trees
    for (let y = y0; y < y0 + wh; y++) for (let x = x0; x < x0 + ww; x++) set(house, x, y, pane)
    for (let y = y0 - 1; y <= y0 + wh; y++) { set(house, x0 - 2, y, INDEX.trees); set(house, x0 + ww + 1, y, INDEX.trees) }
  }
}

/** An old street lamp: a slim post, a curled arm and a glass lantern. */
export function paintStreetlamp(width: number, height: number): IndexedLayer {
  const lamp = layer(width, height)
  const c = Math.round(width / 2)
  for (let y = 8; y < height; y++) for (let w = -1; w <= (y > height - 5 ? 1 : 0); w++) set(lamp, c + w, y, INDEX.trees)
  for (let x = c - 3; x <= c + 3; x++) { set(lamp, x, 1, INDEX.trees); set(lamp, x, 7, INDEX.trees) }
  for (let y = 2; y < 7; y++) for (let x = c - 2; x <= c + 2; x++) set(lamp, x, y, Math.abs(x - c) === 2 ? INDEX.trees : INDEX.lamp)
  set(lamp, c, 0, INDEX.trees)
  return lamp
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

/** A cluster of crystal shards growing from a point, up (1) or down (-1),
 *  each in the crystal slot of where it stands so a glow can sweep across. */
function crystals(target: IndexedLayer, x: number, y: number, size: number, way: number, seed: number) {
  for (let s = 0; s < 3 + Math.floor(fxRandom(seed, 1) * 4); s++) {
    const lean = (fxRandom(seed, s + 10) - .5) * 1.2, tall = size * (.5 + fxRandom(seed, s + 20) * .8), half = 1 + Math.floor(size * .12)
    for (let d = 0; d < tall; d++) {
      const w = Math.max(0, Math.round(half * (1 - d / tall)))
      for (let k = -w; k <= w; k++) {
        const px = Math.round(x + lean * d * .5 + k), slot = INDEX.crystal + ((px >> 4) % INDEX.crystalSteps)
        set(target, px, Math.round(y - way * d), k === w ? INDEX.lamp : slot)
      }
    }
  }
}

function rock(target: IndexedLayer, x: number, y: number, seed: number) {
  set(target, x, y, fxRandom(seed, (x >> 2) * 131 + (y >> 2)) > .55 ? INDEX.near : INDEX.far)
}

/** The cave's mouth close to the lens: rock all round a ragged opening,
 *  stalactites hanging into it and crystals on its lower lip. */
export function paintCaveMouth(width: number, height: number, seed: number): IndexedLayer {
  const mouth = layer(width, height)
  const cx = width / 2, cy = height * .52
  const open = (x: number, y: number) => {
    const a = Math.atan2(y - cy, x - cx), edge = 1 + (fxRandom(seed, Math.floor((a + 4) * 12)) - .5) * .12
    return Math.hypot((x - cx) / (width * .3), (y - cy) / (height * .36)) < edge
  }
  // The mouth is in shadow: near-black rock with a faint lit rim.
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) if (!open(x, y)) set(mouth, x, y, open(x, y - 2) || open(x - 2, y) || open(x + 2, y) ? INDEX.far : INDEX.trees)
  for (let x = Math.round(width * .15); x < width * .85; x += 3 + Math.floor(fxRandom(seed, x) * 6)) {
    let y = 0
    while (y < height && !open(x, y)) y++
    const length = 4 + fxRandom(seed, x + 99) * height * .16
    for (let d = 0; d < length; d++) for (let k = -Math.floor((1 - d / length) * 2); k <= Math.floor((1 - d / length) * 2); k++) set(mouth, x + k, y + d, INDEX.trees)
  }
  for (let c = 0; c < 7; c++) {
    const x = Math.round(width * (.26 + c * .08)), y = Math.round(height * .88 - Math.abs(c - 3) * height * .02)
    crystals(mouth, x, y, height * (.1 + fxRandom(seed, c + 300) * .1), 1, seed + c)
  }
  return mouth
}

/** The far wall of the grotto: rough rock, stalagmites and hanging
 *  stalactites, and crystal clusters glowing from floor and ceiling. */
export function paintGrotto(width: number, height: number, seed: number): IndexedLayer {
  const wall = layer(width, height)
  // Lit from the crystals below, the rock fades into darkness toward the vault.
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
    const light = y / height
    if (bayer(x, y) > light * 1.3) set(wall, x, y, INDEX.trees)
    else rock(wall, x, y, seed + 7)
  }
  for (let c = 0; c < width / 26; c++) {
    const x = Math.round((c + fxRandom(seed, c)) * 26)
    crystals(wall, x, height - 2, height * (.08 + fxRandom(seed, c + 50) * .14), 1, seed + c * 3)
    if (fxRandom(seed, c + 90) > .5) crystals(wall, x + 11, 1, height * .08, -1, seed + c * 5)
  }
  return wall
}

/** A swirling sky over the painted one: spiral bands around a few vortices
 *  and long wind currents between them, in the swirl slots so cycling turns
 *  the spirals; stars wear rings in the halo slots. */
export function paintSwirls(sky: IndexedLayer, seed: number) {
  const vortices = [[.3, .28, 70], [.62, .18, 50], [.82, .36, 40]].map(([x, y, r]) => [x * sky.width, y * sky.height, r] as const)
  for (let y = 0; y < sky.height * .8; y++) for (let x = 0; x < sky.width; x++) {
    let band = -1
    for (const [vx, vy, r] of vortices) {
      const d = Math.hypot(x - vx, (y - vy) * 1.6)
      if (d > r) continue
      const spiral = Math.atan2((y - vy) * 1.6, x - vx) / (Math.PI * 2) * 8 + d / 7
      if (bayer(x, y) < .75 - d / r * .3) band = Math.floor(((spiral % 8) + 8) % 8)
    }
    if (band < 0) {
      // Wind: long wavy streaks flowing across the rest of the sky.
      const flow = y / 6 + Math.sin(x / 40 + seed + y / 30) * 2.5
      if ((flow % 1) < .45 && bayer(x, y) < .6) band = Math.floor(((x / 24 + flow) % 8 + 8) % 8)
    }
    if (band >= 0) set(sky, x, y, INDEX.swirl + band)
  }
  for (let s = 0; s < 11; s++) {
    const sx = fxRandom(seed, s) * sky.width, sy = (.05 + fxRandom(seed, s + 40) * .45) * sky.height, r = 5 + fxRandom(seed, s + 80) * 6
    for (let y = Math.floor(sy - r * 1.6); y <= sy + r * 1.6; y++) for (let x = Math.floor(sx - r * 1.6); x <= sx + r * 1.6; x++) {
      const d = Math.hypot(x - sx, y - sy) / r
      if (d < .35) set(sky, x, y, INDEX.moon)
      else if (d < 1.6 && bayer(x, y) < 1.1 - d * .6) set(sky, x, y, INDEX.halo + Math.min(2, Math.floor(d * 2)))
    }
  }
  return sky
}

/** A cypress like a dark flame, its flickering outline in the swirl slots. */
export function paintCypress(width: number, height: number): IndexedLayer {
  const tree = layer(width, height)
  const cx = width / 2
  for (let y = 0; y < height; y++) {
    const t = y / height, half = width * .45 * Math.sin(Math.min(1, t * 1.25) * Math.PI * .5) * (1 - t * .2)
    const sway = Math.sin(t * 9) * width * .06 * (1 - t)
    for (let x = Math.round(cx + sway - half); x <= cx + sway + half; x++) {
      const edge = Math.abs(x - cx - sway) > half - 2
      // Long wavering strokes rising up the tree, like brushed flames.
      const flame = Math.sin((x - cx - sway) * .9 + Math.sin(y * .09) * 2.5) > .55
      set(tree, x, y, edge || flame ? INDEX.swirl + ((y >> 3) & 7) : INDEX.trees)
    }
  }
  return tree
}

/** A 5x7 pixel font, just the letters the motel needs. */
const GLYPHS: Record<string, string[]> = {
  M: ['10001', '11011', '10101', '10101', '10001', '10001', '10001'],
  O: ['01110', '10001', '10001', '10001', '10001', '10001', '01110'],
  T: ['11111', '00100', '00100', '00100', '00100', '00100', '00100'],
  E: ['11111', '10000', '10000', '11110', '10000', '10000', '11111'],
  L: ['10000', '10000', '10000', '10000', '10000', '10000', '11111'],
  V: ['10001', '10001', '10001', '10001', '01010', '01010', '00100'],
  A: ['01110', '10001', '10001', '11111', '10001', '10001', '10001'],
  C: ['01110', '10001', '10000', '10000', '10000', '10001', '01110'],
  N: ['10001', '11001', '10101', '10011', '10001', '10001', '10001'],
  Y: ['10001', '10001', '01010', '00100', '00100', '00100', '00100'],
}

/** Write `text` at (x, y) in `scale`-pixel blocks, letter i in slot(i). */
export function paintText(target: IndexedLayer, text: string, x: number, y: number, scale: number, slot: (i: number) => number) {
  ;[...text].forEach((char, i) => GLYPHS[char]?.forEach((row, r) => [...row].forEach((bit, c) => {
    if (bit !== '1') return
    for (let dy = 0; dy < scale; dy++) for (let dx = 0; dx < scale; dx++) set(target, x + (i * 6 + c) * scale + dx, y + r * scale + dy, slot(i))
  })))
}

/** A roadside motel at night: a long low block of doors and lit windows,
 *  and a tall sign whose letters light one by one, a chasing arrow and a
 *  flickering VACANCY. */
export function paintMotel(width: number, height: number): IndexedLayer {
  const motel = layer(width, height)
  const roof = Math.round(height * .62), x0 = Math.round(width * .32)
  for (let y = roof; y < height; y++) for (let x = x0; x < width - 8; x++) {
    const unit = (x - x0) % 22, door = unit > 3 && unit < 8 && y > roof + 7, window = unit > 11 && unit < 18 && y > roof + 7 && y < roof + 14
    set(motel, x, y, y < roof + 3 ? INDEX.nearRim : door ? INDEX.trees : window ? INDEX.window + ((x - x0) / 22 & 7) : INDEX.near)
  }
  const post = Math.round(width * .14)
  for (let y = Math.round(height * .12); y < height; y++) for (let dx = 0; dx < 3; dx++) set(motel, post + dx, y, INDEX.trees)
  // The sign board, its letters and the arrow of bulbs pointing to the office.
  const bx = post - 31, by = Math.round(height * .08)
  for (let y = by; y < by + 30; y++) for (let x = bx; x < bx + 68; x++) set(motel, x, y, y === by || y === by + 29 || x === bx || x === bx + 67 ? INDEX.neon + 1 : INDEX.trees)
  paintText(motel, 'MOTEL', bx + 5, by + 8, 2, i => INDEX.sign + i)
  for (let k = 0; k < 12; k++) set(motel, bx + 68 + k * 3, by + 33 + Math.round(k * 1.4), INDEX.bulb + (k % INDEX.bulbSteps))
  paintText(motel, 'VACANCY', bx + 6, by + 36, 1, () => INDEX.sign + 5)
  return motel
}

/** A straight desert road laid on the floor: dark asphalt, pale edges and a
 *  dashed centre line, tiling along its length so it can flow. */
export function paintRoad(width: number, height: number): IndexedLayer {
  const road = layer(width, height)
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
    const edge = x < 2 || x >= width - 2, centre = Math.abs(x - width / 2) < 1 && y % 24 < 12
    // Sparse grit in the asphalt, not a regular pattern.
    const grit = ((x * 7919 + y * 104729) % 31) === 0
    set(road, x, y, edge || centre ? INDEX.farRim : grit ? INDEX.near : INDEX.trees)
  }
  return road
}

/** Puffy fair-weather clouds: round billows with a lit top and a shaded
 *  base, placed at the given centres (in texels). */
export function paintClouds(width: number, height: number, seed: number, centres: [number, number, number][]): IndexedLayer {
  const sky = layer(width, height)
  centres.forEach(([cx, cy, size], c) => {
    for (let b = 0; b < 6; b++) {
      const bx = cx + (fxRandom(seed, c * 9 + b) - .5) * size * 1.6, by = cy - fxRandom(seed, c * 9 + b + 50) * size * .4, r = size * (.35 + fxRandom(seed, c * 9 + b + 90) * .3)
      for (let y = Math.floor(by - r); y <= by + r; y++) for (let x = Math.floor(bx - r); x <= bx + r; x++) {
        if (y > cy + size * .15 || Math.hypot(x - bx, y - by) > r) continue
        set(sky, x, y, y > cy - size * .05 ? INDEX.haloOuter : y < by - r * .3 ? INDEX.moon : INDEX.haloInner)
      }
    }
  })
  return sky
}

/** A meadow on the floor: rows of grass tones with a scatter of flowers. */
export function paintMeadow(width: number, height: number, seed: number): IndexedLayer {
  const meadow = layer(width, height)
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
    // Gentle swells of lighter grass, dithered in gradually.
    const swell = (Math.sin(x * .03 + seed) + Math.sin(y * .05 + x * .012) + 2) / 4
    const flower = fxRandom(seed, x * 977 + y) > .993
    set(meadow, x, y, flower ? INDEX.tulip + ((x + y) & 3) : bayer(x, y) < swell * .7 ? INDEX.nearRim : INDEX.near)
  }
  return meadow
}

/** The clouds' shadows for the floor: dithered dark patches (empty around
 *  them), at the same centres so they travel under their clouds. */
export function paintCloudShadows(width: number, height: number, centres: [number, number, number][]): IndexedLayer {
  const shade = layer(width, height)
  for (const [cx, cy, size] of centres) for (let y = Math.floor(cy - size); y <= cy + size; y++) for (let x = Math.floor(cx - size * 1.4); x <= cx + size * 1.4; x++) {
    const d = Math.hypot((x - cx) / 1.4, y - cy) / size
    // Soft-edged, and half-dithered so the grass shows through the shade.
    if (d < 1 && bayer(x, y) < .35 + (1 - d) * .2) set(shade, ((x % width) + width) % width, y, INDEX.trees)
  }
  return shade
}

/** A brass gear filling its square plane: teeth round the rim, spokes and
 *  a hub, lit on its upper edge. */
export function paintGear(size: number, teeth: number): IndexedLayer {
  const gear = layer(size, size)
  const c = (size - 1) / 2, root = size * .42, tip = size * .49
  for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) {
    const d = Math.hypot(x - c, y - c), a = Math.atan2(y - c, x - c)
    const tooth = Math.cos(a * teeth) > .15
    if (d > (tooth ? tip : root)) continue
    const spoke = d > size * .16 && d < root - size * .07 && Math.abs(Math.sin(a * 3)) > .28
    if (spoke) continue
    const lit = y < c - d * .4
    set(gear, x, y, d < size * .06 ? INDEX.trees : d > root - size * .07 || d < size * .16 ? (lit ? INDEX.nearRim : INDEX.near) : INDEX.far)
  }
  return gear
}

/** A clock face with its twelve marks (the hands are separate planes). */
export function paintClockFace(size: number): IndexedLayer {
  const face = layer(size, size)
  const c = (size - 1) / 2
  for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) {
    const d = Math.hypot(x - c, y - c) / (size / 2)
    if (d > 1) continue
    const a = Math.atan2(y - c, x - c), mark = d > .8 && d < .92 && Math.abs(Math.sin(a * 6)) < (Math.abs(Math.cos(a * 3)) > .9 ? .12 : .06)
    set(face, x, y, d > .95 ? INDEX.nearRim : mark ? INDEX.trees : INDEX.moon)
  }
  return face
}

/** A clock hand pointing up from the plane's centre. */
export function paintHand(width: number, height: number, length: number): IndexedLayer {
  const hand = layer(width, height)
  const cx = Math.floor(width / 2), cy = Math.floor(height / 2)
  for (let y = cy - Math.round(length * height / 2); y <= cy + 2; y++) for (let dx = -1; dx <= 1; dx++) set(hand, cx + dx, y, INDEX.trees)
  return hand
}

/** A pendulum hanging from the plane's centre: rod and a round bob. */
export function paintPendulum(width: number, height: number): IndexedLayer {
  const pendulum = layer(width, height)
  const cx = Math.floor(width / 2), bob = Math.round(height * .9), r = width * .3
  for (let y = Math.floor(height / 2); y < bob; y++) set(pendulum, cx, y, INDEX.near)
  for (let y = Math.floor(bob - r); y <= bob + r; y++) for (let x = Math.floor(cx - r); x <= cx + r; x++) {
    const d = Math.hypot(x - cx, y - bob) / r
    if (d <= 1) set(pendulum, x, y, d > .8 ? INDEX.near : x < cx && y < bob ? INDEX.moon : INDEX.nearRim)
  }
  return pendulum
}

/** A dark riveted iron wall behind the works. */
export function paintIronWall(width: number, height: number, seed = 1): IndexedLayer {
  const wall = layer(width, height)
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
    const seam = x % 48 === 0 || y % 32 === 0, rivet = (x % 48 === 4 || x % 48 === 44) && y % 8 === 4
    // Patches of rust and wear, different on every wall.
    const wear = fxRandom(seed, (x >> 3) * 131 + (y >> 3)) > .82 && bayer(x, y) < .4
    set(wall, x, y, seam ? INDEX.trees : rivet || wear ? INDEX.far : bayer(x, y) < .12 ? INDEX.far : INDEX.trees)
  }
  return wall
}

/** A round planet in one colour, lit toward the plane's centre side and
 *  shaded round its rim. */
export function paintPlanetDisc(size: number, tone: number): IndexedLayer {
  const planet = layer(size, size)
  const c = (size - 1) / 2
  for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) {
    const d = Math.hypot(x - c, y - c) / (size / 2)
    if (d <= 1) set(planet, x, y, d > .8 && bayer(x, y) < (d - .8) * 5 ? INDEX.trees : tone)
  }
  return planet
}

/** Thin elliptical orbit lines, and a scatter of asteroids in a belt. */
export function paintOrbits(size: number, radii: number[], belt: [number, number], seed: number): IndexedLayer {
  const orbits = layer(size, size)
  const c = size / 2
  for (const r of radii) for (let a = 0; a < 2000; a++) {
    const t = a / 2000 * Math.PI * 2
    if (a % 6 < 3) set(orbits, Math.round(c + Math.cos(t) * r), Math.round(c + Math.sin(t) * r), INDEX.far)
  }
  for (let k = 0; k < 420; k++) {
    const t = fxRandom(seed, k) * Math.PI * 2, r = belt[0] + fxRandom(seed, k + 500) * (belt[1] - belt[0])
    set(orbits, Math.round(c + Math.cos(t) * r), Math.round(c + Math.sin(t) * r), k % 5 ? INDEX.near : INDEX.nearRim)
  }
  return orbits
}

/** A rainbow arcing across its plane: five bands, the outer ones slightly
 *  dithered so it fades into the sky at its edges and feet. */
export function paintRainbowArc(width: number, height: number): IndexedLayer {
  const arc = layer(width, height)
  const cx = width / 2, cy = height * 1.05, outer = width * .46, band = width * .018
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
    const d = outer - Math.hypot(x - cx, (y - cy) * 1.35)
    if (d < 0 || d >= band * 5) continue
    const fade = Math.min(1, (height - y) / (height * .25) + .25)
    if (bayer(x, y) < .85 * fade) set(arc, x, y, INDEX.rainbow + Math.floor(d / band))
  }
  return arc
}

/** One frame of a pulsing jellyfish: the bell squeezes narrow and tall on
 *  the stroke and relaxes wide and flat, its tentacles rippling behind,
 *  all in the glow slots so light runs through it. */
export function paintJellyfish(width: number, height: number, frame: number, frames: number): IndexedLayer {
  const jelly = layer(width, height)
  const phase = frame / frames * Math.PI * 2, squeeze = .5 + .5 * Math.sin(phase)
  const cx = width / 2, top = height * .08, bellW = width * (.46 - squeeze * .12), bellH = height * (.24 + squeeze * .08)
  for (let y = 0; y < bellH; y++) {
    const half = bellW * Math.sqrt(Math.max(0, 1 - ((bellH - y) / bellH) ** 2))
    for (let x = Math.round(cx - half); x <= cx + half; x++) {
      const rim = y > bellH - 2 || Math.abs(x - cx) > half - 1.5
      set(jelly, x, Math.round(top + y), rim ? INDEX.lamp : INDEX.crystal + ((x >> 2) & 7))
    }
  }
  const foot = top + bellH
  for (let t = 0; t < 7; t++) {
    const x0 = cx - bellW * .8 + t * bellW * .27, length = height * (.45 + ((t * 37) % 5) * .06)
    for (let d = 0; d < length; d++) {
      const x = Math.round(x0 + Math.sin(d * .18 - phase * 1.5 + t) * (2 + d * .06))
      set(jelly, x, Math.round(foot + d), INDEX.crystal + ((Math.round(foot + d) >> 2) & 7))
    }
  }
  return jelly
}
