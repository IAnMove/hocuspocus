import { fetchAsset, type AssetCatalogItem } from '../../api/assets'
import type { SceneTemplateDefinition, SceneTemplateSlot, TemplateSlotName } from './catalog'
import type { TemplateAsset, TemplateBindings } from './sceneBuilders'
import { catalogLocation } from './catalogLocation'

export type CatalogSelections = Partial<Record<TemplateSlotName, AssetCatalogItem>>

/** Strict product path. Inline demo artwork is intentionally handled elsewhere. */
export function catalogAssetBinding(item: AssetCatalogItem, workspace: string, slot: SceneTemplateSlot): TemplateAsset {
  if (!item.id?.trim() || item.metadata_status !== 'canonical') throw new Error('Needs a canonical Library identity and metadata; legacy files are not migrated automatically.')
  if ((item.kind !== 'image' && item.kind !== 'model3d') || !slot.kinds.includes(item.kind)) throw new Error(`El slot ${slot.id} no admite ${item.kind}.`)
  const location = catalogLocation(item, workspace)
  if (item.kind === 'model3d' && !/\.glb$/i.test(location.filename)) throw new Error('The compositor needs a GLB, not another 3D format.')
  return { source: location.url, type: item.kind, name: location.filename, catalogAtAssignment: {
    assetId: item.id, workspaceId: workspace, filename: location.filename, metadataStatus: 'canonical',
    originTool: item.origin.tool, provider: item.model.provider, modelId: item.model.id,
    runId: item.execution.run_id, taskId: item.execution.task_id,
  } }
}

export function catalogBindingIssue(item: AssetCatalogItem, workspace: string, slot: SceneTemplateSlot): string | undefined {
  try { catalogAssetBinding(item, workspace, slot); return undefined }
  catch (error) { return error instanceof Error ? error.message : 'Asset unavailable.' }
}

/** Re-resolve by identity before compiling; a stale filename is never a fallback.
 * Missing metadata/files require user repair, not a call to a generator. */
export async function resolveCatalogBindings(template: SceneTemplateDefinition, selections: CatalogSelections, workspace: string, signal: AbortSignal): Promise<TemplateBindings> {
  const bindings: TemplateBindings = {}
  for (const slot of template.slots) {
    const selected = selections[slot.id]
    if (!selected) {
      if (slot.required) throw new Error(`Required slot ${slot.id} is missing.`)
      continue
    }
    const current = await fetchAsset(selected.id, signal)
    signal.throwIfAborted()
    if (current.id !== selected.id || current.kind !== selected.kind) throw new Error('The asset\'s identity or type changed. Select it again.')
    const previous = catalogAssetBinding(selected, workspace, slot)
    const next = catalogAssetBinding(current, workspace, slot)
    if (next.source !== previous.source) throw new Error('The asset\'s location changed. Select it again to review its content.')
    bindings[slot.id] = next
  }
  return bindings
}
