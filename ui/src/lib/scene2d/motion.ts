// Optional path, frame sequence, anchored atmosphere and stored rhythm.
// Every function is a no-op unless the new field is present.
import type { AnimatorLayer, LayerState } from './types'

export type ScenePath = { points: Array<{ x: number; y: number }>; orient: boolean; rotationOffset?: number }
export type FrameSequence = { kind: 'frames'; sources: string[]; fps: number; loop: 'loop' | 'pingpong' | 'once' }
  | { kind: 'sheet'; source: string; columns: number; rows: number; count: number; fps: number; loop: 'loop' | 'pingpong' | 'once' }
export type AtmosphereEmitter = { mode: 'frame' | 'point' | 'layer'; x?: number; y?: number; targetLayerId?: string; offsetX?: number; offsetY?: number; direction: number; spread: number; rate: number; lifetime: number; speed: number; gravity: number }
export type SceneRhythm = { bpm: number; beats: number[]; downbeats?: number[]; energy?: { fps: number; values: number[] } }

const clamp = (value: number, min: number, max: number) => Math.max(min, Math.min(max, value))
const num = (value: unknown, fallback: number, min: number, max: number) => typeof value === 'number' && Number.isFinite(value) ? clamp(value, min, max) : fallback

export function parsePath(raw: unknown): ScenePath | undefined {
  if (!raw || typeof raw !== 'object') return undefined
  const value = raw as ScenePath
  const points = Array.isArray(value.points) ? value.points.filter(point => point && Number.isFinite(point.x) && Number.isFinite(point.y)).slice(0, 32).map(point => ({ x: clamp(point.x, -20, 120), y: clamp(point.y, -20, 120) })) : []
  if (points.length < 2) return undefined
  return { points, orient: value.orient === true, ...(Number.isFinite(value.rotationOffset) ? { rotationOffset: clamp(value.rotationOffset ?? 0, -180, 180) } : {}) }
}

export function parseSequence(raw: unknown): FrameSequence | undefined {
  if (!raw || typeof raw !== 'object') return undefined
  const value = raw as FrameSequence
  const fps = num(value.fps, 12, 1, 60)
  const loop = value.loop === 'pingpong' || value.loop === 'once' ? value.loop : 'loop'
  if (value.kind === 'frames' && Array.isArray(value.sources)) {
    const sources = value.sources.filter(source => typeof source === 'string' && source.trim()).slice(0, 120)
    return sources.length ? { kind: 'frames', sources, fps, loop } : undefined
  }
  if (value.kind === 'sheet' && typeof value.source === 'string' && value.source.trim()) {
    return { kind: 'sheet', source: value.source.trim(), columns: Math.round(num(value.columns, 1, 1, 32)), rows: Math.round(num(value.rows, 1, 1, 32)), count: Math.round(num(value.count, 1, 1, 120)), fps, loop }
  }
  return undefined
}

export function sequenceFrame(sequence: FrameSequence, seconds: number) {
  const count = sequence.kind === 'frames' ? sequence.sources.length : sequence.count
  const raw = Math.floor(Math.max(0, seconds) * sequence.fps)
  if (sequence.loop === 'once') return Math.min(count - 1, raw)
  if (sequence.loop === 'pingpong') {
    const cycle = Math.max(1, count * 2 - 2)
    const at = raw % cycle
    return at < count ? at : cycle - at
  }
  return raw % Math.max(1, count)
}

export function sequenceSource(sequence: FrameSequence, seconds: number) {
  if (sequence.kind === 'sheet') return sequence.source
  return sequence.sources[sequenceFrame(sequence, seconds)] ?? sequence.sources[0]
}

function catmull(p0: number, p1: number, p2: number, p3: number, t: number) {
  const t2 = t * t
  const t3 = t2 * t
  return 0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2 + (-p0 + 3 * p1 - 3 * p2 + p3) * t3)
}

function uniformPoint(path: ScenePath, progress: number) {
  const points = path.points
  const span = Math.max(1, points.length - 1)
  const scaled = clamp(progress, 0, 1) * span
  const index = Math.min(points.length - 2, Math.floor(scaled))
  const t = scaled - index
  const at = (offset: number) => points[clamp(index + offset, 0, points.length - 1)]
  const x = catmull(at(-1).x, at(0).x, at(1).x, at(2).x, t)
  const y = catmull(at(-1).y, at(0).y, at(1).y, at(2).y, t)
  const ahead = catmull(at(-1).x, at(0).x, at(1).x, at(2).x, Math.min(1, t + 0.02))
  const aheadY = catmull(at(-1).y, at(0).y, at(1).y, at(2).y, Math.min(1, t + 0.02))
  const rotation = Math.atan2(aheadY - y, ahead - x) * 180 / Math.PI + (path.rotationOffset ?? 0)
  return { x, y, rotation }
}

function arcParameter(path: ScenePath, progress: number) {
  const steps = 24
  const lengths = [0]
  let previous = uniformPoint(path, 0)
  for (let step = 1; step <= steps; step += 1) {
    const point = uniformPoint(path, step / steps)
    lengths.push(lengths[step - 1] + Math.hypot(point.x - previous.x, point.y - previous.y))
    previous = point
  }
  const total = lengths[steps]
  if (!(total > 0)) return clamp(progress, 0, 1)
  const target = clamp(progress, 0, 1) * total
  let index = 1
  while (index < lengths.length && lengths[index] < target) index += 1
  const span = lengths[index] - lengths[index - 1] || 1
  return (index - 1 + (target - lengths[index - 1]) / span) / steps
}

export function pathPoint(path: ScenePath, progress: number) {
  return uniformPoint(path, arcParameter(path, progress))
}

export function sheetCrop(sequence: FrameSequence, seconds: number, width: number, height: number) {
  if (sequence.kind !== 'sheet' || !(width > 0) || !(height > 0)) return undefined
  const frame = sequenceFrame(sequence, seconds)
  const column = frame % sequence.columns
  const row = Math.floor(frame / sequence.columns) % sequence.rows
  return {
    x: column * width / sequence.columns,
    y: row * height / sequence.rows,
    width: width / sequence.columns,
    height: height / sequence.rows,
  }
}

export function emitterSample(emitter: AtmosphereEmitter, index: number, seconds: number, anchor: { x: number; y: number }) {
  const birth = index / Math.max(0.1, emitter.rate)
  const age = seconds - birth
  if (age < 0 || age > emitter.lifetime) return undefined
  const spread = ((index * 37) % 1000) / 1000 - 0.5
  const angle = (emitter.direction + spread * emitter.spread) * Math.PI / 180
  const travel = emitter.speed * age * 0.08
  return {
    x: anchor.x + Math.cos(angle) * travel,
    y: anchor.y + Math.sin(angle) * travel + emitter.gravity * age * age * 0.015,
    alpha: Math.max(0, 1 - age / emitter.lifetime),
  }
}

export function applyScenePath(state: LayerState, layer: AnimatorLayer, progress: number): LayerState {
  const path = layer.animation.path
  if (!path || path.points.length < 2) return state
  const point = pathPoint(path, progress)
  return { ...state, x: point.x, y: point.y, ...(path.orient ? { rotation: point.rotation } : {}) }
}

export function parseEmitter(raw: unknown): AtmosphereEmitter | undefined {
  if (!raw || typeof raw !== 'object') return undefined
  const value = raw as AtmosphereEmitter
  const mode = value.mode === 'point' || value.mode === 'layer' ? value.mode : value.mode === 'frame' ? 'frame' : undefined
  if (!mode) return undefined
  return {
    mode, direction: num(value.direction, 0, -180, 180), spread: num(value.spread, 30, 0, 180),
    rate: num(value.rate, 12, 0.1, 80), lifetime: num(value.lifetime, 1.2, 0.05, 12), speed: num(value.speed, 20, 0, 200), gravity: num(value.gravity, 0, -80, 80),
    ...(value.x != null ? { x: num(value.x, 50, 0, 100) } : {}),
    ...(value.y != null ? { y: num(value.y, 50, 0, 100) } : {}),
    ...(typeof value.targetLayerId === 'string' ? { targetLayerId: value.targetLayerId.slice(0, 120) } : {}),
    ...(value.offsetX != null ? { offsetX: num(value.offsetX, 0, -100, 100) } : {}),
    ...(value.offsetY != null ? { offsetY: num(value.offsetY, 0, -100, 100) } : {}),
  }
}

export function parseRhythm(raw: unknown): SceneRhythm | undefined {
  if (!raw || typeof raw !== 'object') return undefined
  const value = raw as SceneRhythm
  const beats = Array.isArray(value.beats) ? value.beats.filter(beat => typeof beat === 'number' && Number.isFinite(beat)).slice(0, 2000) : []
  if (!beats.length || !Number.isFinite(value.bpm)) return undefined
  const downbeats = Array.isArray(value.downbeats) ? value.downbeats.filter(beat => typeof beat === 'number' && Number.isFinite(beat)).slice(0, 2000) : undefined
  const energy = value.energy && Array.isArray(value.energy.values)
    ? { fps: num(value.energy.fps, 10, 1, 60), values: value.energy.values.filter(item => typeof item === 'number' && Number.isFinite(item)).slice(0, 6000) }
    : undefined
  return { bpm: clamp(value.bpm, 40, 240), beats, ...(downbeats?.length ? { downbeats } : {}), ...(energy?.values.length ? { energy } : {}) }
}

export function beatEnvelope(rhythm: SceneRhythm | undefined, seconds: number, on: 'beats' | 'downbeats' = 'beats') {
  const marks = on === 'downbeats' ? rhythm?.downbeats ?? rhythm?.beats : rhythm?.beats
  if (!marks?.length) return 0
  let nearest = 99
  for (const beat of marks) nearest = Math.min(nearest, Math.abs(seconds - beat))
  return Math.max(0, 1 - nearest / 0.12)
}

export function applyBeatPulse(state: LayerState, amount: number, envelope: number): LayerState {
  if (!(amount > 0) || !(envelope > 0)) return state
  return { ...state, scale: state.scale * (1 + amount * envelope) }
}

export function rhythmFromAnalysis(analysis: { bpm: number; beats: Array<{ time: number }>; downbeats?: number[]; onset_envelope?: number[] }, start: number, duration: number) {
  const shift = (time: number) => time + start
  const beats = analysis.beats.map(beat => shift(beat.time)).filter(time => time >= 0 && time <= duration)
  const downbeats = (analysis.downbeats ?? []).map(shift).filter(time => time >= 0 && time <= duration)
  const values = (analysis.onset_envelope ?? []).filter(item => Number.isFinite(item))
  return parseRhythm({
    bpm: analysis.bpm,
    beats,
    downbeats,
    ...(values.length ? { energy: { fps: 10, values } } : {}),
  })
}
