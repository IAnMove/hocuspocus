import { vecCross, vecLength, vecNormalize, vecSub } from './camera.ts'
import type { Vec3 } from './types.ts'

/** One window of camera shake, in scene seconds. The offset is in camera space and
 * is added after the camera pose (family, framing, rhythm) is computed. */
export type Scene3DCameraShake = {
  start: number
  end: number
  /** Metres of sideways and vertical camera travel at full strength. */
  amplitude: number
  /** Oscillations per second. */
  frequency: number
  /** Picks the noise; the same seed always shakes the same way. */
  seed?: number
  /** Exponential fall-off per second from `start`; absent or 0 keeps full strength. */
  decay?: number
}

export const CAMERA_SHAKE_LIMITS = { windows: 16, amplitude: 2, frequency: 60, decay: 60, seed: 1_000_000 } as const
/** Roll in radians per metre of amplitude: 0.1 m of shake also rolls about 2°. */
const ROLL_PER_METRE = 0.35
const RANGES: Record<string, readonly [number, number]> = {
  start: [0, 600], end: [0, 600], amplitude: [0, CAMERA_SHAKE_LIMITS.amplitude], frequency: [0, CAMERA_SHAKE_LIMITS.frequency],
  seed: [0, CAMERA_SHAKE_LIMITS.seed], decay: [0, CAMERA_SHAKE_LIMITS.decay],
}
const REQUIRED = ['start', 'end', 'amplitude', 'frequency']
const PARTIALS = [{ ratio: 1, weight: 1 }, { ratio: 2.31, weight: 0.5 }, { ratio: 0.53, weight: 0.35 }] as const
const WEIGHT = PARTIALS.reduce((sum, partial) => sum + partial.weight, 0)

const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value)
const within = (value: unknown, min: number, max: number) => finite(value) && value >= min && value <= max

function validWindow(raw: unknown): raw is Scene3DCameraShake {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return false
  const value = raw as Record<string, number>
  const known = (key: string) => Object.hasOwn(RANGES, key) && (value[key] === undefined ? !REQUIRED.includes(key) : within(value[key], ...RANGES[key]))
  if (!REQUIRED.every(key => key in value) || !Object.keys(value).every(known)) return false
  if (value.seed !== undefined && !Number.isInteger(value.seed)) return false
  return value.end > value.start && value.amplitude > 0 && value.frequency > 0
}

/** A stored `camera.shake`: at most 16 windows of known, bounded numbers. */
export function validCameraShake(raw: unknown): raw is Scene3DCameraShake[] {
  return Array.isArray(raw) && raw.length <= CAMERA_SHAKE_LIMITS.windows && raw.every(validWindow)
}

function hash(seed: number, index: number) {
  let value = Math.imul((seed + 1) ^ (index + 1) * 0x9e3779b1, 0x45d9f3b)
  value = Math.imul(value ^ (value >>> 16), 0x45d9f3b)
  return ((value ^ (value >>> 16)) >>> 0) / 4294967296
}

/** Smooth noise in [-1, 1]: three detuned sines with seeded phases. */
function noise(seed: number, axis: number, frequency: number, local: number) {
  let sum = 0
  PARTIALS.forEach((partial, index) => {
    const phase = hash(seed, axis * PARTIALS.length + index) * Math.PI * 2
    sum += partial.weight * Math.sin(Math.PI * 2 * frequency * partial.ratio * local + phase)
  })
  return sum / WEIGHT
}

/** Strength of one window at `seconds`: 0 outside, a one-frame attack and a short release. */
function envelope(shake: Scene3DCameraShake, seconds: number) {
  if (seconds < shake.start || seconds >= shake.end) return 0
  const local = seconds - shake.start
  const span = shake.end - shake.start
  const attack = Math.min(1, local / Math.min(0.02, span * 0.1))
  const release = Math.min(1, (shake.end - seconds) / Math.min(0.08, span * 0.25))
  return attack * release * Math.exp(-(shake.decay ?? 0) * local)
}

/** Camera-space offset (metres right and up) and roll (radians) at `seconds`. A pure function of time. */
export function cameraShakeAt(shakes: readonly Scene3DCameraShake[] | undefined, seconds: number) {
  const offset = { right: 0, up: 0, roll: 0 }
  for (const shake of shakes ?? []) {
    const strength = envelope(shake, seconds) * shake.amplitude
    if (!strength) continue
    const local = seconds - shake.start
    const seed = shake.seed ?? 1
    offset.right += strength * noise(seed, 0, shake.frequency, local)
    offset.up += strength * 0.8 * noise(seed, 1, shake.frequency, local)
    offset.roll += strength * ROLL_PER_METRE * noise(seed, 2, shake.frequency * 0.7, local)
  }
  return offset
}

/** Move eye and look together along the camera's right and up axes, and report the roll to add. */
export function shakeCamera(shakes: readonly Scene3DCameraShake[] | undefined, seconds: number, eye: Vec3, look: Vec3) {
  const offset = cameraShakeAt(shakes, seconds)
  if (!offset.right && !offset.up && !offset.roll) return { eye, look, roll: 0 }
  const forward = vecNormalize(vecSub(look, eye))
  const crossed = vecCross(forward, [0, 1, 0])
  const right = vecLength(crossed) < 1e-6 ? [1, 0, 0] as Vec3 : vecNormalize(crossed)
  const up = vecCross(right, forward)
  const move = [0, 1, 2].map(i => right[i] * offset.right + up[i] * offset.up)
  return {
    eye: eye.map((value, i) => value + move[i]) as unknown as Vec3,
    look: look.map((value, i) => value + move[i]) as unknown as Vec3,
    roll: offset.roll,
  }
}
