// The finish pieces the 3D grades use and the 2D finish lacked: a tone curve, a gel, tape and scanlines.
// world3d_modifiers.json `grades` names the intention; these pieces let the 2D finishes of the same names reach it.
import { applyRetroPixels } from '../../features/sceneFx/retroPaint'

export const TONE_CURVES = ['aces', 'agx', 'neutral'] as const
export type ToneCurve = (typeof TONE_CURVES)[number]
export type SceneGel = { color: string; amount: number; shadows?: string }
export type SceneAmount = { amount: number }

/** How far the curve moves a display-referred picture: a full film curve crushes a finished picture's shadows. */
const TONE_STRENGTH = 0.6
const HEX = /^#[0-9a-f]{6}$/i
const AGX_MIN_EV = -12.47393
const AGX_MAX_EV = 4.026069
const VHS_SEED = 7
const VHS_WIDTH = 640

const clamp01 = (value: number) => Math.max(0, Math.min(1, value))
const amountOf = (value: unknown) => typeof value === 'number' && Number.isFinite(value) ? clamp01(value) : 0
const toLinear = (value: number) => value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4
const toDisplay = (value: number) => value <= 0.0031308 ? value * 12.92 : 1.055 * value ** (1 / 2.4) - 0.055

/** Narkowicz's ACES fit, 0.6 exposure so mid grey stays near mid grey. */
function aces(linear: number) {
  const x = linear * 0.6
  return (x * (2.51 * x + 0.03)) / (x * (2.43 * x + 0.59) + 0.14)
}

/** The AgX default-contrast polynomial on the log2 encoding (display-encoded output). */
function agx(linear: number) {
  const x = clamp01((Math.log2(Math.max(linear, 1e-10)) - AGX_MIN_EV) / (AGX_MAX_EV - AGX_MIN_EV))
  return 15.5 * x ** 6 - 40.14 * x ** 5 + 31.96 * x ** 4 - 6.868 * x ** 3 + 0.4298 * x ** 2 + 0.1191 * x - 0.00232
}

/** Khronos PBR Neutral's shoulder on one channel. Its toe takes off the 4 % reflection a render adds; a picture has
 * none, so the toe is left out and everything below the shoulder stays as it is. */
function neutral(linear: number) {
  if (linear < 0.76) return linear
  const room = 0.24
  return 1 - room * room / (linear + room - 0.76)
}

const CURVES: Record<ToneCurve, (display: number) => number> = {
  aces: display => toDisplay(aces(toLinear(display)) / aces(1)),
  agx: display => agx(toLinear(display)) / agx(1),
  neutral: display => toDisplay(neutral(toLinear(display))),
}

const luts = new Map<ToneCurve, Uint8ClampedArray>()

/** 256 levels per channel. Black stays black; aces and agx keep white, neutral rolls the brightest top off. */
export function toneLut(curve: ToneCurve) {
  const cached = luts.get(curve)
  if (cached) return cached
  const lut = new Uint8ClampedArray(256)
  for (let level = 0; level < 256; level += 1) {
    const display = level / 255
    const shaped = clamp01(CURVES[curve](display))
    lut[level] = Math.round((display + (shaped - display) * TONE_STRENGTH) * 255)
  }
  luts.set(curve, lut)
  return lut
}

export function applyTone(pixels: Uint8ClampedArray, curve: ToneCurve) {
  const lut = toneLut(curve)
  for (let index = 0; index < pixels.length; index += 4) {
    pixels[index] = lut[pixels[index]]
    pixels[index + 1] = lut[pixels[index + 1]]
    pixels[index + 2] = lut[pixels[index + 2]]
  }
}

export function takeToneCurve(raw: unknown): ToneCurve | undefined {
  return (TONE_CURVES as readonly unknown[]).includes(raw) ? raw as ToneCurve : undefined
}

export function takeGel(raw: unknown): SceneGel | undefined {
  if (!raw || typeof raw !== 'object') return undefined
  const value = raw as Partial<SceneGel>
  if (typeof value.color !== 'string' || !HEX.test(value.color)) return undefined
  const shadows = typeof value.shadows === 'string' && HEX.test(value.shadows) ? value.shadows : undefined
  return { color: value.color, amount: amountOf(value.amount), ...(shadows ? { shadows } : {}) }
}

export function takeAmount(raw: unknown): SceneAmount | undefined {
  if (!raw || typeof raw !== 'object') return undefined
  return { amount: amountOf((raw as Partial<SceneAmount>).amount) }
}

export function paintTone(ctx: CanvasRenderingContext2D, width: number, height: number, curve: ToneCurve | undefined) {
  if (!curve || width < 1 || height < 1) return
  const frame = ctx.getImageData(0, 0, width, height)
  applyTone(frame.data, curve)
  ctx.putImageData(frame, 0, 0)
}

/** A gel multiplies the light like the 3D lamp's tint; `shadows` lifts the dark parts towards a second colour. */
export function paintGel(ctx: CanvasRenderingContext2D, width: number, height: number, gel: SceneGel | undefined) {
  if (!gel || gel.amount <= 0) return
  ctx.save()
  ctx.globalCompositeOperation = 'multiply'
  ctx.globalAlpha = gel.amount
  ctx.fillStyle = gel.color
  ctx.fillRect(0, 0, width, height)
  if (gel.shadows) {
    ctx.globalCompositeOperation = 'screen'
    ctx.globalAlpha = gel.amount * 0.5
    ctx.fillStyle = gel.shadows
    ctx.fillRect(0, 0, width, height)
  }
  ctx.restore()
}

/** The 3D `vhs` screen effect (colour bleed, row wobble, tape noise and the tracking bar) on one frame's pixels. */
export function vhsTape(pixels: Uint8ClampedArray, width: number, height: number, amount: number, seconds: number) {
  if (amount > 0) applyRetroPixels(pixels, width, height, 'vhs', amount, VHS_SEED, seconds)
}

/** Tape is soft: the effect runs at a VHS-like width and is drawn back smoothed. */
export function paintVhs(ctx: CanvasRenderingContext2D, width: number, height: number, seconds: number, vhs: SceneAmount | undefined, work: (width: number, height: number) => HTMLCanvasElement | undefined) {
  if (!vhs || vhs.amount <= 0 || width < 1 || height < 1) return
  const tapeWidth = Math.min(width, VHS_WIDTH)
  const tapeHeight = Math.max(1, Math.round(height * tapeWidth / width))
  const tape = work(tapeWidth, tapeHeight)
  const tapeCtx = tape?.getContext('2d', { willReadFrequently: true })
  if (!tape || !tapeCtx) return
  tapeCtx.drawImage(ctx.canvas, 0, 0, tapeWidth, tapeHeight)
  const frame = tapeCtx.getImageData(0, 0, tapeWidth, tapeHeight)
  vhsTape(frame.data, tapeWidth, tapeHeight, vhs.amount, seconds)
  tapeCtx.putImageData(frame, 0, 0)
  ctx.save()
  ctx.imageSmoothingEnabled = true
  ctx.drawImage(tape, 0, 0, width, height)
  ctx.restore()
}

/** Dark lines every other row band (about 240 lines a frame) and a soft bright band rolling down, as the 3D `scanline`. */
export function scanlineBands(height: number, seconds: number) {
  const step = Math.max(2, Math.round(height / 240))
  const rows: number[] = []
  for (let y = 0; y < height; y += step * 2) rows.push(y)
  return { step, rows, roll: ((seconds * 0.35) % 1) * height }
}

export function paintScanlines(ctx: CanvasRenderingContext2D, width: number, height: number, seconds: number, scanlines: SceneAmount | undefined) {
  if (!scanlines || scanlines.amount <= 0) return
  const { step, rows, roll } = scanlineBands(height, seconds)
  ctx.save()
  ctx.globalAlpha = scanlines.amount * 0.3
  ctx.fillStyle = '#000000'
  for (const y of rows) ctx.fillRect(0, y, width, step)
  ctx.globalCompositeOperation = 'screen'
  ctx.globalAlpha = scanlines.amount * 0.12
  ctx.fillStyle = '#ffffff'
  ctx.fillRect(0, roll, width, Math.max(step * 2, height * 0.035))
  ctx.restore()
}
