/** Geometry warnings before a render: characters under the floor or floating, bodies through props or
 * each other, the camera inside a model, characters out of frame. They only warn; nothing is blocked.

Samples come from the stage (`geometrySample`): world boxes of every loaded model at one scene time.
This module only reads them, so it runs anywhere and is the same in the browser and the server render.
*/
import type { Vec3 } from './types'

export type GeometrySlotSample = {
  id: string
  /** Animated models; static models are props. */
  character: boolean
  /** The ground under the slot, and whether the scene means it to stand there. */
  ground: number
  onFloor: boolean
  min: Vec3
  max: Vec3
  /** Any part of the box is inside the camera frustum. */
  visible: boolean
}
export type GeometrySample = { t: number; camera: Vec3; slots: GeometrySlotSample[] }
export type GeometryCode = 'below_floor' | 'floating' | 'intersects' | 'camera_inside' | 'out_of_frame'
export type GeometryWarning = {
  code: GeometryCode
  severity: 'watch' | 'fail'
  slot: string
  other?: string
  start: number
  end: number
  detail: string
}
export type GeometryReport = { verdict: 'ok' | 'watch' | 'fail'; samples: number; warnings: GeometryWarning[] }

const BELOW = 0.02          // of the character's height under its ground
const FLOAT = 0.04          // of the character's height over its ground
const FLOAT_HOLD = 0.6      // seconds in the air before it is floating rather than a jump
const OVERLAP = 0.25        // of the smaller box's volume shared with another body
const OUT_HOLD = 0.5        // seconds out of frame before it is worth a warning
const SEVERITY: Record<GeometryCode, 'watch' | 'fail'> = {
  below_floor: 'fail', camera_inside: 'fail', floating: 'watch', intersects: 'watch', out_of_frame: 'watch',
}

/** Sample times: every quarter second, at most 240 samples, always including the last moment. */
export function geometrySampleTimes(duration: number): number[] {
  const step = Math.max(0.25, duration / 240)
  const times: number[] = []
  for (let t = 0; t < duration; t += step) times.push(Math.round(t * 1000) / 1000)
  times.push(duration)
  return times
}

export function checkGeometry(samples: readonly GeometrySample[]): GeometryReport {
  const flags = new Map<string, { code: GeometryCode; slot: string; other?: string; times: number[]; detail: string }>()
  const flag = (code: GeometryCode, slot: string, t: number, detail: string, other?: string) => {
    const key = `${code}\0${slot}\0${other ?? ''}`
    const entry = flags.get(key) ?? { code, slot, other, times: [], detail }
    entry.times.push(t)
    flags.set(key, entry)
  }
  for (const sample of samples) {
    for (const slot of sample.slots) {
      checkGround(slot, sample.t, flag)
      if (slot.character && !slot.visible) flag('out_of_frame', slot.id, sample.t, 'the character is outside the camera view')
      if (inside(sample.camera, slot, 0.05)) flag('camera_inside', slot.id, sample.t, 'the camera is inside this model')
    }
    checkOverlaps(sample, flag)
  }
  const step = stepOf(samples)
  const warnings = [...flags.values()].flatMap(entry => intervals(entry.times, step)
    .filter(([start, end]) => long(entry.code, end - start + step))
    .map(([start, end]) => ({ code: entry.code, severity: SEVERITY[entry.code], slot: entry.slot, ...(entry.other ? { other: entry.other } : {}), start, end, detail: entry.detail })))
  warnings.sort((a, b) => a.start - b.start || a.code.localeCompare(b.code))
  const verdict = warnings.some(item => item.severity === 'fail') ? 'fail' : warnings.length ? 'watch' : 'ok'
  return { verdict, samples: samples.length, warnings }
}

type Flag = (code: GeometryCode, slot: string, t: number, detail: string, other?: string) => void

function checkGround(slot: GeometrySlotSample, t: number, flag: Flag) {
  if (!slot.character || !slot.onFloor) return
  const height = Math.max(1e-6, slot.max[1] - slot.min[1])
  const gap = slot.min[1] - slot.ground
  if (gap < -BELOW * height) flag('below_floor', slot.id, t, 'part of the character is under the floor')
  else if (gap > FLOAT * height) flag('floating', slot.id, t, 'the character does not touch the floor')
}

function checkOverlaps(sample: GeometrySample, flag: Flag) {
  const { slots } = sample
  for (let i = 0; i < slots.length; i++) {
    for (let j = i + 1; j < slots.length; j++) {
      const a = slots[i], b = slots[j]
      if (!a.character && !b.character) continue
      if (sharedShare(a, b) > OVERLAP) {
        const [body, other] = a.character ? [a, b] : [b, a]
        flag('intersects', body.id, sample.t, 'this body goes through another model', other.id)
      }
    }
  }
}

function sharedShare(a: GeometrySlotSample, b: GeometrySlotSample): number {
  let shared = 1
  for (let axis = 0; axis < 3; axis++) shared *= Math.max(0, Math.min(a.max[axis], b.max[axis]) - Math.max(a.min[axis], b.min[axis]))
  return shared / Math.max(1e-9, Math.min(volume(a), volume(b)))
}

function volume(box: GeometrySlotSample): number {
  return Math.max(0, box.max[0] - box.min[0]) * Math.max(0, box.max[1] - box.min[1]) * Math.max(0, box.max[2] - box.min[2])
}

function inside(point: Vec3, box: GeometrySlotSample, shrink: number): boolean {
  for (let axis = 0; axis < 3; axis++) {
    const margin = (box.max[axis] - box.min[axis]) * shrink
    if (point[axis] < box.min[axis] + margin || point[axis] > box.max[axis] - margin) return false
  }
  return true
}

function stepOf(samples: readonly GeometrySample[]): number {
  return samples.length > 1 ? Math.max(1e-3, samples[1].t - samples[0].t) : 0.25
}

/** Consecutive flagged sample times merged into [start, end] runs. */
function intervals(times: readonly number[], step: number): [number, number][] {
  const runs: [number, number][] = []
  for (const t of times) {
    const last = runs[runs.length - 1]
    if (last && t - last[1] <= step * 1.5) last[1] = t
    else runs.push([t, t])
  }
  return runs
}

function long(code: GeometryCode, length: number): boolean {
  if (code === 'floating') return length >= FLOAT_HOLD
  if (code === 'out_of_frame') return length >= OUT_HOLD
  return true
}
