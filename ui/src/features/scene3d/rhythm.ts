import type { Scene3DSlot, Vec3 } from './types'

/** One explicit song clock, shared by actors, camera and light. */
export type Scene3DRhythm = { bpm: number; offset: number; cameraPulse: number; lightPulse: number }
export type Scene3DSlotRhythm = { beats: number; phase: number; bounce: number; sway: number; yaw: number; pulse: number }

function object(raw: unknown, keys: string[]): Record<string, unknown> | undefined {
  if (raw === undefined) return undefined
  if (!raw || typeof raw !== 'object' || Array.isArray(raw) || Object.keys(raw).some(key => !keys.includes(key))) throw new Error('Invalid rhythm settings')
  return raw as Record<string, unknown>
}

function number(value: unknown, fallback: number, min: number, max: number) {
  if (value === undefined) return fallback
  if (typeof value !== 'number' || !Number.isFinite(value) || value < min || value > max) throw new Error('Rhythm value is out of range')
  return value
}

export function parseRhythm(raw: unknown): Scene3DRhythm | undefined {
  const value = object(raw, ['bpm', 'offset', 'cameraPulse', 'lightPulse'])
  if (!value) return undefined
  return { bpm: number(value.bpm, 120, 40, 240), offset: number(value.offset, 0, -600, 600),
    cameraPulse: number(value.cameraPulse, 0, 0, .25), lightPulse: number(value.lightPulse, 0, 0, 1) }
}

export function parseSlotRhythm(raw: unknown): Scene3DSlotRhythm | undefined {
  const value = object(raw, ['beats', 'phase', 'bounce', 'sway', 'yaw', 'pulse'])
  if (!value) return undefined
  return { beats: number(value.beats, 1, .25, 16), phase: number(value.phase, 0, -16, 16),
    bounce: number(value.bounce, 0, 0, 1), sway: number(value.sway, 0, 0, .75),
    yaw: number(value.yaw, 0, 0, .7), pulse: number(value.pulse, 0, 0, .2) }
}

function wave(rhythm: Scene3DRhythm, seconds: number, beats = 1, phase = 0) {
  const cycles = (seconds + rhythm.offset) * rhythm.bpm / (60 * beats) + phase
  const fraction = ((cycles % 1) + 1) % 1
  return { angle: fraction * 2 * Math.PI, kick: Math.exp(-fraction * 10) }
}

/** Compose with authored travel; sampling and backward seeking have no state. */
export function rhythmicSlotPose(slot: Scene3DSlot, pose: { position: Vec3; rotationY: number }, seconds: number, clock?: Scene3DRhythm) {
  if (!clock || !slot.rhythm) return { ...pose, scale: slot.scale }
  const r = slot.rhythm, w = wave(clock, seconds, r.beats, r.phase), swing = Math.sin(w.angle)
  return { position: [pose.position[0] + r.sway * swing, pose.position[1] + r.bounce * (1 - Math.cos(w.angle)) / 2, pose.position[2]] as Vec3,
    rotationY: pose.rotationY + r.yaw * swing, scale: slot.scale * (1 + r.pulse * w.kick) }
}

export function rhythmicCameraEye(eye: Vec3, look: Vec3, seconds: number, clock?: Scene3DRhythm): Vec3 {
  if (!clock) return eye
  const factor = 1 - clock.cameraPulse * wave(clock, seconds).kick
  return eye.map((value, index) => look[index] + (value - look[index]) * factor) as unknown as Vec3
}

/** Assign from the current palette/atmosphere base, never accumulate pulses. */
export function rhythmicLightIntensity(base: number, seconds: number, clock?: Scene3DRhythm) {
  return base * (1 + (clock ? clock.lightPulse * wave(clock, seconds).kick : 0))
}
