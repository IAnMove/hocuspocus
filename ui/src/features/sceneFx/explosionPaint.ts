import { fxRandom, type SceneFx } from './types'
import { rasterizeWorldFx } from './explosionSprite'

function blob(ctx: CanvasRenderingContext2D, x: number, y: number, rx: number, ry: number, rot: number) {
  ctx.save()
  ctx.translate(x, y)
  ctx.rotate(rot)
  ctx.beginPath()
  ctx.ellipse(0, 0, Math.max(0.0008, rx), Math.max(0.0008, ry), 0, 0, Math.PI * 2)
  ctx.fill()
  ctx.restore()
}

function rgba(r: number, g: number, b: number, a: number) {
  return `rgba(${r | 0},${g | 0},${b | 0},${Math.max(0, Math.min(1, a))})`
}

/** Same 3D blast when WebGL is available; particle fire if it is not. */
export function paintExplosion(ctx: CanvasRenderingContext2D, cue: SceneFx, time: number, progress: number) {
  const sprite = typeof ctx.drawImage === 'function' ? rasterizeWorldFx(cue, time) : null
  if (sprite) {
    ctx.save()
    ctx.globalCompositeOperation = 'lighter'
    ctx.drawImage(sprite, -0.62, -0.78, 1.24, 1.28)
    ctx.restore()
    return
  }
  const power = cue.intensity
  const flash = Math.pow(Math.max(0, 1 - progress * 5.2), 2)
  const fire = Math.pow(Math.max(0, 1 - progress * 1.05), 0.62)
  const smoke = Math.max(0, (progress - 0.08) / 0.92)
  const expand = Math.pow(progress, 0.38)

  ctx.save()
  ctx.globalCompositeOperation = 'source-over'
  for (let i = 0; i < 48; i++) {
    const a = fxRandom(cue.seed, i) * Math.PI * 2
    const d = smoke * (0.04 + fxRandom(cue.seed, i + 40) * 0.34)
    const lift = smoke * (0.02 + fxRandom(cue.seed, i + 80) * 0.28)
    blob(ctx, Math.cos(a) * d, Math.sin(a) * d * 0.55 - lift,
      0.05 + fxRandom(cue.seed, i + 120) * 0.12 + smoke * 0.08,
      0.04 + fxRandom(cue.seed, i + 160) * 0.1 + smoke * 0.07,
      a * 0.4)
    ctx.fillStyle = rgba(28 + fxRandom(cue.seed, i + 200) * 40, 22, 18, 0.07 * smoke * power)
  }

  ctx.globalCompositeOperation = 'lighter'
  for (let i = 0; i < 140; i++) {
    const a = fxRandom(cue.seed, i + 300) * Math.PI * 2
    const d = fire * expand * (0.02 + fxRandom(cue.seed, i + 340) * 0.28)
    const heat = fxRandom(cue.seed, i + 380)
    const x = Math.cos(a) * d
    const y = Math.sin(a) * d * 0.72 - fire * 0.03 - progress * 0.05
    ctx.fillStyle = heat > 0.72
      ? rgba(255, 236, 170, 0.16 * fire * power)
      : heat > 0.4
        ? rgba(255, 120, 28, 0.2 * fire * power)
        : rgba(180, 28, 6, 0.14 * fire * power)
    blob(ctx, x, y,
      0.018 + fxRandom(cue.seed, i + 420) * 0.055,
      0.012 + fxRandom(cue.seed, i + 460) * 0.05,
      a + fxRandom(cue.seed, i + 500))
  }

  for (let i = 0; i < 22; i++) {
    const a = fxRandom(cue.seed, i + 540) * Math.PI * 2
    ctx.fillStyle = rgba(255, 250, 230, 0.22 * fire * power)
    blob(ctx,
      Math.cos(a) * fire * 0.03,
      Math.sin(a) * fire * 0.02,
      0.02 + fxRandom(cue.seed, i + 580) * 0.03,
      0.015 + fxRandom(cue.seed, i + 620) * 0.025,
      a)
  }

  if (flash > 0.04) {
    for (let i = 0; i < 18; i++) {
      const a = fxRandom(cue.seed, i + 700) * Math.PI * 2
      ctx.fillStyle = rgba(255, 252, 240, 0.18 * flash)
      blob(ctx, Math.cos(a) * 0.03, Math.sin(a) * 0.02,
        0.04 + fxRandom(cue.seed, i + 740) * 0.08,
        0.03 + fxRandom(cue.seed, i + 780) * 0.06, a)
    }
  }

  ctx.globalCompositeOperation = 'lighter'
  for (let i = 0; i < 110; i++) {
    const a = fxRandom(cue.seed, i + 820) * Math.PI * 2
    const dist = expand * (0.06 + fxRandom(cue.seed, i + 860) * 0.55)
    const lift = progress * 0.06 * fxRandom(cue.seed, i + 900)
    const glow = fxRandom(cue.seed, i + 940)
    ctx.fillStyle = glow > 0.62
      ? rgba(255, 210, 90, Math.pow(1 - progress, 0.75) * 0.55 * power)
      : rgba(255, 90, 20, Math.pow(1 - progress, 0.6) * 0.28 * power)
    blob(ctx, Math.cos(a) * dist, Math.sin(a) * dist * 0.78 + lift,
      0.004 + fxRandom(cue.seed, i + 980) * 0.012,
      0.003 + fxRandom(cue.seed, i + 1020) * 0.01,
      a)
  }
  ctx.restore()
}
