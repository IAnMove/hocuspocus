import { fetchAsset, type AssetCatalogItem } from '../../api/assets'
import { requiredSlots, type ControlValue, type SceneTemplateDefinition, type SceneTemplateSlot, type TemplateSlotName } from './catalog'
import type { TemplateAsset, TemplateBindings } from './sceneBuilders'
import { catalogLocation } from './catalogLocation'

export type CatalogSelections = Partial<Record<TemplateSlotName, AssetCatalogItem>>

/** Strict product path. Inline demo artwork is intentionally handled elsewhere. */
export function catalogAssetBinding(item: AssetCatalogItem, workspace: string, slot: SceneTemplateSlot): TemplateAsset {
  if (!item.id?.trim() || item.metadata_status !== 'canonical') throw new Error('Necesita identidad y metadatos canónicos de Library; los archivos heredados no se migran automáticamente.')
  if ((item.kind !== 'image' && item.kind !== 'model3d' && item.kind !== 'video') || !slot.kinds.includes(item.kind)) throw new Error(`El slot ${slot.id} no admite ${item.kind}.`)
  const location = catalogLocation(item, workspace)
  if (item.kind === 'model3d' && !/\.glb$/i.test(location.filename)) throw new Error('El compositor necesita un GLB, no otro formato 3D.')
  return { source: location.url, type: item.kind, name: location.filename, catalogAtAssignment: {
    assetId: item.id, workspaceId: workspace, filename: location.filename, metadataStatus: 'canonical',
    originTool: item.origin.tool, provider: item.model.provider, modelId: item.model.id,
    runId: item.execution.run_id, taskId: item.execution.task_id,
  } }
}

export function catalogBindingIssue(item: AssetCatalogItem, workspace: string, slot: SceneTemplateSlot): string | undefined {
  try { catalogAssetBinding(item, workspace, slot); return undefined }
  catch (error) { return error instanceof Error ? error.message : 'Asset no disponible.' }
}

/** Re-resolve by identity before compiling; a stale filename is never a fallback.
 * Missing metadata/files require user repair, not a call to a generator. */
export async function resolveCatalogBindings(template: SceneTemplateDefinition, selections: CatalogSelections, workspace: string, signal: AbortSignal, controls: Readonly<Record<string, ControlValue>> = {}): Promise<TemplateBindings> {
  const bindings: TemplateBindings = {}
  const needed = new Set(requiredSlots(template, controls).map(slot => slot.id))
  for (const slot of template.slots) {
    const selected = selections[slot.id]
    if (!selected) {
      if (needed.has(slot.id)) throw new Error(`Falta el slot obligatorio ${slot.id}.`)
      continue
    }
    const current = await fetchAsset(selected.id, signal)
    signal.throwIfAborted()
    if (current.id !== selected.id || current.kind !== selected.kind) throw new Error('La identidad o el tipo del asset cambió. Vuelve a seleccionarlo.')
    const previous = catalogAssetBinding(selected, workspace, slot)
    const next = catalogAssetBinding(current, workspace, slot)
    if (next.source !== previous.source) throw new Error('La ubicación del asset cambió. Vuelve a seleccionarlo para revisar su contenido.')
    bindings[slot.id] = next
  }
  return bindings
}
