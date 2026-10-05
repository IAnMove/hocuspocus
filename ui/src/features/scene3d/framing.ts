import { lerp3, vecAdd } from './camera'
import type { Scene3DFraming, Scene3DSlot, Vec3 } from './types'

export function validFraming(raw: unknown): raw is Scene3DFraming {
  if (!raw || typeof raw !== 'object') return false
  const f = raw as Scene3DFraming
  const vector = (v: unknown) => Array.isArray(v) && v.length === 3 && v.every(n => typeof n === 'number' && Number.isFinite(n))
  return typeof f.targetSlot === 'string' && Boolean(f.targetSlot)
    && ['head', 'center', 'feet'].includes(f.anchor)
    && vector(f.from) && vector(f.to)
    && [f.lookFrom, f.lookTo].every(v => v == null || vector(v))
    && [f.orbitTurns, f.rollFrom, f.rollTo, f.fovFrom, f.fovTo].every(n => n == null || (typeof n === 'number' && Number.isFinite(n)))
    && [f.fovFrom, f.fovTo].every(n => n == null || (n > 8 && n < 140))
    && (f.relativeToFacing == null || typeof f.relativeToFacing === 'boolean')
    && validMoveWindow(f)
}

const unit = (value: unknown) => typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 1

function validMoveWindow(f: Scene3DFraming) {
  if ((f.moveStart != null && !unit(f.moveStart)) || (f.moveEnd != null && !unit(f.moveEnd))) return false
  if ((f.moveStart ?? 0) >= (f.moveEnd ?? 1)) return false
  return f.ease == null || f.ease === 'smooth' || f.ease === 'snap'
}

/** Progress of the from→to move: held before `moveStart`, settled after `moveEnd` (fractions of the shot).
 * `smooth` eases in and out; `snap` leaves at full speed and settles, like a crash zoom. */
export function framingProgress(f: Scene3DFraming | undefined, seconds: number, duration: number) {
  const span = duration > 1e-6 ? duration : 1
  const raw = Math.min(1, Math.max(0, seconds / span))
  const start = f?.moveStart ?? 0, end = f?.moveEnd ?? 1
  const u = Math.min(1, Math.max(0, (raw - start) / Math.max(1e-6, end - start)))
  return f?.ease === 'snap' ? 1 - (1 - u) ** 3 : u * u * (3 - 2 * u)
}

export function framingFov(f: Scene3DFraming | undefined, fallback: number, seconds: number, duration: number) {
  const start = f?.fovFrom ?? f?.fovTo
  if (start == null) return fallback
  const end = f?.fovTo ?? start
  return start + (end - start) * framingProgress(f, seconds, duration)
}

function turn(vector: Vec3, yaw: number, scale: number): Vec3 {
  const [x, y, z] = vector
  return [(x * Math.cos(yaw) + z * Math.sin(yaw)) * scale, y * scale, (z * Math.cos(yaw) - x * Math.sin(yaw)) * scale]
}

export function framingPose(f: Scene3DFraming, anchor: Vec3, slot: Scene3DSlot, seconds: number, duration: number) {
  const t = framingProgress(f, seconds, duration)
  const yaw = f.relativeToFacing === false ? 0 : slot.rotationY
  const offset = turn(lerp3(f.from, f.to, t), yaw + (f.orbitTurns ?? 0) * Math.PI * 2 * t, slot.scale)
  const look = turn(lerp3(f.lookFrom ?? [0, 0, 0], f.lookTo ?? f.lookFrom ?? [0, 0, 0], t), yaw, slot.scale)
  return {
    eye: vecAdd(anchor, offset), look: vecAdd(anchor, look),
    roll: ((f.rollFrom ?? 0) + ((f.rollTo ?? f.rollFrom ?? 0) - (f.rollFrom ?? 0)) * t) * Math.PI / 180,
  }
}
