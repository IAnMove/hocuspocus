import { makeBlob } from '../../api/blobBody'
import { useStore } from '../../stores/useStore'
import type { AgentBlobMakeAction } from './agentActions'

export async function executeBlobMake(action: AgentBlobMakeAction, workspace?: string) {
  const active = workspace || useStore.getState().activeWorkspace
  const result = await makeBlob({
    workspace: active,
    name: action.name,
    preset: action.preset || undefined,
    height: action.height,
    build: action.build,
    headWidth: action.headWidth,
    hands: action.hands,
    feet: action.feet,
    family: action.family,
    hairStyle: action.hairStyle,
  })
  const store = useStore.getState()
  if (store.mediaFilter !== 'model3d') store.setMediaFilter('model3d')
  await store.maybeRefreshGallery({ message: 'Blob listo', force: true })
  store.setSelectedOutput(0)
  return {
    message: `Built ${result.rigged_file}. It is in the 3D gallery.`,
    target: { kind: 'output', id: result.rigged_file, title: action.name || 'Blob' },
    outputNames: [result.rigged_file, result.file],
    metadata: { ...result },
  }
}
