import type { AssetKind } from '../../api/assets'

export const ASSET_PICKER_PAGE_SIZE = 60

export type CatalogSort = 'created_desc' | 'created_asc' | 'name_asc' | 'name_desc'

export type CatalogAssetRef = {
  version: 1
  scheme: 'catalog'
  id: string
  workspaceId: string
  filename: string
}

export type LegacyOutputRef = {
  version: 1
  scheme: 'legacy-output'
  workspaceId: string
  filename: string
  outputType: 'video' | 'image' | 'audio' | 'model3d' | 'scene' | 'comic'
}

export type AssetRef = CatalogAssetRef | LegacyOutputRef

export type AssetConstraints = {
  kinds: readonly AssetKind[]
  maxCount: number
  optional: boolean
}

export type Compatibility =
  | { allowed: true }
  | { allowed: false; reasonKey: 'picker.incompatibleKind' | 'picker.tooMany' }

export type PickerItem = {
  ref: AssetRef
  kind: AssetKind
  filename: string
  title: string
  createdAt: number | null
  sizeBytes: number
  url: string
  thumbnailUrl: string
}

export type AssetPickerIntent =
  | { type: 'provisional'; items: PickerItem[] }
  | { type: 'confirm'; items: PickerItem[] }
  | { type: 'cancel' }
  | { type: 'clear' }

export function assetRefKey(ref: AssetRef): string {
  if (ref.scheme === 'catalog') return `catalog:${ref.id}@${ref.workspaceId}:${ref.filename}`
  return `legacy-output:${ref.workspaceId}:${ref.filename}`
}

export function isSameRef(left: AssetRef, right: AssetRef): boolean {
  return assetRefKey(left) === assetRefKey(right)
}

export function isConfirmIntent(intent: AssetPickerIntent): intent is Extract<AssetPickerIntent, { type: 'confirm' }> {
  return intent.type === 'confirm'
}
