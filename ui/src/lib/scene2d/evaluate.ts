// Pure Video 2D layer evaluation: timing, relationships, orbits, camera and strips.
// Extracted from the Scene Animator so preview, browser export and the headless
// scene2d renderer compute identical states for the same document and time.
import { evaluateSceneLayer, getSceneLayerTiming, sceneLayerMotionProgress, sceneTimeToLayerTime } from '../sceneTimeline'
import { boundedNumber, isVisualLayer, normalizedStrip, stripOffsets } from './layerStyle'
import { applyBeatPulse, applyScenePath, beatEnvelope } from './motion'
import type { AnimatorLayer, AnimatorScene, LayerState } from './types'

export type SceneEvaluator = ReturnType<typeof createSceneEvaluator>

/** Shift the drawn box so `focus` stays on the anchor. 50,50 and a missing focus are no-ops. */
function pinFocus(scene: AnimatorScene, layer: AnimatorLayer, state: LayerState): LayerState {
  const focus = layer.focus
  if (!focus || layer.type === 'camera' || layer.type === 'effect') return state
  const boxX = layer.type === 'model3d' ? .52 : 1
  const boxY = layer.type === 'model3d' ? .75 : 1
  const ox = (focus.x - 50) / 100 * scene.width * boxX * state.scale
  const oy = (focus.y - 50) / 100 * scene.height * boxY * state.scale
  const theta = state.rotation * Math.PI / 180
  const cos = Math.cos(theta)
  const sin = Math.sin(theta)
  return {
    ...state,
    x: state.x - (cos * ox - sin * oy) / scene.width * 100,
    y: state.y - (sin * ox + cos * oy) / scene.height * 100,
  }
}

/** `time` is scene progress in [0, 1], as used by the animator timeline. */
export function createSceneEvaluator(scene: AnimatorScene) {
  const baseLayerState = (layer: AnimatorLayer, time: number): LayerState => {
    const seconds = time * scene.duration
    const state = applyScenePath({ ...evaluateSceneLayer(layer, sceneTimeToLayerTime(layer, seconds)), z: layer.z }, layer, layer.animation.duration > 0 ? sceneLayerMotionProgress(layer, seconds) : time)
    const pulse = layer.beatPulse
    return pulse ? applyBeatPulse(state, pulse.amount, beatEnvelope(scene.rhythm, seconds, pulse.on)) : state
  }
  const activeCameraLayer = () => [...scene.layers].filter(layer => layer.type === 'camera' && layer.visible).sort((a, b) => b.z - a.z)[0]
  const cameraState = (time: number): LayerState => {
    const camera = activeCameraLayer()
    return camera ? layerState(camera, time) : { x: 50, y: 50, scale: 1, opacity: 1, rotation: 0, z: 0 }
  }
  const applyCameraTransform = (state: LayerState, layer: AnimatorLayer, time: number): LayerState => {
    const camera = activeCameraLayer()
    if (!camera || layer.type === 'camera' || layer.type === 'effect') return state
    const view = layerState(camera, time)
    const parallax = effectiveParallax(layer)
    const dx = state.x - 50 - (view.x - 50) * parallax
    const dy = state.y - 50 - (view.y - 50) * parallax
    const radians = view.rotation * Math.PI / 180
    const cos = Math.cos(radians); const sin = Math.sin(radians)
    const zoom = Math.max(.05, view.scale)
    const aspect = scene.width / Math.max(1, scene.height)
    return {
      ...state,
      // Rotate in scene pixels rather than percent-space so portrait and
      // landscape shots keep a physically correct camera roll.
      x: 50 + (dx * cos + dy / aspect * sin) * zoom,
      y: 50 + (-dx * aspect * sin + dy * cos) * zoom,
      scale: state.scale * zoom,
      rotation: state.rotation - view.rotation,
    }
  }
  function effectiveParallax(layer: AnimatorLayer, visited = new Set<string>()): number {
    if (visited.has(layer.id)) return layer.parallax ?? 1
    const nextVisited = new Set(visited); nextVisited.add(layer.id)
    const targetId = layer.relationship?.targetLayerId ?? layer.animation.orbit?.targetLayerId
    const target = targetId && scene.layers.find(item => item.id === targetId)
    return target && isVisualLayer(target) ? effectiveParallax(target, nextVisited) : layer.parallax ?? 1
  }
  // Parent/follow/lookAt relationship relative to an already evaluated target.
  function relatedState(state: LayerState, relationship: NonNullable<AnimatorLayer['relationship']>, target: AnimatorLayer, time: number, visited: Set<string>, applyShake: boolean): LayerState {
    const targetState = layerState(target, time, visited, applyShake)
    if (relationship.type === 'parent') {
      const targetOrigin = layerState(target, 0, visited, applyShake)
      const scaleRatio = targetState.scale / Math.max(.01, targetOrigin.scale)
      const angle = (targetState.rotation - targetOrigin.rotation) * Math.PI / 180
      const relativeX = (state.x - targetOrigin.x) * scene.width
      const relativeY = (state.y - targetOrigin.y) * scene.height
      const rotatedX = (relativeX * Math.cos(angle) - relativeY * Math.sin(angle)) * scaleRatio
      const rotatedY = (relativeX * Math.sin(angle) + relativeY * Math.cos(angle)) * scaleRatio
      return {
        ...state,
        x: targetState.x + rotatedX / scene.width,
        y: targetState.y + rotatedY / scene.height,
        scale: state.scale * scaleRatio,
        rotation: state.rotation + targetState.rotation - targetOrigin.rotation,
      }
    }
    if (relationship.type === 'follow') {
      const strength = Math.max(0, Math.min(1, relationship.strength ?? 1))
      const targetX = targetState.x + (relationship.offsetX ?? 0)
      const targetY = targetState.y + (relationship.offsetY ?? 0)
      return { ...state, x: state.x + (targetX - state.x) * strength, y: state.y + (targetY - state.y) * strength }
    }
    const dx = (targetState.x - state.x) * scene.width
    const dy = (targetState.y - state.y) * scene.height
    return { ...state, rotation: Math.atan2(dy, dx) * 180 / Math.PI + (relationship.rotationOffset ?? 0) }
  }
  function orbitState(state: LayerState, layer: AnimatorLayer, target: AnimatorLayer, time: number, visited: Set<string>, applyShake: boolean): LayerState {
    const orbit = layer.animation.orbit!
    const targetState = layerState(target, time, visited, applyShake)
    const orbitProgress = sceneLayerMotionProgress(layer, time * scene.duration)
    const angle = orbit.phase * Math.PI / 180 + orbitProgress * orbit.turns * Math.PI * 2
    const depth = Math.sin(angle)
    const centerX = targetState.x + (orbit.centerOffsetX ?? 0)
    const centerY = targetState.y + (orbit.centerOffsetY ?? 0)
    return { ...state, x: centerX + Math.cos(angle) * orbit.radiusX, y: centerY + depth * orbit.radiusY, scale: state.scale * (1 + depth * .12), z: target.z + (depth >= 0 ? 1 : -1) }
  }
  // Deterministic camera shake inside the layer's active local window.
  function shakenState(state: LayerState, layer: AnimatorLayer, time: number): LayerState {
    const shake = layer.animation.shake!
    const amount = Math.max(0, Math.min(8, shake.amount))
    const frequency = Math.max(.1, Math.min(30, shake.frequency))
    const sceneSeconds = time * scene.duration
    const timing = getSceneLayerTiming(layer)
    const elapsed = Math.max(0, sceneSeconds - timing.offset) * timing.speed
    if (sceneSeconds < timing.offset || (!timing.loop && elapsed > timing.span)) return state
    const localTime = sceneTimeToLayerTime(layer, sceneSeconds)
    const shakeStart = shake.startTime ?? timing.trimStart
    const shakeEnd = shake.endTime ?? timing.trimEnd
    if (localTime < shakeStart || localTime > shakeEnd) return state
    const phase = (localTime - shakeStart) * frequency * Math.PI * 2 + (shake.seed ?? 0)
    return { ...state, x: state.x + Math.sin(phase) * amount, y: state.y + Math.sin(phase * 1.37 + 1.2) * amount * .65, rotation: state.rotation + Math.sin(phase * .73 + .4) * amount * .35 }
  }
  function layerState(layer: AnimatorLayer, time: number, visited = new Set<string>(), applyShake = true): LayerState {
    let state = baseLayerState(layer, time)
    if (visited.has(layer.id)) return state
    const nextVisited = new Set(visited); nextVisited.add(layer.id)
    const relationship = layer.relationship
    const relationshipTarget = relationship && scene.layers.find(item => item.id === relationship.targetLayerId)
    if (relationship && relationshipTarget && isVisualLayer(relationshipTarget) && !nextVisited.has(relationshipTarget.id)) {
      state = relatedState(state, relationship, relationshipTarget, time, nextVisited, applyShake)
    }
    const orbit = layer.animation.orbit
    const target = orbit && scene.layers.find(item => item.id === orbit.targetLayerId)
    if (orbit && target && isVisualLayer(target) && target.id !== layer.id && !nextVisited.has(target.id)) {
      state = orbitState(state, layer, target, time, nextVisited, applyShake)
    }
    if (applyShake && layer.type === 'camera' && layer.animation.shake?.amount) state = shakenState(state, layer, time)
    return state
  }
  const renderedLayerStates = (layer: AnimatorLayer, time: number) => {
    const orbitCount = layer.animation.orbit ? Math.round(boundedNumber(layer.animation.orbit.count, 1, 1, 12)) : 1
    const offsets = stripOffsets(layer, time * scene.duration)
    const instances: LayerState[] = []
    for (let orbitIndex = 0; orbitIndex < orbitCount; orbitIndex += 1) {
      const orbit = layer.animation.orbit
      const instanceLayer = orbit && orbitCount > 1 ? { ...layer, animation: { ...layer.animation, orbit: { ...orbit, phase: orbit.phase + orbitIndex * 360 / orbitCount } } } : layer
      let orbitState = layerState(instanceLayer, time)
      if (layer.type === 'model3d' && layer.animation.spin) {
        const timing = getSceneLayerTiming(layer)
        const localSeconds = sceneTimeToLayerTime(layer, time * scene.duration) - timing.trimStart
        orbitState = { ...orbitState, modelYaw: localSeconds * (layer.animation.rotationSpeed ?? 35) }
      }
      for (const offset of offsets) {
        let state = { ...orbitState, x: orbitState.x + offset.x, y: orbitState.y + offset.y }
        if (orbit && orbit.facing && orbit.facing !== 'fixed') {
          const target = scene.layers.find(item => item.id === orbit.targetLayerId)
          if (target && isVisualLayer(target)) {
            const targetState = layerState(target, time)
            const centerX = targetState.x + (orbit.centerOffsetX ?? 0)
            const centerY = targetState.y + (orbit.centerOffsetY ?? 0)
            const angle = Math.atan2((centerY - state.y) * scene.height, (centerX - state.x) * scene.width) * 180 / Math.PI
            const facingAngle = angle + (orbit.facing === 'outward' ? 180 : 0)
            state = layer.type === 'model3d'
              ? { ...state, modelYaw: facingAngle }
              : { ...state, rotation: facingAngle }
          }
        }
        instances.push(pinFocus(scene, layer, applyCameraTransform(state, layer, time)))
      }
    }
    // Each 3D copy is a live WebGL context. orbit(12) × strip(12) = 144
    // viewers, which locks the GPU and can freeze the host.
    const cap = layer.type === 'model3d' ? 4 : 24
    return instances.slice(0, cap)
  }
  const seamCoverStates = (layer: AnimatorLayer, time: number) => {
    const strip = normalizedStrip(layer.strip)
    if (!strip.enabled || !strip.seamOccluder.enabled) return []
    const offsets = stripOffsets({ ...layer, strip: { ...strip, phase: strip.phase + strip.spacing / 2 } }, time * scene.duration)
    const base = layerState(layer, time)
    return offsets.map(offset => applyCameraTransform({
      ...base,
      x: base.x + offset.x,
      y: 82,
      scale: strip.seamOccluder.scale,
      opacity: Math.min(1, base.opacity * strip.seamOccluder.opacity),
    }, layer, time))
  }
  return { baseLayerState, activeCameraLayer, cameraState, applyCameraTransform, effectiveParallax, layerState, renderedLayerStates, seamCoverStates }
}
