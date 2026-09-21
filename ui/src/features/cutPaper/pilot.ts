import { rebuildCutoutDialogueLayers } from '../../lib/cutoutDialogue'
import type { Scene, SceneKeyframe, SceneLayer } from '../../types'
import {
  assertCutPaperKitHasNoPrivateGlb,
  cutPaperCamera,
  cutPaperLocationLayer,
  cutPaperPuppetLayers,
  emptyCutPaperScene,
  slidePuppet,
} from './puppet.ts'
import { cutPaperDialogueBeats, cutPaperVoiceFilename, type CutPaperLocale } from './voiceAlign.ts'

export const CUT_PAPER_PILOT_DURATION = 78

export const CUT_PAPER_PILOT_SCRIPT = [
  { id: 'nilo-1', speaker: 'nilo', start: 6, end: 16, text: 'La fuente no está congelada. Alguien le pegó un cuadrado de papel cebolla.' },
  { id: 'berta-1', speaker: 'berta', start: 17, end: 24, text: 'Pues sabe a hielo. Lo probé.' },
  { id: 'nilo-2', speaker: 'nilo', start: 25, end: 30, text: 'Berta, eso es cola.' },
  { id: 'berta-2', speaker: 'berta', start: 31, end: 38, text: 'Cola fría. Como hielo.' },
  { id: 'kito-1', speaker: 'kito', start: 62, end: 68, text: '¡Era un sticker!' },
] as const

export const CUT_PAPER_PILOT_SCRIPT_EN = [
  { id: 'nilo-1', speaker: 'nilo', start: 6, end: 16, text: 'The fountain is not frozen. Someone stuck a square of tracing paper on it.' },
  { id: 'berta-1', speaker: 'berta', start: 17, end: 24, text: 'Well it tastes like ice. I tried it.' },
  { id: 'nilo-2', speaker: 'nilo', start: 25, end: 30, text: "Berta, that's glue." },
  { id: 'berta-2', speaker: 'berta', start: 31, end: 38, text: 'Cold glue. Like ice.' },
  { id: 'kito-1', speaker: 'kito', start: 62, end: 68, text: 'It was a sticker!' },
] as const

/** 78 s, three shots: plaza, talk, paper-sled gag. Dialogue first, then mouths, then slides. */
export function compileCutPaperPilotScene(locale: CutPaperLocale = 'es'): Scene {
  const script = locale === 'en' ? CUT_PAPER_PILOT_SCRIPT_EN : CUT_PAPER_PILOT_SCRIPT
  const duration = CUT_PAPER_PILOT_DURATION
  const scene = emptyCutPaperScene(locale === 'en' ? 'Tijeral · the fountain' : 'Tijeral · la fuente', duration)
  scene.layers = [
    cutPaperCamera(duration),
    cutPaperLocationLayer('plaza', duration),
    ...cutPaperPuppetLayers({ characterId: 'nilo', x: 36, y: 62, scale: 1, z0: 20 }, duration),
    ...cutPaperPuppetLayers({ characterId: 'berta', x: 62, y: 64, scale: 0.95, z0: 30 }, duration),
    ...cutPaperPuppetLayers({ characterId: 'kito', x: 118, y: 70, scale: 0.7, z0: 40 }, duration),
  ]
  scene.layers.push({
    id: 'sticker-ice', name: 'Papel cebolla', type: 'image',
    source: '/examples/cut-paper/props/onion-paper.png',
    visible: true, locked: false, z: 8,
    transform: { x: 50, y: 58, scale: 0.22, opacity: 1, rotation: -6 },
    animation: {
      start: { x: 50, y: 58, scale: 0.22, opacity: 1, rotation: -6 },
      end: { x: 78, y: 82, scale: 0.18, opacity: 0, rotation: 18 },
      duration, curve: 'ease',
      keyframes: [
        { id: 'ice-0', time: 0, x: 50, y: 58, scale: 0.22, opacity: 1, rotation: -6, curve: 'hold' },
        { id: 'ice-1', time: 54, x: 50, y: 58, scale: 0.22, opacity: 1, rotation: -6, curve: 'ease' },
        { id: 'ice-2', time: 61, x: 78, y: 82, scale: 0.18, opacity: 0, rotation: 18, curve: 'ease' },
        { id: 'ice-3', time: duration, x: 78, y: 82, scale: 0.18, opacity: 0, rotation: 18, curve: 'hold' },
      ],
    },
    parallax: 0.4,
  })
  scene.layers = slidePuppet(scene.layers, 'kito', { x: 118, y: 70 }, { x: 52, y: 70 }, 54, 61)
  scene.dialogueBeats = script.flatMap(line => cutPaperDialogueBeats(line, line.start, locale))
  scene.layers = rebuildCutoutDialogueLayers(scene.layers, scene.dialogueBeats ?? [], 30, duration)
  scene.texts = [
    { id: 'title', text: 'Tijeral', start: 0.4, end: 3.6, preset: 'rise', x: 50, y: 12, size: 7, color: '#1d2b5a', rotation: 0 },
  ]
  scene.audioTracks = script.map(line => ({
    id: `vo-${line.id}`, filename: cutPaperVoiceFilename(line.speaker, line.id, locale),
    name: `${line.speaker} · ${line.text.slice(0, 24)}`, kind: 'speech' as const,
    startTime: line.start, volume: 1,
  }))
  assertCutPaperKitHasNoPrivateGlb(scene)
  return scene
}

export type CutPaperShotId = 'plaza' | 'talk' | 'sticker'

/**
 * Scene Animator import expands a layer (and then the scene) to the last
 * keyframe time. A shot sliced from the 78 s pilot must not keep t=78
 * holds or the later ice-peel, or opening the beat becomes a 78 s timeline.
 */
function clampLayerToShotDuration(layer: SceneLayer, duration: number): SceneLayer {
  const frames = [...(layer.animation.keyframes ?? [])].sort((left, right) => left.time - right.time)
  if (!frames.length) {
    return { ...layer, animation: { ...layer.animation, duration } }
  }
  const epsilon = 1e-9
  const kept = frames.filter(frame => frame.time <= duration + epsilon)
  let keyframes: SceneKeyframe[]
  if (frames.length === 2 && frames[0].time <= epsilon && frames[1].time > duration + epsilon) {
    keyframes = [
      { ...frames[0], time: 0 },
      { ...frames[1], id: `${layer.id}-${Math.round(duration * 1000)}`, time: duration },
    ]
  } else {
    keyframes = kept.length ? kept : [{ ...frames[0], time: 0 }]
    const lastKept = keyframes[keyframes.length - 1]
    if (lastKept.time < duration - epsilon) {
      keyframes = [...keyframes, { ...lastKept, id: `${layer.id}-${Math.round(duration * 1000)}`, time: duration }]
    }
  }
  const first = keyframes[0]
  const last = keyframes[keyframes.length - 1]
  return {
    ...layer,
    animation: {
      ...layer.animation,
      duration,
      start: { x: first.x, y: first.y, scale: first.scale, opacity: first.opacity, rotation: first.rotation },
      end: { x: last.x, y: last.y, scale: last.scale, opacity: last.opacity, rotation: last.rotation },
      keyframes,
    },
  }
}

/** One Video 2D clip per Story Lab beat. Same kit, shorter timeline. */
export function compileCutPaperShot(shot: CutPaperShotId, locale: CutPaperLocale = 'es'): Scene {
  const full = compileCutPaperPilotScene(locale)
  const script = locale === 'en' ? CUT_PAPER_PILOT_SCRIPT_EN : CUT_PAPER_PILOT_SCRIPT
  if (shot === 'plaza') {
    const duration = 6
    const layers = full.layers.filter(layer => layer.type === 'camera' || layer.id === 'location-plaza' || layer.id === 'sticker-ice')
      .map(layer => clampLayerToShotDuration(layer, duration))
    const scene = { ...full, name: locale === 'en' ? 'Tijeral · shot 1 plaza' : 'Tijeral · plano 1 plaza', duration, layers, dialogueBeats: [], audioTracks: [], texts: full.texts }
    assertCutPaperKitHasNoPrivateGlb(scene)
    return scene
  }
  if (shot === 'talk') {
    const duration = 40
    const layers = full.layers.filter(layer =>
      layer.type === 'camera' || layer.id === 'location-plaza' || layer.id === 'sticker-ice'
      || layer.id.startsWith('puppet-nilo') || layer.id.startsWith('puppet-berta'))
      .map(layer => clampLayerToShotDuration(layer, duration))
    const scene = {
      ...full, name: locale === 'en' ? 'Tijeral · shot 2 cold glue' : 'Tijeral · plano 2 cola fría', duration, layers,
      dialogueBeats: (full.dialogueBeats ?? []).filter(beat => beat.start < 40),
      audioTracks: (full.audioTracks ?? []).filter(track => track.startTime < 40),
      texts: [],
    }
    assertCutPaperKitHasNoPrivateGlb(scene)
    return scene
  }
  const duration = 26
  const scene = emptyCutPaperScene(locale === 'en' ? 'Tijeral · shot 3 sticker' : 'Tijeral · plano 3 sticker', duration)
  scene.layers = [
    cutPaperCamera(duration),
    cutPaperLocationLayer('plaza', duration),
    ...cutPaperPuppetLayers({ characterId: 'nilo', x: 36, y: 62, scale: 1, z0: 20 }, duration),
    ...cutPaperPuppetLayers({ characterId: 'berta', x: 62, y: 64, scale: 0.95, z0: 30 }, duration),
    ...cutPaperPuppetLayers({ characterId: 'kito', x: 118, y: 70, scale: 0.7, z0: 40 }, duration),
    full.layers.find(layer => layer.id === 'sticker-ice')!,
  ]
  const ice = scene.layers.find(layer => layer.id === 'sticker-ice')
  if (ice) {
    ice.animation = {
      ...ice.animation, duration,
      keyframes: [
        { id: 'ice-0', time: 0, x: 50, y: 58, scale: 0.22, opacity: 1, rotation: -6, curve: 'hold' },
        { id: 'ice-1', time: 2, x: 50, y: 58, scale: 0.22, opacity: 1, rotation: -6, curve: 'ease' },
        { id: 'ice-2', time: 9, x: 78, y: 82, scale: 0.18, opacity: 0, rotation: 18, curve: 'ease' },
        { id: 'ice-3', time: duration, x: 78, y: 82, scale: 0.18, opacity: 0, rotation: 18, curve: 'hold' },
      ],
    }
  }
  scene.layers = slidePuppet(scene.layers, 'kito', { x: 118, y: 70 }, { x: 52, y: 70 }, 2, 9)
  const kito = script.find(line => line.id === 'kito-1')!
  scene.dialogueBeats = cutPaperDialogueBeats(kito, 10, locale)
  scene.layers = rebuildCutoutDialogueLayers(scene.layers, scene.dialogueBeats ?? [], 30, duration)
    .map(layer => clampLayerToShotDuration(layer, duration))
  scene.audioTracks = [{ id: 'vo-kito-1', filename: cutPaperVoiceFilename('kito', 'kito-1', locale), name: 'kito · sticker', kind: 'speech', startTime: 10, volume: 1 }]
  assertCutPaperKitHasNoPrivateGlb(scene)
  return scene
}
