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
  controls?: NarrativeSceneControls
}

export type NarrativeSceneControls = {
  mood?: 'calm' | 'tense' | 'dreamy' | 'heroic'
  intensity?: 1 | 2 | 3
  direction?: 'left' | 'right'
  camera?: 'restrained' | 'push' | 'drift'
  palette?: 'natural' | 'cool' | 'warm' | 'neon'
  voiceSpace?: 'left' | 'right' | 'center'
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

/** Applies narrative knobs to the ordinary scene graph created by a template. */
export const applyNarrativeSceneControls = (scene: Scene, controls: NarrativeSceneControls = {}): Scene => {
  const intensity = controls.intensity ?? 2
  const palette = controls.palette ?? 'natural'
  const mood = controls.mood ?? 'calm'
  const heroShift = controls.voiceSpace === 'left' ? 14 : controls.voiceSpace === 'right' ? -14 : 0
  const direction = controls.direction === 'left' ? -1 : 1
  return {
    ...scene,
    layers: scene.layers.map(layer => {
      const isHero = layer.id === 'hero' || layer.id === 'prop' || layer.id === 'landmark'
      const isCamera = layer.type === 'camera'
      const palettePatch = palette === 'cool' ? { hue: 12, saturation: .9 } : palette === 'warm' ? { hue: -10, saturation: 1.08 } : palette === 'neon' ? { hue: 42, saturation: 1.35, contrast: 1.12 } : {}
      const moodPatch = mood === 'tense' ? { contrast: 1.15, saturation: .82 } : mood === 'dreamy' ? { glow: .65 + intensity * .25, saturation: 1.12 } : mood === 'heroic' ? { glow: .35 + intensity * .18, contrast: 1.13, saturation: 1.12 } : { brightness: .98 + intensity * .02 }
      const movement = isHero ? heroShift : 0
      const shift = (frame: SceneKeyframe) => ({ ...frame, x: frame.x + movement, rotation: frame.rotation + (isHero ? direction * (controls.direction ? .6 : 0) : 0) })
      const animation = isCamera && controls.camera === 'restrained'
        ? { ...layer.animation, keyframes: layer.animation.keyframes?.map(frame => ({ ...frame, scale: 1 + (frame.scale - 1) * .45 })) }
        : isCamera && controls.camera === 'push'
          ? { ...layer.animation, keyframes: layer.animation.keyframes?.map((frame, index, frames) => ({ ...frame, scale: frame.scale + index / Math.max(1, (frames?.length ?? 1) - 1) * .08 })) }
          : isCamera && controls.camera === 'drift'
            ? { ...layer.animation, keyframes: layer.animation.keyframes?.map((frame, index) => ({ ...frame, x: frame.x + Math.sin(index * 1.7) * 1.3, y: frame.y + Math.cos(index * 1.7) * .7 })) }
            : isHero ? { ...layer.animation, start: { ...layer.animation.start, x: layer.animation.start.x + movement }, end: { ...layer.animation.end, x: layer.animation.end.x + movement }, keyframes: layer.animation.keyframes?.map(shift) }
              : layer.animation
      const transform = isHero ? { ...layer.transform, x: layer.transform.x + movement } : layer.transform
      return { ...layer, transform, animation, effects: layer.type === 'camera' ? layer.effects : { ...layer.effects, ...palettePatch, ...(isHero ? moodPatch : {}) } }
    }),
  }
}

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
  } else if (id === 'character-turntable') {
    const hero = heroLayer(input, duration, point(50, 52, .88), point(50, 52, .9), { effects: { glow: .45, brightness: 1.06, saturation: 1.04, contrast: 1.08 } })
    hero.animation = { ...hero.animation, spin: true, rotationSpeed: 18 }
    layers = [plate, withKeyframes(hero, buildDriftKeyframes('hero-turntable', duration, point(50, 52, .88), point(50, 52, .9), { bob: .25, pulse: .01 })), cameraLayer(duration, point(50, 50, 1.02), point(50, 50, 1.055), buildDriftKeyframes('camera-turntable', duration, point(50, 50, 1.02), point(50, 50, 1.055), { bob: .04, curve: 'linear' }))]
  } else if (id === 'silent-reaction') {
    const hero = heroLayer(input, duration, point(44, 54, .9), point(43, 52, .98), { effects: { glow: .12, brightness: .96, saturation: .84, contrast: 1.08 } })
    layers = [withKeyframes(plate, buildDriftKeyframes('plate-reaction', duration, point(51, 50, 1.02), point(49, 50, 1.1), { bob: .04 })), withKeyframes(hero, buildDriftKeyframes('hero-reaction', duration, point(44, 54, .9), point(43, 52, .98), { bob: .22, pulse: .007, rotation: .18 })), cameraLayer(duration, point(52, 51, 1), point(48, 49, 1.1), buildDriftKeyframes('camera-reaction', duration, point(52, 51, 1), point(48, 49, 1.1), { bob: .05 }))]
  } else if (id === 'portal-arrival') {
    const hero = heroLayer(input, duration, point(50, 64, .32, 0), point(50, 53, .98, 1), { effects: { glow: .8, brightness: 1.04, saturation: 1.1, contrast: 1.08 } })
    const prop = baseLayer('portal', input.prop?.name ?? 'Portal', input.prop?.type ?? 'image', input.prop?.source ?? '', 8, duration, point(50, 50, .08, 0), point(50, 50, 1.12, 1), { effects: { glow: 2.3, brightness: 1.25, saturation: 1.35, blendMode: 'screen' } })
    layers = [plate, withKeyframes(prop, [at('portal-0', 0, point(50, 50, .08, 0), 'dramatic'), at('portal-1', duration * .28, point(50, 50, .92, 1), 'ease'), at('portal-2', duration * .7, point(50, 50, 1.1, .88), 'ease'), at('portal-3', duration, point(50, 50, 1.12, .94), 'ease')]), withKeyframes(hero, [at('portal-hero-0', 0, point(50, 64, .32, 0), 'dramatic'), at('portal-hero-1', duration * .36, point(50, 58, .72, 1), 'ease'), at('portal-hero-2', duration * .72, point(50, 53, .96, 1), 'ease'), at('portal-hero-3', duration, point(50, 52, .98, 1), 'ease')]), cameraLayer(duration, point(50, 50, 1), point(50, 49, 1.07), buildDriftKeyframes('camera-portal', duration, point(50, 50, 1), point(50, 49, 1.07), { bob: .06 }))]
  } else if (id === 'icon-reveal') {
    const prop = baseLayer('prop', input.prop?.name ?? 'Iconic object', input.prop?.type ?? 'model3d', input.prop?.source ?? '', 10, duration, point(50, 53, .35, 0), point(50, 50, .92, 1), { effects: { glow: 1, brightness: 1.15, saturation: 1.08, contrast: 1.12 } })
    prop.animation = { ...prop.animation, spin: prop.type === 'model3d', rotationSpeed: 22 }
    layers = [withKeyframes(plate, buildDriftKeyframes('plate-icon', duration, point(48, 51, 1.06), point(52, 49, 1.1), { bob: .03 })), withKeyframes(prop, [at('icon-0', 0, point(50, 53, .35, 0), 'dramatic'), at('icon-1', duration * .24, point(50, 51, .74, 1), 'ease'), at('icon-2', duration * .66, point(50, 50, .9, 1), 'ease'), at('icon-3', duration, point(50, 50, .92, 1), 'linear')]), cameraLayer(duration, point(50, 50, 1.02), point(50, 50, 1.09), buildDriftKeyframes('camera-icon', duration, point(50, 50, 1.02), point(50, 50, 1.09), { bob: .03 }))]
  } else if (id === 'place-establishing') {
    const landmark = input.prop?.source ? baseLayer('landmark', input.prop.name ?? 'Landmark', input.prop.type ?? 'model3d', input.prop.source, 8, duration, point(58, 55, .45, .1), point(54, 52, .72, 1), { parallax: 1.35, effects: { glow: .35, brightness: 1.04, saturation: 1.08 } }) : undefined
    layers = [withKeyframes(plate, buildDriftKeyframes('plate-place', duration, point(44, 53, 1.16), point(57, 47, 1.25), { bob: .08 })), ...(landmark ? [withKeyframes(landmark, buildDriftKeyframes('landmark-place', duration, point(58, 55, .45, .1), point(54, 52, .72, 1), { bob: .16 }))] : []), cameraLayer(duration, point(46, 53, 1), point(54, 47, 1.08), buildDriftKeyframes('camera-place', duration, point(46, 53, 1), point(54, 47, 1.08), { bob: .04, curve: 'linear' }))]
  } else if (id === 'memory-drift') {
    const hero = heroLayer(input, duration, point(57, 55, .78, .3), point(43, 48, .92, 1), { effects: { glow: .35, brightness: .88, saturation: .62, contrast: .9 } })
    layers = [withKeyframes(plate, buildDriftKeyframes('plate-memory', duration, point(56, 50, 1.08), point(44, 50, 1.16), { bob: .08 })), withKeyframes(hero, buildDriftKeyframes('hero-memory', duration, point(57, 55, .78, .3), point(43, 48, .92, 1), { bob: .45, pulse: .008, rotation: .35 })), cameraLayer(duration, point(54, 51, 1.03), point(46, 49, 1.12), buildDriftKeyframes('camera-memory', duration, point(54, 51, 1.03), point(46, 49, 1.12), { bob: .04 }))]
  } else if (id === 'surreal-transit') {
    const hero = heroLayer(input, duration, point(24, 57, .65), point(76, 44, 1.02), { parallax: 1.25, effects: { glow: .7, brightness: 1.06, saturation: 1.2, contrast: 1.1 } })
    const foreground = input.foreground?.source ? baseLayer('foreground', input.foreground.name ?? 'Foreground', input.foreground.type ?? 'image', input.foreground.source, 15, duration, point(50, 50, 1.3, .35), point(50, 50, 1.3, .35), { fill: true, parallax: 1.7, strip: { enabled: true, count: 4, spacing: 100, direction: 'right', speed: 36, phase: 0 }, effects: { blur: .25 } }) : undefined
    layers = [withKeyframes(plate, buildDriftKeyframes('plate-transit', duration, point(58, 53, 1.1), point(42, 47, 1.18), { bob: .06 })), withKeyframes(hero, buildDriftKeyframes('hero-transit', duration, point(24, 57, .65), point(76, 44, 1.02), { bob: .55, pulse: .01, rotation: .65 })), ...(foreground ? [foreground] : []), cameraLayer(duration, point(48, 52, 1), point(52, 48, 1.07, 1, 1), buildDriftKeyframes('camera-transit', duration, point(48, 52, 1), point(52, 48, 1.07, 1, 1), { bob: .1, rotation: .15 }))]
  } else {
    plate.strip = { enabled: true, count: 4, spacing: 100, direction: 'right', speed: 12, phase: 0 }
    const runner = withKeyframes(heroLayer(input, duration, point(38, 54, .88), point(39, 54, .9), { effects: { glow: .15, brightness: 1, saturation: 1.04, contrast: 1.08 } }), buildDriftKeyframes('hero-run', duration, point(38, 54, .88, 1, -2), point(39, 54, .9, 1, 2), { bob: .9, rotation: 1.5, curve: 'linear' }))
    const foreground = input.foreground?.source ? baseLayer('foreground', input.foreground.name ?? 'Foreground', input.foreground.type ?? 'image', input.foreground.source, 15, duration, point(50, 50, 1.3, .4), point(50, 50, 1.3, .4), { fill: true, parallax: 1.7, strip: { enabled: true, count: 4, spacing: 100, direction: 'right', speed: 58, phase: 0 }, effects: { blur: .35 } }) : undefined
    layers = [plate, runner, ...(foreground ? [foreground] : []), cameraLayer(duration, point(50, 50, 1), point(50, 50, 1.018), buildDriftKeyframes('camera-run', duration, point(50, 50, 1), point(50, 50, 1.018), { bob: .05, curve: 'linear' }))]
  }

  return applyNarrativeSceneControls({ version: 1, name: template.title, width: input.width ?? 1280, height: input.height ?? 720, fps: input.fps ?? 30, duration, layers, composition: { showGrid: false, gridSize: 10, snap: false, safeArea: 'none' }, narrative: { templateId: template.id, controls: { ...input.controls } } }, input.controls)
}
