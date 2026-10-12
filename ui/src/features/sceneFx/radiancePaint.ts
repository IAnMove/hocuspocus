import { fxRandom, type SceneFx } from './types'
import { TAU, type FxPainter } from './energyBrush'
import { css, cueLoop, loopCycles, loopNoise, rgb, smoothstep, type Rgb } from './cinematicPaint'

/** Light that has to read in a dark painted frame (candle-lit, tenebrist, night): a shockwave of
 * light, a shield or holy aura, glowing embers. They add light ('lighter'): on a dark picture they
 * glow, on a light one they only brighten it. In 2D overlays shockwave and shield replace the
 * filmed 3D sprite (paint.ts), which shows a ground ring as a flat ellipse and clamps an
 * overdriven colour to yellow.
 *
 * Colour: the soft layers are the cue colour at alphas that stay below the point where a channel
 * saturates (gold added past 255 in red keeps gaining green and turns lemon-green), their thin edges
 * take a deeper shade of it (a faint gold over a blue night stays gold, not grey), and only the thin
 * cores whiten, toward a white that takes the blue up with the green. Every painter is a pure
 * function of (seed, time). */

const clamp01 = (value: number) => Math.max(0, Math.min(1, value))
/** Offsets the soft profiles are sampled at. */
const STOPS = Array.from({ length: 17 }, (_, index) => index / 16)
/** Pieces of a ring line: each has its own light and width. */
const SEGMENTS = 120

/** `color` mixed toward white by `amount` (0–1): the hot core of a light of that colour. */
export const whiter = (color: Rgb, amount: number): Rgb => color.map(value => value + (255 - value) * clamp01(amount)) as unknown as Rgb
/** `color` with its channels pushed away from the brightest by `amount` (1 keeps it): the deeper
 * glow at the edge of a light, which keeps its hue where it thins over a dark or cool picture. */
export const richer = (color: Rgb, amount: number): Rgb => {
  const peak = Math.max(...color)
  return color.map(value => Math.max(0, peak - (peak - value) * amount)) as unknown as Rgb
}
const mix = (from: Rgb, to: Rgb, amount: number): Rgb => from.map((value, channel) => value + (to[channel] - value) * clamp01(amount)) as unknown as Rgb

/** A soft band of light at `radius`: a bell `inner` wide inside it and `outer` wide outside (a
 * front is sharp ahead and trails light behind), `alpha` at its peak. */
function band(ctx: CanvasRenderingContext2D, radius: number, inner: number, outer: number, color: Rgb, alpha: number) {
  if (alpha <= .002) return
  const from = Math.max(0, radius - inner * 2.4), to = Math.max(from + 1e-4, radius + outer * 2.4)
  const gradient = ctx.createRadialGradient(0, 0, from, 0, 0, to)
  for (const offset of STOPS) {
    const distance = from + (to - from) * offset - radius
    gradient.addColorStop(offset, css(color, alpha * Math.exp(-((distance / (distance < 0 ? inner : outer)) ** 2))))
  }
  ctx.fillStyle = gradient
  ctx.beginPath(); ctx.arc(0, 0, to, 0, TAU); ctx.fill()
}

/** A round glow at (x, y): a whiter point in a bloom of the colour that fades out at `radius`. */
function bloom(ctx: CanvasRenderingContext2D, x: number, y: number, radius: number, color: Rgb, hot: Rgb, alpha: number) {
  if (alpha <= .002 || radius <= 0) return
  const gradient = ctx.createRadialGradient(x, y, 0, x, y, radius)
  gradient.addColorStop(0, css(hot, alpha)); gradient.addColorStop(.12, css(color, alpha * .7))
  gradient.addColorStop(.4, css(color, alpha * .2)); gradient.addColorStop(1, css(color, 0))
  ctx.fillStyle = gradient
  ctx.beginPath(); ctx.arc(x, y, radius, 0, TAU); ctx.fill()
}

/** Light (0–1) around a ring, a turn being 0–1: three layers of smooth noise that repeat around it
 * and slide along it with time, so a line of energy is uneven and alive, never a drawn circle. */
function ringShape(seed: number, time: number, floor = .6, depth = .45) {
  return (turn: number) => clamp01(floor + depth * (.55 * loopNoise(seed, turn + time * .05, 7)
    + .3 * loopNoise(seed + 1, turn - time * .09, 15) + .15 * loopNoise(seed + 2, turn + time * .02, 31)))
}

/** The line of a ring in pieces whose light and width follow `shape`, moved in and out by
 * `wobble` (a fraction of the radius). */
function brokenRing(ctx: CanvasRenderingContext2D, radius: number, width: number, color: Rgb, alpha: number,
  shape: (turn: number) => number, wobble: (turn: number) => number) {
  if (alpha <= .003 || radius <= 0) return
  const point = (turn: number) => {
    const r = radius * (1 + wobble(turn)), angle = turn * TAU
    return [Math.cos(angle) * r, Math.sin(angle) * r] as const
  }
  ctx.strokeStyle = css(color)
  let [px, py] = point(0)
  for (let i = 1; i <= SEGMENTS; i++) {
    const [x, y] = point(i / SEGMENTS), light = shape((i - .5) / SEGMENTS)
    if (light * alpha > .004) {
      ctx.globalAlpha = Math.min(1, alpha * light); ctx.lineWidth = width * (.3 + 1.1 * light)
      ctx.beginPath(); ctx.moveTo(px, py); ctx.lineTo(x, y); ctx.stroke()
    }
    px = x; py = y
  }
  ctx.globalAlpha = 1
}

/** A spark: a whiter point in a small halo of the colour. */
function mote(ctx: CanvasRenderingContext2D, x: number, y: number, size: number, color: Rgb, hot: Rgb, alpha: number) {
  if (alpha <= .01) return
  bloom(ctx, x, y, size * 5, color, hot, Math.min(1, alpha * .4))
  ctx.globalAlpha = Math.min(1, alpha); ctx.fillStyle = css(hot)
  ctx.beginPath(); ctx.arc(x, y, size, 0, TAU); ctx.fill()
  ctx.globalAlpha = 1
}

// ---------------------------------------------------------------------------------------------
// shockwave: a ring of light from x/y; size its reach (the front ends half the size from the centre).

/** Where the front ends and where it starts, in cue units (1 is the cue size). */
export const SHOCK_REACH = .5
const SHOCK_START = .025
/** The fainter fronts that follow it: delay in fractions of the cue, share of the light. */
const SHOCK_ECHOES = [[.07, .5], [.15, .24]] as const

export type ShockFront = { radius: number; light: number }
export type Shockwave = { front: ShockFront; echoes: ShockFront[]; flash: number; power: number }

/** The front `seconds` into a cue `span` long: it slows as it spreads (an ease out), lights up in
 * the first tenth of a second and dims as it goes. */
export function shockFrontAt(span: number, seconds: number): ShockFront {
  const progress = clamp01(seconds / span)
  return {
    radius: SHOCK_START + (SHOCK_REACH - SHOCK_START) * (1 - (1 - progress) ** 2.6),
    light: seconds < 0 ? 0 : clamp01(seconds / Math.min(.1, span * .12)) * (1 - progress) ** 1.3,
  }
}

/** The wave at `time` (seconds into the cue): its front, the two fainter echoes that follow it and
 * the flash where it starts, which dies in about half a second. intensity sets the light. */
export function shockwaveState(cue: Pick<SceneFx, 'start' | 'end' | 'intensity'>, time: number): Shockwave {
  const span = Math.max(.05, cue.end - cue.start)
  return {
    front: shockFrontAt(span, time),
    echoes: SHOCK_ECHOES.map(([delay, share]) => {
      const echo = shockFrontAt(span, time - delay * span)
      return { radius: echo.radius, light: echo.light * share }
    }).filter(echo => echo.light > 0),
    flash: clamp01(time / .04) * Math.exp(-time / .22),
    power: Math.min(1.5, cue.intensity),
  }
}

/** One front: the air it has crossed keeps some of its light, then a soft band, a glowing line, a
 * thin hot core and brighter patches where the line is brightest. An echo has no core. */
function shockFront(ctx: CanvasRenderingContext2D, front: ShockFront, color: Rgb, hot: Rgb, power: number,
  shape: (turn: number) => number, wobble: (turn: number) => number, echo: boolean, seed = 1) {
  const { radius, light } = front
  if (light <= .003) return
  const grow = radius / SHOCK_REACH, width = .012 + .05 * grow, deep = richer(color, 1.5)
  if (echo) {
    band(ctx, radius, width * 2.2, width * .9, deep, .22 * light * power)
    brokenRing(ctx, radius, width * .7, color, .16 * light * power, shape, wobble)
    return
  }
  band(ctx, radius, radius * .38, width * .4, deep, .11 * light * power)
  band(ctx, radius, width * 1.6, width * .5, deep, .3 * light * power)
  brokenRing(ctx, radius, width * .55, color, .26 * light * power, shape, wobble)
  brokenRing(ctx, radius, .003 + .0025 * grow, hot, .9 * light * Math.min(1, power), shape, wobble)
  // Strands of light just behind the line, each a part of the way round, sliding along it.
  ctx.strokeStyle = css(hot)
  for (let i = 0; i < 16; i++) {
    const random = (slot: number) => fxRandom(seed, 900 + i * 5 + slot)
    const from = random(0) * TAU + (random(1) - .5) * radius * 1.2, length = .25 + .6 * random(2)
    const lit = shape(from / TAU % 1)
    ctx.globalAlpha = Math.min(1, .28 * light * power * lit); ctx.lineWidth = .0012 + .0018 * random(3)
    ctx.beginPath(); ctx.arc(0, 0, radius * (.95 + .04 * random(4)), from, from + length); ctx.stroke()
  }
  ctx.globalAlpha = 1
  for (let i = 0; i < 18; i++) {
    const turn = (i + .5) / 18, flare = clamp01((shape(turn) - .6) / .4)
    if (flare <= 0) continue
    ctx.save(); ctx.rotate(turn * TAU); ctx.translate(radius * (1 + wobble(turn)), 0); ctx.scale(.3, 1)
    bloom(ctx, 0, 0, width * 3.2, color, hot, .3 * light * power * flare)
    ctx.restore()
  }
}

/** A four-point glint: a soft star of thin rays and a bloom, for the brightest sparks. */
function glint(ctx: CanvasRenderingContext2D, x: number, y: number, size: number, color: Rgb, hot: Rgb, alpha: number) {
  if (alpha <= .02) return
  for (const [dx, dy] of [[1, 0], [0, 1]] as const) {
    const gradient = ctx.createLinearGradient(x - dx * size, y - dy * size, x + dx * size, y + dy * size)
    gradient.addColorStop(0, css(color, 0)); gradient.addColorStop(.5, css(hot, alpha)); gradient.addColorStop(1, css(color, 0))
    ctx.strokeStyle = gradient; ctx.lineWidth = size * .05
    ctx.beginPath(); ctx.moveTo(x - dx * size, y - dy * size); ctx.lineTo(x + dx * size, y + dy * size); ctx.stroke()
  }
  bloom(ctx, x, y, size * .35, color, hot, alpha * .6)
}

const shockwave: FxPainter = (ctx, cue, time) => {
  const span = Math.max(.05, cue.end - cue.start)
  const wave = shockwaveState(cue, time), color = rgb(cue.color), hot = whiter(color, .6)
  const wobble = (turn: number) => .014 * loopNoise(cue.seed * 7 + 9, turn, 9)
  ctx.save(); ctx.globalCompositeOperation = 'lighter'; ctx.lineCap = 'butt'
  // The light where the wave starts: a white-hot point in a wide bloom, and a thin flare across it.
  bloom(ctx, 0, 0, .12 + .2 * (1 - wave.flash), color, hot, wave.flash * Math.min(1, wave.power))
  bloom(ctx, 0, 0, .7, color, richer(color, 1.5), .2 * wave.flash * wave.power)
  if (wave.flash > .02) {
    ctx.save(); ctx.scale(1, .025); bloom(ctx, 0, 0, .9, color, hot, .5 * wave.flash * Math.min(1, wave.power)); ctx.restore()
  }
  wave.echoes.forEach((echo, index) => shockFront(ctx, echo, color, hot, wave.power, ringShape(cue.seed * 7 + 20 + index * 4, time, .5, .8), wobble, true))
  shockFront(ctx, wave.front, color, hot, wave.power, ringShape(cue.seed * 7, time, .5, .85), wobble, false, cue.seed)
  // Motes the front throws off: each left it a moment ago and drifts on more slowly, dimming, so
  // the freshest ride the front and the older trail behind it.
  for (let i = 0; i < Math.round(40 + 50 * wave.power); i++) {
    const random = (slot: number) => fxRandom(cue.seed, 700 + i * 7 + slot)
    const age = random(1) ** 1.4 * .55, born = shockFrontAt(span, time - age)
    if (born.light <= .01) continue
    const angle = random(0) * TAU + (random(2) - .5) * .06
    const r = born.radius * (1 + wobble(angle / TAU)) + age * (.03 + .05 * random(6))
    const twinkle = .45 + .55 * Math.sin(time * (5 + 9 * random(3)) + random(4) * TAU) ** 2
    const alpha = born.light * wave.power * twinkle * (1 - age / .55) ** 1.5
    const x = Math.cos(angle) * r, y = Math.sin(angle) * r
    if (i % 11 === 0) glint(ctx, x, y, .02 + .025 * random(5), color, hot, alpha * .8)
    else mote(ctx, x, y, .0012 + .0026 * random(5), color, hot, alpha)
  }
  ctx.restore()
}

// ---------------------------------------------------------------------------------------------
// shield: a dome of light around x/y (a force field, a holy aura); size its height.

/** The dome's radius in cue units and its width to its height (a figure is taller than wide). */
export const SHIELD_RADIUS = .46
export const SHIELD_ASPECT = .9

export type ShieldState = { radius: number; light: number; breath: number; power: number }

/** The dome at `time`: it swells in over the first second, breathes slowly (about one breath every
 * 3.5 s, a whole number of them over the cue) and fades out in the last half second. intensity sets
 * the light on a square-root curve, so a low value (0.4) still reads. */
export function shieldState(cue: Pick<SceneFx, 'start' | 'end' | 'intensity'>, time: number): ShieldState {
  const { span, loop } = cueLoop(cue, time)
  const rise = smoothstep(0, Math.min(.9, span * .3), time), fall = smoothstep(0, Math.min(.6, span * .2), span - time)
  const breath = Math.sin(loop * loopCycles(span, .28) * TAU)
  return {
    radius: SHIELD_RADIUS * (.88 + .12 * rise) * (1 + .02 * breath),
    light: rise * fall * (.88 + .12 * breath), breath, power: Math.min(1.5, Math.sqrt(cue.intensity)),
  }
}

/** How much a lit bubble glows at `offset` (0 centre, 1 rim) seen face on: little through its
 * middle, more where the eye looks through more of its skin. Never more than 0.25. */
export const shieldBody = (offset: number) => .03 + .22 * (1 - Math.sqrt(Math.max(0, 1 - (clamp01(offset) * .985) ** 2))) ** 1.4

const shield: FxPainter = (ctx, cue, time) => {
  const state = shieldState(cue, time)
  if (state.light <= .003) return
  const color = rgb(cue.color), hot = whiter(color, .55), deep = richer(color, 1.5), r = state.radius, light = state.light * state.power
  ctx.save(); ctx.globalCompositeOperation = 'lighter'; ctx.lineCap = 'butt'; ctx.scale(SHIELD_ASPECT, 1)
  // The air around it glows, more above: the light seems to come from over it.
  band(ctx, r, r * .05, r * .3, deep, .16 * light)
  bloom(ctx, 0, -r * .55, r * 1.25, deep, color, .07 * light)
  const body = ctx.createRadialGradient(0, 0, 0, 0, 0, r)
  for (const offset of STOPS) body.addColorStop(offset, css(deep, light * shieldBody(offset)))
  ctx.fillStyle = body
  ctx.beginPath(); ctx.arc(0, 0, r, 0, TAU); ctx.fill()
  ctx.save(); ctx.beginPath(); ctx.arc(0, 0, r, 0, TAU); ctx.clip()
  // Inside: slow soft shimmer, light ripples rising over the dome and a highlight high on one side.
  for (let i = 0; i < 4; i++) {
    const random = (slot: number) => fxRandom(cue.seed, 200 + i * 5 + slot)
    const x = r * .45 * Math.sin(time * (.11 + .08 * random(0)) + random(1) * TAU)
    const y = r * .4 * Math.sin(time * (.09 + .07 * random(2)) + random(3) * TAU)
    bloom(ctx, x, y, r * (.35 + .2 * random(4)), deep, deep, .06 * light)
  }
  for (let i = 0; i < 4; i++) {
    const phase = (time * .07 + i / 4) % 1, y = r * (.92 - 1.84 * phase), half = Math.sqrt(Math.max(0, r * r - y * y))
    const alpha = light * Math.sin(Math.PI * phase)
    ctx.save(); ctx.translate(0, y); ctx.scale(1, .16)
    band(ctx, half * .98, half * .12, half * .06, deep, .07 * alpha)
    ctx.restore()
  }
  bloom(ctx, -r * .36, -r * .52, r * .55, color, hot, .1 * light)
  ctx.restore()
  // The rim: a soft band and an uneven bright line that drifts slowly round it.
  band(ctx, r * .985, r * .09, r * .025, color, .4 * light)
  brokenRing(ctx, r * .985, .0042, hot, .75 * light, ringShape(cue.seed * 11, time * .5, .55, .6), turn => .006 * loopNoise(cue.seed * 11 + 5, turn + time * .01, 6))
  // Motes drift up through it and twinkle.
  for (let i = 0; i < Math.round(20 + 24 * state.power); i++) {
    const random = (slot: number) => fxRandom(cue.seed, 400 + i * 8 + slot)
    const period = 5 + 6 * random(0), phase = (time / period + random(1)) % 1
    const y = r * (.9 - 1.95 * phase), across = Math.sqrt(Math.max(.06, 1 - (y / r) ** 2))
    const x = (random(2) * 2 - 1) * r * .9 * across + Math.sin(time * (.5 + random(3)) + random(4) * TAU) * r * .05
    const twinkle = .55 + .45 * Math.sin(time * (2.5 + 4 * random(5)) + random(6) * TAU)
    mote(ctx, x, y, .0018 + .0028 * random(7), color, hot, 1.3 * state.light * Math.min(1, state.power) * Math.sin(Math.PI * phase) ** .7 * twinkle)
  }
  ctx.restore()
}

// ---------------------------------------------------------------------------------------------
// embers: sparks rising from the bottom of the cue box (a brazier, a candle, a pyre).

/** Embers rise and drift as they cool: each starts near white, takes the cue colour and dims to a
 * darker glow of it, flickers and leaves a short streak along its path. intensity sets how many. */
const embers: FxPainter = (ctx, cue, time) => {
  const span = cue.end - cue.start, fade = Math.min(1, time * 2.5, (span - time) * 2.5)
  if (fade <= 0) return
  const color = rgb(cue.color), hot = whiter(color, .7), cool = color.map(value => value * .45) as unknown as Rgb
  ctx.save(); ctx.globalCompositeOperation = 'lighter'; ctx.lineCap = 'round'
  for (let i = 0; i < Math.round(80 * cue.intensity); i++) {
    const random = (slot: number) => fxRandom(cue.seed, i * 11 + slot)
    const period = 2.4 + 2.6 * random(0), life = ((time + random(1) * period) / period) % 1
    const start = (random(2) - .5) * 1.2 * (.35 + .65 * random(3)), drift = (random(4) - .5) * .25
    const at = (t: number) => [
      start + drift * t + Math.sin(t * TAU * (.5 + .9 * random(5)) + random(6) * TAU) * .05 * (.25 + t),
      .5 - t * (.75 + .4 * random(7)),
    ] as const
    // The streak is about one frame of its path at 24 fps: motion blur, not a dash.
    const [x, y] = at(life), [px, py] = at(Math.max(0, life - .012))
    const flicker = .55 + .45 * Math.sin(time * (8 + 14 * random(8)) + i * 2.1)
    const alpha = fade * Math.sin(Math.PI * life) ** .5 * flicker
    if (alpha <= .01) continue
    const size = .0015 + .0035 * random(9), tone = life < .3 ? mix(hot, color, life / .3) : mix(color, cool, (life - .3) / .7)
    bloom(ctx, x, y, size * 8, tone, tone, alpha * .3)
    ctx.strokeStyle = css(tone, alpha * .8); ctx.lineWidth = size * 1.5
    ctx.beginPath(); ctx.moveTo(px, py); ctx.lineTo(x, y); ctx.stroke()
    ctx.fillStyle = css(whiter(tone, .35), alpha)
    ctx.beginPath(); ctx.arc(x, y, size * .8, 0, TAU); ctx.fill()
  }
  ctx.restore()
}

/** Light painted straight on the frame; shockwave and shield also replace their 3D sprite in 2D overlays. */
export const radiancePainters: Record<string, FxPainter> = { shockwave, shield, embers }
