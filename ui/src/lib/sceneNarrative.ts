import type { Scene, SceneCurve, SceneKeyframe, SceneLayer, SceneLayerType } from '../types'
import { suggestSeamOccluderKind } from './seamOccluder'

export type NarrativeSceneId =
  | 'inner-thought'
  | 'hero-arrival'
  | 'character-turntable'
  | 'silent-reaction'
  | 'dialogue-medium-single'
  | 'emotional-close-up'
  | 'american-action-frame'
  | 'profile-listen'
  | 'low-angle-hero'
  | 'high-angle-isolation'
  | 'cutout-dialogue-hold'
  | 'cutout-reaction-snap'
  | 'two-shot-master'
  | 'over-shoulder-dialogue'
  | 'reverse-over-shoulder'
  | 'pov-detail-glance'
  | 'dutch-tension'
  | 'foreground-reveal'
  | 'cutout-talking-head'
  | 'cutout-speaking-blink'
  | 'dream-orbit'
  | 'portal-arrival'
  | 'icon-reveal'
  | 'detail-insert'
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

export type NarrativeTemplateCategory = 'dialogue' | 'character' | 'world' | 'object' | 'transition' | 'travel'

/** Gallery-facing metadata kept deliberately descriptive and model-agnostic. */
export type NarrativeGalleryMetadata = {
  category: NarrativeTemplateCategory
  visualIntent: string
  referenceMotion: string
  evaluationCues: string[]
}

export type NarrativeSceneTemplate = {
  id: NarrativeSceneId
  title: string
  description: string
  category: NarrativeTemplateCategory
  visualIntent: string
  referenceMotion: string
  evaluationCues: string[]
  defaultDuration: 10 | 12
  assetSlots: NarrativeAssetSlot[]
  controls: Array<'mood' | 'intensity' | 'direction' | 'camera' | 'palette' | 'voiceSpace'>
  constraints: Array<'continuous_motion' | 'hero_visible_late' | 'existing_assets_only' | 'no_invented_rig'>
  previewPrompt: string
  createScene: (input: NarrativeTemplateInput) => Scene
  experimental?: boolean
}

export type NarrativeTemplateInput = {
  hero?: { source: string; type?: Extract<SceneLayerType, 'model3d' | 'image' | 'video'>; name?: string }
  plate?: { source: string; type?: Extract<SceneLayerType, 'model3d' | 'image' | 'video'>; name?: string; seamlessHorizontal?: boolean }
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

// Conventional screen coverage for a single expressive character.  An MCU
// (chest/shoulders up) preserves hands and posture while making the eyes and
// mouth readable; it is a better default than a full figure for a dialogue or
// reaction beat.  The templates still use the same hero layer and pose — this
// is composition, not an attempt to synthesize a new facial performance.
const mediumClose = (x: number, y: number, scale: number, opacity = 1, rotation = 0) => point(x, y, scale, opacity, rotation)

/** Alternating opaque mouth layers make limited cutout dialogue readable without inventing a facial rig. */
const cutoutMouthFrames = (id: string, duration: number, open: boolean) => {
  const openBeats = new Set([1, 3, 4, 7, 9, 10, 13, 15])
  return Array.from({ length: 17 }, (_, index) => {
    const isOpen = openBeats.has(index)
    return at(`${id}-${index}`, duration * index / 16, point(50, 48, .115, open ? Number(isOpen) : Number(!isOpen)), 'hold')
  })
}

const cutoutBlinkFrames = (id: string, duration: number) => {
  const blinkBeats = new Set([4, 5, 11, 12])
  return Array.from({ length: 17 }, (_, index) => at(`${id}-${index}`, duration * index / 16, point(50, 35, .2, Number(blinkBeats.has(index))), 'hold'))
}

const at = (id: string, time: number, point: MotionPoint, curve: SceneCurve = 'ease'): SceneKeyframe => ({ id, time, curve, ...point })
const point = (x: number, y: number, scale: number, opacity = 1, rotation = 0): MotionPoint => ({ x, y, scale, opacity, rotation })
const durationOf = (input: NarrativeTemplateInput, fallback: 10 | 12) => Math.max(10, Math.min(60, input.duration ?? fallback))
const narrativeProvenance = (template: NarrativeSceneTemplate, input: NarrativeTemplateInput) => {
  const assets = (['hero', 'plate', 'prop', 'foreground'] as const).flatMap(slot => {
    const asset = input[slot]
    return asset?.source ? [{ slot, source: asset.source, name: asset.name, type: asset.type }] : []
  })
  const controls = Object.entries(input.controls ?? {}).filter(([, value]) => value !== undefined).map(([key, value]) => `${key}: ${value}`).join(', ')
  return {
    assets,
    category: template.category,
    visualIntent: template.visualIntent,
    referenceMotion: template.referenceMotion,
    evaluationCues: [...template.evaluationCues],
    prompt: `${template.title}. ${template.description}${controls ? ` Direction — ${controls}.` : ''}`,
  }
}

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
    seamlessHorizontal: input.plate?.seamlessHorizontal === true,
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

const NARRATIVE_SCENE_TEMPLATE_DATA: Array<Omit<NarrativeSceneTemplate, 'constraints' | 'previewPrompt' | 'createScene'>> = [
  { id: 'inner-thought', title: 'Inner thought', description: 'A three-quarter medium close-up for voice-over and a contemplative beat.', category: 'dialogue', visualIntent: 'Hold attention on the face and upper-body performance while leaving visual space for narration.', referenceMotion: 'Slow lateral drift with a subtle breathing bob; chest-up framing.', evaluationCues: ['Eyes and mouth remain readable throughout.', 'Hands or upper-body gesture can still read.', 'Motion is calm enough for voice-over.', 'Late frames still show visible movement.'], defaultDuration: 10, assetSlots: [{ id: 'hero', label: 'Character', types: ['model3d', 'image', 'video'], required: true }, { id: 'plate', label: 'Background', types: ['image', 'video'], required: true }], controls: ['mood', 'intensity', 'voiceSpace', 'camera'] },
  { id: 'hero-arrival', title: 'Hero arrival', description: 'An entrance that settles into a living pose.', category: 'character', visualIntent: 'Stage a delayed entrance that gives the hero a clear final pose.', referenceMotion: 'Fade and scale up from below, then settle.', evaluationCues: ['Hero is initially absent or small.', 'Reveal feels intentional rather than abrupt.', 'Final pose has a readable silhouette.'], defaultDuration: 12, assetSlots: [{ id: 'hero', label: 'Character', types: ['model3d', 'image', 'video'], required: true }, { id: 'plate', label: 'Background', types: ['image', 'video'], required: true }], controls: ['intensity', 'direction', 'camera'] },
  { id: 'character-turntable', title: 'Character presentation', description: 'A controlled silhouette and costume reveal.', category: 'character', visualIntent: 'Present a design consistently like a compact character showcase.', referenceMotion: 'Near-static stance with a slow turntable rotation.', evaluationCues: ['Rotation speed stays even.', 'Silhouette and costume remain legible.', 'Camera movement does not compete with the turn.'], defaultDuration: 10, assetSlots: [{ id: 'hero', label: 'Character', types: ['model3d', 'image', 'video'], required: true }, { id: 'plate', label: 'Background', types: ['image', 'video'], required: true }], controls: ['direction', 'palette', 'camera'] },
  { id: 'silent-reaction', title: 'Silent reaction', description: 'A restrained medium close-up for listening, resolve or a held reaction.', category: 'dialogue', visualIntent: 'Make a small change in facial expression, posture or framing carry the emotional beat.', referenceMotion: 'Minimal drift with controlled headroom and a chest-up push-in.', evaluationCues: ['Face stays large and unobstructed.', 'Change is subtle but visible.', 'Hands or shoulders retain enough room for body language.', 'Grade supports the emotional temperature.'], defaultDuration: 10, assetSlots: [{ id: 'hero', label: 'Character', types: ['model3d', 'image', 'video'], required: true }, { id: 'plate', label: 'Background', types: ['image', 'video'], required: true }], controls: ['mood', 'intensity', 'camera'] },
  { id: 'dialogue-medium-single', title: 'Dialogue medium', description: 'Waist-up single: the workhorse coverage for spoken performance and gesture.', category: 'dialogue', visualIntent: 'Balance face, hands and a small amount of environment so dialogue can cut cleanly.', referenceMotion: 'Quiet locked-off medium with a restrained, motivated settle.', evaluationCues: ['Waist and hands have room when present.', 'Face remains easy to read.', 'Background gives orientation without competing.'], defaultDuration: 10, assetSlots: [{ id: 'hero', label: 'Character', types: ['model3d', 'image', 'video'], required: true }, { id: 'plate', label: 'Background', types: ['image', 'video'], required: true }], controls: ['mood', 'voiceSpace', 'camera'] },
  { id: 'emotional-close-up', title: 'Emotional close-up', description: 'Head-and-shoulders emphasis for one precise emotional beat.', category: 'dialogue', visualIntent: 'Let eyes and mouth carry the moment while keeping the camera motion nearly invisible.', referenceMotion: 'Very slow close-up settle with deliberate eyeline room.', evaluationCues: ['Eyes occupy the emotional focal area.', 'No distracting zoom or rotation.', 'Use as punctuation, not continuous coverage.'], defaultDuration: 10, assetSlots: [{ id: 'hero', label: 'Character', types: ['model3d', 'image', 'video'], required: true }, { id: 'plate', label: 'Background', types: ['image', 'video'], required: true }], controls: ['mood', 'voiceSpace', 'camera'] },
  { id: 'american-action-frame', title: 'American action frame', description: 'Mid-thigh action framing: dynamic pose, prop and setting stay legible together.', category: 'character', visualIntent: 'Keep a dynamic stance and its prop readable without losing the character’s face.', referenceMotion: 'Stable three-quarter composition with a minimal forward settle.', evaluationCues: ['Frame reads from roughly mid-thigh upward.', 'Action pose and prop are both visible.', 'The environment still establishes direction.'], defaultDuration: 10, assetSlots: [{ id: 'hero', label: 'Character', types: ['model3d', 'image', 'video'], required: true }, { id: 'plate', label: 'Background', types: ['image', 'video'], required: true }], controls: ['intensity', 'direction', 'camera'] },
  { id: 'profile-listen', title: 'Profile listen', description: 'Three-quarter listening single with clean eyeline space for an off-screen partner.', category: 'dialogue', visualIntent: 'Suggest a conversation partner off-screen without inventing a second actor or a false OTS.', referenceMotion: 'Chest-up profile hold; only a slight breath and reframing.', evaluationCues: ['Look direction leaves clean lead room.', 'Face stays readable in three-quarter profile.', 'No fake second character is introduced.'], defaultDuration: 10, assetSlots: [{ id: 'hero', label: 'Character', types: ['model3d', 'image', 'video'], required: true }, { id: 'plate', label: 'Background', types: ['image', 'video'], required: true }], controls: ['mood', 'direction', 'camera'] },
  { id: 'low-angle-hero', title: 'Low-angle hero', description: 'A stable low-angle single for resolve, threat or a decisive declaration.', category: 'character', visualIntent: 'Give a character scale and authority while preserving a readable pose.', referenceMotion: 'Low-angle settle with no gratuitous spin or zoom.', evaluationCues: ['Hero feels grounded and dominant.', 'Silhouette remains readable.', 'Camera movement stays motivated.'], defaultDuration: 10, assetSlots: [{ id: 'hero', label: 'Character', types: ['model3d', 'image', 'video'], required: true }, { id: 'plate', label: 'Background', types: ['image', 'video'], required: true }], controls: ['mood', 'intensity', 'camera'] },
  { id: 'high-angle-isolation', title: 'High-angle isolation', description: 'A quiet high-angle single for doubt, vulnerability or a reflective pause.', category: 'dialogue', visualIntent: 'Let surrounding space make a character feel small without losing the face.', referenceMotion: 'Reserved high-angle drift with a deliberately wider frame.', evaluationCues: ['Space around the hero is meaningful.', 'Face remains available to the viewer.', 'The grade supports vulnerability without obscuring.'], defaultDuration: 10, assetSlots: [{ id: 'hero', label: 'Character', types: ['model3d', 'image', 'video'], required: true }, { id: 'plate', label: 'Background', types: ['image', 'video'], required: true }], controls: ['mood', 'voiceSpace', 'camera'] },
  { id: 'cutout-dialogue-hold', title: 'Cutout dialogue hold', description: 'Limited cutout-TV dialogue: held pose, tiny pose changes and a fixed camera.', category: 'dialogue', visualIntent: 'Create economical graphic timing from a flat character asset without claiming mouth or limb animation.', referenceMotion: 'Three held chest-up poses with decisive snaps; no continuous bobbing.', evaluationCues: ['Pose holds read as intentional timing.', 'There is no fake lip-sync.', 'Camera stays nearly locked.'], defaultDuration: 10, assetSlots: [{ id: 'hero', label: 'Cutout character', types: ['model3d', 'image', 'video'], required: true }, { id: 'plate', label: 'Graphic background', types: ['image', 'video'], required: true }], controls: ['mood', 'voiceSpace', 'camera'] },
  { id: 'cutout-reaction-snap', title: 'Cutout reaction snap', description: 'Limited cutout-TV reaction: pause, short snap and another held pose.', category: 'dialogue', visualIntent: 'Give a punchline or reaction a graphic beat using only existing assets.', referenceMotion: 'Long hold, abrupt reframing, long hold; no invented facial rig.', evaluationCues: ['The snap has a clear comic timing beat.', 'Holds are stable instead of floaty.', 'No false claim of facial animation.'], defaultDuration: 10, assetSlots: [{ id: 'hero', label: 'Cutout character', types: ['model3d', 'image', 'video'], required: true }, { id: 'plate', label: 'Graphic background', types: ['image', 'video'], required: true }], controls: ['mood', 'intensity', 'camera'] },
  { id: 'two-shot-master', title: 'Two-shot master', description: 'A stable wide two-person master for dialogue geography and edits.', category: 'dialogue', visualIntent: 'Establish both performers and their shared space before tighter coverage.', referenceMotion: 'Mostly locked composition with subtle independent held poses.', evaluationCues: ['Both performers are readable.', 'Clear space separates the pair.', 'Works as the anchor for subsequent singles.'], defaultDuration: 10, assetSlots: [{ id: 'hero', label: 'Primary character', types: ['model3d', 'image', 'video'], required: true }, { id: 'prop', label: 'Second character', types: ['model3d', 'image', 'video'], required: true }, { id: 'plate', label: 'Background', types: ['image', 'video'], required: true }], controls: ['mood', 'intensity', 'camera'] },
  { id: 'over-shoulder-dialogue', title: 'Over-shoulder dialogue', description: 'A genuine two-asset OTS: one character foregrounds the other’s medium close-up.', category: 'dialogue', visualIntent: 'Create depth, eyeline and spatial connection for shot/reverse-shot coverage.', referenceMotion: 'Foreground shoulder holds; focal character has a restrained medium-close beat.', evaluationCues: ['Foreground figure frames rather than hides the subject.', 'Focal face remains readable.', 'Requires two separate character assets.'], defaultDuration: 10, assetSlots: [{ id: 'hero', label: 'Focal character', types: ['model3d', 'image', 'video'], required: true }, { id: 'prop', label: 'Foreground character', types: ['model3d', 'image', 'video'], required: true }, { id: 'plate', label: 'Background', types: ['image', 'video'], required: true }], controls: ['mood', 'direction', 'camera'] },
  { id: 'reverse-over-shoulder', title: 'Reverse over-shoulder', description: 'The complementary OTS angle; swap the character assignments to complete coverage.', category: 'dialogue', visualIntent: 'Make the reverse angle spatially compatible with the first OTS rather than inventing a new scene.', referenceMotion: 'Foreground figure holds on the opposite side; partner takes the focal medium-close frame.', evaluationCues: ['Pairs cleanly with Over-shoulder dialogue.', 'Opposite foreground preserves shot/reverse rhythm.', 'Requires two separate character assets.'], defaultDuration: 10, assetSlots: [{ id: 'hero', label: 'Foreground character', types: ['model3d', 'image', 'video'], required: true }, { id: 'prop', label: 'Focal character', types: ['model3d', 'image', 'video'], required: true }, { id: 'plate', label: 'Background', types: ['image', 'video'], required: true }], controls: ['mood', 'direction', 'camera'] },
  { id: 'pov-detail-glance', title: 'POV detail glance', description: 'A subjective-looking insert for a clue or object, ready to bridge dialogue.', category: 'object', visualIntent: 'Direct attention to a small narrative object while leaving a trace of the world behind it.', referenceMotion: 'Tight object hold with a brief deliberate settle.', evaluationCues: ['Object reads immediately.', 'Framing feels subjective rather than product-like.', 'Cuts cleanly between character shots.'], defaultDuration: 10, assetSlots: [{ id: 'prop', label: 'Looked-at object', types: ['model3d', 'image', 'video'], required: true }, { id: 'plate', label: 'Background', types: ['image', 'video'], required: true }], controls: ['intensity', 'palette', 'camera'] },
  { id: 'dutch-tension', title: 'Dutch tension', description: 'A controlled canted frame for unease, revelation or comic imbalance.', category: 'transition', visualIntent: 'Use a measured diagonal composition for tension, not a constant gimmick.', referenceMotion: 'Held diagonal with a barely perceptible settle.', evaluationCues: ['Tilt has a clear story purpose.', 'Hero remains readable.', 'Avoids continuous spinning.'], defaultDuration: 10, assetSlots: [{ id: 'hero', label: 'Character', types: ['model3d', 'image', 'video'], required: true }, { id: 'plate', label: 'Background', types: ['image', 'video'], required: true }], controls: ['mood', 'intensity', 'camera'] },
  { id: 'foreground-reveal', title: 'Foreground reveal', description: 'A subject is discovered through an optional foreground occluder.', category: 'transition', visualIntent: 'Use depth and partial concealment to motivate a reveal without a hard cut.', referenceMotion: 'Foreground slides aside as the hero settles into a medium frame.', evaluationCues: ['Foreground creates depth without blocking the final read.', 'Reveal is motivated and continuous.', 'Hero is clearly visible late in the shot.'], defaultDuration: 10, assetSlots: [{ id: 'hero', label: 'Character', types: ['model3d', 'image', 'video'], required: true }, { id: 'plate', label: 'Background', types: ['image', 'video'], required: true }, { id: 'foreground', label: 'Foreground shape or character', types: ['image', 'video'], required: true }], controls: ['mood', 'direction', 'camera'] },
  { id: 'cutout-talking-head', title: 'Cutout talking head', description: 'Limited cutout dialogue with separate closed/open mouth layers and small head snaps.', category: 'dialogue', visualIntent: 'Add economical speech rhythm to a graphic character while keeping the body and camera deliberately stable.', referenceMotion: 'Held chest-up pose; alternating mouth layers; two subtle head-position snaps.', evaluationCues: ['Mouth layers alternate instead of scaling the whole character.', 'Body remains an intentional held pose.', 'No claim of phoneme-perfect lip-sync or a full facial rig.'], defaultDuration: 10, assetSlots: [{ id: 'hero', label: 'Head / character cutout', types: ['model3d', 'image', 'video'], required: true }, { id: 'prop', label: 'Open-mouth overlay', types: ['image', 'video'], required: true }, { id: 'foreground', label: 'Closed-mouth overlay', types: ['image', 'video'], required: true }, { id: 'plate', label: 'Graphic background', types: ['image', 'video'], required: true }], controls: ['mood', 'voiceSpace', 'camera'] },
  { id: 'cutout-speaking-blink', title: 'Cutout speaking performance', description: 'Limited cutout performance with mouth flap, blink overlay and clearer head-pose snaps.', category: 'dialogue', visualIntent: 'Make a graphic performer feel alive through only the small facial changes a cutout system can honestly support.', referenceMotion: 'Held chest-up pose, rhythmic mouth flap, two quick blinks and three clear head snaps.', evaluationCues: ['Open mouth and blink are independent layers.', 'Head changes are graphic, not floaty.', 'Does not claim phoneme-perfect lip-sync or a full facial rig.'], defaultDuration: 10, assetSlots: [{ id: 'hero', label: 'Head / character cutout', types: ['model3d', 'image', 'video'], required: true }, { id: 'prop', label: 'Open-mouth overlay', types: ['image', 'video'], required: true }, { id: 'foreground', label: 'Blink-eye overlay', types: ['image', 'video'], required: true }, { id: 'plate', label: 'Graphic background', types: ['image', 'video'], required: true }], controls: ['mood', 'voiceSpace', 'camera'] },
  { id: 'dream-orbit', title: 'Dream orbit', description: 'An arcing, luminous internal-world shot.', category: 'transition', visualIntent: 'Create a floating, heightened state around the subject.', referenceMotion: 'Diagonal orbit with glow, bob and gentle rotation.', evaluationCues: ['Orbit reads as intentional 3D-like motion.', 'Glow does not erase the subject.', 'The arc remains active near the end.'], defaultDuration: 12, assetSlots: [{ id: 'hero', label: 'Character', types: ['model3d', 'image', 'video'], required: true }, { id: 'plate', label: 'Background', types: ['image', 'video'], required: true }], controls: ['mood', 'intensity', 'palette', 'camera'] },
  { id: 'portal-arrival', title: 'Portal / invocation', description: 'A character reveal with a magical or sci-fi prop.', category: 'transition', visualIntent: 'Use a prop bloom to motivate and frame the character reveal.', referenceMotion: 'Prop expands first; hero follows with a shorter rise-in.', evaluationCues: ['Prop establishes the reveal before the hero.', 'Hero and prop remain visually distinct.', 'Brightness/glow has a controlled peak.'], defaultDuration: 12, assetSlots: [{ id: 'hero', label: 'Character', types: ['model3d', 'image', 'video'], required: true }, { id: 'prop', label: 'Portal or prop', types: ['model3d', 'image', 'video'], required: true }, { id: 'plate', label: 'Background', types: ['image', 'video'], required: true }], controls: ['intensity', 'palette', 'camera'] },
  { id: 'icon-reveal', title: 'Iconic object reveal', description: 'A relic, weapon or product-like insert.', category: 'object', visualIntent: 'Give a single object a clean, memorable hero moment.', referenceMotion: 'Scale and opacity reveal followed by a measured spin.', evaluationCues: ['Object is the strongest focal point.', 'Rotation remains smooth and comprehensible.', 'Edges separate from the background.'], defaultDuration: 10, assetSlots: [{ id: 'prop', label: 'Object', types: ['model3d', 'image', 'video'], required: true }, { id: 'plate', label: 'Background', types: ['image', 'video'], required: true }], controls: ['intensity', 'palette', 'camera'] },
  { id: 'detail-insert', title: 'Detail insert', description: 'A controlled macro-like insert for a clue, hand-held prop or narrative detail.', category: 'object', visualIntent: 'Punctuate a sequence with one object detail while dialogue or sound can continue.', referenceMotion: 'Tight, almost-static detail with a short focus-like settle.', evaluationCues: ['Object fills the frame without clipping its important detail.', 'Motion is subtle enough to cut into another scene.', 'Use sparingly as narrative punctuation.'], defaultDuration: 10, assetSlots: [{ id: 'prop', label: 'Detail object', types: ['model3d', 'image', 'video'], required: true }, { id: 'plate', label: 'Background', types: ['image', 'video'], required: true }], controls: ['intensity', 'palette', 'camera'] },
  { id: 'place-establishing', title: 'Establishing location', description: 'A location is discovered through parallax and atmosphere.', category: 'world', visualIntent: 'Let the viewer read the space before introducing a landmark.', referenceMotion: 'Wide background sweep with a slower landmark parallax.', evaluationCues: ['Location reads without a narration crutch.', 'Depth order is apparent from relative speeds.', 'Optional landmark supports, not hides, the setting.'], defaultDuration: 12, assetSlots: [{ id: 'plate', label: 'Environment', types: ['image', 'video'], required: true }, { id: 'prop', label: 'Optional landmark', types: ['model3d', 'image', 'video'], required: false }], controls: ['mood', 'direction', 'camera'] },
  { id: 'memory-drift', title: 'Memory / flashback', description: 'A soft medium close-up recollection with a changing grade.', category: 'transition', visualIntent: 'Signal recollection through softness, desaturation and reverse drift while retaining facial access.', referenceMotion: 'Slow chest-up cross-frame drift with a gentle memory-like bob.', evaluationCues: ['Grade clearly separates the memory state.', 'Face remains identifiable despite softness.', 'Motion feels slower than a present-time shot.', 'Upper-body gesture still has room.'], defaultDuration: 10, assetSlots: [{ id: 'hero', label: 'Character or object', types: ['model3d', 'image', 'video'], required: true }, { id: 'plate', label: 'Background', types: ['image', 'video'], required: true }], controls: ['mood', 'palette', 'voiceSpace'] },
  { id: 'surreal-transit', title: 'Surreal transit', description: 'Independent subject and world movement for journeys.', category: 'travel', visualIntent: 'Separate subject, world and foreground speeds to imply impossible travel.', referenceMotion: 'Hero crosses frame while background and foreground scroll independently.', evaluationCues: ['Relative layer speeds create depth.', 'Hero path stays readable.', 'Foreground occlusion feels deliberate when supplied.'], defaultDuration: 12, assetSlots: [{ id: 'hero', label: 'Character', types: ['model3d', 'image', 'video'], required: true }, { id: 'plate', label: 'Background', types: ['image', 'video'], required: true }, { id: 'foreground', label: 'Optional foreground', types: ['image', 'video'], required: false }], controls: ['intensity', 'direction', 'palette', 'camera'] },
  { id: 'run-travel-parallax', title: 'Run / travel parallax', description: 'A stylised movement illusion; it does not invent a running rig.', category: 'travel', visualIntent: 'Suggest forward travel from a held running pose and a looping world.', referenceMotion: 'World scrolls opposite the facing direction; foreground occludes faster.', evaluationCues: ['World scrolls opposite the hero facing.', 'Seams stay hidden or unobtrusive.', 'Do not evaluate this as a true legged run.'], defaultDuration: 12, assetSlots: [{ id: 'hero', label: 'Running-pose character', types: ['model3d', 'image', 'video'], required: true }, { id: 'plate', label: 'Seamless background', types: ['image', 'video'], required: true }, { id: 'foreground', label: 'Optional foreground strip', types: ['image', 'video'], required: false }], controls: ['intensity', 'direction', 'camera'], experimental: true },
]

/** Registry entries compile into the same ordinary Scene graph the user edits. */
export const NARRATIVE_SCENE_TEMPLATES: NarrativeSceneTemplate[] = NARRATIVE_SCENE_TEMPLATE_DATA.map(template => ({
  ...template,
  constraints: [
    'continuous_motion',
    'existing_assets_only',
    ...(template.assetSlots.some(slot => slot.id === 'hero' || slot.id === 'prop') ? ['no_invented_rig' as const] : []),
    ...(template.assetSlots.some(slot => slot.id === 'hero') ? ['hero_visible_late' as const] : []),
  ],
  previewPrompt: `${template.title}: ${template.description}`,
  createScene: input => createNarrativeScene(template.id, input),
}))

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
      const strip = layer.strip?.enabled && scene.narrative?.templateId === 'run-travel-parallax'
        ? { ...layer.strip, direction: (controls.direction === 'left' ? 'right' : 'left') as NonNullable<SceneLayer['strip']>['direction'] }
        : layer.strip
      return { ...layer, transform, animation, strip, effects: layer.type === 'camera' ? layer.effects : { ...layer.effects, ...palettePatch, ...(isHero ? moodPatch : {}) } }
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
    const hero = heroLayer(input, duration, mediumClose(63, 67, 1.34), mediumClose(67, 65, 1.43), { effects: { glow: 1.1, brightness: 1, saturation: .92, contrast: 1 } })
    layers = [withKeyframes(hero, buildDriftKeyframes('hero-thought', duration, mediumClose(63, 67, 1.34), mediumClose(67, 65, 1.43), { bob: .35, pulse: .008, rotation: .25 })), plate, cameraLayer(duration, point(48, 51, 1), point(52, 49, 1.025), buildDriftKeyframes('camera-thought', duration, point(48, 51, 1), point(52, 49, 1.025), { bob: .08 }))]
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
    const hero = heroLayer(input, duration, mediumClose(43, 67, 1.38), mediumClose(42, 65, 1.52), { effects: { glow: .12, brightness: .96, saturation: .84, contrast: 1.08 } })
    layers = [withKeyframes(plate, buildDriftKeyframes('plate-reaction', duration, point(51, 50, 1.02), point(49, 50, 1.07), { bob: .03 })), withKeyframes(hero, buildDriftKeyframes('hero-reaction', duration, mediumClose(43, 67, 1.38), mediumClose(42, 65, 1.52), { bob: .12, pulse: .004, rotation: .1 })), cameraLayer(duration, point(52, 51, 1), point(48, 49, 1.045), buildDriftKeyframes('camera-reaction', duration, point(52, 51, 1), point(48, 49, 1.045), { bob: .03 }))]
  } else if (id === 'dialogue-medium-single') {
    const hero = heroLayer(input, duration, point(58, 60, 1.12), point(57, 59, 1.16), { effects: { glow: .08, brightness: 1, saturation: .96, contrast: 1.04 } })
    layers = [withKeyframes(plate, buildDriftKeyframes('plate-dialogue-medium', duration, point(49, 50, 1.03), point(51, 50, 1.055), { bob: .02 })), withKeyframes(hero, buildDriftKeyframes('hero-dialogue-medium', duration, point(58, 60, 1.12), point(57, 59, 1.16), { bob: .1, pulse: .003, rotation: .06 })), cameraLayer(duration, point(49, 50, 1), point(51, 50, 1.02), buildDriftKeyframes('camera-dialogue-medium', duration, point(49, 50, 1), point(51, 50, 1.02), { bob: .02 }))]
  } else if (id === 'emotional-close-up') {
    const hero = heroLayer(input, duration, mediumClose(60, 75, 1.72), mediumClose(59, 73, 1.8), { effects: { glow: .1, brightness: 1.02, saturation: .94, contrast: 1.1 } })
    layers = [withKeyframes(plate, buildDriftKeyframes('plate-emotional-close', duration, point(49, 50, 1.05), point(51, 50, 1.065), { bob: .01 })), withKeyframes(hero, buildDriftKeyframes('hero-emotional-close', duration, mediumClose(60, 75, 1.72), mediumClose(59, 73, 1.8), { bob: .06, pulse: .002, rotation: .04 })), cameraLayer(duration, point(50, 50, 1), point(50, 50, 1.012), buildDriftKeyframes('camera-emotional-close', duration, point(50, 50, 1), point(50, 50, 1.012), { bob: .01 }))]
  } else if (id === 'american-action-frame') {
    const hero = heroLayer(input, duration, point(54, 58, 1.02), point(55, 57, 1.08), { effects: { glow: .2, brightness: 1.04, saturation: 1.05, contrast: 1.08 } })
    layers = [withKeyframes(plate, buildDriftKeyframes('plate-american', duration, point(49, 51, 1.04), point(51, 49, 1.09), { bob: .04 })), withKeyframes(hero, buildDriftKeyframes('hero-american', duration, point(54, 58, 1.02), point(55, 57, 1.08), { bob: .16, pulse: .006, rotation: .12 })), cameraLayer(duration, point(49, 51, 1), point(51, 49, 1.035), buildDriftKeyframes('camera-american', duration, point(49, 51, 1), point(51, 49, 1.035), { bob: .03 }))]
  } else if (id === 'profile-listen') {
    const hero = heroLayer(input, duration, mediumClose(66, 68, 1.36), mediumClose(65, 67, 1.42), { effects: { glow: .06, brightness: .98, saturation: .9, contrast: 1.08 } })
    layers = [withKeyframes(plate, buildDriftKeyframes('plate-profile', duration, point(51, 50, 1.03), point(49, 50, 1.06), { bob: .02 })), withKeyframes(hero, buildDriftKeyframes('hero-profile', duration, mediumClose(66, 68, 1.36), mediumClose(65, 67, 1.42), { bob: .08, pulse: .003, rotation: .08 })), cameraLayer(duration, point(51, 50, 1), point(49, 50, 1.02), buildDriftKeyframes('camera-profile', duration, point(51, 50, 1), point(49, 50, 1.02), { bob: .02 }))]
  } else if (id === 'low-angle-hero') {
    const hero = heroLayer(input, duration, point(51, 60, 1.12), point(50, 58, 1.18), { effects: { glow: .25, brightness: 1.06, saturation: 1.05, contrast: 1.12 } })
    layers = [withKeyframes(plate, buildDriftKeyframes('plate-low-angle', duration, point(50, 54, 1.08), point(50, 51, 1.13), { bob: .02 })), withKeyframes(hero, buildDriftKeyframes('hero-low-angle', duration, point(51, 60, 1.12), point(50, 58, 1.18), { bob: .08, pulse: .004, rotation: .08 })), cameraLayer(duration, point(50, 56, .98), point(50, 53, 1.035), buildDriftKeyframes('camera-low-angle', duration, point(50, 56, .98), point(50, 53, 1.035), { bob: .02 }))]
  } else if (id === 'high-angle-isolation') {
    const hero = heroLayer(input, duration, point(57, 55, .82), point(54, 53, .88), { effects: { glow: .08, brightness: .94, saturation: .82, contrast: 1.04 } })
    layers = [withKeyframes(plate, buildDriftKeyframes('plate-high-angle', duration, point(47, 46, 1.16), point(53, 54, 1.22), { bob: .04 })), withKeyframes(hero, buildDriftKeyframes('hero-high-angle', duration, point(57, 55, .82), point(54, 53, .88), { bob: .08, pulse: .003, rotation: .08 })), cameraLayer(duration, point(47, 45, 1.04), point(53, 55, 1.08), buildDriftKeyframes('camera-high-angle', duration, point(47, 45, 1.04), point(53, 55, 1.08), { bob: .02 }))]
  } else if (id === 'cutout-dialogue-hold') {
    const hero = heroLayer(input, duration, mediumClose(59, 67, 1.34), mediumClose(59, 67, 1.34), { effects: { brightness: 1.04, saturation: 1.12, contrast: 1.16 } })
    const holds = [at('cutout-talk-0', 0, mediumClose(59, 67, 1.34), 'hold'), at('cutout-talk-1', duration * .33, mediumClose(60, 66, 1.36, 1, .35), 'hold'), at('cutout-talk-2', duration * .66, mediumClose(58, 67, 1.34, 1, -.25), 'hold'), at('cutout-talk-3', duration, mediumClose(59, 67, 1.34), 'hold')]
    layers = [plate, withKeyframes(hero, holds), cameraLayer(duration, point(50, 50, 1), point(50, 50, 1), [at('cutout-camera-0', 0, point(50, 50, 1), 'hold'), at('cutout-camera-1', duration, point(50, 50, 1), 'hold')])]
  } else if (id === 'cutout-reaction-snap') {
    const hero = heroLayer(input, duration, mediumClose(48, 67, 1.34), mediumClose(48, 67, 1.34), { effects: { brightness: 1.02, saturation: 1.08, contrast: 1.18 } })
    const holds = [at('cutout-react-0', 0, mediumClose(48, 67, 1.34), 'hold'), at('cutout-react-1', duration * .46, mediumClose(45, 65, 1.48, 1, -1.2), 'hold'), at('cutout-react-2', duration * .58, mediumClose(45, 65, 1.48, 1, -1.2), 'hold'), at('cutout-react-3', duration, mediumClose(48, 67, 1.34), 'hold')]
    layers = [plate, withKeyframes(hero, holds), cameraLayer(duration, point(50, 50, 1), point(50, 50, 1), [at('cutout-camera-0', 0, point(50, 50, 1), 'hold'), at('cutout-camera-1', duration, point(50, 50, 1), 'hold')])]
  } else if (id === 'two-shot-master') {
    const hero = heroLayer(input, duration, point(31, 60, .86), point(32, 59, .88), { effects: { brightness: 1.02, saturation: 1.04, contrast: 1.05 } })
    const partner = baseLayer('partner', input.prop?.name ?? 'Second character', input.prop?.type ?? 'image', input.prop?.source ?? '', 9, duration, point(69, 60, .86), point(68, 59, .88), { fill: false, effects: { brightness: 1.02, saturation: 1.04, contrast: 1.05 } })
    layers = [plate, withKeyframes(hero, buildDriftKeyframes('master-hero', duration, point(31, 60, .86), point(32, 59, .88), { bob: .06, pulse: .002 })), withKeyframes(partner, buildDriftKeyframes('master-partner', duration, point(69, 60, .86), point(68, 59, .88), { bob: .06, pulse: .002 })), cameraLayer(duration, point(50, 50, 1), point(50, 50, 1.01), buildDriftKeyframes('master-camera', duration, point(50, 50, 1), point(50, 50, 1.01), { bob: .01 }))]
  } else if (id === 'over-shoulder-dialogue') {
    const hero = heroLayer(input, duration, mediumClose(66, 67, 1.36), mediumClose(65, 66, 1.42), { effects: { brightness: 1.02, saturation: .96, contrast: 1.08 } })
    const shoulder = baseLayer('shoulder', input.prop?.name ?? 'Foreground character', input.prop?.type ?? 'image', input.prop?.source ?? '', 15, duration, point(6, 76, 1.65, .55), point(7, 76, 1.65, .55), { fill: false, effects: { blur: 1.1, brightness: .72, saturation: .72 } })
    layers = [plate, withKeyframes(hero, buildDriftKeyframes('ots-hero', duration, mediumClose(66, 67, 1.36), mediumClose(65, 66, 1.42), { bob: .08, pulse: .003 })), shoulder, cameraLayer(duration, point(51, 50, 1), point(49, 50, 1.018), buildDriftKeyframes('ots-camera', duration, point(51, 50, 1), point(49, 50, 1.018), { bob: .01 }))]
  } else if (id === 'reverse-over-shoulder') {
    const foregroundHero = heroLayer(input, duration, point(94, 76, 1.65, .55), point(93, 76, 1.65, .55), { effects: { blur: 1.1, brightness: .72, saturation: .72 } })
    const partner = baseLayer('partner', input.prop?.name ?? 'Focal character', input.prop?.type ?? 'image', input.prop?.source ?? '', 10, duration, mediumClose(34, 67, 1.36), mediumClose(35, 66, 1.42), { fill: false, effects: { brightness: 1.02, saturation: .96, contrast: 1.08 } })
    layers = [plate, foregroundHero, withKeyframes(partner, buildDriftKeyframes('reverse-ots-partner', duration, mediumClose(34, 67, 1.36), mediumClose(35, 66, 1.42), { bob: .08, pulse: .003 })), cameraLayer(duration, point(49, 50, 1), point(51, 50, 1.018), buildDriftKeyframes('reverse-ots-camera', duration, point(49, 50, 1), point(51, 50, 1.018), { bob: .01 }))]
  } else if (id === 'pov-detail-glance') {
    const prop = baseLayer('prop', input.prop?.name ?? 'Detail object', input.prop?.type ?? 'image', input.prop?.source ?? '', 10, duration, point(52, 55, 1.1, .8), point(50, 53, 1.28, 1), { effects: { glow: .12, brightness: 1.12, saturation: 1.1, contrast: 1.14 } })
    layers = [withKeyframes(plate, buildDriftKeyframes('pov-plate', duration, point(50, 50, 1.1), point(50, 50, 1.13), { bob: .01 })), withKeyframes(prop, [at('pov-0', 0, point(52, 55, 1.1, .8), 'ease'), at('pov-1', duration * .25, point(51, 54, 1.2, 1), 'ease'), at('pov-2', duration, point(50, 53, 1.28, 1), 'hold')]), cameraLayer(duration, point(50, 50, 1), point(50, 50, 1.01), buildDriftKeyframes('pov-camera', duration, point(50, 50, 1), point(50, 50, 1.01), { bob: .01 }))]
  } else if (id === 'dutch-tension') {
    const hero = heroLayer(input, duration, mediumClose(52, 67, 1.3), mediumClose(51, 66, 1.36), { effects: { brightness: .96, saturation: .88, contrast: 1.16 } })
    layers = [withKeyframes(plate, buildDriftKeyframes('dutch-plate', duration, point(50, 50, 1.08, 1, -4), point(50, 50, 1.11, 1, -5), { bob: .02 })), withKeyframes(hero, buildDriftKeyframes('dutch-hero', duration, mediumClose(52, 67, 1.3, 1, -3), mediumClose(51, 66, 1.36, 1, -4), { bob: .05, pulse: .002 })), cameraLayer(duration, point(50, 50, 1, 1, -3), point(50, 50, 1.018, 1, -4), buildDriftKeyframes('dutch-camera', duration, point(50, 50, 1, 1, -3), point(50, 50, 1.018, 1, -4), { bob: .01 }))]
  } else if (id === 'foreground-reveal') {
    const hero = heroLayer(input, duration, mediumClose(54, 68, 1.18, .3), mediumClose(55, 66, 1.36, 1), { effects: { brightness: 1.04, saturation: 1.04, contrast: 1.08 } })
    const foreground = baseLayer('foreground', input.foreground?.name ?? 'Foreground', input.foreground?.type ?? 'image', input.foreground?.source ?? '', 15, duration, point(50, 67, 1.42, .7), point(112, 67, 1.42, .2), { fill: false, effects: { blur: .35, brightness: .82 } })
    layers = [plate, withKeyframes(hero, [at('reveal-hero-0', 0, mediumClose(54, 68, 1.18, .3), 'ease'), at('reveal-hero-1', duration * .38, mediumClose(55, 67, 1.28, 1), 'ease'), at('reveal-hero-2', duration, mediumClose(55, 66, 1.36, 1), 'ease')]), withKeyframes(foreground, [at('reveal-foreground-0', 0, point(50, 67, 1.42, .7), 'ease'), at('reveal-foreground-1', duration * .45, point(94, 67, 1.42, .35), 'ease'), at('reveal-foreground-2', duration, point(112, 67, 1.42, .2), 'ease')]), cameraLayer(duration, point(50, 50, 1), point(50, 50, 1.025), buildDriftKeyframes('reveal-camera', duration, point(50, 50, 1), point(50, 50, 1.025), { bob: .02 }))]
  } else if (id === 'cutout-talking-head') {
    const hero = heroLayer(input, duration, mediumClose(50, 67, 1.34), mediumClose(50, 67, 1.34), { effects: { brightness: 1.04, saturation: 1.12, contrast: 1.16 } })
    const openMouth = baseLayer('mouth-open', input.prop?.name ?? 'Open mouth', input.prop?.type ?? 'image', input.prop?.source ?? '', 16, duration, point(50, 48, .115, 0), point(50, 48, .115, 0), { fill: false, effects: { brightness: 1.05, saturation: 1.05 } })
    const closedMouth = baseLayer('mouth-closed', input.foreground?.name ?? 'Closed mouth', input.foreground?.type ?? 'image', input.foreground?.source ?? '', 17, duration, point(50, 48, .115, 1), point(50, 48, .115, 1), { fill: false, effects: { brightness: 1.05, saturation: 1.05 } })
    const headFrames = [at('talk-head-0', 0, mediumClose(50, 67, 1.34), 'hold'), at('talk-head-1', duration * .34, mediumClose(50.5, 66.8, 1.35, 1, .25), 'hold'), at('talk-head-2', duration * .67, mediumClose(49.5, 67.1, 1.34, 1, -.2), 'hold'), at('talk-head-3', duration, mediumClose(50, 67, 1.34), 'hold')]
    layers = [plate, withKeyframes(hero, headFrames), withKeyframes(openMouth, cutoutMouthFrames('mouth-open', duration, true)), withKeyframes(closedMouth, cutoutMouthFrames('mouth-closed', duration, false)), cameraLayer(duration, point(50, 50, 1), point(50, 50, 1), [at('talk-camera-0', 0, point(50, 50, 1), 'hold'), at('talk-camera-1', duration, point(50, 50, 1), 'hold')])]
  } else if (id === 'cutout-speaking-blink') {
    const hero = heroLayer(input, duration, mediumClose(50, 67, 1.34), mediumClose(50, 67, 1.34), { effects: { brightness: 1.04, saturation: 1.12, contrast: 1.16 } })
    const openMouth = baseLayer('mouth-open', input.prop?.name ?? 'Open mouth', input.prop?.type ?? 'image', input.prop?.source ?? '', 16, duration, point(50, 48, .115, 0), point(50, 48, .115, 0), { fill: false, effects: { brightness: 1.05, saturation: 1.05 } })
    const blinkEyes = baseLayer('blink-eyes', input.foreground?.name ?? 'Blink eyes', input.foreground?.type ?? 'image', input.foreground?.source ?? '', 17, duration, point(50, 35, .2, 0), point(50, 35, .2, 0), { fill: false, effects: { brightness: 1.04, saturation: 1.02 } })
    const headFrames = [at('speak-head-0', 0, mediumClose(50, 67, 1.34), 'hold'), at('speak-head-1', duration * .28, mediumClose(51.2, 66.5, 1.36, 1, .55), 'hold'), at('speak-head-2', duration * .56, mediumClose(48.8, 67.4, 1.34, 1, -.45), 'hold'), at('speak-head-3', duration * .78, mediumClose(50.7, 66.7, 1.35, 1, .28), 'hold'), at('speak-head-4', duration, mediumClose(50, 67, 1.34), 'hold')]
    layers = [plate, withKeyframes(hero, headFrames), withKeyframes(openMouth, cutoutMouthFrames('speak-mouth-open', duration, true)), withKeyframes(blinkEyes, cutoutBlinkFrames('speak-blink', duration)), cameraLayer(duration, point(50, 50, 1), point(50, 50, 1), [at('speak-camera-0', 0, point(50, 50, 1), 'hold'), at('speak-camera-1', duration, point(50, 50, 1), 'hold')])]
  } else if (id === 'portal-arrival') {
    const hero = heroLayer(input, duration, point(50, 64, .32, 0), point(50, 53, .98, 1), { effects: { glow: .8, brightness: 1.04, saturation: 1.1, contrast: 1.08 } })
    const prop = baseLayer('portal', input.prop?.name ?? 'Portal', input.prop?.type ?? 'image', input.prop?.source ?? '', 8, duration, point(50, 50, .08, 0), point(50, 50, 1.12, 1), { effects: { glow: 2.3, brightness: 1.25, saturation: 1.35, blendMode: 'screen' } })
    layers = [plate, withKeyframes(prop, [at('portal-0', 0, point(50, 50, .08, 0), 'dramatic'), at('portal-1', duration * .28, point(50, 50, .92, 1), 'ease'), at('portal-2', duration * .7, point(50, 50, 1.1, .88), 'ease'), at('portal-3', duration, point(50, 50, 1.12, .94), 'ease')]), withKeyframes(hero, [at('portal-hero-0', 0, point(50, 64, .32, 0), 'dramatic'), at('portal-hero-1', duration * .36, point(50, 58, .72, 1), 'ease'), at('portal-hero-2', duration * .72, point(50, 53, .96, 1), 'ease'), at('portal-hero-3', duration, point(50, 52, .98, 1), 'ease')]), cameraLayer(duration, point(50, 50, 1), point(50, 49, 1.07), buildDriftKeyframes('camera-portal', duration, point(50, 50, 1), point(50, 49, 1.07), { bob: .06 }))]
  } else if (id === 'icon-reveal') {
    const prop = baseLayer('prop', input.prop?.name ?? 'Iconic object', input.prop?.type ?? 'model3d', input.prop?.source ?? '', 10, duration, point(50, 53, .35, 0), point(50, 50, .92, 1), { effects: { glow: 1, brightness: 1.15, saturation: 1.08, contrast: 1.12 } })
    prop.animation = { ...prop.animation, spin: prop.type === 'model3d', rotationSpeed: 22 }
    layers = [withKeyframes(plate, buildDriftKeyframes('plate-icon', duration, point(48, 51, 1.06), point(52, 49, 1.1), { bob: .03 })), withKeyframes(prop, [at('icon-0', 0, point(50, 53, .35, 0), 'dramatic'), at('icon-1', duration * .24, point(50, 51, .74, 1), 'ease'), at('icon-2', duration * .66, point(50, 50, .9, 1), 'ease'), at('icon-3', duration, point(50, 50, .92, 1), 'linear')]), cameraLayer(duration, point(50, 50, 1.02), point(50, 50, 1.09), buildDriftKeyframes('camera-icon', duration, point(50, 50, 1.02), point(50, 50, 1.09), { bob: .03 }))]
  } else if (id === 'detail-insert') {
    const prop = baseLayer('prop', input.prop?.name ?? 'Detail object', input.prop?.type ?? 'image', input.prop?.source ?? '', 10, duration, point(52, 56, 1.25, .65), point(50, 54, 1.42, 1), { effects: { glow: .35, brightness: 1.12, saturation: 1.08, contrast: 1.15 } })
    layers = [withKeyframes(plate, buildDriftKeyframes('plate-detail', duration, point(50, 50, 1.1), point(50, 50, 1.13), { bob: .01 })), withKeyframes(prop, [at('detail-0', 0, point(52, 56, 1.25, .65), 'ease'), at('detail-1', duration * .3, point(51, 55, 1.34, 1), 'ease'), at('detail-2', duration, point(50, 54, 1.42, 1), 'linear')]), cameraLayer(duration, point(50, 50, 1), point(50, 50, 1.015), buildDriftKeyframes('camera-detail', duration, point(50, 50, 1), point(50, 50, 1.015), { bob: .01 }))]
  } else if (id === 'place-establishing') {
    const landmark = input.prop?.source ? baseLayer('landmark', input.prop.name ?? 'Landmark', input.prop.type ?? 'model3d', input.prop.source, 8, duration, point(58, 55, .45, .1), point(54, 52, .72, 1), { parallax: 1.35, effects: { glow: .35, brightness: 1.04, saturation: 1.08 } }) : undefined
    layers = [withKeyframes(plate, buildDriftKeyframes('plate-place', duration, point(44, 53, 1.16), point(57, 47, 1.25), { bob: .08 })), ...(landmark ? [withKeyframes(landmark, buildDriftKeyframes('landmark-place', duration, point(58, 55, .45, .1), point(54, 52, .72, 1), { bob: .16 }))] : []), cameraLayer(duration, point(46, 53, 1), point(54, 47, 1.08), buildDriftKeyframes('camera-place', duration, point(46, 53, 1), point(54, 47, 1.08), { bob: .04, curve: 'linear' }))]
  } else if (id === 'memory-drift') {
    const hero = heroLayer(input, duration, mediumClose(58, 68, 1.2, .3), mediumClose(43, 64, 1.38, 1), { effects: { glow: .35, brightness: .88, saturation: .62, contrast: .9 } })
    layers = [withKeyframes(plate, buildDriftKeyframes('plate-memory', duration, point(56, 50, 1.08), point(44, 50, 1.13), { bob: .06 })), withKeyframes(hero, buildDriftKeyframes('hero-memory', duration, mediumClose(58, 68, 1.2, .3), mediumClose(43, 64, 1.38, 1), { bob: .24, pulse: .006, rotation: .2 })), cameraLayer(duration, point(54, 51, 1.03), point(46, 49, 1.07), buildDriftKeyframes('camera-memory', duration, point(54, 51, 1.03), point(46, 49, 1.07), { bob: .03 }))]
  } else if (id === 'surreal-transit') {
    const hero = heroLayer(input, duration, point(24, 57, .65), point(76, 44, 1.02), { parallax: 1.25, effects: { glow: .7, brightness: 1.06, saturation: 1.2, contrast: 1.1 } })
    const foreground = input.foreground?.source ? baseLayer('foreground', input.foreground.name ?? 'Foreground', input.foreground.type ?? 'image', input.foreground.source, 15, duration, point(50, 50, 1.3, .35), point(50, 50, 1.3, .35), { fill: true, parallax: 1.7, strip: { enabled: true, count: 4, spacing: 100, direction: 'right', speed: 36, phase: 0 }, effects: { blur: .25 } }) : undefined
    layers = [withKeyframes(plate, buildDriftKeyframes('plate-transit', duration, point(58, 53, 1.1), point(42, 47, 1.18), { bob: .06 })), withKeyframes(hero, buildDriftKeyframes('hero-transit', duration, point(24, 57, .65), point(76, 44, 1.02), { bob: .55, pulse: .01, rotation: .65 })), ...(foreground ? [foreground] : []), cameraLayer(duration, point(48, 52, 1), point(52, 48, 1.07, 1, 1), buildDriftKeyframes('camera-transit', duration, point(48, 52, 1), point(52, 48, 1.07, 1, 1), { bob: .1, rotation: .15 }))]
  } else {
    // A right-facing runner only looks like they are going forward if the
    // world scrolls the other way. `direction: 'left'` flips that pair.
    const scrollDirection = input.controls?.direction === 'left' ? 'right' : 'left'
    plate.strip = {
      enabled: true,
      count: 4,
      spacing: 100,
      direction: scrollDirection,
      speed: 12,
      phase: 0,
      seamOccluder: {
        enabled: true,
        kind: suggestSeamOccluderKind([input.plate?.name, template.title, template.description].filter(Boolean).join(' ')),
      },
    }
    const runner = withKeyframes(heroLayer(input, duration, point(38, 54, .88), point(39, 54, .9), { effects: { glow: .15, brightness: 1, saturation: 1.04, contrast: 1.08 } }), buildDriftKeyframes('hero-run', duration, point(38, 54, .88, 1, -2), point(39, 54, .9, 1, 2), { bob: .9, rotation: 1.5, curve: 'linear' }))
    const foreground = input.foreground?.source ? baseLayer('foreground', input.foreground.name ?? 'Foreground', input.foreground.type ?? 'image', input.foreground.source, 15, duration, point(50, 50, 1.3, .4), point(50, 50, 1.3, .4), { fill: true, parallax: 1.7, strip: { enabled: true, count: 4, spacing: 100, direction: scrollDirection, speed: 58, phase: 0 }, effects: { blur: .35 } }) : undefined
    layers = [plate, runner, ...(foreground ? [foreground] : []), cameraLayer(duration, point(50, 50, 1), point(50, 50, 1.018), buildDriftKeyframes('camera-run', duration, point(50, 50, 1), point(50, 50, 1.018), { bob: .05, curve: 'linear' }))]
  }

  return applyNarrativeSceneControls({ version: 1, name: template.title, width: input.width ?? 1280, height: input.height ?? 720, fps: input.fps ?? 30, duration, layers, composition: { showGrid: false, gridSize: 10, snap: false, safeArea: 'none' }, narrative: { templateId: template.id, controls: { ...input.controls }, ...narrativeProvenance(template, input) } }, input.controls)
}
