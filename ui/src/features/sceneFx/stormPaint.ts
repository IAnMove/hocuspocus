import { fxRandom } from './types'
import { glow, TAU, type FxPainter } from './energyBrush'
import { boltChannels, strikeState, type BoltChannel } from './lightningBolt'

type Point = [number, number]

/** Map a unit bolt (y along the stroke) onto a segment in cue space. */
function mapChannel(channel: BoltChannel, from: Point, to: Point, leader: number): Point[] {
  const dx = to[0] - from[0], dy = to[1] - from[1], length = Math.hypot(dx, dy) || 1
  const ux = dx / length, uy = dy / length
  const out: Point[] = []
  for (let i = 0; i < channel.points.length; i++) {
    if (channel.order[i] > leader) break
    const [x, y] = channel.points[i]
    out.push([from[0] + ux * y * length - uy * x * length, from[1] + uy * y * length + ux * x * length])
  }
  return out
}

function polyline(ctx: CanvasRenderingContext2D, points: Point[]) {
  ctx.beginPath()
  points.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)))
  ctx.stroke()
}

/** Wide coloured halo, tighter glow, then a white-hot core. */
function strokeBolt(ctx: CanvasRenderingContext2D, points: Point[], color: string, width: number, brightness: number) {
  if (points.length < 2) return
  ctx.save()
  ctx.lineJoin = 'round'; ctx.lineCap = 'round'; ctx.strokeStyle = color
  ctx.globalAlpha = Math.min(1, .07 * brightness); ctx.lineWidth = width * 9; polyline(ctx, points)
  ctx.globalAlpha = Math.min(1, .2 * brightness); ctx.lineWidth = width * 3.6; polyline(ctx, points)
  ctx.globalAlpha = Math.min(1, .65 * brightness); ctx.lineWidth = width * 1.6; polyline(ctx, points)
  ctx.strokeStyle = '#ffffff'; ctx.globalAlpha = Math.min(1, brightness); ctx.lineWidth = width * .6; polyline(ctx, points)
  ctx.restore()
}

/** Light thrown across the whole frame by a strike, centred on the bolt. */
function skyFlash(ctx: CanvasRenderingContext2D, color: string, amount: number) {
  if (amount <= .01 || !ctx.canvas || typeof ctx.getTransform !== 'function') return
  // The cue's origin in canvas pixels is the transform's translation.
  const { e: x, f: y } = ctx.getTransform()
  const { width, height } = ctx.canvas
  ctx.save(); ctx.setTransform(1, 0, 0, 1, 0, 0)
  const gradient = ctx.createRadialGradient(x, y, 0, x, y, Math.max(width, height) * .9)
  gradient.addColorStop(0, color); gradient.addColorStop(1, color + '00')
  ctx.globalCompositeOperation = 'screen'; ctx.globalAlpha = Math.min(.55, amount * .45)
  ctx.fillStyle = gradient; ctx.fillRect(0, 0, width, height)
  ctx.restore()
}

export const lightningStrike: FxPainter = (ctx, cue, time) => {
  const state = strikeState(cue.seed, time, cue.end - cue.start)
  if (state.brightness <= .005) return
  const shapeSeed = cue.seed * 31 + state.strike
  const brightness = state.brightness * cue.intensity
  skyFlash(ctx, cue.color, state.flash * cue.intensity)
  ctx.save(); ctx.globalCompositeOperation = 'lighter'
  const from: Point = [(fxRandom(shapeSeed, 1) - .5) * .25, -.62]
  const to: Point = [(fxRandom(shapeSeed, 2) - .5) * .35, .52]
  for (const channel of boltChannels(shapeSeed)) {
    strokeBolt(ctx, mapChannel(channel, from, to, state.leader), cue.color, .006 * channel.width, brightness * (.55 + channel.width * .45))
  }
  if (state.leader >= 1) {
    ctx.save(); ctx.translate(to[0], to[1]); glow(ctx, cue.color, .12 + .08 * Math.min(1, brightness), Math.min(1, brightness * .8)); ctx.restore()
  }
  ctx.restore()
}

export const lightningStorm: FxPainter = (ctx, cue, time, progress) => {
  const fade = Math.min(1, progress * 10, (1 - progress) * 8)
  ctx.save(); ctx.globalCompositeOperation = 'lighter'; ctx.globalAlpha = fade
  glow(ctx, cue.color, .55, .22 + .08 * Math.sin(time * 23))
  const arms = Math.round(6 + 3 * cue.intensity)
  for (let arm = 0; arm < arms; arm++) {
    // Each arm crackles on its own clock so the ball never pulses in unison.
    const state = strikeState(cue.seed + arm * 97, time + arm * .13, cue.end - cue.start + 1, [.12, .34])
    if (state.brightness <= .01) continue
    const shapeSeed = cue.seed * 17 + arm * 131 + state.strike
    const angle = arm / arms * TAU + (fxRandom(shapeSeed, 5) - .5) * .9
    const reach = .32 + fxRandom(shapeSeed, 6) * .24
    const to: Point = [Math.cos(angle) * reach, Math.sin(angle) * reach]
    for (const channel of boltChannels(shapeSeed, { branches: 3, detail: 5 })) {
      strokeBolt(ctx, mapChannel(channel, [0, 0], to, state.leader), cue.color, .0042 * channel.width, state.brightness * cue.intensity * fade)
    }
  }
  glow(ctx, '#ffffff', .07, fade)
  ctx.restore()
}

export const laserBeam: FxPainter = (ctx, cue, time, progress) => {
  const span = cue.end - cue.start
  const reach = Math.min(1, time / Math.min(.25, span * .15))
  const fade = Math.min(1, (span - time) * 6)
  const start = -.62, end = start + reach * 1.3
  const pulse = 1 + Math.sin(time * 38) * .08 + (fxRandom(cue.seed, Math.floor(time * 30)) - .5) * .1
  const width = .016 * cue.intensity * pulse
  ctx.save(); ctx.globalCompositeOperation = 'lighter'; ctx.globalAlpha = fade
  for (const [scale, alpha, color] of [[5, .12, cue.color], [2.4, .35, cue.color], [1, .9, cue.color], [.35, 1, '#ffffff']] as const) {
    const gradient = ctx.createLinearGradient(0, -width * scale, 0, width * scale)
    gradient.addColorStop(0, color + '00'); gradient.addColorStop(.5, color); gradient.addColorStop(1, color + '00')
    ctx.globalAlpha = fade * alpha; ctx.fillStyle = gradient
    ctx.fillRect(start, -width * scale, end - start, width * scale * 2)
  }
  ctx.globalAlpha = fade
  ctx.save(); ctx.translate(start, 0); glow(ctx, cue.color, .1 * pulse); ctx.restore()
  if (reach >= 1) {
    ctx.save(); ctx.translate(end, 0); glow(ctx, cue.color, .13 * pulse, .9)
    ctx.strokeStyle = '#ffffff'; ctx.lineCap = 'round'
    for (let i = 0; i < 14; i++) {
      const life = (time * 2.4 + fxRandom(cue.seed, i)) % 1
      const angle = Math.PI + (fxRandom(cue.seed, i + 30) - .5) * 2.2
      const r = life * (.08 + fxRandom(cue.seed, i + 60) * .12)
      ctx.globalAlpha = fade * (1 - life); ctx.lineWidth = .004 * (1 - life)
      ctx.beginPath(); ctx.moveTo(Math.cos(angle) * r * .6, Math.sin(angle) * r * .6); ctx.lineTo(Math.cos(angle) * r, Math.sin(angle) * r); ctx.stroke()
    }
    ctx.restore()
  }
  ctx.restore(); void progress
}

/** Weather fills the frame, not the cue's box: size scales the drops. */
function frame(ctx: CanvasRenderingContext2D) {
  const width = ctx.canvas?.width ?? 1, height = ctx.canvas?.height ?? 1
  ctx.save(); ctx.setTransform(1, 0, 0, 1, 0, 0)
  return { width, height, unit: Math.min(width, height) }
}

function envelope(time: number, span: number) {
  return Math.min(1, time * 2.5, (span - time) * 2.5)
}

export const rainFall: FxPainter = (ctx, cue, time) => {
  const { width, height, unit } = frame(ctx)
  const fade = envelope(time, cue.end - cue.start), scale = cue.size / 95
  const slant = Math.sin((cue.rotation ?? 0) * Math.PI / 180) + .18
  ctx.lineCap = 'round'; ctx.strokeStyle = cue.color
  const count = Math.round(260 * cue.intensity)
  for (let i = 0; i < count; i++) {
    const depth = .35 + fxRandom(cue.seed, i) * .65
    const speed = 1.6 + depth * 1.4
    const y = ((fxRandom(cue.seed, i + 500) + time * speed) % 1.15) - .1
    const x = (fxRandom(cue.seed, i + 1000) * 1.3 - .15) + y * slant * .25
    const length = unit * .05 * depth * scale
    ctx.globalAlpha = fade * (.12 + depth * .38); ctx.lineWidth = Math.max(.6, unit * .0018 * depth * scale)
    ctx.beginPath(); ctx.moveTo(x * width, y * height); ctx.lineTo(x * width - length * slant * .4, y * height - length); ctx.stroke()
  }
  // Splashes where drops meet the lower part of the frame.
  ctx.strokeStyle = cue.color; ctx.lineWidth = Math.max(.6, unit * .0015)
  for (let i = 0; i < Math.round(40 * cue.intensity); i++) {
    const life = (time * 3 + fxRandom(cue.seed, i + 2000)) % 1
    const x = fxRandom(cue.seed, i + 2100) * width, y = height * (.78 + fxRandom(cue.seed, i + 2200) * .2)
    ctx.globalAlpha = fade * .45 * (1 - life)
    ctx.beginPath(); ctx.ellipse(x, y, unit * .012 * life * scale, unit * .004 * life * scale, 0, 0, TAU); ctx.stroke()
  }
  ctx.restore()
}

export const snowFall: FxPainter = (ctx, cue, time) => {
  const { width, height, unit } = frame(ctx)
  const fade = envelope(time, cue.end - cue.start), scale = cue.size / 95
  ctx.fillStyle = cue.color
  for (let i = 0; i < Math.round(180 * cue.intensity); i++) {
    const depth = .3 + fxRandom(cue.seed, i) * .7
    const y = ((fxRandom(cue.seed, i + 500) + time * (.05 + depth * .09)) % 1.1) - .05
    const sway = Math.sin(time * (.8 + depth) + i) * .018
    const x = (fxRandom(cue.seed, i + 1000) + sway + time * .01) % 1
    ctx.globalAlpha = fade * (.3 + depth * .6)
    ctx.beginPath(); ctx.arc(x * width, y * height, Math.max(.7, unit * .0045 * depth * scale), 0, TAU); ctx.fill()
  }
  ctx.restore()
}

function puff(ctx: CanvasRenderingContext2D, x: number, y: number, radius: number, color: string, alpha: number) {
  const gradient = ctx.createRadialGradient(x, y - radius * .2, 0, x, y, radius)
  gradient.addColorStop(0, color); gradient.addColorStop(.55, color + 'aa'); gradient.addColorStop(1, color + '00')
  ctx.globalAlpha = alpha; ctx.fillStyle = gradient
  ctx.beginPath(); ctx.arc(x, y, radius, 0, TAU); ctx.fill()
}

export const fogBank: FxPainter = (ctx, cue, time) => {
  const { width, height } = frame(ctx)
  const fade = envelope(time, cue.end - cue.start) * cue.intensity
  for (let i = 0; i < 14; i++) {
    const drift = ((fxRandom(cue.seed, i) + time * (.012 + fxRandom(cue.seed, i + 20) * .02)) % 1.4) - .2
    const y = height * (.45 + fxRandom(cue.seed, i + 40) * .5)
    const radius = width * (.22 + fxRandom(cue.seed, i + 60) * .2)
    ctx.save(); ctx.translate(drift * width, y); ctx.scale(1, .32)
    puff(ctx, 0, 0, radius, cue.color, .16 * fade)
    ctx.restore()
  }
  ctx.restore()
}

export const smokePlume: FxPainter = (ctx, cue, time) => {
  const fade = envelope(time, cue.end - cue.start)
  const shade = '#1c1a22'
  for (let i = 0; i < 26; i++) {
    const life = (time * .22 + fxRandom(cue.seed, i)) % 1
    const x = (fxRandom(cue.seed, i + 30) - .5) * .12 + Math.sin(life * 3 + i) * .05 + life * life * .18
    const y = .3 - life * .78
    const radius = .06 + life * .22
    const alpha = Math.sin(life * Math.PI) * .32 * fade * cue.intensity
    puff(ctx, x + .015, y + .02, radius, shade, alpha * .7)
    puff(ctx, x, y, radius * .92, cue.color, alpha)
  }
}

export const dustCloud: FxPainter = (ctx, cue, time) => {
  const fade = envelope(time, cue.end - cue.start) * cue.intensity
  for (let i = 0; i < 18; i++) {
    const life = (time * .18 + fxRandom(cue.seed, i)) % 1
    const x = (fxRandom(cue.seed, i + 30) - .5) * .9 + life * .25
    const y = .32 - life * .12 - fxRandom(cue.seed, i + 60) * .08
    ctx.save(); ctx.translate(x, y); ctx.scale(1.6, .7)
    puff(ctx, 0, 0, .06 + life * .1, cue.color, Math.sin(life * Math.PI) * .3 * fade)
    ctx.restore()
  }
  ctx.fillStyle = '#fff2d6'
  for (let i = 0; i < 60; i++) {
    const life = (time * .25 + fxRandom(cue.seed, i + 100)) % 1
    const x = (fxRandom(cue.seed, i + 130) - .5) * 1.1 + Math.sin(time + i) * .02
    const y = .35 - life * .45
    ctx.globalAlpha = Math.sin(life * Math.PI) * .6 * fade
    ctx.beginPath(); ctx.arc(x, y, .0025 + fxRandom(cue.seed, i + 160) * .003, 0, TAU); ctx.fill()
  }
}

export const sparkSpray: FxPainter = (ctx, cue, time) => {
  const fade = envelope(time, cue.end - cue.start)
  ctx.save(); ctx.globalCompositeOperation = 'lighter'; ctx.lineCap = 'round'
  glow(ctx, cue.color, .08, .5 * fade)
  for (let i = 0; i < Math.round(90 * cue.intensity); i++) {
    const period = .55 + fxRandom(cue.seed, i) * .6
    const life = ((time + fxRandom(cue.seed, i + 40) * period) % period) / period
    const angle = -Math.PI / 2 + (fxRandom(cue.seed, i + 80) - .5) * 2.1
    const speed = .45 + fxRandom(cue.seed, i + 120) * .55
    const at = (t: number) => [Math.cos(angle) * speed * t * .6, Math.sin(angle) * speed * t * .6 + t * t * .55] as const
    const [x, y] = at(life), [px, py] = at(Math.max(0, life - .06))
    ctx.globalAlpha = fade * (1 - life)
    ctx.strokeStyle = life < .3 ? '#fff6d8' : cue.color
    ctx.lineWidth = .005 * (1 - life * .6)
    ctx.beginPath(); ctx.moveTo(px, py); ctx.lineTo(x, y); ctx.stroke()
  }
  ctx.restore()
}

/** Screen-space painters that replace the filmed 3D sprite in 2D overlays:
 *  beams and weather read better drawn directly on the frame. */
export const stormPainters: Record<string, FxPainter> = {
  lightning: lightningStrike, lightning_storm: lightningStorm, laser: laserBeam,
  rain: rainFall, snow: snowFall, fog: fogBank, smoke: smokePlume, dust: dustCloud, sparks: sparkSpray,
}
