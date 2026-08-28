import type { SceneFaceBindingState, SceneLayer } from '../types'

export type CharacterKitStyle = 'cutout' | 'children-illustration' | 'anime-2d'
export type CharacterKitReviewState = 'pending' | 'approved' | 'rejected'
export type CharacterKitAlphaStatus = 'unknown' | 'transparent' | 'opaque'
export type CharacterMouthState = 'closed' | 'small' | 'wide' | 'round'

export interface CharacterKitAsset {
  id: string
  name: string
  source: string
  kind: 'image' | 'overlay'
  alphaStatus: CharacterKitAlphaStatus
  reviewState: CharacterKitReviewState
  prompt?: string
  model?: string
  workspace?: string
}

export interface CharacterFaceAnchor {
  offsetX: number
  offsetY: number
  scale: number
  rotation: number
}

export interface CharacterKit {
  version: 1
  id: string
  name: string
  style: CharacterKitStyle
  identityReference?: CharacterKitAsset
  base?: CharacterKitAsset
  poses: Record<string, CharacterKitAsset>
  mouth: Partial<Record<CharacterMouthState, CharacterKitAsset>>
  eyes: Partial<Record<'open' | 'blink', CharacterKitAsset>>
  anchors: Record<string, { mouth: CharacterFaceAnchor; eyes?: CharacterFaceAnchor }>
  provenance: Array<Record<string, unknown>>
  createdAt?: string
  updatedAt?: string
}

export interface CharacterKitLibrary {
  version: 1
  revision: number
  activeId: string
  kits: Record<string, CharacterKit>
}

export const emptyCharacterKitLibrary = (): CharacterKitLibrary => ({ version: 1, revision: 0, activeId: '', kits: {} })

const cleanId = (value: string) => value.trim().toLocaleLowerCase().replace(/[^a-z0-9._-]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 120)

export function createCharacterKit(name: string, style: CharacterKitStyle = 'cutout'): CharacterKit {
  const now = new Date().toISOString()
  const id = cleanId(name) || `character-${Date.now().toString(36)}`
  return { version: 1, id, name: name.trim() || 'Untitled character', style, poses: {}, mouth: {}, eyes: {}, anchors: {}, provenance: [], createdAt: now, updatedAt: now }
}

export function characterKitAssetFromLayer(
  layer: SceneLayer,
  workspace: string,
  options: { alphaStatus?: CharacterKitAlphaStatus; reviewState?: CharacterKitReviewState; prompt?: string; model?: string } = {},
): CharacterKitAsset {
  if (layer.type !== 'image' && layer.type !== 'overlay') throw new Error('Character Kit assets must be image or overlay layers.')
  if (!layer.source || layer.source.startsWith('blob:')) throw new Error('Save or upload this layer before adding it to a Character Kit.')
  return {
    id: cleanId(layer.id) || `asset-${Date.now().toString(36)}`,
    name: layer.name,
    source: layer.source,
    kind: layer.type,
    alphaStatus: options.alphaStatus ?? (layer.type === 'overlay' ? 'unknown' : 'opaque'),
    reviewState: options.reviewState ?? 'pending',
    workspace,
    ...(options.prompt ? { prompt: options.prompt } : {}),
    ...(options.model ? { model: options.model } : {}),
  }
}

export function captureCharacterFaceAnchor(pose: SceneLayer, face: SceneLayer): CharacterFaceAnchor {
  const poseScale = Math.max(.001, pose.transform.scale)
  return {
    offsetX: face.transform.x - pose.transform.x,
    offsetY: face.transform.y - pose.transform.y,
    scale: face.transform.scale / poseScale,
    rotation: (face.transform.rotation ?? 0) - (pose.transform.rotation ?? 0),
  }
}

const stateForBinding = (state: CharacterMouthState): SceneFaceBindingState => state

export function mountCharacterKitLayers(
  kit: CharacterKit,
  poseId = 'base',
  transform: SceneLayer['transform'] = { x: 50, y: 55, scale: .72, opacity: 1, rotation: 0 },
  duration = 10,
): SceneLayer[] {
  const poseAsset = poseId === 'base' ? kit.base : kit.poses[poseId]
  if (!poseAsset) throw new Error(`Character Kit “${kit.name}” has no ${poseId} pose.`)
  if (poseAsset.reviewState !== 'approved') throw new Error(`Review and approve ${poseAsset.name} before mounting it.`)
  const poseLayerId = `kit-${kit.id}-pose-${cleanId(poseId) || 'base'}`
  const animation = { start: { ...transform }, end: { ...transform }, duration, curve: 'hold' as const }
  const pose: SceneLayer = {
    id: poseLayerId, name: `${kit.name} · ${poseId}`, type: 'image', source: poseAsset.source,
    visible: true, locked: false, z: 20, fill: false, parallax: 1, transform: { ...transform }, animation,
  }
  const anchors = kit.anchors[poseId] ?? kit.anchors.base
  const mouthAnchor = anchors?.mouth ?? { offsetX: 0, offsetY: 0, scale: .16, rotation: 0 }
  const faceTransform = (anchor: CharacterFaceAnchor) => ({
    x: transform.x + anchor.offsetX,
    y: transform.y + anchor.offsetY,
    scale: transform.scale * anchor.scale,
    opacity: 1,
    rotation: (transform.rotation ?? 0) + anchor.rotation,
  })
  const layers: SceneLayer[] = [pose]
  let z = 21
  for (const state of ['closed', 'small', 'wide', 'round'] as const) {
    const asset = kit.mouth[state]
    if (!asset || asset.reviewState !== 'approved') continue
    const mouthTransform = faceTransform(mouthAnchor)
    layers.push({
      id: `kit-${kit.id}-mouth-${state}`, name: `${kit.name} Mouth ${state}`, type: 'overlay', source: asset.source,
      visible: true, locked: false, z: z++, fill: false, parallax: 1, transform: mouthTransform,
      animation: { start: { ...mouthTransform, opacity: state === 'closed' ? 1 : 0 }, end: { ...mouthTransform, opacity: state === 'closed' ? 1 : 0 }, duration, curve: 'hold' },
      faceBinding: { poseLayerId, role: 'mouth', state: stateForBinding(state) },
      relationship: { type: 'parent', targetLayerId: poseLayerId },
    })
  }
  const blink = kit.eyes.blink
  if (blink?.reviewState === 'approved') {
    const eyeTransform = faceTransform(anchors?.eyes ?? mouthAnchor)
    layers.push({
      id: `kit-${kit.id}-eyes-blink`, name: `${kit.name} Eyes blink`, type: 'overlay', source: blink.source,
      visible: true, locked: false, z: z++, fill: false, parallax: 1, transform: eyeTransform,
      animation: { start: { ...eyeTransform, opacity: 0 }, end: { ...eyeTransform, opacity: 0 }, duration, curve: 'hold' },
      faceBinding: { poseLayerId, role: 'blink', state: 'blink' },
      relationship: { type: 'parent', targetLayerId: poseLayerId },
    })
  }
  return layers
}

export function characterKitInventory(library: CharacterKitLibrary): Array<Record<string, unknown>> {
  return Object.values(library.kits).map(kit => ({
    id: kit.id,
    name: kit.name,
    style: kit.style,
    poses: [kit.base?.reviewState === 'approved' ? 'base' : '', ...Object.entries(kit.poses).filter(([, asset]) => asset.reviewState === 'approved').map(([id]) => id)].filter(Boolean),
    mouth: Object.entries(kit.mouth).filter(([, asset]) => asset?.reviewState === 'approved').map(([state]) => state),
    eyes: Object.entries(kit.eyes).filter(([, asset]) => asset?.reviewState === 'approved').map(([state]) => state),
  }))
}
