import type { Scene, SceneKeyframe, SceneLayer } from '../../types'
import { applyCutoutDialogue, planCutoutDialogue } from '../../lib/cutoutDialogue'
import {
  CUT_PAPER_CAST,
  CUT_PAPER_KIT_ID,
  CUT_PAPER_PIECES,
  CUT_PAPER_PUBLIC_ROOT,
  CUT_PAPER_VISEMES,
  cutPaperAssetUrl,
  type CutPaperExpression,
  type CutPaperViseme,
} from './bible.ts'

/** One transparent body + four paper-cut mouth cards. Never stack opaque copies. */
const BODY_SCALE: Record<string, number> = { nilo: 0.42, berta: 0.4, kito: 0.32 }

/** Pose-local mouth anchors (percent of the body layer, same units as Character Kit). */
export const CUT_PAPER_MOUTH_ANCHOR: Record<string, { offsetX: number; offsetY: number; scale: number }> = {
  nilo: { offsetX: 0.86, offsetY: -17.55, scale: 0.12 },
  berta: { offsetX: 0.17, offsetY: -16.55, scale: 0.11 },
  kito: { offsetX: 0, offsetY: 6.39, scale: 0.16 },
}
const DEFAULT_MOUTH_ANCHOR = { offsetX: 0, offsetY: -17, scale: 0.11 }

function key(id: string, time: number, x: number, y: number, scale: number, opacity: number, rotation = 0, curve: SceneKeyframe['curve'] = 'hold'): SceneKeyframe {
  return { id: `${id}-${Math.round(time * 1000)}`, time, x, y, scale, opacity, rotation, curve }
}

function imageLayer(input: {
  id: string
  name: string
  source: string
  z: number
  x: number
  y: number
  scale: number
  duration: number
  parent?: string
  parallax?: number
  faceBinding?: SceneLayer['faceBinding']
  shadow?: number
  fill?: boolean
  opacity?: number
}): SceneLayer {
  const { id, name, source, z, x, y, scale, duration, parent, parallax, faceBinding, shadow, fill } = input
  const opacity = input.opacity ?? 1
  return {
    id, name, type: 'image', source, visible: true, locked: false, z,
    transform: { x, y, scale, opacity, rotation: 0 },
    animation: {
      start: { x, y, scale, opacity, rotation: 0 },
      end: { x, y, scale, opacity, rotation: 0 },
      duration, curve: 'hold',
      keyframes: [key(id, 0, x, y, scale, opacity), key(id, duration, x, y, scale, opacity)],
    },
    ...(fill ? { fill: true } : {}),
    ...(parent ? { relationship: { type: 'parent', targetLayerId: parent } } : {}),
    ...(parallax != null ? { parallax } : {}),
    ...(faceBinding ? { faceBinding } : {}),
    ...(shadow ? { effects: { shadow, blendMode: 'normal', mask: 'none', maskRadius: 12, blur: 0, brightness: 1, contrast: 1, saturation: 1, hue: 0, glow: 0 } } : {}),
  }
}

export type PuppetPlacement = {
  characterId: string
  x: number
  y: number
  scale: number
  expression?: CutPaperExpression
  z0?: number
}

/** One transparent body plus four mouth overlays (small paper visemes, not lipstick cards). */
export function cutPaperPuppetLayers(placement: PuppetPlacement, duration: number): SceneLayer[] {
  const character = CUT_PAPER_CAST.find(item => item.id === placement.characterId)
  if (!character) throw new Error(`Unknown cut-paper character: ${placement.characterId}`)
  const rootId = `puppet-${character.id}`
  const z0 = placement.z0 ?? 20
  const bodyScale = (BODY_SCALE[character.id] ?? 0.4) * placement.scale
  const pose = imageLayer({
    id: rootId,
    name: `${character.name} pose`,
    source: `${CUT_PAPER_PUBLIC_ROOT}/puppets/${character.id}-body.png`,
    z: z0 + 12,
    x: placement.x, y: placement.y, scale: bodyScale,
    duration, parallax: 1, shadow: 0.25,
  })
  const layers: SceneLayer[] = [pose]
  const anchor = CUT_PAPER_MOUTH_ANCHOR[character.id] ?? DEFAULT_MOUTH_ANCHOR
  const mouthX = placement.x + anchor.offsetX * bodyScale
  const mouthY = placement.y + anchor.offsetY * bodyScale
  const mouthScale = bodyScale * anchor.scale
  for (const viseme of CUT_PAPER_VISEMES) {
    layers.push(imageLayer({
      id: `${rootId}-mouth-${viseme}`,
      name: `${character.name} mouth ${viseme}`,
      source: `${CUT_PAPER_PUBLIC_ROOT}/mouths/paper-${viseme}.png`,
      z: z0 + 20,
      x: mouthX,
      y: mouthY,
      scale: mouthScale,
      duration, parent: rootId,
      faceBinding: { poseLayerId: rootId, role: 'mouth', state: viseme },
      opacity: 0,
    }))
  }
  return layers
}

export function slidePuppet(layers: SceneLayer[], characterId: string, from: { x: number; y: number }, to: { x: number; y: number }, start: number, end: number): SceneLayer[] {
  const rootId = `puppet-${characterId}`
  return layers.map(layer => {
    if (layer.id !== rootId) return layer
    const frames = [
      key(layer.id, 0, from.x, from.y, layer.transform.scale, 1, 0, 'hold'),
      key(layer.id, start, from.x, from.y, layer.transform.scale, 1, 0, 'ease'),
      key(layer.id, end, to.x, to.y, layer.transform.scale, 1, 0, 'ease'),
      key(layer.id, layer.animation.duration, to.x, to.y, layer.transform.scale, 1, 0, 'hold'),
    ]
    return {
      ...layer,
      transform: { ...layer.transform, x: from.x, y: from.y },
      animation: { ...layer.animation, start: { x: from.x, y: from.y, scale: layer.transform.scale, opacity: 1 }, end: { x: to.x, y: to.y, scale: layer.transform.scale, opacity: 1 }, keyframes: frames, curve: 'ease' },
    }
  })
}

export function applyPuppetSpeech(layers: SceneLayer[], characterId: string, text: string, start: number, end: number, fps: number): SceneLayer[] {
  const rootId = `puppet-${characterId}`
  const mouth = Object.fromEntries(CUT_PAPER_VISEMES.map(state => [state, layers.find(layer => layer.id === `${rootId}-mouth-${state}`)])) as Partial<Record<CutPaperViseme, SceneLayer>>
  if (!mouth.closed) return layers
  const generated = applyCutoutDialogue({
    closed: mouth.closed, small: mouth.small, wide: mouth.wide, round: mouth.round,
  }, planCutoutDialogue(text, start, end, fps))
  return layers.map(layer => {
    const frames = generated[layer.id]
    if (!frames?.length) return layer
    return { ...layer, animation: { ...layer.animation, keyframes: frames, curve: 'hold' } }
  })
}

export function cutPaperCamera(duration: number): SceneLayer {
  return {
    id: 'camera', name: 'Camera', type: 'camera', source: '', visible: true, locked: false, z: 100,
    transform: { x: 50, y: 50, scale: 1, opacity: 1, rotation: 0 },
    animation: {
      start: { x: 50, y: 50, scale: 1, opacity: 1, rotation: 0 },
      end: { x: 50, y: 50, scale: 1.04, opacity: 1, rotation: 0 },
      duration, curve: 'ease',
      keyframes: [
        key('camera', 0, 50, 50, 1, 1, 0, 'ease'),
        key('camera', duration, 50, 50, 1.04, 1, 0, 'ease'),
      ],
    },
  }
}

export function cutPaperLocationLayer(locationId: string, duration: number): SceneLayer {
  return imageLayer({
    id: `location-${locationId}`,
    name: `Location ${locationId}`,
    source: cutPaperAssetUrl('location', locationId),
    z: 0, x: 50, y: 50, scale: 1, duration, parallax: 0.15, fill: true,
  })
}

export function emptyCutPaperScene(name: string, duration: number): Scene {
  return {
    version: 1, name, width: 1280, height: 720, fps: 30, duration,
    layers: [cutPaperCamera(duration)],
    generationPolicy: 'provided_only',
  }
}

export function assertCutPaperKitHasNoPrivateGlb(scene: Scene) {
  const glb = scene.layers.filter(layer => /\.glb(\?|$)/i.test(layer.source) || layer.type === 'model3d')
  if (glb.length) throw new Error(`${CUT_PAPER_KIT_ID} must not use private GLB bodies (${glb.map(layer => layer.id).join(', ')})`)
  if (scene.layers.some(layer => layer.source.includes('tv-head-humanoid'))) {
    throw new Error(`${CUT_PAPER_KIT_ID} must not use tv-head-humanoid.glb`)
  }
}

export function cutPaperKitManifest() {
  return {
    id: CUT_PAPER_KIT_ID,
    root: CUT_PAPER_PUBLIC_ROOT,
    characters: CUT_PAPER_CAST.map(item => item.id),
    pieces: [...CUT_PAPER_PIECES],
    visemes: [...CUT_PAPER_VISEMES],
  }
}
