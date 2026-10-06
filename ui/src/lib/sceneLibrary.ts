import type { ApiOutput } from '../api/client'
import { parseScene3DDocument } from '../features/scene3d/document'
import type { Scene3DDocument } from '../features/scene3d/types'
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

/** A scene file's readable name: without the time stamp and the revision id a save appends
 *  (``_abc123`` from the editor, ``-<10 hex>`` from scenes.document.save, ``-<32 hex>.world3d`` from Video 3D). */
export const sceneLibraryTitle = (name: string) => {
  const stem = name
    .replace(/\.scene\.json$/i, '')
    .replace(/\.(mp4|webm)$/i, '')
    .replace(/\.world3d$/i, '')
    .replace(/^\d{4}-\d{2}-\d{2}-\d{2}h\d{2}m\d{2}s_/, '')
    .replace(/-[a-f0-9]{32}$/i, '')
    .replace(/-[a-f0-9]{10}$/i, '')
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

function libraryParams(payload: unknown): Record<string, unknown> | null {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) return null
  const record = payload as Record<string, unknown>
  const params = record.params
  if (params && typeof params === 'object' && !Array.isArray(params)) return params as Record<string, unknown>
  return record
}

function libraryRecipe(payload: unknown): Record<string, unknown> | null {
  const params = libraryParams(payload)
  if (!params) return null
  const recipe = params.scene_recipe ?? params.recipe
  return recipe && typeof recipe === 'object' && !Array.isArray(recipe)
    ? recipe as Record<string, unknown>
    : null
}

/** Video3D MP4 sidecars store the real document in the recipe and an empty 2D stub in `scene`. */
export const isWorld3DLibraryRecipe = (payload: unknown): boolean => libraryRecipe(payload)?.engine === 'world3d'

export const world3dDocumentFromLibraryPayload = (payload: unknown): Scene3DDocument | null => {
  const recipe = libraryRecipe(payload)
  return recipe?.engine === 'world3d' ? parseScene3DDocument(recipe.document) : null
}

export const sceneFromLibraryPayload = (payload: unknown): Scene => {
  if (isWorld3DLibraryRecipe(payload)) {
    throw new Error('This output is a Video3D export. Open it in Video 3D.')
  }
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
