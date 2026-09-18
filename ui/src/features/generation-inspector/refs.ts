import { isHostPath, portableFilename } from '../../lib/generationRecord'
import { asMap, portableUri, text } from './fields'
import type { CanonicalRef, CatalogItem } from './types'

export const REF_ROLES = [
  'image_refs', 'image_start', 'image_end', 'image_guide', 'image_mask',
  'video_guide', 'video_source', 'audio_guide', 'audio_source',
  'h3_ref_videos', 'h3_ref_audios', 'minimax_h3_references',
] as const

function emptyRef(role: string): CanonicalRef {
  return { role, assetId: null, filename: null, workspace: null, uri: null, missing: true }
}

function fromObject(role: string, value: unknown): CanonicalRef {
  const raw = asMap(value)
  const assetId = text(raw.asset_id || raw.assetId || raw.id)
  const filename = portableFilename(raw.filename || raw.name || raw.uri)
  const workspace = text(raw.workspace || raw.workspace_id || raw.output_folder)
  const uri = portableUri(raw.uri || raw.url)
  const host = isHostPath(text(raw.uri) || text(raw.path) || '')
  const missing = host || (!assetId && !filename && !uri)
  return { role, assetId, filename, workspace, uri: host ? null : uri, missing }
}

function fromString(role: string, value: string): CanonicalRef {
  if (isHostPath(value)) return emptyRef(role)
  if (value.startsWith('asset')) {
    return { role, assetId: value, filename: null, workspace: null, uri: null, missing: false }
  }
  const uri = portableUri(value)
  const filename = portableFilename(value)
  return {
    role,
    assetId: null,
    filename,
    workspace: null,
    uri,
    missing: !filename && !uri,
  }
}

export function parseRef(role: string, value: unknown): CanonicalRef | null {
  if (value == null || value === '') return null
  if (typeof value === 'string') return fromString(role, value)
  if (typeof value === 'object') return fromObject(role, value)
  return emptyRef(role)
}

export function parseRefList(role: string, value: unknown): CanonicalRef[] {
  if (value == null || value === '') return []
  const items = Array.isArray(value) ? value : [value]
  return items.map(item => parseRef(role, item)).filter((item): item is CanonicalRef => item != null)
}

export function matchCatalog(ref: CanonicalRef, catalog: CatalogItem[]): CatalogItem | undefined {
  return catalog.find(item => {
    const assetId = item.assetId || item.id
    const filename = item.filename || item.name
    if (ref.assetId && assetId && ref.assetId === assetId) return true
    if (!ref.filename || !filename || ref.filename !== filename) return false
    if (ref.workspace && item.workspace && ref.workspace !== item.workspace) return false
    return true
  })
}

function fillFromCatalog(ref: CanonicalRef, match: CatalogItem): CanonicalRef {
  return {
    ...ref,
    assetId: ref.assetId || match.assetId || match.id || null,
    filename: ref.filename || match.filename || match.name || null,
    workspace: ref.workspace || match.workspace || null,
    missing: false,
  }
}

export function resolveRef(ref: CanonicalRef, catalog: CatalogItem[] = []): CanonicalRef {
  if (!ref.assetId && !ref.filename && !ref.uri) return { ...ref, missing: true }
  const match = matchCatalog(ref, catalog)
  if (match) return fillFromCatalog(ref, match)
  return { ...ref, missing: catalog.length > 0 || ref.missing }
}

export function catalogFromOutputs(outputs: Array<{
  name?: string
  asset_id?: string
  workspace_id?: string
  id?: string
}>): CatalogItem[] {
  return outputs.map(item => ({
    assetId: item.asset_id,
    filename: item.name,
    workspace: item.workspace_id,
    name: item.name,
    id: item.id,
  }))
}
