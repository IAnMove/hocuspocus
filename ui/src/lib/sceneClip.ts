import type { SceneLayer } from '../types'

const finiteNumber = (value: unknown, fallback: number) => typeof value === 'number' && Number.isFinite(value) ? value : fallback
const boundedNumber = (value: unknown, fallback: number, min: number, max: number) => Math.max(min, Math.min(max, finiteNumber(value, fallback)))

/** Maps scene time to a deterministic paused frame inside a baked GLB clip. */
export const getSceneClipTime = (layer: SceneLayer, sceneSeconds: number, clipDuration: number) => {
  const duration = Math.max(.001, finiteNumber(clipDuration, 0))
  if (duration <= .001) return 0
  const offset = boundedNumber(layer.animation.clipOffset, 0, 0, 3600)
  const speed = boundedNumber(layer.animation.clipSpeed, 1, .05, 8)
  const trimStart = boundedNumber(layer.animation.clipTrimStart, 0, 0, Math.max(0, duration - .001))
  const trimEnd = boundedNumber(layer.animation.clipTrimEnd, duration, trimStart + .001, duration)
  const span = Math.max(.001, trimEnd - trimStart)
  const elapsed = Math.max(0, sceneSeconds - offset) * speed
  const local = layer.animation.clipLoop === false ? Math.min(span, elapsed) : elapsed % span
  return layer.animation.clipReverse ? trimEnd - local : trimStart + local
}
