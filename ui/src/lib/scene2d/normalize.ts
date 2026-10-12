// Pure Video 2D document normalization shared by the Scene Animator import and
// the headless scene2d renderer. Character-kit synchronization stays in the editor.
import { canonicalSceneFps } from '../sceneFps'
import { holdFields } from '../../features/stopMotion'
import { normalizeFaceBinding } from '../cutoutDialogue'
import { parseFinish } from './finish'
import { parseSceneFx } from '../../features/sceneFx/types'
import { lyricFields, parseKineticTexts } from '../kineticText'
import { parsePath, parseRhythm, parseSequence } from './motion'
import { getSceneLayerTiming, normalizeSceneEvents, normalizeSceneKeyframes, withNormalizedSceneTiming, withSceneKeyframes } from '../sceneTimeline'
import type { SceneCurve } from '../../types'
import { boundedNumber, finiteNumber, normalizedAtmosphere, normalizedEffects, normalizedStrip } from './layerStyle'
import type { AnimatorLayer, AnimatorLayerType, AnimatorScene } from './types'

export const isMissingSource = (source: string) => source.startsWith('blob:')
export const isAnimatorLayerType = (value: unknown): value is AnimatorLayerType => value === 'model3d' || value === 'image' || value === 'video' || value === 'overlay' || value === 'effect' || value === 'camera'
export const assignZ = (layers: AnimatorLayer[]) => layers.map((layer, index) => ({ ...layer, z: index * 10 }))
export const normalizeZ = (layers: AnimatorLayer[]) => assignZ([...layers].sort((a, b) => a.z - b.z))

export const dependencyTargets = (layer: AnimatorLayer) => [layer.relationship?.targetLayerId, layer.animation.orbit?.targetLayerId, layer.atmosphere?.emitter?.mode === 'layer' ? layer.atmosphere.emitter.targetLayerId : undefined].filter((id): id is string => Boolean(id))
export const dependencyWouldCycleIn = (layers: AnimatorLayer[], layerId: string, targetId: string) => {
  const pending = [targetId]
  const visited = new Set<string>()
  while (pending.length > 0) {
    const currentId = pending.pop()
    if (!currentId) continue
    if (currentId === layerId) return true
    if (visited.has(currentId)) continue
    visited.add(currentId)
    const current = layers.find(layer => layer.id === currentId)
    if (current) pending.push(...dependencyTargets(current))
  }
  return false
}
export const breakDependencyCycles = (layers: AnimatorLayer[]) => {
  let next = layers
  for (const candidate of layers) {
    const current = next.find(layer => layer.id === candidate.id)
    if (!current) continue
    if (current.relationship && dependencyWouldCycleIn(next, current.id, current.relationship.targetLayerId)) {
      next = next.map(layer => layer.id === current.id ? { ...layer, relationship: undefined } : layer)
    }
    const withRelationshipChecked = next.find(layer => layer.id === candidate.id)
    if (withRelationshipChecked?.animation.orbit && dependencyWouldCycleIn(next, withRelationshipChecked.id, withRelationshipChecked.animation.orbit.targetLayerId)) {
      next = next.map(layer => layer.id === withRelationshipChecked.id ? { ...layer, animation: { ...layer.animation, orbit: undefined } } : layer)
    }
  }
  return next
}
export function dropEmitterCycles(layers: AnimatorLayer[]) {
  let next = layers
  for (let pass = 0; pass < layers.length; pass += 1) {
    let changed = false
    next = next.map(layer => {
      const emitter = layer.atmosphere?.emitter
      if (emitter?.mode !== 'layer' || !emitter.targetLayerId || !dependencyWouldCycleIn(next, layer.id, emitter.targetLayerId)) return layer
      changed = true
      return { ...layer, atmosphere: { ...layer.atmosphere!, emitter: { ...emitter, mode: 'frame' } } }
    })
    if (!changed) return next
  }
  return next
}

type RawLayer = AnimatorLayer
type LayerContext = { visualIds: Set<string>; activeCameraId?: string; sceneDuration: unknown; isMissing: (source: string) => boolean }
type Transform = AnimatorLayer['transform'] & { rotation: number }
type Animation = AnimatorLayer['animation']

const finiteOr = (value: unknown, fallback: number) => typeof value === 'number' && Number.isFinite(value) ? value : fallback
const optionalSeconds = (value: unknown) => typeof value === 'number' && Number.isFinite(value) ? Math.max(0, Math.min(3600, value)) : undefined

function normalizeTransform(raw: RawLayer['transform'] | undefined): Transform {
  return {
    ...raw,
    x: finiteNumber(raw?.x, 50),
    y: finiteNumber(raw?.y, 50),
    scale: boundedNumber(raw?.scale, 1, .01, 20),
    opacity: boundedNumber(raw?.opacity, 1, 0, 1),
    rotation: finiteNumber(raw?.rotation, 0),
    rotationX: boundedNumber(raw?.rotationX, 75, 1, 179),
    rotationY: finiteNumber(raw?.rotationY, 0),
  }
}

function normalizeEndpoint(point: Partial<Animation['start']> | undefined, transform: Transform): Animation['start'] {
  return {
    x: finiteNumber(point?.x, transform.x),
    y: finiteNumber(point?.y, transform.y),
    scale: boundedNumber(point?.scale, transform.scale, .01, 20),
    opacity: boundedNumber(point?.opacity, transform.opacity, 0, 1),
    rotation: finiteNumber(point?.rotation, transform.rotation),
  }
}

function normalizeRelationship(raw: RawLayer, isCamera: boolean, visualIds: Set<string>): AnimatorLayer['relationship'] {
  const relationship = raw.relationship
  if (!relationship || !['parent', 'follow', 'lookAt'].includes(relationship.type)) return undefined
  if ((isCamera && relationship.type !== 'follow') || relationship.targetLayerId === raw.id || !visualIds.has(relationship.targetLayerId)) return undefined
  return {
    type: relationship.type,
    targetLayerId: relationship.targetLayerId,
    offsetX: finiteOr(relationship.offsetX, 0),
    offsetY: finiteOr(relationship.offsetY, 0),
    strength: Number.isFinite(relationship.strength) ? Math.max(0, Math.min(1, relationship.strength ?? 1)) : 1,
    rotationOffset: finiteOr(relationship.rotationOffset, 0),
  } as AnimatorLayer['relationship']
}

function normalizeShake(raw: Animation['shake'] | undefined, isCamera: boolean): Animation['shake'] {
  if (!isCamera || !raw || !Number.isFinite(raw.amount) || !Number.isFinite(raw.frequency)) return undefined
  return {
    amount: Math.max(0, Math.min(8, raw.amount)),
    frequency: Math.max(.1, Math.min(30, raw.frequency)),
    seed: finiteOr(raw.seed, 0),
    startTime: optionalSeconds(raw.startTime),
    endTime: optionalSeconds(raw.endTime),
  }
}

function normalizeOrbit(raw: RawLayer, isCamera: boolean, visualIds: Set<string>): Animation['orbit'] {
  const orbit = raw.animation?.orbit
  if (isCamera || !orbit || orbit.targetLayerId === raw.id || !visualIds.has(orbit.targetLayerId)) return undefined
  return {
    targetLayerId: orbit.targetLayerId,
    radiusX: boundedNumber(orbit.radiusX, 18, 0, 100),
    radiusY: boundedNumber(orbit.radiusY, 9, 0, 100),
    turns: boundedNumber(orbit.turns, 1, -20, 20),
    phase: boundedNumber(orbit.phase, 0, -360, 360),
    count: Math.round(boundedNumber(orbit.count, 1, 1, 12)),
    facing: ['fixed', 'center', 'outward'].includes(orbit.facing ?? '') ? orbit.facing as 'fixed' | 'center' | 'outward' : 'fixed',
    centerOffsetX: boundedNumber(orbit.centerOffsetX, 0, -100, 100),
    centerOffsetY: boundedNumber(orbit.centerOffsetY, 0, -100, 100),
  }
}

function normalizeModelClip(animation: Partial<Animation> | undefined, isModel: boolean): Partial<Animation> {
  if (!isModel) return { clip: undefined, clipOffset: undefined, clipSpeed: undefined, clipReverse: undefined, clipLoop: undefined, clipTrimStart: undefined, clipTrimEnd: undefined }
  const clipTrimStart = boundedNumber(animation?.clipTrimStart, 0, 0, 3600)
  const trimEnd = animation?.clipTrimEnd
  return {
    clip: typeof animation?.clip === 'string' && animation.clip.trim() ? animation.clip.trim().slice(0, 200) : undefined,
    clipOffset: boundedNumber(animation?.clipOffset, 0, 0, 3600),
    clipSpeed: boundedNumber(animation?.clipSpeed, 1, .05, 8),
    clipReverse: animation?.clipReverse === true,
    clipLoop: animation?.clipLoop !== false,
    clipTrimStart,
    clipTrimEnd: typeof trimEnd === 'number' && Number.isFinite(trimEnd) ? Math.max(clipTrimStart + .001, Math.min(3600, trimEnd)) : undefined,
  }
}

function normalizeTiming(animation: Partial<Animation> | undefined, sceneDuration: unknown, layerId: string) {
  const duration = boundedNumber(animation?.duration, finiteNumber(sceneDuration, 5), .1, 3600)
  const curve: SceneCurve = animation?.curve && ['linear', 'ease', 'dramatic', 'bounce', 'hold'].includes(animation.curve) ? animation.curve : 'linear'
  return { duration, curve, events: normalizeSceneEvents(animation?.events, duration, layerId) }
}

function normalizeVisuals(raw: RawLayer, isCamera: boolean, isEffect: boolean) {
  return {
    effects: isCamera ? undefined : normalizedEffects(raw.effects),
    strip: isCamera ? undefined : normalizedStrip(raw.strip),
    atmosphere: isEffect ? normalizedAtmosphere(raw.atmosphere) : undefined,
    parallax: isCamera ? undefined : typeof raw.parallax === 'number' && Number.isFinite(raw.parallax) ? Math.max(0, Math.min(2, raw.parallax)) : 1,
  }
}

/** ``parallaxZoom`` is kept only as ``true`` on a visual layer; anything else is dropped. */
function parallaxZoomField(raw: RawLayer, isCamera: boolean): { parallaxZoom?: true } {
  return !isCamera && raw.parallaxZoom === true ? { parallaxZoom: true } : {}
}

const VIDEO_LOOPS = ['loop', 'hold', 'pingpong'] as const

/** ``playback`` is kept only on a video layer, bounded like ``series_layers`` (start 0–3600 s, speed 0.1–4). */
function playbackField(raw: RawLayer): { playback?: AnimatorLayer['playback'] } {
  const value = raw.playback
  if (raw.type !== 'video' || !value || typeof value !== 'object') return {}
  const loop = VIDEO_LOOPS.find(item => item === value.loop) ?? 'loop'
  return { playback: { start: boundedNumber(value.start, 0, 0, 3600), loop, speed: boundedNumber(value.speed, 1, .1, 4) } }
}

function layerPath(rawLayer: RawLayer) {
  const path = parsePath(rawLayer.animation?.path)
  return path ? { path } : {}
}

function layerExtras(rawLayer: RawLayer) {
  const sequence = parseSequence(rawLayer.sequence)
  const pulse = rawLayer.beatPulse
  const beatPulse = pulse && Number.isFinite(pulse.amount)
    ? { amount: Math.max(0, Math.min(1, pulse.amount)), on: pulse.on === 'downbeats' ? 'downbeats' as const : 'beats' as const }
    : undefined
  return { ...(sequence ? { sequence } : {}), ...(beatPulse ? { beatPulse } : {}) }
}

function layerWithoutFocus(raw: RawLayer): Omit<RawLayer, 'focus' | 'parallaxZoom' | 'playback'> {
  const rest = { ...raw }
  delete rest.focus
  delete rest.parallaxZoom
  delete rest.playback
  return rest
}

function focusFields(raw: RawLayer): { focus?: { x: number; y: number } } {
  const focus = raw.focus
  if (!focus || typeof focus.x !== 'number' || typeof focus.y !== 'number') return {}
  if (!Number.isFinite(focus.x) || !Number.isFinite(focus.y)) return {}
  return { focus: { x: Math.max(0, Math.min(100, focus.x)), y: Math.max(0, Math.min(100, focus.y)) } }
}

function normalizeLayer(rawLayer: RawLayer, context: LayerContext): AnimatorLayer {
  if (!isAnimatorLayerType((rawLayer as { type?: unknown }).type)) throw new Error(`Unsupported scene layer type: ${String((rawLayer as { type?: unknown }).type ?? 'missing')}`)
  const isCamera = rawLayer.type === 'camera'
  const isEffect = rawLayer.type === 'effect'
  const transform = normalizeTransform(rawLayer.transform)
  const source = String(rawLayer.source ?? '')
  const layer = {
    ...layerWithoutFocus(rawLayer),
    name: typeof rawLayer.name === 'string' && rawLayer.name.trim() ? rawLayer.name : `Layer ${rawLayer.id}`,
    source: isCamera ? '' : source,
    visible: isCamera ? rawLayer.id === context.activeCameraId : rawLayer.visible !== false,
    locked: rawLayer.locked === true,
    faceBinding: normalizeFaceBinding(rawLayer.faceBinding),
    relationship: normalizeRelationship(rawLayer, isCamera, context.visualIds),
    ...normalizeVisuals(rawLayer, isCamera, isEffect),
    ...parallaxZoomField(rawLayer, isCamera),
    transform,
    animation: {
      ...rawLayer.animation,
      start: normalizeEndpoint(rawLayer.animation?.start, transform),
      end: normalizeEndpoint(rawLayer.animation?.end, transform),
      keyframes: undefined,
      ...normalizeTiming(rawLayer.animation, context.sceneDuration, rawLayer.id),
      ...normalizeModelClip(rawLayer.animation, rawLayer.type === 'model3d'),
      shake: normalizeShake(rawLayer.animation?.shake, isCamera),
      orbit: normalizeOrbit(rawLayer, isCamera, context.visualIds),
      ...layerPath(rawLayer),
    },
    missingAsset: isCamera || isEffect ? false : Boolean(rawLayer.missingAsset || !source.trim() || context.isMissing(source)),
    ...layerExtras(rawLayer),
    ...focusFields(rawLayer),
    ...playbackField(rawLayer),
  } as AnimatorLayer
  const timedLayer = withNormalizedSceneTiming(layer) as AnimatorLayer
  const keyframes = normalizeSceneKeyframes(rawLayer.animation?.keyframes, timedLayer)
  return keyframes ? withSceneKeyframes(timedLayer, keyframes, timedLayer.animation.duration) as AnimatorLayer : timedLayer
}

/** Validate ids and normalize every layer exactly like the editor import. */
export function normalizeScene2DLayers(incoming: AnimatorScene, isMissing: (source: string) => boolean = isMissingSource): { width: number; height: number; layers: AnimatorLayer[] } {
  const incomingIds = incoming.layers.map((layer, index) => {
    const id = (layer as { id?: unknown } | null)?.id
    if (typeof id !== 'string' || !id.trim()) throw new Error(`Layer ${index + 1} needs a valid id.`)
    return id
  })
  if (new Set(incomingIds).size !== incomingIds.length) throw new Error('Every scene layer must have a unique id.')
  const width = Math.round(boundedNumber(incoming.width, 1280, 64, 7680))
  const height = Math.round(boundedNumber(incoming.height, 720, 64, 7680))
  const context: LayerContext = {
    visualIds: new Set(incoming.layers.filter(layer => layer && layer.type !== 'camera').map(layer => layer.id)),
    activeCameraId: [...incoming.layers].filter(layer => layer.type === 'camera' && layer.visible).sort((a, b) => (b.z ?? 0) - (a.z ?? 0))[0]?.id,
    sceneDuration: incoming.duration,
    isMissing,
  }
  return { width, height, layers: normalizeZ(incoming.layers.map(layer => normalizeLayer(layer, context))) }
}

/** Full headless normalization: layers, bounded size/fps/duration, texts and SFX. */
export function normalizeScene2D(raw: unknown): AnimatorScene {
  const incoming = raw as AnimatorScene
  if (!incoming || typeof incoming !== 'object' || incoming.version !== 1 || !Array.isArray(incoming.layers)) throw new Error('Use a version 1 Video 2D scene with layers.')
  const { width, height, layers: normalized } = normalizeScene2DLayers(incoming)
  const layers = dropEmitterCycles(breakDependencyCycles(normalized))
  const duration = Math.min(3600, Math.max(.1, Number.isFinite(incoming.duration) ? incoming.duration : 5, ...layers.map(layer => { const timing = getSceneLayerTiming(layer); return timing.offset + timing.span / timing.speed })))
  const finish = parseFinish(incoming.finish)
  const rhythm = parseRhythm(incoming.rhythm)
  // Same cue parser as the editor: catalog colour and bounded fields. Painters
  // call addColorStop(cue.color) and failed on cues saved without a colour.
  const sfx = parseSceneFx(incoming.sfx)
  const hold = holdFields(incoming.motionStep, incoming.stopMotionJitter)
  const scene: AnimatorScene = { ...incoming, sfx: sfx.length ? sfx : undefined, texts: parseKineticTexts(incoming.texts), ...lyricFields(incoming.lyrics), ...(finish ? { finish } : {}), ...(rhythm ? { rhythm } : {}), ...hold, name: typeof incoming.name === 'string' && incoming.name.trim() ? incoming.name : 'Scene', width, height, fps: canonicalSceneFps(incoming.fps), duration, layers }
  if (!hold.motionStep) delete scene.motionStep
  if (!hold.stopMotionJitter) delete scene.stopMotionJitter
  return scene
}
