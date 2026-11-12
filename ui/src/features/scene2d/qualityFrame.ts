import { motionBlurOf, subframeTimes, supersampledSize } from '../scene3d/exportQuality.ts'

/** The export plan fields the Video 2D page needs in order to honor a level. */
export type QualityPlan = {
  width: number
  height: number
  fps?: number
  supersample?: number
  subframes?: number
  shutter?: number
}

/** Sample times for one output frame. A draft plan stays the single requested time. */
export function qualitySampleTimes(plan: QualityPlan, seconds: number, duration: number): number[] {
  const fps = plan.fps && plan.fps > 0 ? plan.fps : 30
  return subframeTimes(seconds, motionBlurOf(plan), 1 / fps, duration)
}

/** Paint size before the frame is scaled back to the output. Draft stays the output size. */
export function qualityPaintSize(plan: QualityPlan): { width: number; height: number } {
  const factor = Number(plan.supersample)
  return supersampledSize({ width: plan.width, height: plan.height }, Number.isFinite(factor) ? factor : 1)
}

/** A lost canvas reads back as RGBA zeros, so every alpha byte is 0. A painted frame starts with an opaque
 * background, so it never looks like this; a fade to black is opaque black (alpha 255) and passes. */
export function isBlankFrame(pixels: ArrayLike<number>): boolean {
  for (let index = 3; index < pixels.length; index += 4) if (pixels[index] !== 0) return false
  return true
}

/** How many times one output frame is painted before the export gives up (the first try plus one repaint). */
export const FRAME_PAINT_ATTEMPTS = 2

/** Paints one output frame and checks the pixels that were read back. A blank result is painted once more
 * (`attempt` is 0 the first time, so the caller can drop canvases that may have been lost); a second blank
 * stops the export instead of letting a black frame into the video. */
export async function paintVisibleFrame<T>(seconds: number, paint: (attempt: number) => Promise<{ frame: T; pixels: ArrayLike<number> }>): Promise<T> {
  for (let attempt = 0; attempt < FRAME_PAINT_ATTEMPTS; attempt += 1) {
    const painted = await paint(attempt)
    if (!isBlankFrame(painted.pixels)) return painted.frame
  }
  throw new Error(`Video 2D frame at ${seconds.toFixed(3)} s came out blank (fully transparent) ${FRAME_PAINT_ATTEMPTS} times; the canvas was probably lost. Export stopped instead of encoding a black frame.`)
}
