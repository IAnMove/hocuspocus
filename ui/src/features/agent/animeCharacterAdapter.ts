import { makeAnime } from '../../api/blobBody'
import { useStore } from '../../stores/useStore'
import type { AgentAnimeMakeAction } from './agentActions'

export async function executeAnimeMake(action: AgentAnimeMakeAction, workspace?: string) {
  const active = workspace || useStore.getState().activeWorkspace
  const result = await makeAnime({
    workspace: active,
    name: action.name,
    gender: action.gender,
    body: action.body,
    height: action.height,
    skin: action.skin,
    eyeColor: action.eyeColor,
    hairStyle: action.hairStyle,
    hairColor: action.hairColor,
    outfit: action.outfit,
    faceSource: action.faceSource,
    faceImage: action.faceImage,
    faceStyle: action.faceStyle,
    faceShape: action.faceShape,
  })
  const store = useStore.getState()
  if (store.mediaFilter !== 'model3d') store.setMediaFilter('model3d')
  await store.maybeRefreshGallery({ message: 'Personaje anime listo', force: true })
  store.setSelectedOutput(0)
  return {
    message: `Built ${result.rigged_file} with face kit ${result.kit_id}. The body is in the 3D gallery, the face in Characters.`,
    target: { kind: 'output', id: result.rigged_file, title: action.name || 'Anime' },
    outputNames: [result.rigged_file, result.file],
    metadata: { ...result },
  }
}
