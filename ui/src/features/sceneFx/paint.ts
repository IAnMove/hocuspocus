import { fxRandom, type SceneFx } from './types'
import { magicPainters } from './magicPaint'
import { animePainters } from './animePaint'
import { paintExplosion } from './explosionPaint'
import { isWorldSfxKind } from './world'
import { rasterizeWorldFx, SPRITE_RECT } from './explosionSprite'
import { applyRetroLook, isRetroLook } from './retroPaint'
import { stormPainters } from './stormPaint'
import { glow } from './energyBrush'

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
  const burst = cue.kind === 'confetti'
  const rising = cue.kind === 'embers' || cue.kind === 'bubbles'
  const count = Math.round(100 * cue.intensity)
  if (cue.kind === 'embers' || cue.kind === 'stars') ctx.globalCompositeOperation = 'lighter'
  for (let i = 0; i < count; i++) {
    const a = fxRandom(cue.seed, i * 4), b = fxRandom(cue.seed, i * 4 + 1)
    const c = fxRandom(cue.seed, i * 4 + 2), phase = (time * (.12 + b * .13) + a) % 1
    const angle = a * tau, travel = Math.pow(progress, .6) * (.12 + b * .45)
    const x = burst ? Math.cos(angle) * travel : (a - .5) * 1.5 + Math.sin(time * (1 + b) + i) * .03
    const y = burst ? Math.sin(angle) * travel + progress * progress * .15 : (rising ? .5 - phase : phase - .5)
    const radius = .002 + c * .005
    const twinkle = cue.kind === 'stars' ? .5 + .5 * Math.sin(time * (3 + b * 5) + i) : 1
    ctx.globalAlpha = (burst ? Math.pow(1 - progress, .5) : .35 + .65 * Math.sin(phase * Math.PI)) * twinkle
    ctx.fillStyle = ctx.strokeStyle = burst ? `hsl(${a * 360} 90% 70%)` : cue.color
    if (burst) { ctx.save(); ctx.translate(x, y); ctx.rotate(time * (b - .5) * 9); ctx.scale(1, Math.cos(time * (4 + b * 6) + i)); ctx.fillRect(-.004, -.009, .008, .018); ctx.restore() }
    else if (cue.kind === 'stars') { line(ctx, x - radius * 2.5, y, x + radius * 2.5, y); line(ctx, x, y - radius * 2.5, x, y + radius * 2.5); circle(ctx, x, y, radius * .5) }
    else if (cue.kind === 'embers') { circle(ctx, x, y, radius * .7); ctx.globalAlpha *= .25; circle(ctx, x, y, radius * 2.2) }
    else circle(ctx, x, y, radius * 1.4, cue.kind === 'bubbles')
  }
}
/** Shells launch, burst into drooping trails and fade, several per cue. */
const fireworks: Painter = (ctx, cue, time) => {
  ctx.globalCompositeOperation = 'lighter'; ctx.lineCap = 'round'
  const shells = Math.max(1, Math.round((cue.end - cue.start) * 1.4 * cue.intensity))
  for (let shell = 0; shell < shells; shell++) {
    const launch = shell * .7 * (cue.end - cue.start) / shells, local = time - launch
    if (local < 0 || local > 2.2) continue
    const cx = (fxRandom(cue.seed, shell) - .5) * .8, cy = -.15 - fxRandom(cue.seed, shell + 20) * .25
    const hue = fxRandom(cue.seed, shell + 40) * 360
    if (local < .45) {
      const rise = local / .45
      ctx.globalAlpha = .9; ctx.strokeStyle = '#ffe9b0'; ctx.lineWidth = .003
      line(ctx, cx, .5 - (.5 - cy) * rise, cx, .5 - (.5 - cy) * Math.max(0, rise - .12))
      continue
    }
    const t = local - .45, fade = Math.max(0, 1 - t / 1.75)
    if (t < .12) { ctx.save(); ctx.translate(cx, cy); glow(ctx, `hsl(${hue} 100% 75%)`, .2, 1 - t / .12); ctx.restore() }
    for (let i = 0; i < 48; i++) {
      const angle = i / 48 * tau + fxRandom(cue.seed, shell * 100 + i) * .2
      const speed = .22 + fxRandom(cue.seed, shell * 100 + i + 50) * .1
      const at = (s: number) => [cx + Math.cos(angle) * speed * (1 - Math.exp(-s * 2.4)), cy + Math.sin(angle) * speed * (1 - Math.exp(-s * 2.4)) + s * s * .06] as const
      const [x, y] = at(t), [px, py] = at(Math.max(0, t - .18))
      ctx.globalAlpha = fade * (.6 + .4 * Math.sin(t * 30 + i))
      ctx.strokeStyle = `hsl(${hue + (i % 3) * 18} 95% ${60 + fade * 25}%)`; ctx.lineWidth = .0035 * fade + .001
      line(ctx, px, py, x, y)
    }
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
const special: Record<string, Painter> = { portal: rings, shockwave: rings, speedlines, scanline, aurora, explosion: paintExplosion, fireworks, ...magicPainters, ...animePainters, ...stormPainters }

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
      const sprite = isWorldSfxKind(cue.kind) && !stormPainters[cue.kind] && typeof ctx.drawImage === 'function' ? rasterizeWorldFx(cue, time) : null
      if (sprite) {
        ctx.save(); ctx.globalCompositeOperation = cue.kind === 'tornado' ? 'source-over' : 'lighter'
        ctx.drawImage(sprite, SPRITE_RECT.x, SPRITE_RECT.y, SPRITE_RECT.width, SPRITE_RECT.height)
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
