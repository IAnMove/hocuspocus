/** Render settings of a server export quality level (draft, final, master).

The server freezes them in the export plan. Draft is today's export: no supersampling
and no multisampled composer, so its frames stay byte-identical.
*/
export type ExportRenderQuality = { supersample: number; samples: number }

export const DRAFT_RENDER: ExportRenderQuality = { supersample: 1, samples: 0 }

/** WebGL2 guarantees at least 4096; the long side of a supersampled frame stays within 8192. */
export const MAX_SUPERSAMPLED_SIDE = 8192
/** The server plans 1.5x (final) or 2x (master); 4x is accepted for reference renders. */
export const MAX_SUPERSAMPLE = 4

/** The plan's render fields. Anything missing, invalid or out of range falls back to draft. */
export function renderQualityOf(plan: { supersample?: unknown; samples?: unknown } | null | undefined): ExportRenderQuality {
  const supersample = Number(plan?.supersample)
  const samples = Number(plan?.samples)
  return {
    supersample: Number.isFinite(supersample) ? Math.min(MAX_SUPERSAMPLE, Math.max(1, supersample)) : 1,
    samples: Number.isInteger(samples) && samples > 0 ? Math.min(8, samples) : 0,
  }
}

function even(value: number): number {
  const rounded = Math.max(2, Math.round(value))
  return rounded - (rounded % 2)
}

/** The size the stage renders at before the frame is scaled down to the output size. */
export function supersampledSize(size: { width: number; height: number }, supersample: number, maxSide = MAX_SUPERSAMPLED_SIDE) {
  const longest = Math.max(size.width, size.height, 1)
  const factor = Math.max(1, Math.min(supersample, maxSide / longest))
  if (factor === 1) return { width: size.width, height: size.height }
  return { width: even(size.width * factor), height: even(size.height * factor) }
}

/** Motion blur of a server export: how many subframes one output frame averages, and the shutter angle. */
export type MotionBlur = { subframes: number; shutter: number }

export const NO_MOTION_BLUR: MotionBlur = { subframes: 1, shutter: 0 }

/** The plan's blur fields. Missing, invalid or a closed shutter means one sharp frame. */
export function motionBlurOf(plan: { subframes?: unknown; shutter?: unknown } | null | undefined): MotionBlur {
  const subframes = Number(plan?.subframes)
  const shutter = Number(plan?.shutter)
  if (!Number.isInteger(subframes) || subframes < 2 || !Number.isFinite(shutter) || shutter <= 0) return NO_MOTION_BLUR
  return { subframes: Math.min(16, subframes), shutter: Math.min(360, shutter) }
}

/** Scene times a blurred frame averages. Like a film camera, the shutter opens at the frame time and stays open
 * for `shutter / 360` of a frame; `frameSeconds` is one output frame in scene time. Never past the scene's end. */
export function subframeTimes(frameTime: number, blur: MotionBlur, frameSeconds: number, end: number): number[] {
  if (blur.subframes < 2) return [frameTime]
  const open = (blur.shutter / 360) * frameSeconds
  return Array.from({ length: blur.subframes }, (_unused, index) => Math.min(end, frameTime + ((index + 0.5) / blur.subframes) * open))
}

const TO_LINEAR = Float32Array.from({ length: 256 }, (_unused, value) => {
  const c = value / 255
  return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
})
const LINEAR_STEPS = 4096
const TO_SRGB = Uint8ClampedArray.from({ length: LINEAR_STEPS + 1 }, (_unused, step) => {
  const c = step / LINEAR_STEPS
  return Math.round(255 * (c <= 0.0031308 ? c * 12.92 : 1.055 * c ** (1 / 2.4) - 0.055))
})

/** Averages RGBA8 frames in linear light, as light adds up on film; alpha is averaged as is. */
export class FrameAccumulator {
  readonly length: number
  private readonly sum: Float32Array
  private count = 0
  constructor(length: number) { this.length = length; this.sum = new Float32Array(length) }

  add(data: ArrayLike<number>) {
    if (data.length !== this.length) throw new Error('Subframes must share one size')
    const { sum } = this
    for (let i = 0; i < data.length; i += 4) {
      sum[i] += TO_LINEAR[data[i]]; sum[i + 1] += TO_LINEAR[data[i + 1]]; sum[i + 2] += TO_LINEAR[data[i + 2]]; sum[i + 3] += data[i + 3]
    }
    this.count++
  }

  result(): Uint8ClampedArray {
    const out = new Uint8ClampedArray(this.length)
    const { sum, count } = this
    if (!count) return out
    for (let i = 0; i < out.length; i += 4) {
      out[i] = TO_SRGB[Math.round((sum[i] / count) * LINEAR_STEPS)]
      out[i + 1] = TO_SRGB[Math.round((sum[i + 1] / count) * LINEAR_STEPS)]
      out[i + 2] = TO_SRGB[Math.round((sum[i + 2] / count) * LINEAR_STEPS)]
      out[i + 3] = Math.round(sum[i + 3] / count)
    }
    return out
  }
}
