import { lerp3, unitProgress, vecAdd } from './camera'
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
}

export function framingFov(f: Scene3DFraming | undefined, fallback: number, seconds: number, duration: number) {
  const start = f?.fovFrom ?? f?.fovTo
  if (start == null) return fallback
  const end = f?.fovTo ?? start
  return start + (end - start) * unitProgress(seconds, duration)
}

function turn(vector: Vec3, yaw: number, scale: number): Vec3 {
  const [x, y, z] = vector
  return [(x * Math.cos(yaw) + z * Math.sin(yaw)) * scale, y * scale, (z * Math.cos(yaw) - x * Math.sin(yaw)) * scale]
}

export function framingPose(f: Scene3DFraming, anchor: Vec3, slot: Scene3DSlot, seconds: number, duration: number) {
  const t = unitProgress(seconds, duration)
  const yaw = f.relativeToFacing === false ? 0 : slot.rotationY
  const offset = turn(lerp3(f.from, f.to, t), yaw + (f.orbitTurns ?? 0) * Math.PI * 2 * t, slot.scale)
  const look = turn(lerp3(f.lookFrom ?? [0, 0, 0], f.lookTo ?? f.lookFrom ?? [0, 0, 0], t), yaw, slot.scale)
  return {
    eye: vecAdd(anchor, offset), look: vecAdd(anchor, look),
    roll: ((f.rollFrom ?? 0) + ((f.rollTo ?? f.rollFrom ?? 0) - (f.rollFrom ?? 0)) * t) * Math.PI / 180,
  }
}
