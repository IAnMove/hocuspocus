import type { SceneFaceBindingState, SceneLayer } from '../types'
import type { SceneRecipeInventoryItem } from './sceneRecipe'

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
  anchors: Record<string, {
    /** Legacy/default mouth placement used when a state-specific anchor is absent. */
    mouth: CharacterFaceAnchor
    /** Optional per-mouth-state placement for generated facial variants. */
    mouthStates?: Partial<Record<CharacterMouthState, CharacterFaceAnchor>>
    eyes?: CharacterFaceAnchor
  }>
  provenance: Array<Record<string, unknown>>
  /** Style + traits the user picked; Face Rig fills overlay prompts from this. */
  lookNotes?: string
  createdAt?: string
  updatedAt?: string
}

/** Pose-local mouth placement: percent of the character, not of the 16:9 frame. */
export const DEFAULT_CHARACTER_MOUTH_ANCHOR: CharacterFaceAnchor = { offsetX: 0, offsetY: -18, scale: .05, rotation: 0 }
/** Pose-local blink placement. Smaller than a mouth pack that covers the whole head. */
export const DEFAULT_CHARACTER_BLINK_ANCHOR: CharacterFaceAnchor = { offsetX: 0, offsetY: -28, scale: .12, rotation: 0 }

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

/** Attach a generated full-body pose as pending review. Does not approve it. */
export function registerGeneratedKitPose(
  kit: CharacterKit,
  poseId: string,
  asset: CharacterKitAsset,
): CharacterKit {
  const normalizedPoseId = poseId.trim() || 'base'
  if (!asset.source || asset.source.startsWith('blob:')) throw new Error('Generated poses need a persistent source.')
  const nextAsset: CharacterKitAsset = { ...asset, kind: 'image', reviewState: 'pending' }
  return {
    ...kit,
    base: normalizedPoseId === 'base' ? nextAsset : kit.base,
    poses: normalizedPoseId === 'base' ? kit.poses : { ...kit.poses, [normalizedPoseId]: nextAsset },
    provenance: [...kit.provenance, { method: 'character-kit-pose-generate', poseId: normalizedPoseId, source: nextAsset.source }],
    updatedAt: new Date().toISOString(),
  }
}

/** Replace a pose with a mouth-wiped copy. Keeps review state; does not delete the original file. */
export function registerWipedKitPose(
  kit: CharacterKit,
  poseId: string,
  asset: CharacterKitAsset,
): CharacterKit {
  const normalizedPoseId = poseId.trim() || 'base'
  if (!asset.source || asset.source.startsWith('blob:')) throw new Error('Wiped poses need a persistent source.')
  const current = normalizedPoseId === 'base' ? kit.base : kit.poses[normalizedPoseId]
  if (!current) throw new Error(`Character Kit “${kit.name}” has no ${normalizedPoseId} pose to wipe.`)
  const nextAsset: CharacterKitAsset = {
    ...current,
    ...asset,
    kind: 'image',
    reviewState: current.reviewState === 'approved' ? 'approved' : 'pending',
  }
  return {
    ...kit,
    base: normalizedPoseId === 'base' ? nextAsset : kit.base,
    poses: normalizedPoseId === 'base' ? kit.poses : { ...kit.poses, [normalizedPoseId]: nextAsset },
    provenance: [...kit.provenance, {
      method: 'character-kit-mouth-wipe',
      poseId: normalizedPoseId,
      original: current.source,
      source: nextAsset.source,
    }],
    updatedAt: new Date().toISOString(),
  }
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
    offsetX: (face.transform.x - pose.transform.x) / poseScale,
    offsetY: (face.transform.y - pose.transform.y) / poseScale,
    scale: face.transform.scale / poseScale,
    rotation: (face.transform.rotation ?? 0) - (pose.transform.rotation ?? 0),
  }
}

/** Map a pose-local Face Rig anchor onto a character at any scene scale. */
export function appliedCharacterFaceTransform(
  pose: SceneLayer['transform'],
  anchor: CharacterFaceAnchor,
): SceneLayer['transform'] {
  const poseScale = Math.max(.001, pose.scale)
  return {
    x: pose.x + anchor.offsetX * poseScale,
    y: pose.y + anchor.offsetY * poseScale,
    scale: poseScale * Math.max(.001, anchor.scale),
    opacity: 1,
    rotation: (pose.rotation ?? 0) + (anchor.rotation ?? 0),
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
  const mouthAnchor = anchors?.mouth ?? DEFAULT_CHARACTER_MOUTH_ANCHOR
  const faceTransform = (anchor: CharacterFaceAnchor) => appliedCharacterFaceTransform(transform, anchor)
  const layers: SceneLayer[] = [pose]
  let z = 21
  for (const state of ['closed', 'small', 'wide', 'round'] as const) {
    const asset = kit.mouth[state]
    if (!asset || asset.reviewState !== 'approved') continue
    const mouthTransform = { ...faceTransform(anchors?.mouthStates?.[state] ?? mouthAnchor), opacity: state === 'closed' ? 1 : 0 }
    layers.push({
      id: `kit-${kit.id}-mouth-${state}`, name: `${kit.name} Mouth ${state}`, type: 'overlay', source: asset.source,
      visible: true, locked: false, z: z++, fill: false, parallax: 1, transform: mouthTransform,
      animation: { start: { ...mouthTransform, opacity: state === 'closed' ? 1 : 0 }, end: { ...mouthTransform, opacity: state === 'closed' ? 1 : 0 }, duration, curve: 'hold' },
      faceBinding: { poseLayerId, role: 'mouth', state: stateForBinding(state) },
      relationship: { type: 'parent', targetLayerId: poseLayerId },
    })
  }
  const openEyes = kit.eyes.open
  if (openEyes?.reviewState === 'approved') {
    const openTransform = { ...faceTransform(anchors?.eyes ?? DEFAULT_CHARACTER_BLINK_ANCHOR), opacity: 1 }
    layers.push({
      id: `kit-${kit.id}-eyes-open`, name: `${kit.name} Eyes open`, type: 'overlay', source: openEyes.source,
      visible: true, locked: false, z: z++, fill: false, parallax: 1, transform: openTransform,
      animation: { start: { ...openTransform, opacity: 1 }, end: { ...openTransform, opacity: 1 }, duration, curve: 'hold' },
      faceBinding: { poseLayerId, role: 'eyes', state: 'open' },
      relationship: { type: 'parent', targetLayerId: poseLayerId },
    })
  }
  const blink = kit.eyes.blink
  if (blink?.reviewState === 'approved') {
    const eyeTransform = { ...faceTransform(anchors?.eyes ?? DEFAULT_CHARACTER_BLINK_ANCHOR), opacity: 0 }
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

/** Push current Face Rig anchors onto a pose that is already in the scene. */
export function syncMountedCharacterKitLayers(
  layers: SceneLayer[],
  kit: CharacterKit,
  poseId = 'base',
): SceneLayer[] {
  const poseLayerId = `kit-${kit.id}-pose-${cleanId(poseId) || 'base'}`
  const pose = layers.find(layer => layer.id === poseLayerId)
  if (!pose) return layers
  const mounted = mountCharacterKitLayers(kit, poseId, pose.transform, pose.animation?.duration ?? 10)
  const byId = new Map(mounted.map(layer => [layer.id, layer]))
  const next = layers.map(layer => {
    const replacement = byId.get(layer.id)
    if (!replacement) return layer
    const keyframes = layer.animation?.keyframes
    if (keyframes?.length) {
      return {
        ...layer,
        source: replacement.source,
        transform: { ...replacement.transform, opacity: layer.transform.opacity },
        animation: {
          ...layer.animation,
          start: { ...replacement.animation.start, opacity: layer.animation.start.opacity ?? 1 },
          end: { ...replacement.animation.end, opacity: layer.animation.end.opacity ?? 1 },
          keyframes: keyframes.map(frame => ({
            ...frame,
            x: replacement.transform.x,
            y: replacement.transform.y,
            scale: replacement.transform.scale,
            rotation: replacement.transform.rotation ?? frame.rotation ?? 0,
          })),
        },
      }
    }
    return { ...replacement, z: layer.z }
  })
  const extras = mounted.filter(layer => !layers.some(existing => existing.id === layer.id))
  if (!extras.length) return next
  const top = Math.max(...next.map(layer => layer.z), 20)
  return [...next, ...extras.map((layer, index) => ({ ...layer, z: top + index + 1 }))]
}

export function parseCharacterKitPoseLayerId(layerId: string): { kitId: string, poseId: string } | null {
  const match = /^kit-(.+)-pose-(.+)$/.exec(layerId)
  if (!match) return null
  return { kitId: match[1], poseId: match[2] }
}

/** Re-apply the live Character Kit library onto any kit puppets already in a scene. */
export function syncSceneCharacterKits(layers: SceneLayer[], library: CharacterKitLibrary): SceneLayer[] {
  const poseLayerIds = new Set<string>()
  for (const layer of layers) {
    if (parseCharacterKitPoseLayerId(layer.id)) poseLayerIds.add(layer.id)
    const bound = layer.faceBinding?.poseLayerId
    if (bound && parseCharacterKitPoseLayerId(bound)) poseLayerIds.add(bound)
  }
  let next = layers
  for (const poseLayerId of poseLayerIds) {
    const parsed = parseCharacterKitPoseLayerId(poseLayerId)
    const kit = parsed ? library.kits[parsed.kitId] : undefined
    if (!parsed || !kit) continue
    next = syncMountedCharacterKitLayers(next, kit, parsed.poseId)
  }
  return next
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

/** Flatten only reviewed kit pieces into the existing bounded recipe inventory.
 * The active kit is ordered first so its complete face set survives the global
 * inventory cap even in a large workspace. */
export function characterKitRecipeInventory(library: CharacterKitLibrary): SceneRecipeInventoryItem[] {
  const ordered = Object.values(library.kits).sort((a, b) => Number(b.id === library.activeId) - Number(a.id === library.activeId))
  return ordered.flatMap(kit => {
    const items: SceneRecipeInventoryItem[] = []
    const add = (asset: CharacterKitAsset | undefined, role: string) => {
      if (!asset || asset.reviewState !== 'approved') return
      items.push({
        name: `${kit.id}/${role}`,
        kind: 'image',
        source: asset.source,
        description: `APPROVED_CHARACTER_KIT id=${kit.id}; name=${kit.name}; style=${kit.style}; role=${role}; alpha=${asset.alphaStatus}. Keep body, pose and face pieces from this same kit.`,
      })
    }
    add(kit.base, 'base')
    for (const [poseId, asset] of Object.entries(kit.poses)) add(asset, `pose/${poseId}`)
    for (const [state, asset] of Object.entries(kit.mouth)) add(asset, `mouth/${state}`)
    for (const [state, asset] of Object.entries(kit.eyes)) add(asset, `eyes/${state}`)
    return items
  })
}
