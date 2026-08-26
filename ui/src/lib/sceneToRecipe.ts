import type { Scene, SceneLayer } from '../types'
import type { SceneRecipe, SceneRecipeAsset, SceneRecipeLayer } from './sceneRecipe'

/**
 * The recipe representation of a layer contains authored scene state that is
 * intentionally not interpreted here.  The recipe parser/compiler can decide
 * which of these fields are transportable without making this conversion
 * depend on UI state or renderer defaults.
 */
export type SerializedSceneRecipeLayer = SceneRecipeLayer & {
  visible?: boolean
  locked?: boolean
  seamlessHorizontal?: boolean
  relationship?: SceneLayer['relationship']
  strip?: SceneLayer['strip']
  effects?: SceneLayer['effects']
}

const assetKindForLayer = (layer: SceneLayer): SceneRecipeAsset['kind'] | undefined => {
  if (layer.type === 'model3d' || layer.type === 'image' || layer.type === 'video') return layer.type
  // Overlay layers use image assets in the recipe contract.
  if (layer.type === 'overlay') return 'image'
  return undefined
}

const cloneLayerAnimation = (layer: SceneLayer): SceneLayer['animation'] => ({
  ...layer.animation,
  start: { ...layer.animation.start },
  end: { ...layer.animation.end },
  keyframes: layer.animation.keyframes?.map(keyframe => ({ ...keyframe })),
  events: layer.animation.events?.map(event => ({ ...event })),
  shake: layer.animation.shake ? { ...layer.animation.shake } : undefined,
  orbit: layer.animation.orbit ? { ...layer.animation.orbit } : undefined,
})

const cloneLayer = (layer: SceneLayer, asset?: string): SerializedSceneRecipeLayer => ({
  id: layer.id,
  name: layer.name || undefined,
  type: layer.type,
  asset,
  source: layer.source || undefined,
  fill: layer.fill || undefined,
  parallax: layer.parallax,
  z: layer.z,
  seamlessHorizontal: layer.seamlessHorizontal,
  locked: layer.locked,
  visible: layer.visible,
  relationship: layer.relationship ? { ...layer.relationship } : undefined,
  strip: layer.strip
    ? {
        ...layer.strip,
        seamOccluder: layer.strip.seamOccluder ? { ...layer.strip.seamOccluder } : undefined,
      }
    : undefined,
  atmosphere: layer.atmosphere?.kind,
  transform: { ...layer.transform },
  animation: cloneLayerAnimation(layer),
  effects: layer.effects ? { ...layer.effects } : undefined,
  // The recipe contract currently exposes rig timing at layer level too.
  clip: layer.animation.clip as SerializedSceneRecipeLayer['clip'],
  clipSpeed: layer.animation.clipSpeed,
  clipLoop: layer.animation.clipLoop,
})

/**
 * Serialize an edited Scene into the recipe vocabulary without applying any
 * renderer defaults.  The function is pure: it never mutates the Scene and
 * every nested authored object is copied before being returned.
 */
export function sceneToRecipe(scene: Scene): SceneRecipe {
  const assets: SceneRecipeAsset[] = []
  const assetIds = new Map<string, string>()
  let assetIndex = 1
  const recipeLayers = scene.layers.map(layer => {
    const kind = assetKindForLayer(layer)
    if (!kind || !layer.source) return cloneLayer(layer)
    const key = `${kind}:${layer.source}`
    let assetId = assetIds.get(key)
    if (!assetId) {
      assetId = `asset-${assetIndex++}`
      assetIds.set(key, assetId)
      assets.push({ id: assetId, kind, source: layer.source, ...(layer.seamlessHorizontal ? { seamlessHorizontal: true } : {}) })
    }
    return cloneLayer(layer, assetId)
  })

  return {
    version: 1,
    name: scene.name,
    record: false,
    save: false,
    assets,
    audio: scene.audioTracks?.flatMap(track => track.kind === 'audio' ? [] : [{
      id: track.id,
      kind: track.kind,
      source: track.filename,
      name: track.name,
      startTime: track.startTime,
      volume: track.volume,
      prompt: track.prompt,
    }]),
    dialogueBeats: scene.dialogueBeats?.map(beat => ({ ...beat, mouthLayerIds: [...beat.mouthLayerIds] })),
    scene: {
      width: scene.width,
      height: scene.height,
      fps: scene.fps === 60 ? 60 : 30,
      duration: scene.duration,
      layers: recipeLayers as SceneRecipeLayer[],
    },
  }
}

// A descriptive alias for callers that prefer an explicit serialization name.
export const serializeSceneToRecipe = sceneToRecipe
