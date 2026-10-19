import type { ApiOutput } from '../../api/outputs'
import type { AssetCatalogItem } from '../../api/assets'

export type TemplateSlotCapture = {
  generation: number
  workspaceId: string
  slotId: string
}

export type TemplateSlotLive = {
  generation: number
  workspaceId: string
  slotId: string
}

export type TemplateSlotCommit =
  | { action: 'ignore' }
  | { action: 'clear' }
  | { action: 'reject'; reasonKey: 'missing-id' }
  | { action: 'reject'; reasonKey: 'incompatible'; message: string }
  | { action: 'apply'; item: AssetCatalogItem }

export async function commitTemplateSlotChoice(
  live: TemplateSlotLive,
  capture: TemplateSlotCapture,
  item: ApiOutput | null,
  loadAsset: (id: string) => Promise<AssetCatalogItem>,
  bindingIssue: (asset: AssetCatalogItem) => string | undefined,
): Promise<TemplateSlotCommit> {
  if (live.generation !== capture.generation) return { action: 'ignore' }
  if (live.workspaceId !== capture.workspaceId) return { action: 'ignore' }
  if (live.slotId !== capture.slotId) return { action: 'ignore' }
  if (!item) return { action: 'clear' }
  const id = typeof item.asset_id === 'string' ? item.asset_id.trim() : ''
  if (!id) return { action: 'reject', reasonKey: 'missing-id' }
  const asset = await loadAsset(id)
  if (live.generation !== capture.generation) return { action: 'ignore' }
  if (live.workspaceId !== capture.workspaceId) return { action: 'ignore' }
  if (live.slotId !== capture.slotId) return { action: 'ignore' }
  const issue = bindingIssue(asset)
  if (issue) return { action: 'reject', reasonKey: 'incompatible', message: issue }
  return { action: 'apply', item: asset }
}

export function acceptForSlotKinds(kinds: readonly ('image' | 'model3d' | 'video')[]): string {
  const parts: string[] = []
  if (kinds.includes('image')) parts.push('image/*')
  if (kinds.includes('video')) parts.push('video/*')
  if (kinds.includes('model3d')) parts.push('.glb,model/gltf-binary')
  return parts.join(',')
}
