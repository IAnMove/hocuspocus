import { useStore } from '../../stores/useStore'
import { galleryWorkspaceEpoch, galleryWorkspaceName } from '../../stores/gallerySlice'
import { parseScene3DDocument } from '../scene3d/document'
import { parseSceneFile } from '../../lib/sceneFile'
import { presentSceneDocument } from './handoff'

export type ScenePreparationCommand = { version: 1; operation: string; input: Record<string, unknown> }
const operations = ['scenes.effects.apply', 'scenes.effects.showcase', 'scenes.speech.prepare']
export function isScenePreparationCommand(raw: unknown): raw is ScenePreparationCommand {
  if (!raw || typeof raw !== 'object') return false
  const value = raw as ScenePreparationCommand
  return value.version === 1 && operations.includes(value.operation) && !!value.input && typeof value.input === 'object' && !Array.isArray(value.input)
}

export async function prepareWizardScene(command: ScenePreparationCommand) {
  const source = { epoch: galleryWorkspaceEpoch(), workspace: galleryWorkspaceName(useStore.getState()) }
  const current = () => source.epoch === galleryWorkspaceEpoch()
    && source.workspace === galleryWorkspaceName(useStore.getState())
  const response = await fetch('/api/v1/scenes/commands', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(command) })
  const receipt = await response.json() as { status?: string; detail?: string; result?: { state: string; document: unknown; sha256: string } }
  if (!response.ok || receipt.status !== 'completed' || receipt.result?.state !== 'prepared') throw new Error(receipt.detail || 'Scene preparation failed.')
  const world = parseScene3DDocument(receipt.result.document)
  const document = world ?? parseSceneFile(JSON.stringify(receipt.result.document))
  // Keep the actual service result before changing navigation. Presentation failures cannot lose it.
  sessionStorage.setItem('hocuspocus:prepared-scene:' + receipt.result.sha256, JSON.stringify(document))
  if (!current()) throw new Error('Workspace changed while preparing the scene. The returned document remains recoverable.')
  const state = useStore.getState()
  state.setSettingsOpen(false); state.setDashboardOpen(false); state.setMediaFilter(world ? 'world3d' : 'scene3d')
  await presentSceneDocument(world ? '3d' : '2d', document, current)
  const speechDrivers = world ? [...new Set(world.slots.flatMap(slot => slot.speech?.clips?.map(clip => clip.driver) ?? (slot.speech ? [slot.speech.driver] : [])))] : []
  const speechFallback = world?.slots.some(slot => slot.speech?.analysisFallback || slot.speech?.clips?.some(clip => clip.analysisFallback)) ?? false
  return { message: 'Scene prepared and opened in the editor. Save or export it there; no video has been exported.',
    target: { kind: 'video_3d_scene' as const, id: receipt.result.sha256, title: world ? world.templateId : 'Scene SFX' },
    metadata: { prepared: true, exported: false, documentDigest: receipt.result.sha256, speechDrivers, speechFallback } }
}
