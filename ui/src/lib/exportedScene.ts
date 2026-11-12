import { parseScene3DDocument } from '../features/scene3d/document'
import { useStore } from '../stores/useStore'
import { galleryWorkspaceEpoch, galleryWorkspaceName } from '../stores/gallerySlice'
import { parseSceneFile } from './sceneFile'

type Params = Record<string, unknown> | null | undefined

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

/**
 * A Video 2D or Video 3D export keeps the exact scene it rendered in its
 * sidecar (``scene_recipe`` and, for 2D, ``scene``). Whoever made it, an agent
 * through MCP or the user, can reopen that scene in its editor.
 */
export function exportedSceneKind(params: Params): '2d' | '3d' | null {
  const recipe = params?.scene_recipe
  if (!isRecord(recipe)) return null
  if (recipe.engine === 'world3d' && isRecord(recipe.document)) return '3d'
  const scene = params?.scene
  if (recipe.engine === 'video2d' && isRecord(scene) && Array.isArray(scene.layers)) return '2d'
  return null
}

function exportedDocument(kind: '2d' | '3d', params: Record<string, unknown>): unknown {
  if (kind === '3d') return parseScene3DDocument((params.scene_recipe as Record<string, unknown>).document)
  return parseSceneFile(JSON.stringify(params.scene))
}

/** Open the scene behind an exported video in Video 3D (world3d) or Video 2D. Rejects with a readable reason. */
export async function openExportedScene(params: Params): Promise<void> {
  const kind = exportedSceneKind(params)
  if (!kind || !params) throw new Error('This video does not carry the scene it was rendered from.')
  const document = exportedDocument(kind, params)
  if (!document) throw new Error('The scene saved with this video is not valid.')
  const epoch = galleryWorkspaceEpoch()
  const workspace = galleryWorkspaceName(useStore.getState())
  const current = () => epoch === galleryWorkspaceEpoch() && workspace === galleryWorkspaceName(useStore.getState())
  const app = useStore.getState()
  app.setDashboardOpen(false)
  app.setMediaFilter(kind === '3d' ? 'world3d' : 'scene3d')
  const { presentSceneDocument } = await import('../features/sceneFx/handoff')
  await presentSceneDocument(kind, document, current)
}
