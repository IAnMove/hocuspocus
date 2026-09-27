import type { WorldSfx, WorldVec3 } from './world'

export type WorldSfxKeyframe = {
  time: number; position: WorldVec3; rotation: WorldVec3; scale: number
  easing?: 'linear' | 'smooth'
}
export type PortalPlayback = { start: number; speed: number; loop: boolean }
const finite = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v)
const bounded = (v: number, min: number, max: number) => Math.max(min, Math.min(max, v))
function vector(raw: unknown, limit: number): WorldVec3 | undefined {
  if (!raw || typeof raw !== 'object') return
  const v = raw as WorldVec3
  if (![v.x, v.y, v.z].every(finite)) return
  return { x: bounded(v.x, -limit, limit), y: bounded(v.y, -limit, limit), z: bounded(v.z, -limit, limit) }
}
export function parseWorldMotion(raw: unknown): WorldSfxKeyframe[] | undefined {
  if (!Array.isArray(raw)) return
  const frames = new Map<number, WorldSfxKeyframe>()
  for (const frame of raw.slice(0, 32)) {
    if (!frame || !finite(frame.time) || !finite(frame.scale)) continue
    const position = vector(frame.position, 100), rotation = vector(frame.rotation, 36000)
    if (!position || !rotation) continue
    const time = bounded(frame.time, 0, 600)
    frames.set(time, { time, position, rotation, scale: bounded(frame.scale, 0, 64), easing: frame.easing === 'linear' ? 'linear' : 'smooth' })
  }
  return frames.size ? [...frames.values()].sort((a, b) => a.time - b.time) : undefined
}
export function parsePortalPlayback(raw: unknown): PortalPlayback | undefined {
  if (!raw || typeof raw !== 'object') return
  const v = raw as PortalPlayback
  return { start: finite(v.start) ? bounded(v.start, 0, 86400) : 0,
    speed: finite(v.speed) ? bounded(v.speed, .05, 8) : 1, loop: v.loop !== false }
}
const lerp = (a: number, b: number, t: number) => a + (b - a) * t
const mixVector = (a: WorldVec3, b: WorldVec3, t: number): WorldVec3 => ({ x: lerp(a.x, b.x, t), y: lerp(a.y, b.y, t), z: lerp(a.z, b.z, t) })
/** Absolute scene times; angles deliberately retain complete authored rotations. */
export function worldSfxAtTime(cue: WorldSfx, seconds: number): WorldSfx {
  const frames = cue.motion
  if (!frames?.length) return cue
  const right = frames.findIndex(frame => frame.time > seconds)
  const a = frames[Math.max(0, right < 0 ? frames.length - 1 : right - 1)]
  const b = frames[right < 0 ? frames.length - 1 : right]
  const fraction = a.time === b.time ? 0 : bounded((seconds - a.time) / (b.time - a.time), 0, 1)
  const t = a.easing === 'linear' ? fraction : fraction * fraction * (3 - 2 * fraction)
  return { ...cue, position: mixVector(a.position, b.position, t), rotation: mixVector(a.rotation, b.rotation, t), scale: lerp(a.scale, b.scale, t) }
}

/** The transform gizmo edits the current point, retaining the rest of the path. */
export function setWorldMotionPose(cue: WorldSfx, seconds: number, pose: WorldSfx): WorldSfx {
  if (!cue.motion?.length) return pose
  const frames = [...cue.motion]
  const time = bounded(seconds, 0, 600)
  let index = frames.findIndex(frame => Math.abs(frame.time - time) < .001)
  if (index < 0 && frames.length >= 32) index = frames.reduce((best, frame, i) => Math.abs(frame.time - time) < Math.abs(frames[best].time - time) ? i : best, 0)
  const frame = { time, position: pose.position, rotation: pose.rotation, scale: pose.scale, easing: 'smooth' as const }
  if (index < 0) frames.push(frame)
  else frames[index] = { ...frame, easing: frames[index].easing }
  return { ...cue, motion: frames.sort((a, b) => a.time - b.time) }
}
