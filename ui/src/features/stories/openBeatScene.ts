import { useStore } from '../../stores/useStore'
import { parseScene3DDocument } from '../scene3d/document'
import { presentSceneDocument } from '../sceneFx/handoff'
import { parseSceneFile } from '../../lib/sceneFile'
import type { StoryBeatSceneLink } from './types'

/** Load a bundled beat scene into Video 2D or Video 3D so the user can edit it. */
export async function openStoryBeatScene(link: StoryBeatSceneLink) {
  const response = await fetch(link.href)
  if (!response.ok) throw new Error('Could not load the beat scene.')
  const raw = await response.text()
  if (link.editor === 'video3d') {
    const document = parseScene3DDocument(JSON.parse(raw))
    if (!document) throw new Error('The beat is not a valid Video 3D scene.')
    useStore.getState().setMediaFilter('world3d')
    await presentSceneDocument('3d', document)
    return
  }
  const scene = parseSceneFile(raw)
  useStore.getState().setMediaFilter('scene3d')
  await presentSceneDocument('2d', scene)
}
