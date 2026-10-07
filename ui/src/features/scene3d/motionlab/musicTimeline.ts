import { seeded } from './resources'
import type { MotionLabSettings } from './types'

export type MotionMusicKind = 'motion-bouncing-ball' | 'motion-music-machine'
export type MusicContact = { index: number; lane: number; seconds: number; frequency: number; velocity: number }
export const MUSIC_LIMIT_SECONDS = 600
export const BALL_RADIUS = .26
export const HAMMER_RADIUS = .22
export const PLATFORM_DEPTH = .22
export const KEY_DEPTH = .18
const SCALE = [0, 2, 4, 7, 9, 12, 14, 16]

export function hasMotionLabMusic(kind: string | undefined, settings?: MotionLabSettings): boolean {
  return (kind === 'motion-bouncing-ball' || kind === 'motion-music-machine')
    && (!settings || (settings.sound && settings.volume > 0))
}

export function beatSeconds(settings: MotionLabSettings): number {
  return 60 / (settings.bpm * settings.speed)
}

export function musicBeat(settings: MotionLabSettings, seconds: number): number {
  const beat = Math.max(0, Number.isFinite(seconds) ? seconds : 0) / beatSeconds(settings)
  const nearest = Math.round(beat)
  return Math.abs(beat - nearest) < 1e-9 ? nearest : beat
}

export function musicPhase(beat: number, lane: number, count: number): number {
  const cycles = (beat - lane) / count
  return cycles - Math.floor(cycles)
}

/** One original, seeded instrument tuning. A physical key keeps its pitch on every lap. */
export function musicContact(kind: MotionMusicKind, settings: MotionLabSettings, index: number): MusicContact {
  const count = kind === 'motion-bouncing-ball' ? 8 : 4
  const lane = index % count
  const degree = (lane * 3 + Math.floor(seeded(settings.seed, 0) * 8)) % SCALE.length
  const midi = (kind === 'motion-bouncing-ball' ? 60 : 48) + SCALE[degree]
  return { index, lane, seconds: index * beatSeconds(settings), frequency: 440 * 2 ** ((midi - 69) / 12),
    velocity: .65 + seeded(settings.seed, lane + 90) * .25 }
}

/** Half-open scene interval. Geometry uses this same beat/lane clock, never frame collisions. */
export function musicContacts(kind: MotionMusicKind, settings: MotionLabSettings, from: number, to: number): MusicContact[] {
  if (!Number.isFinite(from) || !Number.isFinite(to) || from < 0 || to < from || to - from > MUSIC_LIMIT_SECONDS + 1) {
    throw new Error('Invalid Motion Lab contact interval.')
  }
  const period = beatSeconds(settings)
  const first = Math.max(0, Math.ceil(from / period - 1e-9))
  const end = Math.ceil(to / period - 1e-9)
  return Array.from({ length: Math.max(0, end - first) }, (_, at) => musicContact(kind, settings, first + at))
}

export function platformPosition(settings: MotionLabSettings, lane: number): [number, number, number] {
  const angle = lane * Math.PI / 4
  return [Math.sin(angle) * 3.1, .72 + seeded(settings.seed, lane + 10) * .35, Math.cos(angle) * 3.1]
}

export function bouncingBallPosition(settings: MotionLabSettings, seconds: number): [number, number, number] {
  const beat = musicBeat(settings, seconds), whole = Math.floor(beat), phase = beat - whole
  const from = platformPosition(settings, whole % 8), to = platformPosition(settings, (whole + 1) % 8)
  const hop = settings.amplitude + Math.abs(to[1] - from[1]) * .5
  return [from[0] + (to[0] - from[0]) * phase,
    from[1] + (to[1] - from[1]) * phase + PLATFORM_DEPTH / 2 + BALL_RADIUS + 4 * phase * (1 - phase) * hop,
    from[2] + (to[2] - from[2]) * phase]
}

export function machineKeyPosition(lane: number): [number, number, number] {
  return [(lane - 1.5) * 1.55, .8, 0]
}

export function hammerHeight(settings: MotionLabSettings, seconds: number, lane: number): number {
  const phase = musicPhase(musicBeat(settings, seconds), lane, 4)
  return .8 + KEY_DEPTH / 2 + HAMMER_RADIUS + settings.amplitude * (1 - Math.cos(phase * Math.PI * 2)) / 2
}
