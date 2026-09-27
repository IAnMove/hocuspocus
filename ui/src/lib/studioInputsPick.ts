import type { AssetCatalogItem, AssetKind } from '../api/assets'
import type { ApiOutput } from '../api/outputs'
import { catalogItemToOutput } from '../features/asset-picker'
import { rememberStoredImageFile } from './storedImageFiles'

export function studioMediaPath(item: ApiOutput): string {
  const url = item.url || ''
  if (url.includes('/api/v1/uploads/') || /(^|\/)uploads\//i.test(url)) {
    return `uploads/${item.name}`
  }
  return item.name
}

export function catalogOutputsFor(
  assets: readonly AssetCatalogItem[],
  workspaceId: string,
  kinds: readonly AssetKind[],
): ApiOutput[] {
  const allowed = new Set(kinds)
  return assets
    .filter(asset => allowed.has(asset.kind))
    .map(asset => catalogItemToOutput(asset, workspaceId))
    .filter((item): item is ApiOutput => Boolean(item))
}

function fallbackMime(item: ApiOutput): string {
  if (item.type === 'audio') return 'audio/mpeg'
  if (item.type === 'video') return 'video/mp4'
  if (item.type === 'image') return 'image/png'
  return 'application/octet-stream'
}

export async function fileFromStudioOutput(item: ApiOutput): Promise<File> {
  const response = await fetch(item.url)
  if (!response.ok) throw new Error('Could not read the selected media')
  const blob = await response.blob()
  const file = new File([blob], item.name, { type: blob.type || fallbackMime(item) })
  return item.type === 'image' ? rememberStoredImageFile(file, item.url) : file
}
