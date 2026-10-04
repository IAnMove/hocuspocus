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
