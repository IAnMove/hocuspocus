import type { Scene } from '../types'

const LOCAL_OBJECT_URL = /^blob:/i

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
  if (!parsed || typeof parsed !== 'object') throw new Error('The scene JSON must contain an object.')
  const candidate = parsed as Partial<Scene>
  if (candidate.version !== 1 || !Array.isArray(candidate.layers)) throw new Error('This is not a Loreframe Lab Scene Animator scene.')
  return candidate as Scene
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
