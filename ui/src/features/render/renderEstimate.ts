/** Time and disk estimate for a draft, final or master render.

The seconds come from the 1080p measurements in VIDEO3D_EXPORT_QUALITY.md
(2026-10-03), scaled by pixel count and by how many subframes the shutter keeps.
They are an estimate, not a clock of this machine. Disk is a bitrate guess at
the same scale. Draft ignores the shutter, matching the server.
*/

export type RenderLevel = 'draft' | 'final' | 'master'
export type RenderDevice = 'cpu' | 'gpu'
export type RenderChoice = { level: RenderLevel; shutter: number }

const BASE_PIXELS = 1920 * 1080

const LEVELS = {
  draft: { subframes: 1, secondsPerFrame: { cpu: 0.09, gpu: 0.063 }, megabitsPerSecond: 12 },
  final: { subframes: 4, secondsPerFrame: { cpu: 0.58, gpu: 0.159 }, megabitsPerSecond: 24 },
  master: { subframes: 8, secondsPerFrame: { cpu: 1.6, gpu: 0.242 }, megabitsPerSecond: 40 },
} as const

export function clampShutter(value: number): number {
  if (!Number.isFinite(value)) return 180
  return Math.min(360, Math.max(0, Math.round(value)))
}

/** Subframes one output frame will average. A closed shutter, and every draft, stay sharp. */
export function effectiveSubframes(level: RenderLevel, shutter: number): number {
  if (level === 'draft' || shutter <= 0) return 1
  return LEVELS[level].subframes
}

export function serverLevel(choice: RenderChoice): 'final' | 'master' | null {
  return choice.level === 'draft' ? null : choice.level
}

export type RenderEstimate = {
  frames: number
  seconds: number
  bytes: number
  subframes: number
}

export function estimateRender(input: {
  level: RenderLevel
  shutter: number
  width: number
  height: number
  fps: number
  duration: number
  device: RenderDevice
}): RenderEstimate {
  const profile = LEVELS[input.level]
  const frames = Math.max(1, Math.round(Math.max(0, input.duration) * Math.max(1, input.fps)))
  const pixels = Math.max(1, input.width) * Math.max(1, input.height)
  const scale = pixels / BASE_PIXELS
  const subframes = effectiveSubframes(input.level, input.shutter)
  const seconds = profile.secondsPerFrame[input.device] * scale * (subframes / profile.subframes) * frames
  const bytes = Math.round(profile.megabitsPerSecond * 1_000_000 / 8 * Math.max(0, input.duration) * scale)
  return { frames, seconds, bytes, subframes }
}

export function renderDeviceOf(value: unknown): RenderDevice {
  return value === 'cpu' ? 'cpu' : 'gpu'
}

export function formatEstimateAmount(seconds: number, bytes: number): {
  timeUnit: 'seconds' | 'minutes'
  time: string
  sizeUnit: 'megabytes' | 'gigabytes'
  size: string
} {
  const timeUnit = seconds < 90 ? 'seconds' : 'minutes'
  const time = timeUnit === 'seconds'
    ? String(Math.max(1, Math.round(seconds)))
    : (seconds / 60).toFixed(1)
  const megabytes = bytes / 1_000_000
  const sizeUnit = megabytes < 1000 ? 'megabytes' : 'gigabytes'
  const size = sizeUnit === 'megabytes'
    ? String(Math.max(1, Math.round(megabytes)))
    : (megabytes / 1000).toFixed(1)
  return { timeUnit, time, sizeUnit, size }
}
