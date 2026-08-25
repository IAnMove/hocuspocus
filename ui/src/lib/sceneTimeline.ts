import type { SceneAnimationEvent, SceneCurve, SceneKeyframe, SceneLayer } from '../types'

export type SceneAnimationPoint = Pick<SceneKeyframe, 'x' | 'y' | 'scale' | 'opacity' | 'rotation'>

export type SceneLayerTiming = {
  offset: number
  speed: number
  loop: boolean
  trimStart: number
  trimEnd: number
  span: number
}

const lerp = (a: number, b: number, amount: number) => a + (b - a) * amount

/** Converts real media seconds into the normalized scene coordinate used by preview layers. */
export const sceneProgressFromSeconds = (seconds: number, duration: number) => {
  const safeDuration = Math.max(.001, Number.isFinite(duration) ? duration : .001)
  return Math.max(0, Math.min(1, (Number.isFinite(seconds) ? seconds : 0) / safeDuration))
}

export const applySceneCurve = (amount: number, curve: SceneCurve) => {
  const value = Math.max(0, Math.min(1, amount))
  if (curve === 'ease') return value * value * (3 - 2 * value)
  if (curve === 'dramatic') return value * value
  if (curve === 'bounce') return Math.max(0, Math.min(1, value + Math.sin(value * Math.PI * 3) * (1 - value) * .18))
  return value
}

const pointFrom = (
  point: SceneLayer['animation']['start'],
  layer: SceneLayer,
): SceneAnimationPoint => ({
  x: point.x,
  y: point.y,
  scale: point.scale,
  opacity: point.opacity ?? layer.transform.opacity,
  rotation: point.rotation ?? layer.transform.rotation ?? 0,
})

export const getSceneKeyframes = (layer: SceneLayer): SceneKeyframe[] => {
  const stored = layer.animation.keyframes
  if (stored && stored.length >= 2) {
    return [...stored]
      .filter(frame => Number.isFinite(frame.time))
      .sort((a, b) => a.time - b.time)
      .map(frame => ({
        ...frame,
        opacity: Number.isFinite(frame.opacity) ? frame.opacity : layer.transform.opacity,
        rotation: Number.isFinite(frame.rotation) ? frame.rotation : layer.transform.rotation ?? 0,
        curve: frame.curve ?? layer.animation.curve,
      }))
  }

  return [
    {
      id: `${layer.id}-start`,
      time: 0,
      ...pointFrom(layer.animation.start, layer),
      curve: layer.animation.curve,
    },
    {
      id: `${layer.id}-end`,
      time: Math.max(.1, layer.animation.duration),
      ...pointFrom(layer.animation.end, layer),
      curve: layer.animation.curve,
    },
  ]
}

export const normalizeSceneKeyframes = (value: unknown, layer: SceneLayer): SceneKeyframe[] | undefined => {
  if (!Array.isArray(value)) return undefined
  const curves: SceneCurve[] = ['linear', 'ease', 'dramatic', 'bounce']
  const usedIds = new Set<string>()
  const frames = value.flatMap((raw, index) => {
    if (!raw || typeof raw !== 'object') return []
    const item = raw as Partial<SceneKeyframe>
    if (typeof item.time !== 'number' || !Number.isFinite(item.time)) return []
    const fallbackId = `${layer.id}-keyframe-${index}`
    let id = typeof item.id === 'string' && item.id.trim() ? item.id.trim().slice(0, 200) : fallbackId
    if (usedIds.has(id)) id = fallbackId
    while (usedIds.has(id)) id = `${fallbackId}-${usedIds.size + 1}`
    usedIds.add(id)
    return [{
      id,
      time: Math.max(0, Math.min(3600, item.time)),
      x: typeof item.x === 'number' && Number.isFinite(item.x) ? item.x : layer.transform.x,
      y: typeof item.y === 'number' && Number.isFinite(item.y) ? item.y : layer.transform.y,
      scale: typeof item.scale === 'number' && Number.isFinite(item.scale) ? Math.max(.01, item.scale) : layer.transform.scale,
      opacity: typeof item.opacity === 'number' && Number.isFinite(item.opacity) ? Math.max(0, Math.min(1, item.opacity)) : layer.transform.opacity,
      rotation: typeof item.rotation === 'number' && Number.isFinite(item.rotation) ? item.rotation : layer.transform.rotation ?? 0,
      curve: curves.includes(item.curve as SceneCurve) ? item.curve as SceneCurve : layer.animation.curve,
    }]
  }).sort((a, b) => a.time - b.time)
  const distinctTimes = frames.filter((frame, index) => index === 0 || Math.abs(frame.time - frames[index - 1].time) > .000001)
  return distinctTimes.length >= 2 ? distinctTimes : undefined
}

export const normalizeSceneEvents = (value: unknown, duration: number, idPrefix = 'scene') => {
  if (!Array.isArray(value)) return [] as SceneAnimationEvent[]
  const maxTime = Math.max(.1, Number.isFinite(duration) ? duration : .1)
  const usedIds = new Set<string>()
  const events: SceneAnimationEvent[] = []
  value.forEach((raw, index) => {
    if (!raw || typeof raw !== 'object') return
    const item = raw as Partial<SceneAnimationEvent>
    if (typeof item.time !== 'number' || !Number.isFinite(item.time) || typeof item.name !== 'string' || !item.name.trim()) return
    const fallbackId = `${idPrefix}-event-${index + 1}`
    let id = typeof item.id === 'string' && item.id.trim() ? item.id : fallbackId
    if (usedIds.has(id)) id = fallbackId
    while (usedIds.has(id)) id = `${fallbackId}-${usedIds.size + 1}`
    usedIds.add(id)
    events.push({
      id,
      time: Math.max(0, Math.min(maxTime, item.time)),
      name: item.name.trim().slice(0, 100),
      payload: typeof item.payload === 'string' && item.payload.length > 0 ? item.payload.slice(0, 2000) : undefined,
    })
  })
  return events.sort((a, b) => a.time - b.time)
}

export const getSceneEvents = (layer: SceneLayer) => normalizeSceneEvents(layer.animation.events, layer.animation.duration, layer.id)

export const getSceneLayerTiming = (layer: SceneLayer): SceneLayerTiming => {
  const duration = Math.max(.1, layer.animation.duration)
  const offset = typeof layer.animation.offset === 'number' && Number.isFinite(layer.animation.offset) ? Math.max(0, layer.animation.offset) : 0
  const speed = typeof layer.animation.speed === 'number' && Number.isFinite(layer.animation.speed) ? Math.max(.1, Math.min(8, layer.animation.speed)) : 1
  const rawStart = typeof layer.animation.trimStart === 'number' && Number.isFinite(layer.animation.trimStart) ? layer.animation.trimStart : 0
  const trimStart = Math.max(0, Math.min(duration - .01, rawStart))
  const rawEnd = typeof layer.animation.trimEnd === 'number' && Number.isFinite(layer.animation.trimEnd) ? layer.animation.trimEnd : duration
  const trimEnd = Math.max(trimStart + .01, Math.min(duration, rawEnd))
  return { offset, speed, loop: Boolean(layer.animation.loop), trimStart, trimEnd, span: trimEnd - trimStart }
}

export const sceneTimeToLayerTime = (layer: SceneLayer, sceneTime: number) => {
  const timing = getSceneLayerTiming(layer)
  const elapsed = Math.max(0, sceneTime - timing.offset) * timing.speed
  if (timing.loop && elapsed > 0) return timing.trimStart + (elapsed % timing.span)
  return timing.trimStart + Math.min(timing.span, elapsed)
}

export const layerTimeToSceneTime = (layer: SceneLayer, layerTime: number) => {
  const timing = getSceneLayerTiming(layer)
  return timing.offset + (Math.max(timing.trimStart, layerTime) - timing.trimStart) / timing.speed
}

export const sceneLayerMotionProgress = (layer: SceneLayer, sceneTime: number) => {
  const timing = getSceneLayerTiming(layer)
  return (sceneTimeToLayerTime(layer, sceneTime) - timing.trimStart) / timing.span
}

export const withNormalizedSceneTiming = (layer: SceneLayer): SceneLayer => {
  const timing = getSceneLayerTiming(layer)
  return {
    ...layer,
    animation: {
      ...layer.animation,
      offset: timing.offset,
      speed: timing.speed,
      loop: timing.loop,
      trimStart: timing.trimStart,
      trimEnd: timing.trimEnd,
    },
  }
}

export const evaluateSceneLayer = (layer: SceneLayer, timeSeconds: number): SceneAnimationPoint => {
  const frames = getSceneKeyframes(layer)
  if (timeSeconds <= frames[0].time) return frames[0]
  const finalFrame = frames[frames.length - 1]
  if (timeSeconds >= finalFrame.time) return finalFrame

  const rightIndex = frames.findIndex(frame => frame.time >= timeSeconds)
  const start = frames[Math.max(0, rightIndex - 1)]
  const end = frames[rightIndex]
  const span = Math.max(.0001, end.time - start.time)
  const amount = applySceneCurve((timeSeconds - start.time) / span, start.curve)
  return {
    x: lerp(start.x, end.x, amount),
    y: lerp(start.y, end.y, amount),
    scale: lerp(start.scale, end.scale, amount),
    opacity: lerp(start.opacity, end.opacity, amount),
    rotation: lerp(start.rotation, end.rotation, amount),
  }
}

const framePoint = (frame: SceneKeyframe) => ({
  x: frame.x,
  y: frame.y,
  scale: frame.scale,
  opacity: frame.opacity,
  rotation: frame.rotation,
})

export const withSceneKeyframes = (
  layer: SceneLayer,
  keyframes: SceneKeyframe[],
  requestedDuration = layer.animation.duration,
): SceneLayer => {
  if (keyframes.length < 2) return layer
  const ordered = [...keyframes].map(frame => ({ ...frame, time: Math.max(0, Math.min(3600, frame.time)) })).sort((a, b) => a.time - b.time)
  const duration = Math.min(3600, Math.max(.1, requestedDuration, ordered[ordered.length - 1].time))
  return {
    ...layer,
    animation: {
      ...layer.animation,
      start: framePoint(ordered[0]),
      end: framePoint(ordered[ordered.length - 1]),
      keyframes: ordered,
      duration,
      curve: ordered[0].curve,
    },
  }
}

export const mapSceneAnimationPoints = (
  layer: SceneLayer,
  map: (point: SceneAnimationPoint) => SceneAnimationPoint,
): SceneLayer['animation'] => ({
  ...layer.animation,
  start: map(pointFrom(layer.animation.start, layer)),
  end: map(pointFrom(layer.animation.end, layer)),
  keyframes: layer.animation.keyframes?.map(frame => ({ ...frame, ...map(frame) })),
})
