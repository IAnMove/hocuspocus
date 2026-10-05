import { fxRandom, type SceneFx } from './types'
import { GLITCH_KIND, paintGlitch } from './glitchPaint'

/** Cinematic light and film: whole-frame grades for candle-lit, tenebrist scenes, painted outside
 * the cue's x/y/size transform. Each painter below says what x, y, size and rotation mean for it.
 *
 * Every painter is a pure function of (seed, time) and repeats over the cue: whatever moves makes
 * a whole number of cycles between `start` and `end`, so the frame at `end` is the frame at
 * `start` and a plate as long as the cue loops with no seam. vignette and canvas do not move.
 *
 * candlelight, light_rays, film_grain and canvas blend with the picture under them (colour dodge,
 * screen, overlay, multiply) and glitch moves its pixels, so the editor overlays copy the stage
 * first for them, as for the retro looks. vignette only darkens and paints the same over anything. */
export const CINEMATIC_KINDS = ['candlelight', 'vignette', 'film_grain', 'light_rays', GLITCH_KIND, 'canvas'] as const
const BLENDED = new Set<string>(['candlelight', 'film_grain', 'light_rays', GLITCH_KIND, 'canvas'])

type Rgb = readonly [number, number, number]
type FramePainter = (ctx: CanvasRenderingContext2D, cue: SceneFx, time: number, width: number, height: number) => void

const frac = (value: number) => value - Math.floor(value)
const clamp01 = (value: number) => Math.max(0, Math.min(1, value))
export const smoothstep = (from: number, to: number, value: number) => {
  const t = clamp01((value - from) / (to - from))
  return t * t * (3 - 2 * t)
}
/** Gradient stops: the painters sample their smooth profiles at these offsets. */
const STOPS = Array.from({ length: 13 }, (_, index) => index / 12)

/** The cue's span and the position in it, wrapped first so the frame at `end` is computed exactly
 * as the frame at `start`. */
export function cueLoop(cue: Pick<SceneFx, 'start' | 'end'>, time: number) {
  const span = Math.max(1e-6, cue.end - cue.start)
  return { span, loop: frac(time / span) }
}

/** The whole number of cycles over the cue nearest to `hertz` (at least one). */
export const loopCycles = (span: number, hertz: number) => Math.max(1, Math.round(span * hertz))

/** Smooth noise in [-1, 1] that repeats over the loop: `cycles` random knots (at least two, so it
 * always moves), eased between. */
export function loopNoise(seed: number, loop: number, cycles: number): number {
  const knots = Math.max(2, cycles)
  const at = frac(loop) * knots, index = Math.floor(at), t = at - index
  const knot = (k: number) => fxRandom(seed, k % knots) * 2 - 1
  const from = knot(index)
  return from + (knot(index + 1) - from) * t * t * (3 - 2 * t)
}

export function rgb(color: string): Rgb {
  const hex = /^#[\da-f]{6}$/i.test(color) ? color : '#ffffff'
  return [1, 3, 5].map(offset => parseInt(hex.slice(offset, offset + 2), 16)) as unknown as Rgb
}
const css = (color: Rgb, alpha = 1) =>
  `rgba(${color.map(value => Math.round(Math.max(0, Math.min(255, value)))).join(', ')}, ${Math.round(clamp01(alpha) * 10000) / 10000})`
const scaled = (color: Rgb, amount: number) => color.map(value => value * amount) as unknown as Rgb

/** True for the kinds that need the picture under them in the editor preview. */
export function blendsWithFrame(kind: string): boolean {
  return BLENDED.has(kind)
}

// ---------------------------------------------------------------------------------------------
// candlelight: x/y the flame, size the radius of its pool of light in % of the frame height.

/** The darkness reaches its full strength this many light radii away from the flame. */
export const CANDLE_DARK_REACH = 2.6
/** The flicker changes the light by up to this fraction. */
const CANDLE_FLICKER = .16
const CANDLE_GLOW = .45

/** By distance from the flame in light radii: the pool of light on what is lit (1 at the flame, 0
 * at the radius), the glow in the air close to the flame, and the darkness away from it (0–1). */
export const candlePool = (r: number) => r >= 1 ? 0 : (1 - r * r) ** 2
export const candleGlow = (r: number) => r >= CANDLE_GLOW ? 0 : (1 - r / CANDLE_GLOW) ** 2
export const candleShade = (r: number) => smoothstep(.3, CANDLE_DARK_REACH, r)

export type CandleField = { x: number; y: number; radius: number; flicker: number; light: number; glow: number; darkness: number; color: Rgb }

/** The light at one moment. The flicker is three layers of smooth noise near 1.6, 3.7 and 7.9 Hz:
 * the flame breathes, wavers and trembles, and never strobes. intensity sets the light, the glow
 * and the darkness together. */
export function candlelightField(cue: SceneFx, time: number, width: number, height: number): CandleField {
  const { span, loop } = cueLoop(cue, time)
  const layer = (slot: number, hertz: number) => loopNoise(cue.seed * 13 + slot, loop, loopCycles(span, hertz))
  const flicker = 1 + CANDLE_FLICKER * (.5 * layer(1, 1.6) + .32 * layer(2, 3.7) + .18 * layer(3, 7.9))
  const amount = Math.min(2, cue.intensity)
  const radius = Math.max(1, height * cue.size / 100) * (.95 + .05 * flicker)
  return {
    // The flame sways a little.
    x: width * cue.x / 100 + radius * .03 * layer(4, 1.1),
    y: height * cue.y / 100 + radius * .02 * layer(5, 1.3),
    radius, flicker,
    light: Math.min(.8, .4 * amount * flicker),
    glow: Math.min(.6, .2 * amount * flicker),
    darkness: 1 - Math.exp(-.36 * amount),
    color: rgb(cue.color),
  }
}

/** The colour (0–255 RGB) the painter gives a pixel at (px, py): darkened away from the flame, lit
 * by colour dodge (the picture times up to 1 / (1 - light), so what is there takes the light), and
 * the glow screened over it. The painter draws the same three layers as gradients. */
export function candlelightAt(field: CandleField, px: number, py: number, pixel: Rgb): Rgb {
  const r = Math.hypot(px - field.x, py - field.y) / field.radius
  const shade = 1 - field.darkness * candleShade(r)
  return pixel.map((value, channel) => {
    const base = value / 255 * shade
    const dodge = field.color[channel] / 255 * field.light * candlePool(r)
    const lit = base <= 0 ? 0 : Math.min(1, base / Math.max(1e-6, 1 - dodge))
    const glow = field.color[channel] / 255 * field.glow * candleGlow(r)
    return 255 * (1 - (1 - lit) * (1 - glow))
  }) as unknown as Rgb
}

function radial(ctx: CanvasRenderingContext2D, x: number, y: number, radius: number, stop: (offset: number) => string) {
  const gradient = ctx.createRadialGradient(x, y, 0, x, y, radius)
  for (const offset of STOPS) gradient.addColorStop(offset, stop(offset))
  return gradient
}

const paintCandlelight: FramePainter = (ctx, cue, time, width, height) => {
  const field = candlelightField(cue, time, width, height)
  const { x, y, radius, color } = field
  ctx.save()
  ctx.fillStyle = radial(ctx, x, y, radius * CANDLE_DARK_REACH, offset => css([0, 0, 0], field.darkness * candleShade(offset * CANDLE_DARK_REACH)))
  ctx.fillRect(0, 0, width, height)
  ctx.globalCompositeOperation = 'color-dodge'
  ctx.fillStyle = radial(ctx, x, y, radius, offset => css(scaled(color, field.light * candlePool(offset))))
  ctx.fillRect(x - radius, y - radius, radius * 2, radius * 2)
  const glow = radius * CANDLE_GLOW
  ctx.globalCompositeOperation = 'screen'
  ctx.fillStyle = radial(ctx, x, y, glow, offset => css(scaled(color, field.glow * candleGlow(offset * CANDLE_GLOW))))
  ctx.fillRect(x - glow, y - glow, glow * 2, glow * 2)
  ctx.restore()
}

// ---------------------------------------------------------------------------------------------
// vignette: x/y the clear centre, size how far in the darkening reaches, static.

/** How dark the vignette is (0–1) at `r`, the distance from its centre in half frames (1 at the
 * middle of an edge, √2 at a corner of a centred vignette). size 100 starts it at the centre; at
 * 60 the first 40 % of the way to the corners stays clear. intensity sets how dark the corners get. */
export function vignetteShade(cue: Pick<SceneFx, 'size' | 'intensity'>, r: number): number {
  const inner = Math.SQRT2 * (1 - Math.min(1, cue.size / 100))
  return (1 - Math.exp(-1.3 * cue.intensity)) * smoothstep(inner, Math.SQRT2, r)
}

const paintVignette: FramePainter = (ctx, cue, _time, width, height) => {
  const cx = width * cue.x / 100, cy = height * cue.y / 100, sx = width / 2, sy = height / 2
  // The farthest corner, in half frames: a vignette moved off centre still darkens every corner.
  const far = Math.hypot(Math.max(cx, width - cx) / sx, Math.max(cy, height - cy) / sy)
  const color = rgb(cue.color)
  ctx.save()
  ctx.translate(cx, cy); ctx.scale(sx, sy)
  ctx.fillStyle = radial(ctx, 0, 0, far, offset => css(color, vignetteShade(cue, offset * far)))
  ctx.fillRect(-cx / sx, -cy / sy, width / sx, height / sy)
  ctx.restore()
}

// ---------------------------------------------------------------------------------------------
// light_rays: x/y where the light comes from, rotation where it points (0 right, 90 down), size
// the length of the shafts in % of the frame height.

/** The fan of shafts is about 34 degrees wide. */
export const RAY_SPREAD = .6
export type LightShaft = { angle: number; reach: number; width: number; alpha: number }
export type LightRays = { x: number; y: number; length: number; direction: number; haze: number; glow: number; shafts: LightShaft[] }

/** The shafts at one moment. Each sways over several seconds (0.06–0.12 Hz) and brightens and
 * fades over a few (0.2–0.45 Hz); intensity sets how many there are and how bright. */
export function lightRays(cue: SceneFx, time: number, width: number, height: number): LightRays {
  const { span, loop } = cueLoop(cue, time)
  const amount = Math.min(2, cue.intensity)
  const length = Math.max(1, height * cue.size / 100)
  const direction = (cue.rotation ?? 0) * Math.PI / 180
  const shafts = Array.from({ length: Math.round(10 + 5 * amount) }, (_, index): LightShaft => {
    const random = (slot: number) => fxRandom(cue.seed, index * 8 + slot)
    const drift = loopNoise(cue.seed * 17 + index, loop, loopCycles(span, .06 + .06 * random(5)))
    const shimmer = loopNoise(cue.seed * 29 + index, loop, loopCycles(span, .2 + .25 * random(6)))
    return {
      angle: direction + (random(0) - .5) * RAY_SPREAD + drift * .035,
      reach: length * (.55 + .45 * random(1)),
      width: length * (.05 + .16 * random(2)),
      alpha: Math.min(1, (.035 + .06 * random(3)) * amount * (.55 + .45 * shimmer)),
    }
  })
  return { x: width * cue.x / 100, y: height * cue.y / 100, length, direction, shafts, haze: Math.min(.5, .09 * amount), glow: Math.min(.9, .32 * amount) }
}

/** Widths of the nested wedges of one shaft: equal alpha each, so the edge fades softly. */
const SHAFT_LAYERS = [1, .78, .56, .36, .18] as const

/** A soft shaft along +x after `angle`: a little wide at the source (an opening, not a point),
 * `spread` wide at `reach`, brightest a third of the way out and fading to nothing. */
function shaft(ctx: CanvasRenderingContext2D, angle: number, reach: number, spread: number, color: Rgb, alpha: number) {
  ctx.save(); ctx.rotate(angle)
  const fade = ctx.createLinearGradient(0, 0, reach, 0)
  for (const [offset, share] of [[0, .8], [.3, 1], [.75, .45], [1, 0]] as const) fade.addColorStop(offset, css(color, alpha / SHAFT_LAYERS.length * share))
  ctx.fillStyle = fade
  for (const layer of SHAFT_LAYERS) {
    const end = spread * layer / 2, start = Math.max(end * .12, reach * .006)
    ctx.beginPath(); ctx.moveTo(0, -start); ctx.lineTo(reach, -end); ctx.lineTo(reach, end); ctx.lineTo(0, start)
    ctx.closePath(); ctx.fill()
  }
  ctx.restore()
}

const paintLightRays: FramePainter = (ctx, cue, time, width, height) => {
  const rays = lightRays(cue, time, width, height)
  const color = rgb(cue.color)
  ctx.save()
  ctx.globalCompositeOperation = 'screen'
  ctx.translate(rays.x, rays.y)
  // The lit air of the whole fan, then the shafts in it.
  shaft(ctx, rays.direction, rays.length, rays.length * Math.tan(RAY_SPREAD * .6) * 2, color, rays.haze)
  for (const item of rays.shafts) shaft(ctx, item.angle, item.reach, item.width, color, item.alpha)
  const glow = rays.length * .2
  ctx.fillStyle = radial(ctx, 0, 0, glow, offset => css(color, rays.glow * (1 - offset) ** 2))
  ctx.fillRect(-glow, -glow, glow * 2, glow * 2)
  ctx.restore()
}

// ---------------------------------------------------------------------------------------------
// Off-screen surfaces for the grain and the canvas texture. There are none in Node tests, where
// those two painters draw nothing.

type Surface = { canvas: OffscreenCanvas | HTMLCanvasElement; context: OffscreenCanvasRenderingContext2D | CanvasRenderingContext2D }
const surfaces = new Map<string, Surface>()

function surface(name: string, width: number, height: number): Surface | null {
  let entry = surfaces.get(name)
  if (!entry) {
    const canvas = typeof OffscreenCanvas !== 'undefined' ? new OffscreenCanvas(width, height)
      : typeof document !== 'undefined' ? Object.assign(document.createElement('canvas'), { width, height }) : null
    const context = canvas?.getContext('2d') as Surface['context'] | null | undefined
    if (!canvas || !context) return null
    entry = { canvas, context }
    surfaces.set(name, entry)
    // A few cached textures at most; a new one evicts the oldest.
    if (surfaces.size > 4) surfaces.delete(surfaces.keys().next().value!)
  }
  if (entry.canvas.width !== width || entry.canvas.height !== height) { entry.canvas.width = width; entry.canvas.height = height }
  return entry
}

function put(target: Surface, pixels: Uint8ClampedArray, width: number, height: number) {
  const image = target.context.createImageData(width, height)
  image.data.set(pixels)
  target.context.putImageData(image, 0, 0)
}

// ---------------------------------------------------------------------------------------------
// film_grain: monochrome grain over the whole frame; size the grain size in % of the standard
// (100 is about 2 px on a 1080-line frame); x, y, rotation and colour are not used.

/** New grain this many times a second: every frame of a 24 to 60 fps export has its own. */
export const GRAIN_RATE = 60
/** Grey levels of the grain at intensity 1 (in the overlay layer). */
const GRAIN_LEVELS = 20

export const grainCell = (height: number, size: number) => Math.max(1, height / 540 * size / 100)

/** One frame of grain, RGBA, a grey value per cell around 127.5. It is drawn with `overlay`, which
 * is linear in the grain, so grain with a mean of 127.5 leaves the mean of the picture as it was;
 * like film it shows most in the midtones and least in deep shadows and highlights. */
export function filmGrainTile(cue: SceneFx, time: number, columns: number, rows: number): Uint8ClampedArray {
  const { span, loop } = cueLoop(cue, time)
  const frames = loopCycles(span, GRAIN_RATE)
  // A quarter step late, so frames at 24, 25, 30, 50 or 60 fps never fall on a change of grain.
  const seed = cue.seed * 7919 + (Math.floor(loop * frames + .25) % frames) * 104729
  const amplitude = GRAIN_LEVELS * Math.min(2, cue.intensity)
  const data = new Uint8ClampedArray(columns * rows * 4)
  for (let cell = 0, i = 0; cell < columns * rows; cell++, i += 4) {
    // The sum of three uniform values is close to normal, with a deviation of 0.5.
    const noise = fxRandom(seed, cell * 3) + fxRandom(seed, cell * 3 + 1) + fxRandom(seed, cell * 3 + 2) - 1.5
    data[i] = data[i + 1] = data[i + 2] = 127.5 + noise * amplitude
    data[i + 3] = 255
  }
  return data
}

const paintFilmGrain: FramePainter = (ctx, cue, time, width, height) => {
  const cell = grainCell(height, cue.size)
  const columns = Math.ceil(width / cell), rows = Math.ceil(height / cell)
  const target = typeof ctx.drawImage === 'function' ? surface('grain', columns, rows) : null
  if (!target) return
  put(target, filmGrainTile(cue, time, columns, rows), columns, rows)
  ctx.save()
  ctx.globalCompositeOperation = 'overlay'; ctx.imageSmoothingEnabled = true
  ctx.drawImage(target.canvas, 0, 0, columns * cell, rows * cell)
  ctx.restore()
}

// ---------------------------------------------------------------------------------------------
// canvas: a painted-canvas texture multiplied over the frame, tinted by colour; size the texture
// scale in % of the standard (100: threads about 4.6 px apart on a 1080-line frame); static.

/** Smooth value noise in [0, 1] on a lattice of unit cells. */
function valueNoise(seed: number, x: number, y: number) {
  const ix = Math.floor(x), iy = Math.floor(y), fx = x - ix, fy = y - iy
  const at = (cx: number, cy: number) => fxRandom(seed, (cx & 1023) + ((cy & 1023) << 10))
  const sx = fx * fx * (3 - 2 * fx), sy = fy * fy * (3 - 2 * fy)
  const top = at(ix, iy) + (at(ix + 1, iy) - at(ix, iy)) * sx
  const bottom = at(ix, iy + 1) + (at(ix + 1, iy + 1) - at(ix, iy + 1)) * sx
  return top + (bottom - top) * sy
}

/** Brush strokes at (x, y) in 1080-line pixels, in [0, 1]: ridges stretched along the direction
 * of the nearest patches of paint (each patch has its own), stronger where the paint is thick. */
function brush(seed: number, x: number, y: number) {
  const patch = 170, px = x / patch - .5, py = y / patch - .5
  const ix = Math.floor(px), iy = Math.floor(py), fx = smoothstep(0, 1, px - ix), fy = smoothstep(0, 1, py - iy)
  let ridges = 0
  for (const [dx, dy, weight] of [[0, 0, (1 - fx) * (1 - fy)], [1, 0, fx * (1 - fy)], [0, 1, (1 - fx) * fy], [1, 1, fx * fy]] as const) {
    const cx = ix + dx, cy = iy + dy, index = (cx & 1023) + ((cy & 1023) << 10)
    // Strokes lean the same general way, as a painter's hand does, each patch a little differently.
    const turn = .5 + (fxRandom(seed + 3, index) - .5) * 1.6
    const ox = x - (cx + .5) * patch, oy = y - (cy + .5) * patch
    const along = ox * Math.cos(turn) + oy * Math.sin(turn), across = -ox * Math.sin(turn) + oy * Math.cos(turn)
    const shift = fxRandom(seed + 5, index) * 97
    ridges += weight * (.65 * valueNoise(seed + 7, along / 120 + shift, across / 8) + .35 * valueNoise(seed + 9, along / 40 + shift, across / 3.5))
  }
  return ridges * (.35 + .65 * valueNoise(seed + 11, x / 300, y / 300))
}

/** Thickness of each thread, 0.75–1: a hand-woven cloth is not even. */
const threads = (seed: number, count: number) => Float32Array.from({ length: count }, (_, index) => .75 + .25 * fxRandom(seed, index))

/** The canvas layer, RGBA, `columns` × `rows` pixels of a frame `height` pixels high: woven cloth
 * (warp and weft of uneven thickness, dark between the threads) under brush strokes, tinted by
 * the cue colour. It only darkens (multiply): a few percent in the weave, a little more in the
 * strokes; intensity sets the depth and the tint. The strokes are worked out every 3 pixels and
 * eased between. */
export function canvasTexture(cue: Pick<SceneFx, 'seed' | 'size' | 'intensity' | 'color'>, columns: number, rows: number, height = rows): Uint8ClampedArray {
  const unit = Math.max(.25, height / 1080 * cue.size / 100), pitch = 4.6 * unit
  const amount = Math.min(2, cue.intensity)
  const tint = rgb(cue.color).map(value => 255 * (1 - (1 - value / 255) * Math.min(1, .55 * amount)))
  const weaveDepth = .1 * amount, strokeDepth = .13 * amount
  const warp = threads(cue.seed + 11, Math.ceil(columns / pitch) + 1), weft = threads(cue.seed + 23, Math.ceil(rows / pitch) + 1)
  const step = 3, gridColumns = Math.ceil(columns / step) + 2, gridRows = Math.ceil(rows / step) + 2
  const strokes = new Float32Array(gridColumns * gridRows)
  for (let gy = 0; gy < gridRows; gy++) for (let gx = 0; gx < gridColumns; gx++) strokes[gy * gridColumns + gx] = brush(cue.seed, gx * step / unit, gy * step / unit)
  const data = new Uint8ClampedArray(columns * rows * 4)
  for (let y = 0; y < rows; y++) {
    const v = y / pitch, row = Math.floor(v), weftProfile = Math.abs(Math.sin(Math.PI * v)) ** .7 * weft[row]
    const gy = Math.floor(y / step), ty = y / step - gy
    for (let x = 0; x < columns; x++) {
      const u = x / pitch, column = Math.floor(u)
      // Over and under: the warp shows on one diagonal of the checker, the weft on the other.
      const weave = ((row + column) & 1) === 0 ? Math.abs(Math.sin(Math.PI * u)) ** .7 * warp[column] : weftProfile
      const gx = Math.floor(x / step), tx = x / step - gx, cell = gy * gridColumns + gx
      const top = strokes[cell] + (strokes[cell + 1] - strokes[cell]) * tx
      const bottom = strokes[cell + gridColumns] + (strokes[cell + gridColumns + 1] - strokes[cell + gridColumns]) * tx
      const shade = 1 - weaveDepth * (1 - weave) - strokeDepth * (top + (bottom - top) * ty)
      const i = (y * columns + x) * 4
      data[i] = tint[0] * shade; data[i + 1] = tint[1] * shade; data[i + 2] = tint[2] * shade; data[i + 3] = 255
    }
  }
  return data
}

const paintCanvas: FramePainter = (ctx, cue, _time, width, height) => {
  // At most 2048 px on the long side; larger frames take it scaled up.
  const scale = Math.min(1, 2048 / Math.max(width, height))
  const columns = Math.max(1, Math.round(width * scale)), rows = Math.max(1, Math.round(height * scale))
  const key = `canvas:${columns}x${rows}:${cue.seed}:${cue.size}:${cue.intensity}:${cue.color}`
  const fresh = !surfaces.has(key)
  const target = typeof ctx.drawImage === 'function' ? surface(key, columns, rows) : null
  if (!target) return
  if (fresh) put(target, canvasTexture(cue, columns, rows, rows), columns, rows)
  ctx.save()
  ctx.globalCompositeOperation = 'multiply'; ctx.imageSmoothingEnabled = true
  ctx.drawImage(target.canvas, 0, 0, width, height)
  ctx.restore()
}

const PAINTERS: Record<string, FramePainter> = {
  candlelight: paintCandlelight, vignette: paintVignette, film_grain: paintFilmGrain,
  light_rays: paintLightRays, [GLITCH_KIND]: paintGlitch, canvas: paintCanvas,
}

/** The painter of a cinematic kind, or undefined for any other. */
export function cinematicPainter(kind: string): FramePainter | undefined {
  return PAINTERS[kind]
}
