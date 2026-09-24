import { fxRandom } from '../../sceneFx/types'
import { bayer, INDEX, layer, paintPines, ridge, set, type IndexedLayer } from './pixelPaint'

export type Tone = { body: number; rim: number; lightFrom: number }

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

/** Light from the surface: a shimmering band along the top and slanted rays
 *  that fade with depth, all in cycling slots so they ripple. */
export function paintSeaLight(sky: IndexedLayer, seed: number) {
  for (let y = 0; y < 10; y++) for (let x = 0; x < sky.width; x++) {
    if (bayer(x, y) < y / 10) continue
    set(sky, x, y, INDEX.ray + ((Math.floor(x / 3) + Math.floor(Math.sin(x * .07 + y) * 3) + 16) % INDEX.raySteps))
  }
  for (let r = 0; r < 9; r++) {
    const x0 = sky.width * (.05 + .9 * fxRandom(seed, r)), wide = 8 + fxRandom(seed, r + 20) * 18
    for (let y = 8; y < sky.height * .85; y++) {
      const fade = 1 - y / (sky.height * .85), x = x0 + y * .35
      for (let dx = 0; dx < wide; dx++) if (bayer(Math.round(x + dx), y) < fade * .85) set(sky, Math.round(x + dx), y, INDEX.ray + ((r + Math.floor(y / 6)) % INDEX.raySteps))
    }
  }
  return sky
}

/** A reef: bumpy rock, round coral heads lit from above, and kelp that
 *  bends as it climbs. */
export function paintReef(width: number, height: number, spec: Tone & { seed: number; kelp: number; tall: number }): IndexedLayer {
  const reef = layer(width, height)
  const top = ridge(spec.seed, width, height * (1 - .35 * spec.tall), height * .18, 6, height * .2 * spec.tall)
  for (let x = 0; x < width; x++) for (let y = top[x]; y < height; y++) set(reef, x, y, y - top[x] < 2 ? spec.rim : spec.body)
  for (let c = 0; c < width / 22; c++) {
    const x = Math.floor(fxRandom(spec.seed, c + 300) * width), r = 2 + fxRandom(spec.seed, c + 340) * 5
    for (let y = Math.floor(top[x] - r * 2); y <= top[x]; y++) for (let px = Math.floor(x - r); px <= x + r; px++) {
      const d = Math.hypot(px - x, (y - top[x] + r) * 1.2) / r
      if (d <= 1) set(reef, px, y, d < .55 && y < top[x] - r ? spec.rim : spec.body)
    }
  }
  for (let k = 0; k < width / 9 * spec.kelp; k++) {
    const x0 = Math.floor(fxRandom(spec.seed, k + 500) * width), tall = height * (.25 + fxRandom(spec.seed, k + 560) * .45)
    for (let y = 0; y < tall; y++) {
      const x = Math.round(x0 + Math.sin(y * .18 + k) * 2 + y * .08)
      set(reef, x, top[x0] - y, spec.body)
      if (y % 5 === 2) set(reef, x + (k % 2 ? 1 : -1), top[x0] - y, spec.rim)
    }
  }
  return reef
}

/** A school of small fish silhouettes, bunched in a loose oval. */
export function paintSchool(width: number, height: number, seed: number, count: number): IndexedLayer {
  const school = layer(width, height)
  for (let f = 0; f < count; f++) {
    const a = fxRandom(seed, f) * Math.PI * 2, r = Math.sqrt(fxRandom(seed, f + 90))
    const x = Math.round(width / 2 + Math.cos(a) * r * width * .42), y = Math.round(height / 2 + Math.sin(a) * r * height * .38)
    for (const [dx, dy] of [[0, 0], [1, 0], [2, 0], [1, -1], [1, 1], [-1, -1], [-1, 1]]) set(school, x + dx, y + dy, INDEX.trees)
    set(school, x + 2, y, INDEX.nearRim)
  }
  return school
}

/** A band of valley fog: solid in the middle, dithered away above and below. */
export function paintMist(width: number, height: number, seed: number, density = 1): IndexedLayer {
  const mist = layer(width, height)
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
    const wave = Math.sin(x * .03 + fxRandom(seed, Math.floor(x / 40)) * 3) * .12
    const edge = 1 - Math.abs(y / height - .5 - wave) * 2.4
    if (edge > 0 && bayer(x, y) < edge * density) set(mist, x, y, INDEX.sky + INDEX.skySteps - 3)
  }
  return mist
}

/** A hot-air balloon: striped gores lit on one side, ropes and a basket. */
export function paintBalloon(width: number, height: number, spec: { colors: [number, number]; lightFrom: number }): IndexedLayer {
  const balloon = layer(width, height)
  const cx = (width - 1) / 2, envelope = Math.round(height * .74), r = width / 2 - .5
  for (let y = 0; y < envelope; y++) {
    const t = y / envelope, half = r * (t < .62 ? Math.sin((t / .62) * Math.PI / 2) : 1 - (t - .62) / .38 * .72)
    for (let x = Math.ceil(cx - half); x <= cx + half; x++) {
      const gore = Math.floor(((x - cx) / Math.max(1, half) + 1) * 3) % 2
      const lit = (x - cx) / Math.max(1, half) * (spec.lightFrom < .5 ? -1 : 1) > .45
      set(balloon, x, y, lit ? INDEX.balloon + 4 : spec.colors[gore])
    }
  }
  const neck = r * .28, basketTop = envelope + Math.round(height * .12)
  for (let y = envelope; y < basketTop; y++) { set(balloon, Math.round(cx - neck), y, INDEX.trees); set(balloon, Math.round(cx + neck), y, INDEX.trees) }
  for (let y = basketTop; y < height; y++) for (let x = Math.round(cx - neck); x <= cx + neck; x++) set(balloon, x, y, INDEX.trees)
  return balloon
}

function bulb(target: IndexedLayer, x: number, y: number, slot: number) {
  for (const [dx, dy] of [[0, 0], [1, 0], [0, 1], [1, 1]]) set(target, Math.round(x) + dx, Math.round(y) + dy, slot)
}

/** A Ferris wheel's turning part: rim, spokes and bulbs in the chase slots. */
export function paintWheel(size: number, spec: { body: number; rim: number }): IndexedLayer {
  const wheel = layer(size, size)
  const c = (size - 1) / 2, r = size / 2 - 2
  for (let a = 0; a < 720; a++) {
    const t = a / 720 * Math.PI * 2
    for (const k of [0, 1]) set(wheel, Math.round(c + Math.cos(t) * (r - k)), Math.round(c + Math.sin(t) * (r - k)), k ? spec.body : spec.rim)
    set(wheel, Math.round(c + Math.cos(t) * r * .55), Math.round(c + Math.sin(t) * r * .55), spec.body)
  }
  for (let s = 0; s < 12; s++) {
    const t = s / 12 * Math.PI * 2
    for (let d = 0; d < r; d++) set(wheel, Math.round(c + Math.cos(t) * d), Math.round(c + Math.sin(t) * d), spec.body)
    for (let d = 7; d < r - 2; d += 7) bulb(wheel, c + Math.cos(t) * d, c + Math.sin(t) * d, INDEX.bulb + ((d / 7 + s) % INDEX.bulbSteps))
  }
  for (let b = 0; b < 32; b++) {
    const t = b / 32 * Math.PI * 2
    bulb(wheel, c + Math.cos(t) * r, c + Math.sin(t) * r, INDEX.bulb + (b % INDEX.bulbSteps))
  }
  for (let y = -2; y <= 2; y++) for (let x = -2; x <= 2; x++) set(wheel, Math.round(c + x), Math.round(c + y), spec.rim)
  return wheel
}

/** The wheel's A-frame stand, from the hub down to the ground. */
export function paintStand(width: number, height: number, spec: { body: number; rim: number }): IndexedLayer {
  const stand = layer(width, height)
  const hub = [Math.round(width / 2), 2] as const
  for (const foot of [Math.round(width * .12), Math.round(width * .88)]) {
    for (let y = hub[1]; y < height; y++) {
      const x = Math.round(hub[0] + (foot - hub[0]) * (y - hub[1]) / (height - hub[1]))
      set(stand, x, y, spec.rim); set(stand, x + 1, y, spec.body)
    }
  }
  for (let x = Math.round(width * .2); x < width * .8; x++) set(stand, x, Math.round(height * .7), spec.body)
  return stand
}

/** A gondola that hangs from the rim, in balloon cloth colours. */
export function paintCabin(width: number, height: number, cloth: number): IndexedLayer {
  const cabin = layer(width, height)
  const c = Math.round(width / 2)
  for (let y = 0; y < 3; y++) set(cabin, c, y, INDEX.trees)
  for (let y = 3; y < height - 1; y++) for (let x = 2; x < width - 2; x++) {
    const window = y > 5 && y < height - 4 && x > 3 && x < width - 4
    set(cabin, x, y, y === 3 ? INDEX.trees : window ? INDEX.window + (x & 7) : cloth)
  }
  return cabin
}

/** Striped fair tents with strings of bulbs slung between them. */
export function paintTents(width: number, height: number, seed: number, count: number): IndexedLayer {
  const tents = layer(width, height)
  const ground = height - 1, tops: [number, number][] = []
  for (let t = 0; t < count; t++) {
    const cx = Math.round(width * (t + .5) / count + (fxRandom(seed, t) - .5) * 10), w = 28 + Math.round(fxRandom(seed, t + 9) * 14), h = Math.round(height * (.5 + fxRandom(seed, t + 19) * .25))
    const peak = ground - h
    for (let y = peak; y <= ground; y++) {
      const half = y < peak + h * .5 ? (y - peak) / (h * .5) * w / 2 : w / 2 - 2
      for (let x = Math.round(cx - half); x <= cx + half; x++) set(tents, x, y, Math.floor((x - cx + 40) / 3) % 2 ? INDEX.balloon : INDEX.balloon + 3)
    }
    for (let y = peak - 3; y < peak; y++) set(tents, cx, y, INDEX.trees)
    tops.push([cx, peak - 3])
  }
  for (let i = 1; i < tops.length; i++) {
    const [x0, y0] = tops[i - 1], [x1, y1] = tops[i]
    for (let x = x0; x <= x1; x++) {
      const t = (x - x0) / Math.max(1, x1 - x0), y = Math.round(y0 + (y1 - y0) * t + Math.sin(t * Math.PI) * 5)
      if ((x - x0) % 4 === 0) bulb(tents, x, y, INDEX.bulb + ((x >> 2) % INDEX.bulbSteps)); else set(tents, x, y, INDEX.trees)
    }
  }
  return tents
}

function paintHouse(target: IndexedLayer, x: number, ground: number, w: number, wall: number, seed: number, tone: Tone, chimneys: [number, number][]) {
  const lit = (dx: number, y: number) => y > ground - wall + 2 && y < ground - 2 && dx % 5 >= 2 && dx % 5 < 4 && dx > 1 && dx < w - 2
  for (let y = ground - wall; y <= ground; y++) for (let dx = 0; dx < w; dx++) {
    set(target, x + dx, y, lit(dx, y) && fxRandom(seed, dx * 7 + y) > .25 ? INDEX.window + ((dx + seed) & 7) : tone.body)
  }
  const roof = Math.ceil(w / 2) + 1
  for (let r = 0; r < roof; r++) for (let dx = r - 1; dx <= w - r; dx++) set(target, x + dx, ground - wall - r, r < 2 || dx === r - 1 || dx === w - r ? tone.rim : INDEX.trees)
  const cx = x + Math.round(w * (.25 + fxRandom(seed, 1) * .5)), top = ground - wall - Math.round(roof * .6) - 3
  for (let y = top; y < ground - wall - 1; y++) { set(target, cx, y, INDEX.trees); set(target, cx + 1, y, INDEX.trees) }
  set(target, cx, top, tone.rim); set(target, cx + 1, top, tone.rim)
  chimneys.push([cx + 1, top - 1])
}

/** A snowed-in village on a gentle slope: gabled houses with snow on the
 *  roofs and lit windows, a church with a steeple, and the chimneys' tops
 *  reported so smoke can rise from them. */
export function paintVillage(width: number, height: number, spec: Tone & { seed: number; houses: number }): IndexedLayer & { chimneys: [number, number][] } {
  const village = layer(width, height)
  const chimneys: [number, number][] = []
  const slope = ridge(spec.seed, width, height * .8, height * .05, 1, height * .08)
  for (let x = 0; x < width; x++) for (let y = slope[x]; y < height; y++) set(village, x, y, y === slope[x] ? spec.rim : spec.body)
  const church = Math.round(width * .52)
  for (let h = 0; h < spec.houses; h++) {
    const x = Math.round(width * (.04 + .92 * (h + fxRandom(spec.seed, h) * .6) / spec.houses)), w = 12 + Math.round(fxRandom(spec.seed, h + 30) * 10)
    if (Math.abs(x + w / 2 - church) < 20) continue
    paintHouse(village, x, slope[x] + 1, w, 7 + Math.round(fxRandom(spec.seed, h + 60) * 4), spec.seed + h, spec, chimneys)
  }
  const ground = slope[church] + 1
  for (let y = ground - 26; y <= ground; y++) for (let dx = -4; dx <= 4; dx++) set(village, church + dx, y, y > ground - 22 && y < ground - 18 && Math.abs(dx) < 2 ? INDEX.window + 3 : spec.body)
  for (let r = 0; r < 12; r++) for (let dx = -Math.floor(r / 3); dx <= Math.floor(r / 3); dx++) set(village, church + dx, ground - 38 + r, r < 3 ? spec.rim : INDEX.trees)
  for (let y = ground - 43; y < ground - 38; y++) set(village, church, y, spec.rim)
  set(village, church - 1, ground - 42, spec.rim); set(village, church + 1, ground - 42, spec.rim)
  paintHouse(village, church + 5, ground, 14, 9, spec.seed + 99, spec, chimneys)
  return Object.assign(village, { chimneys })
}

/** A skater gliding, arms out, a few pixels tall. */
export function paintSkater(width: number, height: number, seed: number): IndexedLayer {
  const skater = layer(width, height)
  const c = Math.floor(width / 2), lean = seed % 2 ? 1 : -1
  set(skater, c, 1, INDEX.trees); set(skater, c + lean, 1, INDEX.trees)
  for (let y = 2; y < 6; y++) set(skater, c, y, INDEX.balloon + (seed % 3))
  for (let dx = -2; dx <= 2; dx++) set(skater, c + dx, 3, INDEX.trees)
  set(skater, c - 1, 6, INDEX.trees); set(skater, c + 1, 7, INDEX.trees); set(skater, c - 1, 7, INDEX.trees)
  for (let dx = -2; dx <= 3; dx++) set(skater, c + dx, height - 1, INDEX.nearRim)
  return skater
}

type Falls = { lip: number; cx: number; half: number }

function cliffTop(falls: Falls, x: number, seed: number) {
  const away = Math.abs(x - falls.cx) - falls.half
  // Cliffs stand tallest either side of the fall and drop away from it.
  return away < 0 ? falls.lip : Math.round(falls.lip - 4 + away * .42 + Math.sin(away * .08 + seed) * 5 + (fxRandom(seed, x >> 2) - .5) * 4)
}

function paintCliffs(target: IndexedLayer, falls: Falls, spec: Tone & { seed: number }) {
  for (let x = 0; x < target.width; x++) {
    const away = Math.abs(x - falls.cx) - falls.half, top = cliffTop(falls, x, spec.seed)
    const lit = (x < falls.cx) === (falls.cx / target.width > spec.lightFrom)
    for (let y = top; y < target.height; y++) {
      if (away < 0 && y >= falls.lip) continue
      const ledge = Math.sin(y * .55 + Math.sin(x * .05 + spec.seed) * 2.4) > .86 && bayer(x, y) < .6
      const moss = y - top < 3 && fxRandom(spec.seed, x * 17 + y) > .35
      set(target, x, y, moss ? INDEX.trees : ledge || (lit && y - top < 2) ? spec.rim : spec.body)
    }
    if (away > 0 && away < 10 && fxRandom(spec.seed, x + 700) > .5) for (let y = top; y < top + 6 + (x % 5) * 3; y++) set(target, x, y, INDEX.trees)
  }
}

function paintWater(target: IndexedLayer, falls: Falls, seed: number) {
  for (let x = Math.ceil(falls.cx - falls.half); x <= falls.cx + falls.half; x++) {
    // Neighbouring columns share a phase, so the water pours in streaks;
    // some columns carry bright streaks, the rest are steady water.
    const offset = Math.floor(fxRandom(seed, Math.floor(x / 3) + 300) * 8)
    const streak = fxRandom(seed, Math.floor(x / 2) + 900) > .45
    for (let y = falls.lip; y < target.height; y++) {
      if (Math.abs(x - falls.cx) > falls.half - 2 && bayer(x, y) < .4) continue
      set(target, x, y, streak ? INDEX.fall + ((y + offset) >> 2) % INDEX.fallSteps : INDEX.fallWater)
    }
  }
}

function paintSpray(target: IndexedLayer, falls: Falls) {
  const foot = target.height - 1
  for (let y = foot - 10; y <= foot; y++) {
    const spread = falls.half + (y - foot + 10) * 2.2
    for (let x = Math.floor(falls.cx - spread); x <= falls.cx + spread; x++) if (bayer(x, y) < 1 - Math.abs(x - falls.cx) / spread) set(target, x, y, INDEX.fall + ((x + y) % INDEX.fallSteps))
  }
  for (let band = 0; band < 5; band++) {
    const r = falls.half * 3.2 - band * 1.6
    for (let a = 0; a < 180; a++) {
      const t = Math.PI + a / 180 * Math.PI, x = Math.round(falls.cx + falls.half * 1.4 + Math.cos(t) * r), y = Math.round(foot - 4 + Math.sin(t) * r * .8)
      if (bayer(x, y) < .75 && target.data[y * target.width + x] !== 0) set(target, x, y, INDEX.rainbow + band)
    }
  }
}

/** A waterfall between two cliffs: streaked columns step through the
 *  cycling fall slots so the water pours; foam boils at the foot and a
 *  rainbow hangs in the spray. */
export function paintFalls(width: number, height: number, spec: Tone & { seed: number; wide: number }): IndexedLayer {
  const target = layer(width, height)
  const falls = { lip: Math.round(height * .18), cx: width / 2, half: width * (.04 + spec.wide * .06) }
  paintCliffs(target, falls, spec)
  paintWater(target, falls, spec.seed)
  paintSpray(target, falls)
  return target
}

/** Smooth value noise from the seeded hash, for clouds of gas. */
function valueNoise(seed: number, x: number, y: number) {
  const ix = Math.floor(x), iy = Math.floor(y), fx = x - ix, fy = y - iy
  const at = (a: number, b: number) => fxRandom(seed, a * 7919 + b * 104729)
  const sx = fx * fx * (3 - 2 * fx), sy = fy * fy * (3 - 2 * fy)
  return (at(ix, iy) * (1 - sx) + at(ix + 1, iy) * sx) * (1 - sy) + (at(ix, iy + 1) * (1 - sx) + at(ix + 1, iy + 1) * sx) * sy
}

/** Nebula clouds over the star field, dithered into four glowing slots. */
export function paintNebula(sky: IndexedLayer, seed: number) {
  for (let y = 0; y < sky.height; y++) for (let x = 0; x < sky.width; x++) {
    const n = valueNoise(seed, x / 60, y / 40) * .6 + valueNoise(seed + 1, x / 22, y / 16) * .3 + valueNoise(seed + 2, x / 8, y / 8) * .1
    const band = Math.exp(-(((y / sky.height) - .35 - Math.sin(x / sky.width * 5) * .12) ** 2) * 18)
    const level = (n * band - .22) * 5
    // Gas lies behind the stars and moon: only open sky is painted over.
    const open = sky.data[y * sky.width + x] >= INDEX.sky && sky.data[y * sky.width + x] < INDEX.sky + INDEX.skySteps
    if (open && level > 0 && bayer(x, y) < level % 1 + .001) set(sky, x, y, INDEX.nebula + Math.min(3, Math.floor(level)))
  }
  return sky
}

/** A planet's limb from orbit: a curved horizon with a glowing atmosphere,
 *  cloud bands on the day side and city lights on the night side. */
export function paintPlanetLimb(width: number, height: number, spec: { seed: number; curve: number; lightFrom: number }): IndexedLayer {
  const limb = layer(width, height)
  const cx = width / 2
  for (let x = 0; x < width; x++) {
    const top = Math.round(height * .35 + ((x - cx) / width) ** 2 * height * spec.curve)
    for (let y = top - 3; y < height; y++) {
      if (y < top) { if (bayer(x, y) < (y - top + 4) / 4) set(limb, x, y, INDEX.ray + ((x >> 2) % INDEX.raySteps)); continue }
      const day = (x / width < spec.lightFrom ? 1 - Math.abs(x / width - spec.lightFrom) * 1.6 : 1 - (x / width - spec.lightFrom) * 2.2)
      const cloud = valueNoise(spec.seed, x / 9, y / 2.5) > .7
      const land = valueNoise(spec.seed + 5, x / 26, y / 9) > .58
      if (day > .15) set(limb, x, y, cloud ? INDEX.farRim : land ? INDEX.near : INDEX.far)
      else set(limb, x, y, land && fxRandom(spec.seed, x * 31 + y) > .9 ? INDEX.window + ((x + y) & 7) : INDEX.trees)
    }
  }
  return limb
}

/** A space station: a truss with modules, wide solar wings and blinking lights. */
export function paintStation(width: number, height: number, seed: number): IndexedLayer {
  const station = layer(width, height)
  const mid = Math.round(height / 2)
  for (let x = 4; x < width - 4; x++) set(station, x, mid, INDEX.nearRim)
  for (let m = 0; m < 4; m++) {
    const x0 = Math.round(width * (.3 + m * .1)), w = 5 + (m % 2) * 3
    for (let y = mid - 3; y <= mid + 3; y++) for (let x = x0; x < x0 + w; x++) set(station, x, y, y === mid - 3 ? INDEX.nearRim : INDEX.near)
  }
  for (const x0 of [4, width - 18]) for (const dy of [-8, 5]) {
    for (let y = mid + dy; y < mid + dy + 4; y++) for (let x = x0; x < x0 + 14; x++) set(station, x, y, (x - x0) % 3 === 2 ? INDEX.near : INDEX.far)
    for (let y = Math.min(mid, mid + dy); y <= Math.max(mid, mid + dy); y++) set(station, x0 + 7, y, INDEX.nearRim)
  }
  set(station, Math.round(width * .3), mid - 4, INDEX.tail); set(station, Math.round(width * .62), mid - 4, INDEX.window + (seed & 7))
  return station
}

/** A lumpy asteroid lit on one side. */
export function paintAsteroid(width: number, height: number, seed: number): IndexedLayer {
  const rock = layer(width, height)
  const c = (width - 1) / 2, r = width / 2 - 1
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
    const a = Math.atan2(y - c, x - c), bump = r * (.75 + valueNoise(seed, a * 2 + 9, 0) * .3), d = Math.hypot(x - c, y - c)
    if (d <= bump) set(rock, x, y, x - c < -r * .2 && y - c < r * .3 ? INDEX.nearRim : fxRandom(seed, x * 13 + y) > .85 ? INDEX.trees : INDEX.near)
  }
  return rock
}

/** A flower field for the floor: rows of tulips in four colours between
 *  strips of green, sharp up close and hazing into the distance. */
export function paintField(width: number, height: number, seed: number): IndexedLayer {
  const field = layer(width, height)
  for (let y = 0; y < height; y++) {
    const far = 1 - y / height
    for (let x = 0; x < width; x++) {
      const row = Math.floor(x / 6), inRow = x % 6
      if (far > .55 && bayer(x, y) < (far - .55) * 2.2) { set(field, x, y, INDEX.sand + Math.floor((1 - far) * 4)); continue }
      const soil = inRow >= 4
      const bloom = !soil && fxRandom(seed, x * 131 + (y >> 1)) > .25
      set(field, x, y, soil ? INDEX.trees : bloom ? INDEX.tulip + (row % 4) : INDEX.near)
    }
  }
  return field
}

/** Windmills: tapered towers with a cap; their hubs are reported so the
 *  world can turn sails on them. */
export function paintWindmills(width: number, height: number, spec: Tone & { seed: number; count: number }): IndexedLayer {
  const mills = layer(width, height)
  const hubs: [number, number][] = []
  const ground = ridge(spec.seed, width, height * .9, height * .03, 1, height * .04)
  for (let x = 0; x < width; x++) for (let y = ground[x]; y < height; y++) set(mills, x, y, spec.body)
  for (let m = 0; m < spec.count; m++) {
    const cx = Math.round(width * (.15 + .7 * (m + fxRandom(spec.seed, m) * .5) / spec.count)), base = ground[cx]
    const tall = Math.round(height * (.38 + fxRandom(spec.seed, m + 9) * .22)), top = base - tall
    for (let y = top; y < base; y++) {
      const half = Math.round(3 + (y - top) / tall * 5)
      for (let dx = -half; dx <= half; dx++) set(mills, cx + dx, y, dx === (cx / width < spec.lightFrom ? half : -half) ? spec.rim : spec.body)
      if ((y - top) % 9 === 5) set(mills, cx, y, INDEX.window + (m & 7))
    }
    for (let r = 0; r < 5; r++) for (let dx = -3 + Math.floor(r / 2); dx <= 3 - Math.floor(r / 2); dx++) set(mills, cx + dx, top - 1 - r, INDEX.trees)
    hubs.push([cx, top - 3])
  }
  return Object.assign(mills, { hubs })
}

/** Four lattice sails round a hub, to be turned by the world. */
export function paintSails(size: number): IndexedLayer {
  const sails = layer(size, size)
  const c = (size - 1) / 2
  for (let arm = 0; arm < 4; arm++) {
    const t = arm * Math.PI / 2, ux = Math.cos(t), uy = Math.sin(t)
    for (let d = 1; d < c; d++) {
      set(sails, Math.round(c + ux * d), Math.round(c + uy * d), INDEX.trees)
      if (d > c * .25) for (let w = 1; w <= 3; w++) {
        const x = Math.round(c + ux * d - uy * w), y = Math.round(c + uy * d + ux * w)
        set(sails, x, y, (d + w) % 3 === 0 ? INDEX.trees : INDEX.balloon + 3)
      }
    }
  }
  return sails
}

function paintSign(target: IndexedLayer, x0: number, y0: number, w: number, h: number, slot: number) {
  for (let y = y0; y < y0 + h; y++) for (let x = x0; x < x0 + w; x++) {
    const edge = y === y0 || y === y0 + h - 1 || x === x0 || x === x0 + w - 1
    const glyph = !edge && (x - x0) % 3 !== 0 && (y - y0) % 4 !== 0
    if (edge || glyph) set(target, x, y, INDEX.neon + slot)
    else set(target, x, y, INDEX.trees)
  }
}

function paintFireEscape(target: IndexedLayer, x0: number, top: number, bottom: number) {
  for (let y = top; y < bottom; y += 8) {
    for (let x = x0; x < x0 + 12; x++) set(target, x, y, INDEX.trees)
    for (let s = 0; s < 8; s++) set(target, x0 + (Math.floor(y / 8) % 2 ? s : 11 - s), y + s, INDEX.trees)
  }
}

/** A wall of city façades seen along a street: windows lit in the cycling
 *  slots, fire escapes, shopfronts and neon signs that buzz. */
export function paintFacade(width: number, height: number, spec: Tone & { seed: number }): IndexedLayer {
  const wall = layer(width, height)
  for (let x = 0, b = 0; x < width; b++) {
    const w = 30 + Math.floor(fxRandom(spec.seed, b) * 40), top = Math.round(height * (.05 + fxRandom(spec.seed, b + 30) * .3))
    const tone = b % 2 ? spec.body : INDEX.far
    const isWindow = (dx: number, y: number) => y < height - 14 && (dx % 7) > 1 && (dx % 7) < 5 && ((y - top) % 9) > 2 && ((y - top) % 9) < 7
    for (let y = top; y < height; y++) for (let dx = 0; dx < w; dx++) {
      const window = isWindow(dx, y)
      // Each window is lit or dark as a whole, in its own cycling slot.
      const pane = Math.floor(dx / 7) * 131 + Math.floor((y - top) / 9) + x * 7
      set(wall, x + dx, y, window ? (fxRandom(spec.seed, pane) > .5 ? INDEX.window + (pane & 7) : INDEX.trees) : dx === 0 ? spec.rim : tone)
    }
    for (let dx = 2; dx < w - 2; dx++) for (let y = height - 12; y < height - 2; y++) set(wall, x + dx, y, (dx % 10) < 7 ? INDEX.window + (b & 7) : INDEX.trees)
    if (fxRandom(spec.seed, b + 60) > .4) paintFireEscape(wall, x + 4, top + 6, height - 16)
    if (fxRandom(spec.seed, b + 90) > .25) paintSign(wall, x + Math.round(w * .45), top + 8 + Math.round(fxRandom(spec.seed, b + 120) * 20), 12, 24 + Math.round(fxRandom(spec.seed, b + 150) * 14), b % 4)
    x += w
  }
  return wall
}

function paintCastleTower(target: IndexedLayer, cx: number, base: number, width: number, tall: number, tone: Tone, flag: number) {
  const half = Math.floor(width / 2), top = base - tall, lit = cx / target.width < tone.lightFrom ? half : -half
  const isWindow = (dx: number, y: number) => (y - top) % 8 === 4 && Math.abs(dx) <= Math.max(1, half - 2) && dx % 3 !== 0 && y < base - 5
  for (let y = top; y <= base; y++) for (let dx = -half; dx <= half; dx++) {
    set(target, cx + dx, y, isWindow(dx, y) ? INDEX.window + ((cx + y) & 7) : dx === lit ? tone.rim : tone.body)
  }
  const roof = half + 2
  for (let r = 0; r <= roof * 1.6; r++) {
    const w = Math.round(roof - r / 1.6)
    for (let dx = -w; dx <= w; dx++) set(target, cx + dx, top - r, dx === (lit > 0 ? w : -w) ? tone.rim : INDEX.trees)
  }
  const pole = top - Math.round(roof * 1.6) - 1
  for (let y = pole - 5; y <= pole; y++) set(target, cx, y, INDEX.trees)
  for (let dx = 1; dx <= 4; dx++) for (let y = pole - 5; y < pole - 5 + (dx < 3 ? 3 : 2); y++) set(target, cx + dx, y, flag)
}

/** A castle on its hill: a curtain wall with battlements and a gate, towers
 *  with conical roofs and banners, and windows lit in the cycling slots. */
export function paintCastle(width: number, height: number, spec: Tone & { seed: number }): IndexedLayer {
  const castle = layer(width, height)
  // A rounded hill rising to the castle, dark against the lit stonework.
  const hill = Array.from({ length: width }, (_, x) => Math.round(height * (.72 + .26 * ((x - width / 2) / (width / 2)) ** 2)))
  for (let x = 0; x < width; x++) for (let y = hill[x]; y < height; y++) set(castle, x, y, y - hill[x] < 1 ? spec.rim : INDEX.trees)
  const cx = Math.round(width / 2), wallTop = hill[cx] - Math.round(height * .22), left = cx - Math.round(width * .2), right = cx + Math.round(width * .2)
  for (let x = left; x <= right; x++) {
    for (let y = wallTop; y <= hill[x]; y++) set(castle, x, y, spec.body)
    if ((x - left) % 6 < 3) for (let y = wallTop - 3; y < wallTop; y++) set(castle, x, y, spec.body)
    set(castle, x, wallTop, spec.rim)
  }
  for (let y = hill[cx] - 10; y <= hill[cx]; y++) for (let dx = -3; dx <= 3; dx++) if (Math.hypot(dx, (y - hill[cx] + 7) * .8) < 4 || y > hill[cx] - 7) set(castle, cx + dx, y, INDEX.window + 2)
  const towers: [number, number, number][] = [[left, 9, .42], [right, 9, .4], [cx - 14, 11, .58], [cx + 16, 7, .5], [cx, 13, .7]]
  towers.forEach(([x, w, tall], i) => paintCastleTower(castle, x, hill[x], w, Math.round(height * tall), spec, INDEX.balloon + (i % 3)))
  return castle
}

/** A beach laid on the floor, the water's edge at the top (far) row: wavy
 *  bands of surf in the cycling wave slots, so each wave rolls in toward
 *  the viewer and glows, then wet and dry sand. */
export function paintBeach(width: number, height: number, seed: number): IndexedLayer {
  const beach = layer(width, height)
  const surf = Math.round(height * .6)
  for (let x = 0; x < width; x++) {
    const edge = Math.sin(x * .05 + seed) * 3 + Math.sin(x * .13) * 1.5
    for (let y = 0; y < height; y++) {
      const depth = y - edge
      if (depth < surf) {
        const band = Math.floor(depth / (surf / INDEX.waveSteps))
        const crest = (depth % (surf / INDEX.waveSteps)) < 3.5 + Math.sin(x * .3 + band) * 1.2
        // Wet sand between crests is dark and glassy.
        set(beach, x, y, crest || bayer(x, y) < .18 ? INDEX.wave + Math.max(0, Math.min(INDEX.waveSteps - 1, band)) : INDEX.near)
      } else set(beach, x, y, bayer(x, y) < .35 + (depth - surf) / (height - surf) * .4 ? INDEX.farRim : INDEX.far)
    }
  }
  return beach
}

/** A flock of paper sky lanterns scattered over a plane: rounded bodies
 *  lit from inside in the flame slots, a brighter core near the base. */
export function paintLanterns(width: number, height: number, seed: number, count: number): IndexedLayer {
  const sky = layer(width, height)
  for (let l = 0; l < count; l++) {
    const cx = Math.floor(fxRandom(seed, l) * (width - 6)) + 3, cy = Math.floor(fxRandom(seed, l + 400) * (height - 8)) + 4
    const size = 2 + Math.floor(fxRandom(seed, l + 800) * 3), flame = INDEX.flame + (l % INDEX.flameSteps)
    for (let y = -size; y <= size; y++) for (let x = -size + 1; x < size; x++) {
      if (Math.abs(x) + Math.max(0, -y) * .4 > size) continue
      set(sky, cx + x, cy + y, y >= size - 1 && Math.abs(x) < 2 ? INDEX.lamp : flame)
    }
  }
  return sky
}

// Interiors, travel, seasons and the later worlds live in their own module.
export * from './pixelPaintScenes'
