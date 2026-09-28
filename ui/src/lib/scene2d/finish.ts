// Optional full-frame finish. Missing `finish` leaves the frame untouched.
import finishCatalog from '../../../../app/shared/finish_presets.json' with { type: 'json' }
import { paintRisoPress, takeRiso, type RisoCutLayer, type SceneRiso } from './risoPress'

export type SceneFinish = {
  grade?: { exposure: number; contrast: number; saturation: number; temperature: number; tint: number; fade: number; beatFlash?: number }
  bloom?: { amount: number; threshold: number; radius: number; beat?: number }
  rays?: { amount: number; x: number; y: number; length: number; threshold: number }
  vignette?: { amount: number; softness: number }
  grain?: { amount: number; size: number }
  texture?: { kind: 'none' | 'paper' | 'film-dust' | 'scratches'; amount: number }
  letterbox?: { ratio: 1.85 | 2 | 2.39; color: string }
  applyToTexts?: boolean
  /** Opt-in risograph reprint. Absent on every preset that is not `risoPress`. */
  riso?: SceneRiso
}

const clamp = (value: number, min: number, max: number) => Math.max(min, Math.min(max, value))
const num = (value: unknown, fallback: number, min: number, max: number) =>
  typeof value === 'number' && Number.isFinite(value) ? clamp(value, min, max) : fallback

function takeGrade(grade: SceneFinish['grade']): SceneFinish['grade'] {
  if (!grade) return undefined
  return {
    exposure: num(grade.exposure, 0, -1, 1), contrast: num(grade.contrast, 0, -1, 1),
    saturation: num(grade.saturation, 0, -1, 1), temperature: num(grade.temperature, 0, -1, 1),
    tint: num(grade.tint, 0, -1, 1), fade: num(grade.fade, 0, 0, 1),
    ...(grade.beatFlash != null ? { beatFlash: num(grade.beatFlash, 0, 0, 1) } : {}),
  }
}

function takeBloom(bloom: SceneFinish['bloom']): SceneFinish['bloom'] {
  if (!bloom) return undefined
  return { amount: num(bloom.amount, 0, 0, 1), threshold: num(bloom.threshold, 0.6, 0, 1), radius: num(bloom.radius, 0.4, 0, 1), ...(bloom.beat != null ? { beat: num(bloom.beat, 0, 0, 1) } : {}) }
}

function takeRays(rays: SceneFinish['rays']): SceneFinish['rays'] {
  if (!rays) return undefined
  return { amount: num(rays.amount, 0, 0, 1), x: num(rays.x, 50, 0, 100), y: num(rays.y, 30, 0, 100), length: num(rays.length, 0.5, 0, 1), threshold: num(rays.threshold, 0.7, 0, 1) }
}

function takeTexture(texture: SceneFinish['texture']): SceneFinish['texture'] {
  const kind = texture?.kind
  if (kind !== 'paper' && kind !== 'film-dust' && kind !== 'scratches') return undefined
  return { kind, amount: num(texture?.amount, 0, 0, 1) }
}

function takeLetterbox(bars: SceneFinish['letterbox']): SceneFinish['letterbox'] {
  if (!bars || (bars.ratio !== 1.85 && bars.ratio !== 2 && bars.ratio !== 2.39)) return undefined
  const color = typeof bars.color === 'string' && /^#[0-9a-f]{6}$/i.test(bars.color) ? bars.color : '#000000'
  return { ratio: bars.ratio, color }
}

export function parseFinish(raw: unknown): SceneFinish | undefined {
  if (!raw || typeof raw !== 'object') return undefined
  const value = raw as SceneFinish
  const riso = takeRiso(value.riso)
  const finish: SceneFinish = {
    ...(takeGrade(value.grade) ? { grade: takeGrade(value.grade) } : {}),
    ...(takeBloom(value.bloom) ? { bloom: takeBloom(value.bloom) } : {}),
    ...(takeRays(value.rays) ? { rays: takeRays(value.rays) } : {}),
    ...(value.vignette ? { vignette: { amount: num(value.vignette.amount, 0, 0, 1), softness: num(value.vignette.softness, 0.5, 0, 1) } } : {}),
    ...(value.grain ? { grain: { amount: num(value.grain.amount, 0, 0, 1), size: num(value.grain.size, 1, 0.5, 4) } } : {}),
    ...(takeTexture(value.texture) ? { texture: takeTexture(value.texture) } : {}),
    ...(takeLetterbox(value.letterbox) ? { letterbox: takeLetterbox(value.letterbox) } : {}),
    ...(value.applyToTexts === true ? { applyToTexts: true } : {}),
    ...(riso ? { riso } : {}),
  }
  return Object.keys(finish).length ? finish : undefined
}

export const FINISH_PRESETS: Record<string, SceneFinish> = Object.fromEntries(
  finishCatalog.entries.map(entry => {
    const { id, ...preset } = entry
    return [id, preset]
  }),
) as Record<string, SceneFinish>

const scratch = new Map<string, HTMLCanvasElement>()
function canvas(key: string, width: number, height: number) {
  if (typeof document === 'undefined') return undefined
  const existing = scratch.get(key)
  if (existing && existing.width === width && existing.height === height) return existing
  const next = document.createElement('canvas')
  next.width = width
  next.height = height
  scratch.set(key, next)
  return next
}

function copyFrame(ctx: CanvasRenderingContext2D, width: number, height: number) {
  const buffer = canvas('frame', width, height)
  buffer?.getContext('2d')?.drawImage(ctx.canvas, 0, 0, width, height)
  return buffer
}

export function gradeFilter(grade: NonNullable<SceneFinish['grade']>) {
  const hue = (grade.temperature * -18) + (grade.tint * 16)
  return `brightness(${1 + grade.exposure * 0.55}) contrast(${1 + grade.contrast * 0.7}) saturate(${Math.max(0, 1 + grade.saturation)}) hue-rotate(${hue}deg)`
}

export function grainSeed(seconds: number) {
  return Math.round(seconds * 30)
}

export function paintSceneFinish(ctx: CanvasRenderingContext2D, width: number, height: number, seconds: number, finish?: SceneFinish, envelope = 0, layers?: readonly RisoCutLayer[], duration = 0) {
  if (!finish) return
  paintGrade(ctx, width, height, finish.grade, envelope)
  const bloom = finish.bloom
  if (bloom && bloom.amount > 0) {
    paintBloom(ctx, width, height, { ...bloom, amount: bloom.amount * (1 + (bloom.beat ?? 0) * envelope) })
  }
  paintRays(ctx, width, height, finish.rays)
  paintVignette(ctx, width, height, finish.vignette)
  paintNoise(ctx, width, height, seconds, finish)
  if (finish.riso) paintRisoPress(ctx, width, height, seconds, finish.riso, envelope, layers, duration)
  paintLetterbox(ctx, width, height, finish.letterbox)
}

function paintGrade(ctx: CanvasRenderingContext2D, width: number, height: number, grade: SceneFinish['grade'], envelope: number) {
  if (!grade || !('filter' in ctx)) return
  const source = copyFrame(ctx, width, height)
  if (!source) return
  ctx.save()
  ctx.filter = gradeFilter(grade)
  ctx.drawImage(source, 0, 0, width, height)
  if (grade.fade > 0) { ctx.globalAlpha = grade.fade * 0.35; ctx.fillStyle = grade.temperature >= 0 ? '#c4a574' : '#8aa4c8'; ctx.fillRect(0, 0, width, height) }
  if (grade.beatFlash && envelope > 0) { ctx.globalAlpha = grade.beatFlash * envelope * 0.45; ctx.fillStyle = '#ffffff'; ctx.fillRect(0, 0, width, height) }
  ctx.restore()
}

function paintBloom(ctx: CanvasRenderingContext2D, width: number, height: number, bloom: NonNullable<SceneFinish['bloom']>) {
    const scale = 8
    const small = canvas('bloom', Math.max(2, Math.round(width / scale)), Math.max(2, Math.round(height / scale)))
    const smallCtx = small?.getContext('2d')
    if (small && smallCtx) {
      smallCtx.filter = `blur(${4 + bloom.radius * 8}px) brightness(${1 + bloom.threshold})`
      smallCtx.drawImage(ctx.canvas, 0, 0, small.width, small.height)
      ctx.save()
      ctx.globalCompositeOperation = 'lighter'
      ctx.globalAlpha = bloom.amount * 0.65
      ctx.drawImage(small, 0, 0, width, height)
      ctx.restore()
    }
}

function paintRays(ctx: CanvasRenderingContext2D, width: number, height: number, rays: SceneFinish['rays']) {
  if (rays && rays.amount > 0) {
    ctx.save()
    ctx.globalCompositeOperation = 'lighter'
    ctx.translate(width * rays.x / 100, height * rays.y / 100)
    for (let index = 1; index <= 5; index += 1) {
      ctx.globalAlpha = rays.amount * 0.08 / index
      const grow = 1 + rays.length * index * 0.18
      ctx.drawImage(ctx.canvas, -width * rays.x / 100 * grow, -height * rays.y / 100 * grow, width * grow, height * grow)
    }
    ctx.restore()
  }
}

function paintVignette(ctx: CanvasRenderingContext2D, width: number, height: number, vignette: SceneFinish['vignette']) {
  if (vignette && vignette.amount > 0) {
    const gradient = ctx.createRadialGradient(width / 2, height / 2, Math.min(width, height) * (0.2 + vignette.softness * 0.3), width / 2, height / 2, Math.max(width, height) * 0.7)
    gradient.addColorStop(0, 'rgba(0,0,0,0)')
    gradient.addColorStop(1, `rgba(0,0,0,${vignette.amount})`)
    ctx.save()
    ctx.fillStyle = gradient
    ctx.fillRect(0, 0, width, height)
    ctx.restore()
  }
}

function paintLetterbox(ctx: CanvasRenderingContext2D, width: number, height: number, bars: SceneFinish['letterbox']) {
  if (bars) {
    const target = width / bars.ratio
    const band = Math.max(0, (height - target) / 2)
    ctx.save()
    ctx.fillStyle = bars.color
    ctx.fillRect(0, 0, width, band)
    ctx.fillRect(0, height - band, width, band)
    ctx.restore()
  }
}

function paintNoise(ctx: CanvasRenderingContext2D, width: number, height: number, seconds: number, finish: SceneFinish) {
  const amount = Math.max(finish.grain?.amount ?? 0, finish.texture?.amount ?? 0)
  if (amount <= 0) return
  const noise = canvas('noise', 160, 90)
  const noiseCtx = noise?.getContext('2d')
  if (!noise || !noiseCtx) return
  const frame = grainSeed(seconds)
  const image = noiseCtx.getImageData(0, 0, noise.width, noise.height)
  for (let index = 0; index < image.data.length; index += 4) {
    const value = ((Math.imul(frame + index, 0x45d9f3b) >>> 0) % 255)
    image.data[index] = value
    image.data[index + 1] = value
    image.data[index + 2] = value
    image.data[index + 3] = 255
  }
  noiseCtx.putImageData(image, 0, 0)
  ctx.save()
  ctx.globalAlpha = amount * 0.35
  ctx.drawImage(noise, -(frame % 7), -(frame % 5), width + 14, height + 10)
  ctx.restore()
}
