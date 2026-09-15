import { fxRandom, type SceneFx } from './types'
import { magicPainters } from './magicPaint'
import { animePainters } from './animePaint'
import { paintExplosion } from './explosionPaint'
import { isWorldSfxKind } from './world'
import { rasterizeWorldFx } from './explosionSprite'
import { applyRetroLook, isRetroLook } from './retroPaint'

type Painter = (ctx: CanvasRenderingContext2D, cue: SceneFx, time: number, progress: number) => void
const tau = Math.PI * 2
const circle = (ctx: CanvasRenderingContext2D, x: number, y: number, radius: number, stroke = false) => {
  ctx.beginPath(); ctx.arc(x, y, Math.max(.0001, radius), 0, tau)
  if (stroke) ctx.stroke(); else ctx.fill()
}
const line = (ctx: CanvasRenderingContext2D, x: number, y: number, x2: number, y2: number) => {
  ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x2, y2); ctx.stroke()
}
const particles: Painter = (ctx, cue, time, progress) => {
  const burst = ['fireworks', 'confetti', 'sparks'].includes(cue.kind)
  const cloud = cue.kind === 'smoke' || cue.kind === 'fog'
  const count = Math.round((cloud ? 22 : 100) * cue.intensity)
  for (let i = 0; i < count; i++) {
    const a = fxRandom(cue.seed, i * 4), b = fxRandom(cue.seed, i * 4 + 1)
    const c = fxRandom(cue.seed, i * 4 + 2), phase = (time * (.12 + b * .13) + a) % 1
    const angle = a * tau, travel = Math.pow(progress, .6) * (.12 + b * .45)
    const x = burst ? Math.cos(angle) * travel : (a - .5) * 1.5 + Math.sin(time + i) * .025
    let y = burst ? Math.sin(angle) * travel + progress * progress * .15 : phase - .5
    if (['embers', 'bubbles', 'smoke'].includes(cue.kind)) y = -y
    if (cue.kind === 'fog') y *= .4
    const radius = cloud ? .08 + c * .12 : .002 + c * .005
    ctx.globalAlpha = cloud ? .09 * Math.sin(phase * Math.PI) : burst ? Math.pow(1 - progress, .5) : .35 + .65 * Math.sin(phase * Math.PI)
    ctx.fillStyle = cue.kind === 'confetti' || cue.kind === 'fireworks' ? `hsl(${a * 360} 90% 70%)` : cue.color
    if (cloud) {
      const gradient = ctx.createRadialGradient(x, y, 0, x, y, radius)
      gradient.addColorStop(0, cue.color); gradient.addColorStop(1, 'transparent'); ctx.fillStyle = gradient
    }
    if (cue.kind === 'rain') line(ctx, x, y, x - .014, y + .065)
    else if (cue.kind === 'confetti') { ctx.save(); ctx.translate(x, y); ctx.rotate(time * (b - .5) * 9); ctx.fillRect(-.004, -.009, .008, .018); ctx.restore() }
    else if (cue.kind === 'stars') { line(ctx, x - radius * 2, y, x + radius * 2, y); line(ctx, x, y - radius * 2, x, y + radius * 2) }
    else circle(ctx, x, y, radius, cue.kind === 'bubbles')
  }
}
const rings: Painter = (ctx, cue, time, progress) => {
  for (let i = 0; i < 5; i++) {
    const phase = cue.kind === 'portal' ? (time * .35 + i / 5) % 1 : Math.max(0, progress - i * .055)
    ctx.globalAlpha = (1 - phase) * .6
    ctx.lineWidth = cue.kind === 'portal' ? .005 : .012 * (1 - phase)
    circle(ctx, 0, 0, .03 + phase * .47, true)
  }
  if (cue.kind !== 'portal') return
  for (let i = 0; i < 65; i++) {
    const angle = i / 65 * tau + time * .7, radius = .26 + .05 * Math.sin(time * 2 + i)
    ctx.globalAlpha = .8; circle(ctx, Math.cos(angle) * radius, Math.sin(angle) * radius, .003)
  }
}
const lightning: Painter = (ctx, cue, time) => {
  for (let branch = 0; branch < 3; branch++) {
    ctx.beginPath(); ctx.moveTo(0, -.45)
    for (let i = 1; i <= 12; i++) {
      const jitter = fxRandom(cue.seed + Math.floor(time * 10), i + branch * 20) - .5
      ctx.lineTo(jitter * .22 + branch * .045, -.45 + i * .075)
    }
    ctx.globalAlpha = .8 - branch * .2; ctx.lineWidth = .006 - branch * .0015; ctx.stroke()
  }
}
const speedlines: Painter = (ctx, cue, time) => {
  for (let i = 0; i < 65; i++) {
    const angle = fxRandom(cue.seed, i) * tau, phase = (time * .7 + fxRandom(cue.seed, i + 65)) % 1
    const radius = .13 + phase * .6
    ctx.globalAlpha = Math.sin(phase * Math.PI) * .6
    line(ctx, Math.cos(angle) * radius, Math.sin(angle) * radius, Math.cos(angle) * (radius + .15), Math.sin(angle) * (radius + .15))
  }
}
const scanline: Painter = (ctx, _cue, time) => {
  ctx.globalAlpha = .2
  for (let i = 0; i < 32; i++) line(ctx, -.55, i / 32 - .5, .55, i / 32 - .5)
  ctx.globalAlpha = .8; ctx.lineWidth = .008
  line(ctx, -.55, (time * .35) % 1 - .5, .55, (time * .35) % 1 - .5)
}
const aurora: Painter = (ctx, cue, time) => {
  for (let band = 0; band < 15; band++) {
    ctx.globalAlpha = .06; ctx.lineWidth = .035
    ctx.strokeStyle = `hsl(${150 + band * 5} 85% 65%)`; ctx.beginPath()
    for (let i = 0; i <= 70; i++) {
      const x = i / 70 * 1.6 - .8, y = Math.sin(x * 5 + time * .5 + band * .05) * .14 + band * .012 - .16
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y)
    }
    ctx.stroke()
  }
  ctx.strokeStyle = cue.color
}
const laser: Painter = (ctx, _cue, time) => {
  ctx.save(); ctx.rotate(Math.sin(time * .7) * .35)
  for (let i = 0; i < 4; i++) { ctx.globalAlpha = .15 + i * .18; ctx.lineWidth = .05 / (i + 1); line(ctx, -.65, 0, .65, 0) }
  ctx.strokeStyle = '#ffffff'; ctx.lineWidth = .003; line(ctx, -.65, 0, .65, 0); ctx.restore()
}
const special: Record<string, Painter> = { portal: rings, shockwave: rings, lightning, speedlines, scanline, aurora, laser, explosion: paintExplosion, ...magicPainters, ...animePainters }

/** Composited screen-space effects, identical in the 2D and 3D previews/exports. */
export function paintSceneFx(
  ctx: CanvasRenderingContext2D,
  width: number,
  height: number,
  seconds: number,
  cues: readonly SceneFx[] = [],
  source?: CanvasImageSource | null,
) {
  const live = cues.filter(cue => seconds >= cue.start && seconds < cue.end)
  const looks = live.filter(cue => isRetroLook(cue.kind))
  if (looks.length) {
    if (source && typeof ctx.drawImage === 'function') ctx.drawImage(source, 0, 0, width, height)
    for (const cue of looks) applyRetroLook(ctx, width, height, cue, seconds)
  }
  for (const cue of live) {
    if (isRetroLook(cue.kind)) continue
    const time = seconds - cue.start, progress = time / (cue.end - cue.start)
    const scale = Math.min(width, height) * cue.size / 100
    ctx.save(); ctx.translate(width * cue.x / 100, height * cue.y / 100); ctx.scale(scale, scale)
    ctx.rotate((cue.rotation ?? 0) * Math.PI / 180)
    ctx.fillStyle = cue.color; ctx.strokeStyle = cue.color; ctx.lineWidth = .002; ctx.lineCap = 'round'
    if (cue.kind === 'explosion') paintExplosion(ctx, cue, time, progress)
    else {
      const sprite = isWorldSfxKind(cue.kind) && typeof ctx.drawImage === 'function' ? rasterizeWorldFx(cue, time) : null
      if (sprite) {
        ctx.save(); ctx.globalCompositeOperation = 'lighter'
        ctx.drawImage(sprite, -0.62, -0.78, 1.24, 1.28)
        ctx.restore()
      } else (special[cue.kind] ?? particles)(ctx, cue, time, progress)
    }
    ctx.restore()
    if (cue.label) {
      ctx.save(); ctx.font = `600 ${Math.round(height * .032)}px monospace`; ctx.textAlign = 'left'
      const x = width * .045, y = height * .09
      ctx.fillStyle = '#0c1020'; ctx.fillRect(x - 12, y - height * .032, ctx.measureText(cue.label).width + 24, height * .046)
      ctx.fillStyle = cue.color; ctx.fillText(cue.label, x, y); ctx.restore()
    }
  }
}
