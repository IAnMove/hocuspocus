import { unitProgress } from '../camera.ts'
import type { Vec3 } from '../types.ts'

/**
 * Establishment already dollies on z. Cancel its extra rise so the move stays
 * at eye height, then add a small breath. One formula for the GPU and CPU paths.
 */
export function atmosEye(eye: Vec3, seconds: number, duration: number, family: string): Vec3 {
  const s = unitProgress(seconds, duration)
  const lift = family === 'establishment' ? 0.55 * (1 - s) : 0
  const breath = Math.sin(seconds * 1.55) * 0.014
  const sway = Math.sin(seconds * 0.72) * 0.02
  return [eye[0] + sway, eye[1] - lift + breath, eye[2]]
}
