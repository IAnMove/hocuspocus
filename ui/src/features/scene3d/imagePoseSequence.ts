import { durableScene3DSourceUrl, parseScene3DSourceRef } from './slotSource'
import type { Scene3DSourceRef } from './types'

export type ImagePose = {
  sourceUrl: string
  sourceRef?: Scene3DSourceRef
  duration: number
  height: number
  x: number
  lift: number
}

export const MAX_IMAGE_POSES = 24
const bounded = (v: unknown, fallback: number, min: number, max: number) =>
  typeof v === 'number' && Number.isFinite(v) ? Math.max(min, Math.min(max, v)) : fallback

export function parseImagePoses(raw: unknown): ImagePose[] | undefined {
  if (!Array.isArray(raw) || !raw.length) return undefined
  if (raw.length > MAX_IMAGE_POSES) throw new Error('pose-sequence-too-long')
  return raw.map(value => {
    const sourceUrl = durableScene3DSourceUrl(value?.sourceUrl)
    if (!sourceUrl) throw new Error('pose-sequence-missing-image')
    return { sourceUrl, sourceRef: parseScene3DSourceRef(value.sourceRef),
      duration: bounded(value.duration, 1, 1 / 60, 600), height: bounded(value.height, .9, .05, 2),
      x: bounded(value.x, 0, -1, 1), lift: bounded(value.lift, .02, -1, 1) }
  })
}

/** Each pose holds until its exact boundary. Seeking never depends on playback history. */
export function imagePoseAtTime(poses: readonly ImagePose[], seconds: number, clock: { start: number; speed: number; loop: boolean }) {
  const duration = poses.reduce((sum, pose) => sum + pose.duration, 0)
  if (!poses.length || duration <= 0) return -1
  const raw = Math.max(0, clock.start + Math.max(0, seconds) * clock.speed)
  const time = clock.loop ? raw % duration : Math.min(raw, duration)
  let end = 0
  for (let i = 0; i < poses.length; i++) {
    end += poses[i].duration
    if (time < end - 1e-9) return i
  }
  return poses.length - 1
}

export type PoseBounds = { x: number; y: number; width: number; height: number }

export function imagePoseRect(pose: ImagePose, bounds: PoseBounds, width: number, height: number): PoseBounds {
  const h = height * pose.height, w = h * bounds.width / bounds.height
  return { x: width * (.5 + pose.x) - w / 2, y: height * (1 - pose.lift) - h, width: w, height: h }
}

/** Ignore transparent padding so changing crouch height never floats the feet. */
export function imagePoseBounds(data: Uint8ClampedArray, width: number, height: number): PoseBounds {
  let left = width, top = height, right = -1, bottom = -1
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
    if (data[(y * width + x) * 4 + 3] < 32) continue
    left = Math.min(left, x); right = Math.max(right, x); top = Math.min(top, y); bottom = Math.max(bottom, y)
  }
  if (right < left) throw new Error('pose-sequence-empty-image')
  return { x: left, y: top, width: right - left + 1, height: bottom - top + 1 }
}
