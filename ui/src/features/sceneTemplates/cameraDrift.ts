import type { SceneKeyframe, SceneLayer } from '../../types'
import { evaluateSceneLayer } from '../../lib/sceneTimeline'
import { layer, type BuildContext } from './sceneBuilders'

/** Seconds between drift samples: dense enough that linear segments read as one smooth sway. */
const STEP = .5

/** The slow sway at `seconds` for drift 1: a few percent of the frame, one speed at any shot length. */
function sway(seconds: number) {
  const turn = (period: number) => 2 * Math.PI * seconds / period
  return {
    x: -4 * Math.cos(turn(8)),
    y: 1.5 * Math.sin(turn(11)),
    scale: .03 + .03 * (1 - Math.cos(turn(10))) / 2,
    rotation: .6 * Math.sin(turn(13)),
  }
}

function sampleTimes(item: SceneLayer, duration: number): number[] {
  const steps = Math.max(8, Math.ceil(duration / STEP))
  const own = (item.animation.keyframes ?? []).map(frame => frame.time)
  return [...new Set([...Array.from({ length: steps + 1 }, (_, index) => duration * index / steps), ...own])]
    .filter(time => time >= 0 && time <= duration)
    .sort((a, b) => a - b)
}

/** Adds the sway to the camera the card built, sampled with its own easing so a push or a beat keeps its shape. */
function drifted(item: SceneLayer, amount: number, duration: number): SceneLayer {
  const frames: SceneKeyframe[] = sampleTimes(item, duration).map((time, index) => {
    const base = evaluateSceneLayer(item, time)
    const offset = sway(time)
    return {
      id: `camera-drift-${index}`, time, curve: 'linear', opacity: base.opacity,
      x: base.x + offset.x * amount, y: base.y + offset.y * amount,
      scale: base.scale + offset.scale * amount, rotation: base.rotation + offset.rotation * amount,
    }
  })
  const endpoint = (frame: SceneKeyframe) => ({ ...item.transform, x: frame.x, y: frame.y, scale: frame.scale, rotation: frame.rotation, opacity: frame.opacity })
  return { ...item, animation: { ...item.animation, keyframes: frames, start: endpoint(frames[0]), end: endpoint(frames[frames.length - 1]) } }
}

/**
 * Every music card and choreography has a camera layer with a slow drift (control `drift`, 0–1), so no shot holds a
 * frozen frame (owner rule). Drift 0 keeps the card's own camera, or a still camera layer the user can animate.
 */
export function withCameraDrift(layers: SceneLayer[], ctx: BuildContext): SceneLayer[] {
  if (!('drift' in ctx.options)) return layers
  const amount = Number(ctx.options.drift)
  const index = layers.findIndex(item => item.type === 'camera')
  const current = index >= 0 ? layers[index] : layer('camera', 'camera', '', ctx.duration, {}, 100)
  const next = amount > 0 ? drifted(current, amount, ctx.duration) : current
  return index >= 0 ? layers.map((item, at) => at === index ? next : item) : [...layers, next]
}
