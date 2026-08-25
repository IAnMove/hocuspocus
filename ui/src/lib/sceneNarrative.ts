import type { Scene, SceneCurve, SceneKeyframe, SceneLayer, SceneLayerType } from '../types'

export type NarrativeSceneId =
  | 'inner-thought'
  | 'hero-arrival'
  | 'character-turntable'
  | 'silent-reaction'
  | 'dream-orbit'
  | 'portal-arrival'
  | 'icon-reveal'
  | 'place-establishing'
  | 'memory-drift'
  | 'surreal-transit'
  | 'run-travel-parallax'

export type NarrativeAssetSlot = {
  id: 'hero' | 'plate' | 'prop' | 'foreground'
  label: string
  types: SceneLayerType[]
  required: boolean
}

export type NarrativeSceneTemplate = {
  id: NarrativeSceneId
  title: string
  description: string
  defaultDuration: 10 | 12
  assetSlots: NarrativeAssetSlot[]
  controls: Array<'mood' | 'intensity' | 'direction' | 'camera' | 'palette' | 'voiceSpace'>
  experimental?: boolean
}

export type NarrativeTemplateInput = {
  hero?: { source: string; type?: Extract<SceneLayerType, 'model3d' | 'image' | 'video'>; name?: string }
  plate?: { source: string; type?: Extract<SceneLayerType, 'model3d' | 'image' | 'video'>; name?: string }
  prop?: { source: string; type?: Extract<SceneLayerType, 'model3d' | 'image' | 'video'>; name?: string }
  foreground?: { source: string; type?: Extract<SceneLayerType, 'model3d' | 'image' | 'video'>; name?: string }
  width?: number
  height?: number
  fps?: 30 | 60
  duration?: number
}

type MotionPoint = Pick<SceneKeyframe, 'x' | 'y' | 'scale' | 'opacity' | 'rotation'>

const at = (id: string, time: number, point: MotionPoint, curve: SceneCurve = 'ease'): SceneKeyframe => ({ id, time, curve, ...point })
const point = (x: number, y: number, scale: number, opacity = 1, rotation = 0): MotionPoint => ({ x, y, scale, opacity, rotation })
const durationOf = (input: NarrativeTemplateInput, fallback: 10 | 12) => Math.max(10, Math.min(60, input.duration ?? fallback))

/** A deterministic triangle oscillator. `time` is always scene time in seconds. */
export const sceneTriangleWave = (time: number, frequency: number, phase = 0) => {
  const cycle = ((time * frequency + phase) % 1 + 1) % 1
  return 1 - Math.abs(cycle * 4 - 2)
}

/** Deterministic wave useful for preview, export and long-lived template motion. */
export const sceneSineWave = (time: number, frequency: number, phase = 0) => Math.sin((time * frequency + phase) * Math.PI * 2)

/**
 * Builds three or more motion points over the full duration. This deliberately
 * avoids the common two-point ease that appears to stop long before a 10s clip
 * has ended.
 */
export const buildDriftKeyframes = (
  id: string,
  duration: number,
  start: MotionPoint,
  end: MotionPoint,
  options: { bob?: number; pulse?: number; rotation?: number; curve?: SceneCurve } = {},
): SceneKeyframe[] => {
  const steps = Math.max(4, Math.ceil(duration / 2))
  const curve = options.curve ?? 'ease'
  return Array.from({ length: steps + 1 }, (_, index) => {
    const progress = index / steps
    const wave = sceneSineWave(progress, Math.max(1, steps / 2))
    return at(`${id}-${index}`, duration * progress, point(
      start.x + (end.x - start.x) * progress,
      start.y + (end.y - start.y) * progress + wave * (options.bob ?? 0),
      start.scale + (end.scale - start.scale) * progress + wave * (options.pulse ?? 0),
      start.opacity + (end.opacity - start.opacity) * progress,
      start.rotation + (end.rotation - start.rotation) * progress + wave * (options.rotation ?? 0),
    ), curve)
  })
}

const defaults = (duration: number, start: MotionPoint, end: MotionPoint, keyframes?: SceneKeyframe[]): SceneLayer['animation'] => ({
  start,
  end,
  keyframes,
  duration,
  curve: 'ease',
  offset: 0,
  speed: 1,
  loop: false,
  trimStart: 0,
  trimEnd: duration,
  spin: false,
})

const baseLayer = (id: string, name: string, type: SceneLayerType, source: string, z: number, duration: number, start: MotionPoint, end = start, extras: Partial<SceneLayer> = {}): SceneLayer => ({
  id,
  name,
  type,
  source,
  visible: true,
  z,
  fill: type === 'image' || type === 'video',
  parallax: type === 'camera' ? undefined : 1,
  transform: { x: end.x, y: end.y, scale: end.scale, opacity: end.opacity, rotation: end.rotation },
  animation: defaults(duration, start, end),
  ...extras,
})

const plateLayer = (input: NarrativeTemplateInput, duration: number, id = 'plate', parallax = 0) => {
  const source = input.plate?.source ?? ''
  return baseLayer(id, input.plate?.name ?? 'Environment', input.plate?.type ?? 'image', source, 0, duration, point(50, 50, 1), point(50, 50, 1.06), {
    fill: true,
    parallax,
    effects: { brightness: .72, saturation: 1.06, contrast: 1.04 },
  })
}

const heroLayer = (input: NarrativeTemplateInput, duration: number, start: MotionPoint, end: MotionPoint, extras: Partial<SceneLayer> = {}) => {
  const type = input.hero?.type ?? 'model3d'
  const layer = baseLayer('hero', input.hero?.name ?? 'Hero', type, input.hero?.source ?? '', 10, duration, start, end, {
    fill: false,
    parallax: 1,
    effects: { glow: 0, brightness: 1, saturation: 1, contrast: 1 },
    ...extras,
  })
  return layer
}

const cameraLayer = (duration: number, start: MotionPoint, end: MotionPoint, keyframes?: SceneKeyframe[]) => baseLayer('camera', 'Camera', 'camera', '', 20, duration, start, end, {
  animation: { ...defaults(duration, start, end, keyframes), keyframes },
})

export const NARRATIVE_SCENE_TEMPLATES: NarrativeSceneTemplate[] = [
  { id: 'inner-thought', title: 'Inner thought', description: 'Space for a voice-over and a contemplative drifting subject.', defaultDuration: 10, assetSlots: [{ id: 'hero', label: 'Character', types: ['model3d', 'image', 'video'], required: true }, { id: 'plate', label: 'Background', types: ['image', 'video'], required: true }], controls: ['mood', 'intensity', 'voiceSpace', 'camera'] },
  { id: 'hero-arrival', title: 'Hero arrival', description: 'An entrance that settles into a living pose.', defaultDuration: 12, assetSlots: [{ id: 'hero', label: 'Character', types: ['model3d', 'image', 'video'], required: true }, { id: 'plate', label: 'Background', types: ['image', 'video'], required: true }], controls: ['intensity', 'direction', 'camera'] },
  { id: 'character-turntable', title: 'Character presentation', description: 'A controlled silhouette and costume reveal.', defaultDuration: 10, assetSlots: [{ id: 'hero', label: 'Character', types: ['model3d', 'image', 'video'], required: true }, { id: 'plate', label: 'Background', types: ['image', 'video'], required: true }], controls: ['direction', 'palette', 'camera'] },
  { id: 'silent-reaction', title: 'Silent reaction', description: 'A restrained visual beat for listening or resolve.', defaultDuration: 10, assetSlots: [{ id: 'hero', label: 'Character', types: ['model3d', 'image', 'video'], required: true }, { id: 'plate', label: 'Background', types: ['image', 'video'], required: true }], controls: ['mood', 'intensity', 'camera'] },
  { id: 'dream-orbit', title: 'Dream orbit', description: 'An arcing, luminous internal-world shot.', defaultDuration: 12, assetSlots: [{ id: 'hero', label: 'Character', types: ['model3d', 'image', 'video'], required: true }, { id: 'plate', label: 'Background', types: ['image', 'video'], required: true }], controls: ['mood', 'intensity', 'palette', 'camera'] },
  { id: 'portal-arrival', title: 'Portal / invocation', description: 'A character reveal with a magical or sci-fi prop.', defaultDuration: 12, assetSlots: [{ id: 'hero', label: 'Character', types: ['model3d', 'image', 'video'], required: true }, { id: 'prop', label: 'Portal or prop', types: ['model3d', 'image', 'video'], required: true }, { id: 'plate', label: 'Background', types: ['image', 'video'], required: true }], controls: ['intensity', 'palette', 'camera'] },
  { id: 'icon-reveal', title: 'Iconic object reveal', description: 'A relic, weapon or product-like insert.', defaultDuration: 10, assetSlots: [{ id: 'prop', label: 'Object', types: ['model3d', 'image', 'video'], required: true }, { id: 'plate', label: 'Background', types: ['image', 'video'], required: true }], controls: ['intensity', 'palette', 'camera'] },
  { id: 'place-establishing', title: 'Establishing location', description: 'A location is discovered through parallax and atmosphere.', defaultDuration: 12, assetSlots: [{ id: 'plate', label: 'Environment', types: ['image', 'video'], required: true }, { id: 'prop', label: 'Optional landmark', types: ['model3d', 'image', 'video'], required: false }], controls: ['mood', 'direction', 'camera'] },
  { id: 'memory-drift', title: 'Memory / flashback', description: 'A slow visual recollection with a changing grade.', defaultDuration: 10, assetSlots: [{ id: 'hero', label: 'Character or object', types: ['model3d', 'image', 'video'], required: true }, { id: 'plate', label: 'Background', types: ['image', 'video'], required: true }], controls: ['mood', 'palette', 'voiceSpace'] },
  { id: 'surreal-transit', title: 'Surreal transit', description: 'Independent subject and world movement for journeys.', defaultDuration: 12, assetSlots: [{ id: 'hero', label: 'Character', types: ['model3d', 'image', 'video'], required: true }, { id: 'plate', label: 'Background', types: ['image', 'video'], required: true }, { id: 'foreground', label: 'Optional foreground', types: ['image', 'video'], required: false }], controls: ['intensity', 'direction', 'palette', 'camera'] },
  { id: 'run-travel-parallax', title: 'Run / travel parallax', description: 'A stylised movement illusion; it does not invent a running rig.', defaultDuration: 12, assetSlots: [{ id: 'hero', label: 'Running-pose character', types: ['model3d', 'image', 'video'], required: true }, { id: 'plate', label: 'Seamless background', types: ['image', 'video'], required: true }, { id: 'foreground', label: 'Optional foreground strip', types: ['image', 'video'], required: false }], controls: ['intensity', 'direction', 'camera'], experimental: true },
]

export const getNarrativeTemplate = (id: NarrativeSceneId) => NARRATIVE_SCENE_TEMPLATES.find(template => template.id === id)

const withKeyframes = (layer: SceneLayer, keyframes: SceneKeyframe[]) => ({
  ...layer,
  animation: { ...layer.animation, start: keyframes[0], end: keyframes[keyframes.length - 1], keyframes },
})

/** Produces only ordinary, directly editable Scene Animator layers. */
export const createNarrativeScene = (id: NarrativeSceneId, input: NarrativeTemplateInput): Scene => {
  const template = getNarrativeTemplate(id)
  if (!template) throw new Error(`Unknown narrative scene template: ${id}`)
  const duration = durationOf(input, template.defaultDuration)
  const plate = plateLayer(input, duration)
  let layers: SceneLayer[]

  if (id === 'inner-thought') {
    const hero = heroLayer(input, duration, point(63, 56, .88), point(68, 53, .96), { effects: { glow: 1.1, brightness: 1, saturation: .92, contrast: 1 } })
    layers = [withKeyframes(hero, buildDriftKeyframes('hero-thought', duration, point(63, 56, .88), point(68, 53, .96), { bob: .7, pulse: .012, rotation: .45 })), plate, cameraLayer(duration, point(48, 51, 1), point(52, 49, 1.035), buildDriftKeyframes('camera-thought', duration, point(48, 51, 1), point(52, 49, 1.035), { bob: .12 }))]
  } else if (id === 'hero-arrival') {
    const hero = heroLayer(input, duration, point(50, 66, .25, 0), point(50, 52, 1.06), { effects: { glow: .35, brightness: 1.04, saturation: 1.06, contrast: 1.04 } })
    layers = [plate, withKeyframes(hero, [at('hero-arrival-0', 0, point(50, 66, .25, 0), 'dramatic'), at('hero-arrival-1', duration * .32, point(50, 55, .86, 1), 'ease'), at('hero-arrival-2', duration * .68, point(50, 52, 1.04, 1), 'ease'), at('hero-arrival-3', duration, point(50, 53, 1.06, 1), 'ease')]), cameraLayer(duration, point(50, 51, .99), point(50, 49, 1.065), buildDriftKeyframes('camera-arrival', duration, point(50, 51, .99), point(50, 49, 1.065), { bob: .08 }))]
  } else if (id === 'dream-orbit') {
    const hero = heroLayer(input, duration, point(42, 57, .84, .25, -7), point(57, 48, 1.05, 1, 7), { parallax: 1.3, effects: { glow: 1.5, brightness: 1.08, saturation: 1.12, contrast: 1 } })
    layers = [withKeyframes(plate, buildDriftKeyframes('plate-dream', duration, point(50, 50, 1), point(50, 50, 1.08), { bob: .1 })), withKeyframes(hero, buildDriftKeyframes('hero-dream', duration, point(42, 57, .84, .25, -7), point(57, 48, 1.05, 1, 7), { bob: 1, pulse: .018, rotation: 1.5 })), cameraLayer(duration, point(46, 54, 1, 1, -1.5), point(54, 46, 1.08, 1, 1.5), buildDriftKeyframes('camera-dream', duration, point(46, 54, 1, 1, -1.5), point(54, 46, 1.08, 1, 1.5), { bob: .2, rotation: .25 }))]
  } else {
    const subjectInput = id === 'icon-reveal' ? input.prop : input.hero
    const subject = heroLayer({ ...input, hero: subjectInput }, duration, point(50, 55, .72), point(50, 48, .86))
    if (id === 'character-turntable' || id === 'icon-reveal') subject.animation = { ...subject.animation, spin: true, rotationSpeed: id === 'icon-reveal' ? 18 : 12 }
    if (id === 'run-travel-parallax') {
      plate.strip = { enabled: true, count: 4, spacing: 100, direction: 'right', speed: 12, phase: 0 }
      const runner = withKeyframes(heroLayer(input, duration, point(38, 54, .88), point(39, 54, .9), { effects: { glow: .15, brightness: 1, saturation: 1.04, contrast: 1.08 } }), buildDriftKeyframes('hero-run', duration, point(38, 54, .88, 1, -2), point(39, 54, .9, 1, 2), { bob: .9, rotation: 1.5, curve: 'linear' }))
      const foreground = input.foreground?.source ? baseLayer('foreground', input.foreground.name ?? 'Foreground', input.foreground.type ?? 'image', input.foreground.source, 15, duration, point(50, 50, 1.3, .4), point(50, 50, 1.3, .4), { fill: true, parallax: 1.7, strip: { enabled: true, count: 4, spacing: 100, direction: 'right', speed: 58, phase: 0 }, effects: { blur: .35 } }) : undefined
      layers = [plate, runner, ...(foreground ? [foreground] : []), cameraLayer(duration, point(50, 50, 1), point(50, 50, 1.018), buildDriftKeyframes('camera-run', duration, point(50, 50, 1), point(50, 50, 1.018), { bob: .05, curve: 'linear' }))]
    } else {
      layers = [plate, subject, cameraLayer(duration, point(49, 51, 1), point(51, 49, 1.04), buildDriftKeyframes('camera-generic', duration, point(49, 51, 1), point(51, 49, 1.04), { bob: .1 }))]
    }
  }

  return { version: 1, name: template.title, width: input.width ?? 1280, height: input.height ?? 720, fps: input.fps ?? 30, duration, layers, composition: { showGrid: false, gridSize: 10, snap: false, safeArea: 'none' } }
}
