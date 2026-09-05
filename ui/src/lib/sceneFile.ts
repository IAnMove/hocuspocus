import type { Scene, SceneLayer } from '../types'

const LOCAL_OBJECT_URL = /^blob:/i
const SCENE_LAYER_TYPES = new Set<SceneLayer['type']>([
  'model3d', 'image', 'video', 'overlay', 'effect', 'camera',
])

function finiteOr(value: unknown, fallback: number): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback
}

export const prepareSceneForExport = (scene: Scene): Scene => ({
  ...scene,
  version: 1,
  layers: scene.layers.map(layer => {
    if (layer.type === 'camera' || !LOCAL_OBJECT_URL.test(layer.source)) return { ...layer }
    return {
      ...layer,
      source: '',
      thumbnail: layer.thumbnail && LOCAL_OBJECT_URL.test(layer.thumbnail) ? undefined : layer.thumbnail,
      missingAsset: true,
    }
  }),
})

export const serializeSceneFile = (scene: Scene) => JSON.stringify(prepareSceneForExport(scene), null, 2)

export const parseSceneFile = (text: string): Scene => {
  const normalized = text.replace(/^\uFEFF/, '').trim()
  if (!normalized) throw new Error('The selected scene file is empty.')
  const parsed: unknown = JSON.parse(normalized)
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('The scene JSON must contain an object.')
  const candidate = parsed as Partial<Scene>
  if (candidate.version !== 1 || !Array.isArray(candidate.layers)) throw new Error('This is not a HocusPocus Scene Animator scene.')
  const ids = new Set<string>()
  candidate.layers.forEach((layer, index) => {
    if (!layer || typeof layer !== 'object') throw new Error(`Layer ${index + 1} is not an object.`)
    const id = (layer as { id?: unknown }).id
    const type = (layer as { type?: unknown }).type
    if (typeof id !== 'string' || !id.trim()) throw new Error(`Layer ${index + 1} needs a valid id.`)
    if (ids.has(id)) throw new Error('Every scene layer must have a unique id.')
    ids.add(id)
    if (typeof type !== 'string' || !SCENE_LAYER_TYPES.has(type as SceneLayer['type'])) {
      throw new Error(`Unsupported scene layer type: ${String(type ?? 'missing')}`)
    }
  })
  const width = finiteOr(candidate.width, 1280)
  const height = finiteOr(candidate.height, 720)
  const duration = finiteOr(candidate.duration, 1)
  if (width <= 0 || height <= 0) throw new Error('Scene width and height must be positive.')
  return {
    ...(candidate as Scene),
    version: 1,
    width,
    height,
    duration: duration > 0 ? duration : 1,
    fps: candidate.fps === 60 ? 60 : 30,
    layers: candidate.layers as Scene['layers'],
  }
}

export const sceneFileName = (name: string) => {
  const slug = name
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-zA-Z0-9._-]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 80)
  return `${slug || 'maestro-scene'}.maestro-scene.json`
}
