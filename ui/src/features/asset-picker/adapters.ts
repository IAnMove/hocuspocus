import { getOutputThumbnailUrl, getServerMediaReference, type ApiOutput } from '../../api/outputs'
import type { AssetCatalogItem, AssetKind } from '../../api/assets'
import { displayAssetTitle, knownCreatedAt } from './titles.ts'
import type { AssetConstraints, AssetRef, Compatibility, PickerItem } from './types.ts'

const OUTPUT_KIND: Record<ApiOutput['type'], AssetKind> = {
  image: 'image',
  video: 'video',
  audio: 'audio',
  model3d: 'model3d',
  scene: 'scene',
  comic: 'document',
}

export function pickerThumbnailUrl(filename: string, workspace: string): string {
  const url = getOutputThumbnailUrl(filename, workspace)
  return `${url}${url.includes('?') ? '&' : '?'}size=sm`
}

export function catalogLocation(item: AssetCatalogItem, workspaceId: string) {
  return item.locations.find(entry => entry.workspace_id === workspaceId)
}

export function catalogItemToPickerItem(
  item: AssetCatalogItem,
  workspaceId: string,
  options?: { strict?: boolean },
): PickerItem {
  const location = catalogLocation(item, workspaceId) ?? (options?.strict ? undefined : item.locations[0])
  if (options?.strict && !location) {
    const error = new Error('Asset location not found')
    ;(error as Error & { status: number }).status = 409
    throw error
  }
  const filename = location?.filename || item.filename
  const createdAt = knownCreatedAt(item.created_at)
  const ref: AssetRef = {
    version: 1,
    scheme: 'catalog',
    id: item.id,
    workspaceId: location?.workspace_id || workspaceId,
    filename,
  }
  return {
    ref,
    kind: item.kind,
    filename,
    title: displayAssetTitle(item.kind, createdAt),
    createdAt,
    sizeBytes: item.size_bytes,
    url: location?.url || item.url,
    thumbnailUrl: item.kind === 'image' || item.kind === 'video'
      ? pickerThumbnailUrl(filename, ref.workspaceId) : '',
  }
}

const OUTPUT_TYPE: Partial<Record<AssetKind, ApiOutput['type']>> = {
  image: 'image',
  video: 'video',
  audio: 'audio',
  model3d: 'model3d',
  scene: 'scene',
  document: 'comic',
}

export function catalogItemToOutput(item: AssetCatalogItem, workspaceId: string): ApiOutput | null {
  const type = OUTPUT_TYPE[item.kind]
  if (!type) return null
  const location = catalogLocation(item, workspaceId) ?? item.locations[0]
  if (!location) return null
  return {
    name: location.filename || item.filename,
    type,
    mode: null,
    size: item.size_bytes,
    created_at: item.created_at,
    completed_at: item.completed_at,
    url: location.url || item.url,
    thumbnail_url: item.kind === 'image' || item.kind === 'video'
      ? pickerThumbnailUrl(location.filename || item.filename, location.workspace_id || workspaceId) : '',
    asset_id: item.id,
    workspace_id: location.workspace_id || workspaceId,
    path: location.filename || item.filename,
  }
}

export function matchCatalogByOutput(
  items: readonly AssetCatalogItem[],
  output: ApiOutput,
  workspaceId: string,
): AssetCatalogItem | undefined {
  if (output.asset_id) {
    const byId = items.find(item => item.id === output.asset_id)
    if (!byId) return undefined
    const location = catalogLocation(byId, output.workspace_id || workspaceId) ?? byId.locations[0]
    if (output.workspace_id && location && location.workspace_id !== output.workspace_id) return undefined
    return byId
  }
  const matches = items.filter(item => {
    const mapped = catalogItemToOutput(item, workspaceId)
    return mapped?.url === output.url && mapped.name === output.name && mapped.workspace_id === (output.workspace_id || workspaceId)
  })
  return matches.length === 1 ? matches[0] : undefined
}

export function voiceRefFromOutput(item: ApiOutput, workspaceId?: string): { filename: string; path: string } {
  const ref = getServerMediaReference(item.url, item.name, workspaceId)
  return { filename: item.name, path: ref?.audio_path || item.name }
}

export function outputToPickerItem(item: ApiOutput, workspaceId: string): PickerItem {
  const kind = OUTPUT_KIND[item.type]
  const createdAt = knownCreatedAt(item.created_at)
  const scope = item.workspace_id || workspaceId
  const ref: AssetRef = item.asset_id
    ? { version: 1, scheme: 'catalog', id: item.asset_id, workspaceId: scope, filename: item.name }
    : { version: 1, scheme: 'legacy-output', workspaceId: scope, filename: item.name, outputType: item.type }
  return {
    ref,
    kind,
    filename: item.name,
    title: displayAssetTitle(kind, createdAt, item.name),
    createdAt,
    sizeBytes: item.size,
    url: item.url,
    thumbnailUrl: (item.type === 'image' || item.type === 'video') && scope
      && !/^(blob:|data:|local-edit:)/.test(item.url)
      ? pickerThumbnailUrl(item.name, scope)
      : item.thumbnail_url || '',
  }
}

const PICKER_OUTPUT_TYPE: Partial<Record<AssetKind, ApiOutput['type']>> = {
  image: 'image',
  video: 'video',
  audio: 'audio',
  model3d: 'model3d',
  scene: 'scene',
  document: 'comic',
}

export function pickerItemToOutput(item: PickerItem): ApiOutput | null {
  const type = PICKER_OUTPUT_TYPE[item.kind]
  if (!type) return null
  return {
    name: item.filename,
    type,
    mode: null,
    size: item.sizeBytes,
    created_at: item.createdAt ?? 0,
    url: item.url,
    thumbnail_url: item.thumbnailUrl,
    asset_id: item.ref.scheme === 'catalog' ? item.ref.id : undefined,
    workspace_id: item.ref.workspaceId,
    path: item.filename,
  }
}

export function checkCompatibility(item: PickerItem, constraints: AssetConstraints, alreadyChosen: number): Compatibility {
  if (!constraints.kinds.includes(item.kind)) return { allowed: false, reasonKey: 'picker.incompatibleKind' }
  if (alreadyChosen >= constraints.maxCount) return { allowed: false, reasonKey: 'picker.tooMany' }
  return { allowed: true }
}

export function resolveCatalogMatch(items: AssetCatalogItem[], ref: AssetRef): AssetCatalogItem | undefined {
  if (ref.scheme === 'catalog') {
    return items.find(item => item.id === ref.id)
  }
  return items.find(item => item.locations.some(location => (
    location.workspace_id === ref.workspaceId && location.filename === ref.filename
  )))
}
