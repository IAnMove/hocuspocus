import type { ApiOutput } from '../../api/outputs'
import { getWorld3DWorkingScene, type World3DWorkingScene } from '../../api/world3dWorkspace'
import { parseScene3DDocument } from './document'
import { loadWorld3DOutput } from './sceneLibrary'
import type { Scene3DDocument } from './types'

/** Open dialog items whose url names a working scene (``w3d-…``), not a file. */
const WORKING_SCENE = 'working-scene:'

/** A working Video 3D scene an agent made and did not publish, as an Open dialog item with its own title. */
export function workingSceneItem(scene: World3DWorkingScene, title: string): ApiOutput {
  return {
    name: scene.sceneId, type: 'scene', mode: null, size: 0, created_at: scene.updatedAt, url: `${WORKING_SCENE}${scene.sceneId}`,
    thumbnail_url: null, display_title: title,
  }
}

/** The document of an Open dialog item: a saved scene file, or the current revision of a working scene. */
export async function loadLibraryItem(item: ApiOutput, workspace: string, signal?: AbortSignal): Promise<Scene3DDocument> {
  if (!item.url.startsWith(WORKING_SCENE)) return loadWorld3DOutput(item, workspace, signal)
  const document = parseScene3DDocument(await getWorld3DWorkingScene(workspace, item.url.slice(WORKING_SCENE.length)))
  if (!document) throw new Error('Invalid Video3D scene')
  return document
}
