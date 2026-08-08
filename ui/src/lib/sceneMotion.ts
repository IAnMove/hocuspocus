import type { SceneCurve, SceneLayer } from '../types'
import { getSceneEvents, normalizeSceneEvents, normalizeSceneKeyframes, withNormalizedSceneTiming, withSceneKeyframes } from './sceneTimeline'

type MotionOptions = {
  isValidOrbitTarget?: (targetLayerId: string) => boolean
}

const isRecord = (value: unknown): value is Record<string, unknown> => Boolean(value) && typeof value === 'object' && !Array.isArray(value)
const bounded = (value: number, min: number, max: number) => Math.max(min, Math.min(max, value))

const finiteField = (value: unknown, label: string, min: number, max: number) => {
  if (typeof value !== 'number' || !Number.isFinite(value)) throw new Error(`${label} must be a finite number.`)
  return bounded(value, min, max)
}

const optionalFiniteField = (value: unknown, fallback: number, label: string, min: number, max: number) => value === undefined
  ? fallback
  : finiteField(value, label, min, max)

const optionalBooleanField = (value: unknown, fallback: boolean, label: string) => {
  if (value === undefined) return fallback
  if (typeof value !== 'boolean') throw new Error(`${label} must be true or false.`)
  return value
}

const motionPoint = (value: unknown, fallback: SceneLayer['animation']['start'], label: string) => {
  if (!isRecord(value)) throw new Error(`${label} must contain x, y and scale.`)
  const point: SceneLayer['animation']['start'] = {
    x: finiteField(value.x, `${label}.x`, -500, 500),
    y: finiteField(value.y, `${label}.y`, -500, 500),
    scale: finiteField(value.scale, `${label}.scale`, .01, 20),
  }
  const fallbackOpacity = fallback.opacity
  const fallbackRotation = fallback.rotation
  if (value.opacity !== undefined) point.opacity = finiteField(value.opacity, `${label}.opacity`, 0, 1)
  else if (fallbackOpacity !== undefined) point.opacity = fallbackOpacity
  if (value.rotation !== undefined) point.rotation = finiteField(value.rotation, `${label}.rotation`, -36_000, 36_000)
  else if (fallbackRotation !== undefined) point.rotation = fallbackRotation
  return point
}

/** Validates untrusted LLM/file motion JSON and applies only known animation fields. */
export const sanitizeSceneMotion = (raw: unknown, layer: SceneLayer, options: MotionOptions = {}): SceneLayer => {
  if (!isRecord(raw)) throw new Error('JSON must contain a motion object.')
  const envelopeMotion = raw.motion
  const item = envelopeMotion === undefined ? raw : envelopeMotion
  if (!isRecord(item)) throw new Error('JSON must contain a motion object.')

  const duration = finiteField(item.duration, 'motion.duration', .1, 3600)
  const curves: SceneCurve[] = ['linear', 'ease', 'dramatic', 'bounce']
  if (item.curve !== undefined && !curves.includes(item.curve as SceneCurve)) throw new Error('motion.curve must be linear, ease, dramatic or bounce.')
  const curve = item.curve as SceneCurve | undefined ?? layer.animation.curve
  const start = motionPoint(item.start, layer.animation.start, 'motion.start')
  const end = motionPoint(item.end, layer.animation.end, 'motion.end')

  let shake = layer.animation.shake
  if (item.shake !== undefined) {
    if (item.shake === null) shake = undefined
    else {
      if (layer.type !== 'camera' || !isRecord(item.shake)) throw new Error('motion.shake is only valid for camera layers.')
      shake = {
        amount: finiteField(item.shake.amount, 'motion.shake.amount', 0, 8),
        frequency: finiteField(item.shake.frequency, 'motion.shake.frequency', .1, 30),
        seed: item.shake.seed === undefined ? 0 : finiteField(item.shake.seed, 'motion.shake.seed', -1_000_000, 1_000_000),
        startTime: optionalFiniteField(item.shake.startTime, 0, 'motion.shake.startTime', 0, 3600),
        endTime: optionalFiniteField(item.shake.endTime, duration, 'motion.shake.endTime', 0, 3600),
      }
    }
  }

  let orbit = layer.animation.orbit
  if (item.orbit !== undefined) {
    if (item.orbit === null) orbit = undefined
    else {
      if (layer.type === 'camera' || !isRecord(item.orbit)) throw new Error('motion.orbit is only valid for visual layers.')
      const targetLayerId = typeof item.orbit.targetLayerId === 'string' ? item.orbit.targetLayerId.trim() : ''
      if (!targetLayerId || options.isValidOrbitTarget?.(targetLayerId) === false) throw new Error('motion.orbit.targetLayerId must reference a valid non-cyclic visual layer.')
      const facing = item.orbit.facing ?? 'fixed'
      if (facing !== 'fixed' && facing !== 'center' && facing !== 'outward') throw new Error('motion.orbit.facing must be fixed, center or outward.')
      orbit = {
        targetLayerId,
        radiusX: finiteField(item.orbit.radiusX, 'motion.orbit.radiusX', 0, 100),
        radiusY: finiteField(item.orbit.radiusY, 'motion.orbit.radiusY', 0, 100),
        turns: finiteField(item.orbit.turns, 'motion.orbit.turns', -20, 20),
        phase: finiteField(item.orbit.phase, 'motion.orbit.phase', -360, 360),
        count: Math.round(optionalFiniteField(item.orbit.count, 1, 'motion.orbit.count', 1, 12)),
        facing,
        centerOffsetX: optionalFiniteField(item.orbit.centerOffsetX, 0, 'motion.orbit.centerOffsetX', -100, 100),
        centerOffsetY: optionalFiniteField(item.orbit.centerOffsetY, 0, 'motion.orbit.centerOffsetY', -100, 100),
      }
    }
  }

  const events = item.events === undefined ? getSceneEvents(layer) : normalizeSceneEvents(item.events, duration, layer.id)
  const animation: SceneLayer['animation'] = {
    ...layer.animation,
    start,
    end,
    keyframes: undefined,
    events,
    duration,
    curve,
    offset: optionalFiniteField(item.offset, layer.animation.offset ?? 0, 'motion.offset', 0, 3600),
    speed: optionalFiniteField(item.speed, layer.animation.speed ?? 1, 'motion.speed', .1, 8),
    loop: optionalBooleanField(item.loop, layer.animation.loop ?? false, 'motion.loop'),
    trimStart: optionalFiniteField(item.trimStart, layer.animation.trimStart ?? 0, 'motion.trimStart', 0, 3600),
    trimEnd: optionalFiniteField(item.trimEnd, layer.animation.trimEnd ?? duration, 'motion.trimEnd', .01, 3600),
    spin: optionalBooleanField(item.spin, layer.animation.spin ?? false, 'motion.spin'),
    rotationSpeed: optionalFiniteField(item.rotationSpeed, layer.animation.rotationSpeed ?? 35, 'motion.rotationSpeed', 0, 720),
    shake,
    orbit,
  }
  let updated = withNormalizedSceneTiming({ ...layer, animation })
  if (item.keyframes !== undefined) {
    const keyframes = normalizeSceneKeyframes(item.keyframes, updated)
    if (!keyframes) throw new Error('motion.keyframes must contain at least two valid keyframes.')
    updated = withSceneKeyframes(updated, keyframes, duration)
  }
  return updated
}
