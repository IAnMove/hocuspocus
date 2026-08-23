import type { OutputFile, Scene } from '../types'

export const PENDING_SCENE_KEY = 'maestro_scene_animator_pending_scene'

export async function stageSceneForEditor(file: OutputFile): Promise<Scene> {
  const response = await fetch(file.url)
  if (!response.ok) throw new Error('Could not load the saved scene')
  const scene = await response.json() as Scene
  if (scene.version !== 1 || !Array.isArray(scene.layers)) {
    throw new Error('The selected output is not a valid Loreframe Lab scene')
  }
  sessionStorage.setItem(PENDING_SCENE_KEY, JSON.stringify(scene))
  return scene
}
