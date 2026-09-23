import { fxRandom } from '../../sceneFx/types'
import { bayer, INDEX, layer, paintPines, ridge, set, type IndexedLayer } from './pixelPaint'

type Tone = { body: number; rim: number; lightFrom: number }

/** Windows light up in palette slots, so cycling the slots makes rooms
 *  switch on and off without repainting the city. */
function paintWindows(target: IndexedLayer, x0: number, x1: number, top: number, lit: number, seed: number) {
  for (let y = top + 3; y < target.height - 2; y += 3) {
    for (let x = x0 + 2; x < x1 - 2; x += 3) {
      if (fxRandom(seed, x * 977 + y) > lit) continue
      const slot = INDEX.window + Math.floor(fxRandom(seed + 5, x * 31 + y * 7) * INDEX.windowSteps)
      set(target, x, y, slot)
      if (fxRandom(seed + 9, x + y * 13) > .5) set(target, x + 1, y, slot)
    }
  }
}

function paintTower(target: IndexedLayer, x: number, width: number, top: number, tone: Tone, seed: number, windows: number) {
  for (let y = top; y < target.height; y++) for (let dx = 0; dx < width; dx++) set(target, x + dx, y, tone.body)
  const litSide = x / target.width < tone.lightFrom ? x + width - 1 : x
  for (let y = top; y < target.height; y++) set(target, litSide, y, tone.rim)
  for (let dx = 0; dx < width; dx++) set(target, x + dx, top, tone.rim)
  if (fxRandom(seed, 3) > .7) for (let y = 1; y < 3 + fxRandom(seed, 4) * 8; y++) set(target, x + Math.floor(width / 2), top - y, tone.rim)
  if (fxRandom(seed, 5) > .75 && width > 8) {
    const inset = 2 + Math.floor(fxRandom(seed, 6) * width * .25), rise = 3 + Math.floor(fxRandom(seed, 7) * 8)
    for (let y = top - rise; y < top; y++) for (let dx = inset; dx < width - inset; dx++) set(target, x + dx, y, tone.body)
  }
  paintWindows(target, x, x + width, top, windows, seed)
}

/** A skyline of towers, some with antennas or stepped crowns. */
export function paintSkyline(width: number, height: number, spec: Tone & { seed: number; tall: number; windows: number }): IndexedLayer {
  const city = layer(width, height)
  for (let x = 0, i = 0; x < width; i++) {
    const w = 6 + Math.floor(fxRandom(spec.seed, i) * 20)
    const h = height * (.18 + fxRandom(spec.seed, i + 500) * .75 * spec.tall)
    paintTower(city, x, w, Math.round(height - h), spec, spec.seed * 7 + i, spec.windows)
    x += w + (fxRandom(spec.seed, i + 900) < .25 ? 1 + Math.floor(fxRandom(spec.seed, i + 950) * 4) : 0)
  }
  return city
}

/** Flat-topped buttes with lit faces and strata. */
export function paintMesas(width: number, height: number, spec: Tone & { seed: number; tall: number; count: number }): IndexedLayer {
  const mesas = layer(width, height)
  for (let m = 0; m < spec.count; m++) {
    const center = width * (.08 + .84 * (m + fxRandom(spec.seed, m)) / spec.count)
    const top = Math.round(height * (1 - (.3 + fxRandom(spec.seed, m + 40) * .6) * spec.tall))
    const half = 12 + fxRandom(spec.seed, m + 80) * 34, slope = 6 + fxRandom(spec.seed, m + 120) * 10
    for (let y = top; y < height; y++) {
      const spread = half + (y - top) * slope / 14
      for (let x = Math.floor(center - spread); x <= center + spread; x++) {
        const edge = Math.abs(x - center) > spread - 1.5 && (x < center) === (center / width > spec.lightFrom)
        const strata = (y - top) % 7 === 3 && bayer(x, y) < .5
        set(mesas, x, y, y === top || edge ? spec.rim : strata ? INDEX.farShade : spec.body)
      }
    }
  }
  return mesas
}

/** Sand dunes: soft crests, a lit windward face and a dithered lee side. */
export function paintDunes(width: number, height: number, spec: Tone & { seed: number; tall: number }): IndexedLayer {
  const dunes = layer(width, height)
  const phase = [0, 1, 2].map(k => fxRandom(spec.seed, k) * Math.PI * 2)
  const top = Array.from({ length: width }, (_, x) => Math.round(height * (1 - spec.tall * (.35
    + .3 * (1 - Math.abs(Math.sin(x * .012 + phase[0])))
    + .18 * Math.sin(x * .031 + phase[1]) + .08 * Math.sin(x * .09 + phase[2])))))
  for (let x = 0; x < width; x++) {
    const lee = x > 0 && (top[x] > top[x - 1]) === (x / width > spec.lightFrom)
    for (let y = Math.max(0, top[x]); y < height; y++) {
      const shadow = lee && y - top[x] < 10 && bayer(x, y) < .6 - (y - top[x]) / 20
      set(dunes, x, y, shadow ? INDEX.farShade : spec.body)
    }
    set(dunes, x, top[x], spec.rim)
  }
  return dunes
}

/** A sea cliff on one side with a lighthouse on top; the lamp position is
 *  returned so the world can hang a sweeping beam on it. */
export function paintCliff(width: number, height: number, spec: Tone & { seed: number; tall: number; trees: number }): IndexedLayer {
  const cliff = layer(width, height)
  const start = Math.round(width * .6)
  const top = ridge(spec.seed, width, height * (1 - .55 * spec.tall), height * .14, 2, height * .12)
  for (let x = start; x < width; x++) {
    // A sheer face towards the sea, then ground falling gently inland.
    const ramp = Math.min(1, (x - start) / 26), inland = (x - start) / (width - start) * height * .18
    const surface = Math.round(height - (height - top[x] - inland) * ramp)
    for (let y = surface; y < height; y++) {
      const crack = fxRandom(spec.seed, x * 3 + Math.floor(y / 5)) > .93
      set(cliff, x, y, (x - start < 26 && bayer(x, y) < .35) || crack ? INDEX.nearRim : spec.body)
    }
    set(cliff, x, surface, spec.rim)
  }
  const at = Math.round(width * .74), base = Math.round(top[at] + (at - start) / (width - start) * height * .18)
  const tower = Math.round(height * .38)
  for (let y = base - tower; y < base; y++) for (let dx = -2; dx <= 2; dx++) {
    set(cliff, at + dx, y, Math.floor((y - base) / 4) % 2 ? INDEX.nearRim : INDEX.moon)
  }
  for (let dx = -3; dx <= 3; dx++) set(cliff, at + dx, base - tower - 1, spec.body)
  for (let y = base - tower - 5; y < base - tower - 1; y++) for (let dx = -2; dx <= 2; dx++) set(cliff, at + dx, y, INDEX.lamp)
  for (let r = 0; r < 4; r++) for (let dx = -3 + r; dx <= 3 - r; dx++) set(cliff, at + dx, base - tower - 6 - r, spec.body)
  const trees = top.map((row, x) => x < start + 26 || Math.abs(x - at) < 6 ? height + 20 : Math.round(row + (x - start) / (width - start) * height * .18))
  paintPines(cliff, trees, spec.seed + 4, spec.trees, .7)
  cliff.lamp = [at, base - tower - 3]
  return cliff
}

/** Layers of tall pines, the nearest the darkest. */
export function paintForest(width: number, height: number, spec: { seed: number; tall: number; density: number; body: number }): IndexedLayer {
  const forest = layer(width, height)
  const ground = ridge(spec.seed, width, height * .82, height * .08, 2, height * .1)
  for (let x = 0; x < width; x++) for (let y = ground[x]; y < height; y++) set(forest, x, y, spec.body)
  // Pines in the layer's own tone, so each row of forest reads against the next.
  paintPines(forest, ground, spec.seed, spec.density, 1.6 + spec.tall * 2.4, spec.body)
  return forest
}

/** Fireflies: single pixels in cycling slots that pulse on and off. */
export function paintFireflies(target: IndexedLayer, seed: number, count: number, from: number) {
  for (let i = 0; i < count; i++) {
    const x = Math.floor(fxRandom(seed, i) * target.width)
    const y = Math.floor(target.height * (from + fxRandom(seed, i + 400) * (1 - from) * .9))
    const slot = INDEX.firefly + (i % INDEX.fireflySteps)
    set(target, x, y, slot)
    if (i % 3 === 0) set(target, x + 1, y, slot)
  }
  return target
}

/** A sand floor seen in depth: hazy far off, warm and rippled close up. */
export function paintSand(width: number, height: number, seed: number): IndexedLayer {
  const sand = layer(width, height)
  for (let y = 0; y < height; y++) {
    const t = y / height * (INDEX.sandSteps - 1)
    for (let x = 0; x < width; x++) {
      const ripple = Math.sin(x * .09 + y * .8 + fxRandom(seed, Math.floor(x / 9)) * 2) > .92 ? -1 : 0
      set(sand, x, y, INDEX.sand + Math.max(0, Math.min(INDEX.sandSteps - 1, Math.floor(t + bayer(x, y)) + ripple)))
    }
  }
  return sand
}

/** A stone viaduct: a lit deck on a row of arches over the water. */
export function paintViaduct(width: number, height: number, spec: Tone & { seed: number }): IndexedLayer {
  const bridge = layer(width, height)
  const deck = Math.round(height * .12), under = Math.round(height * .26), span = 44, pier = 7
  for (let x = 0; x < width; x++) {
    const along = (x % span) - span / 2, half = span / 2 - pier
    // Keystone at the top of each opening, the curve falling to the piers.
    const arch = Math.abs(along) < half ? under + Math.round((height - under) * .45 * (1 - Math.sqrt(Math.max(0, 1 - (along / half) ** 2)))) : height
    for (let y = deck; y < height; y++) {
      if (Math.abs(along) < half && y > arch) continue
      const edge = Math.abs(along) < half && y === arch
      const joint = (y - deck) % 5 === 0 && bayer(x, y) < .3
      set(bridge, x, y, y === deck || edge ? spec.rim : joint ? INDEX.farShade : spec.body)
    }
    if (x % 9 === 0) for (let y = deck - 2; y < deck; y++) set(bridge, x, y, spec.body)
  }
  return bridge
}

/** A night train facing right: a locomotive with a lamp and carriages whose
 *  windows glow in the cycling window slots. */
export function paintTrain(width: number, height: number, spec: { seed: number; carriages: number }): IndexedLayer {
  const train = layer(width, height)
  const car = Math.floor((width - 30) / spec.carriages), roof = 1, wheels = height - 2
  const box = (x0: number, x1: number, y0: number, y1: number, index: number) => {
    for (let y = y0; y < y1; y++) for (let x = x0; x < x1; x++) set(train, x, y, index)
  }
  for (let c = 0; c < spec.carriages; c++) {
    const x0 = c * car + 1, x1 = x0 + car - 2
    box(x0, x1, roof, wheels, INDEX.trees)
    box(x0 + 1, x1 - 1, roof, roof + 1, INDEX.nearRim)
    for (let x = x0 + 3; x < x1 - 3; x += 4) box(x, x + 2, roof + 2, roof + 4, INDEX.window + ((x + c * 3 + spec.seed) % INDEX.windowSteps))
  }
  const loco = spec.carriages * car + 1
  box(loco, width - 4, roof + 1, wheels, INDEX.trees)
  box(loco + 2, loco + 8, roof - 1, roof + 3, INDEX.trees)
  box(loco + 3, loco + 6, roof + 1, roof + 3, INDEX.lamp)
  box(width - 6, width - 3, roof + 4, roof + 6, INDEX.lamp)
  box(width - 12, width - 8, 0, roof + 1, INDEX.trees)
  for (let x = 2; x < width - 4; x += 3) set(train, x, wheels, INDEX.farShade)
  return train
}

/** A volcano: a cone with a notched crater and rivers of lava whose pixels
 *  step through the cycling lava slots, so they flow without repainting. */
export function paintVolcano(width: number, height: number, spec: Tone & { seed: number; peak: number; center: number }): IndexedLayer {
  const volcano = layer(width, height)
  const cx = width * spec.center, peakRow = Math.round(height * (1 - spec.peak)), crater = 14
  const top = Array.from({ length: width }, (_, x) => {
    const away = Math.max(0, Math.abs(x - cx) - crater)
    const dip = Math.abs(x - cx) < crater ? 3 - Math.round(3 * (Math.abs(x - cx) / crater) ** 2) : 0
    // Steep by the crater, spreading out towards the base, like a real cone.
    return Math.round(peakRow + (height - peakRow) * 1.15 * (1 - Math.exp(-away / (width * .16))) + (fxRandom(spec.seed, Math.floor(x / 3)) - .5) * 3 + dip)
  })
  for (let x = 0; x < width; x++) {
    const lit = (x < cx) === (cx / width > spec.lightFrom)
    for (let y = Math.max(0, top[x]); y < height; y++) set(volcano, x, y, lit && y - top[x] < 3 ? spec.rim : spec.body)
  }
  for (let river = 0; river < 4; river++) {
    let x = cx + (river - 1.5) * 6, flowed = 0
    const lean = (river - 1.5) * .45
    for (let y = peakRow + 2; y < height - 1; y++, flowed++) {
      x += lean + (fxRandom(spec.seed + river, y) - .5) * 1.6
      const slot = INDEX.lava + ((INDEX.lavaSteps * 8 - Math.floor(flowed / 2)) % INDEX.lavaSteps)
      const wide = 1 + Math.floor(flowed / 40)
      for (let dx = -wide; dx <= wide; dx++) if (y >= top[Math.round(x + dx)]) set(volcano, Math.round(x + dx), y, slot)
      if (fxRandom(spec.seed + river, y + 999) > .996) break
    }
  }
  for (let x = Math.round(cx - crater); x <= cx + crater; x++) {
    for (let y = top[x] - 1; y <= top[x] + 1; y++) set(volcano, x, y, INDEX.lava + (x % INDEX.lavaSteps))
  }
  return volcano
}

/** A row of parked cars seen from behind: rounded bodies, rear windows
 *  catching the screen, and brake lights in their own cycling slots. */
export function paintCars(width: number, height: number, spec: { seed: number; count: number; body: number; rim: number }): IndexedLayer {
  const cars = layer(width, height)
  const pitch = width / spec.count
  for (let c = 0; c < spec.count; c++) {
    if (fxRandom(spec.seed, c) > .82) continue
    const w = Math.round(pitch * (.62 + fxRandom(spec.seed, c + 50) * .16)), x0 = Math.round(c * pitch + (pitch - w) / 2)
    const cabin = Math.round(height * .42), roofInset = Math.round(w * .2)
    for (let y = 0; y < height - 1; y++) {
      const inset = y < cabin ? roofInset - Math.round(y * .6) : Math.max(0, 1 - (y - cabin))
      for (let x = x0 + Math.max(0, inset); x < x0 + w - Math.max(0, inset); x++) {
        const glass = y > 1 && y < cabin - 1 && x > x0 + inset + 1 && x < x0 + w - inset - 2
        set(cars, x, y, y === 0 ? spec.rim : glass ? INDEX.nearRim : spec.body)
      }
    }
    const lights = INDEX.tail + (c % 2), row = cabin + 2
    for (const x of [x0 + 1, x0 + 2, x0 + w - 3, x0 + w - 2]) { set(cars, x, row, lights); set(cars, x, row + 1, lights) }
  }
  return cars
}

/** A cherry tree: a dark forked trunk under a cloud of blossom, lit on the
 *  side facing the sun or moon. */
function paintBlossomTree(target: IndexedLayer, x: number, ground: number, size: number, seed: number, lightFrom: number) {
  const trunk = Math.round(size * 1.1)
  for (let y = 0; y < trunk; y++) {
    const lean = Math.round(Math.sin(y * .25 + seed) * 1.5)
    set(target, x + lean, ground - y, INDEX.trees); set(target, x + lean + 1, ground - y, INDEX.trees)
  }
  const litSide = x / target.width < lightFrom ? 1 : -1
  for (let blob = 0; blob < 7; blob++) {
    const bx = x + (fxRandom(seed, blob) - .5) * size * 2.2, by = ground - trunk - (fxRandom(seed, blob + 10) - .3) * size * .9
    const r = size * (.45 + fxRandom(seed, blob + 20) * .35)
    for (let y = Math.floor(by - r); y <= by + r; y++) for (let px = Math.floor(bx - r); px <= bx + r; px++) {
      const d = Math.hypot(px - bx, y - by) / r
      if (d > 1 || (d > .75 && bayer(px, y) > (1 - d) * 4)) continue
      const light = ((px - bx) * litSide - (y - by)) / r
      set(target, px, y, light > .45 ? INDEX.blossom + 1 : light < -.35 ? INDEX.blossom + 2 : INDEX.blossom)
    }
  }
}

/** A pagoda of stacked tiers with upturned eaves and lit windows. */
function paintPagoda(target: IndexedLayer, x: number, ground: number, tiers: number, tone: Tone) {
  let y = ground, width = 26
  for (let tier = 0; tier < tiers; tier++, width -= 4) {
    const wall = 7, half = Math.round(width / 2) - 3
    for (let dy = 0; dy < wall; dy++) for (let dx = -half; dx <= half; dx++) {
      const window = dy > 1 && dy < 5 && Math.abs(dx) < half - 1 && (dx + 16) % 4 < 2
      set(target, x + dx, y - dy, window ? INDEX.window + ((dx + tier) & 7) : tone.body)
    }
    y -= wall
    for (let dy = 0; dy < 4; dy++) for (let dx = -half - 5 + dy; dx <= half + 5 - dy; dx++) set(target, x + dx, y - dy, dy === 3 ? tone.rim : INDEX.trees)
    set(target, x - half - 6, y, INDEX.trees); set(target, x + half + 6, y, INDEX.trees)
    y -= 4
  }
  for (let dy = 0; dy < 8; dy++) set(target, x, y - dy, tone.rim)
}

/** A stone lantern whose light sits in a window slot. */
function paintLantern(target: IndexedLayer, x: number, ground: number, slot: number) {
  for (let dy = 0; dy < 5; dy++) set(target, x, ground - dy, INDEX.trees)
  for (let dx = -2; dx <= 2; dx++) { set(target, x + dx, ground - 5, INDEX.trees); set(target, x + dx, ground - 9, INDEX.trees) }
  for (let dy = 6; dy <= 8; dy++) for (let dx = -1; dx <= 1; dx++) set(target, x + dx, ground - dy, INDEX.window + slot)
  for (let dx = -3; dx <= 3; dx++) set(target, x + dx, ground - 10, INDEX.trees)
}

/** A garden shore: a low bank with blossom trees, and optionally a pagoda
 *  and stone lanterns. */
export function paintGarden(width: number, height: number, spec: Tone & { seed: number; trees: number; pagoda: boolean; lanterns: number; size: number }): IndexedLayer {
  const garden = layer(width, height)
  const bank = ridge(spec.seed, width, height * .86, height * .05, 1, height * .06)
  for (let x = 0; x < width; x++) for (let y = bank[x]; y < height; y++) set(garden, x, y, y === bank[x] ? spec.rim : spec.body)
  if (spec.pagoda) paintPagoda(garden, Math.round(width * .32), bank[Math.round(width * .32)], 4, spec)
  for (let t = 0; t < spec.trees; t++) {
    const x = Math.round(width * (.05 + .9 * (t + fxRandom(spec.seed, t)) / spec.trees))
    if (spec.pagoda && Math.abs(x - width * .32) < 22) continue
    paintBlossomTree(garden, x, bank[x], spec.size * (.8 + fxRandom(spec.seed, t + 40) * .5), spec.seed + t * 13, spec.lightFrom)
  }
  for (let l = 0; l < spec.lanterns; l++) {
    const x = Math.round(width * (.12 + .76 * (l + .5) / spec.lanterns))
    paintLantern(garden, x, bank[x], l % INDEX.windowSteps)
  }
  return garden
}
