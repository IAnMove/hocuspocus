import type { ApiOutput } from '../api/client'
import type { Scene } from '../types'
import { parseSceneFile } from './sceneFile'

export const SCENE_LIBRARY_PAGE_SIZE = 8

export const isCompositorVideo = (file: Pick<ApiOutput, 'type' | 'mode' | 'name'>) => (
  file.type === 'video'
  && (
    file.mode === '3d-scene-compositor'
    || /_3d_[a-f0-9]{6}\.(mp4|webm)$/i.test(file.name)
  )
)

export const sceneLibraryTitle = (name: string) => {
  const stem = name
    .replace(/\.scene\.json$/i, '')
    .replace(/\.(mp4|webm)$/i, '')
    .replace(/^\d{4}-\d{2}-\d{2}-\d{2}h\d{2}m\d{2}s_/, '')
    .replace(/_3d_[a-f0-9]{6}$/i, '')
    .replace(/_[a-f0-9]{6}$/i, '')
  return stem.replace(/[-_]+/g, ' ').trim() || name
}

export const normalizeSceneLookupName = (value: string) => value
  .normalize('NFD')
  .replace(/[\u0300-\u036f]/g, '')
  .replace(/[^a-zA-Z0-9]+/g, ' ')
  .trim()
  .toLowerCase()

export const sceneOutputMatchesName = (file: Pick<ApiOutput, 'name'>, requestedName: string) => {
  const requested = normalizeSceneLookupName(requestedName)
  return Boolean(requested) && (
    normalizeSceneLookupName(file.name) === requested
    || normalizeSceneLookupName(sceneLibraryTitle(file.name)) === requested
  )
}

export const sceneFromLibraryPayload = (payload: unknown): Scene => {
  if (payload && typeof payload === 'object' && !Array.isArray(payload)) {
    const record = payload as Record<string, unknown>
    if (record.version === 1 && Array.isArray(record.layers)) return parseSceneFile(JSON.stringify(record))
    const params = record.params
    if (params && typeof params === 'object' && !Array.isArray(params)) {
      const scene = (params as Record<string, unknown>).scene
      if (scene) return parseSceneFile(JSON.stringify(scene))
    }
    if (record.scene) return parseSceneFile(JSON.stringify(record.scene))
  }
  throw new Error('This output does not contain a 3D Video scene.')
}
