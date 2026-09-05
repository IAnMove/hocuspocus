import { BASE } from './http'

export type AssetKind = 'image' | 'audio' | 'video' | 'scene' | 'model3d' | 'document' | 'other'
export type AssetMetadataStatus = 'canonical' | 'legacy' | 'missing' | 'unreadable' | 'invalid'

export interface AssetLocation {
  workspace_id: string
  output_folder?: string | null
  filename: string
  url: string
}

export interface AssetCatalogItem {
  id: string
  kind: AssetKind
  filename: string
  size_bytes: number
  created_at: number
  completed_at: number
  metadata_status: AssetMetadataStatus
  workspace_ids: string[]
  locations: AssetLocation[]
  url: string
  origin: {
    tool: string
    capability?: string | null
    actor?: string | null
    workspace_id?: string | null
    output_folder?: string | null
    project?: Record<string, unknown> | null
    production?: Record<string, unknown> | null
  }
  execution: {
    status?: string | null
    mode?: string | null
    command_id?: string | null
    workflow_id?: string | null
    run_id?: string | null
    task_id?: string | null
    job_id?: string | null
    pipeline_id?: string | null
  }
  model: { provider?: string | null; id?: string | null }
  prompt_preview: string
  manifest?: Record<string, unknown>
}

export async function fetchAssets(options: {
  search?: string
  kind?: AssetKind
  workspace?: string
  collection?: 'inbox_legacy'
  limit?: number
  offset?: number
  signal?: AbortSignal
} = {}): Promise<{ assets: AssetCatalogItem[]; total: number }> {
  const params = new URLSearchParams()
  if (options.search) params.set('search', options.search)
  if (options.kind) params.set('kind', options.kind)
  if (options.workspace) params.set('workspace', options.workspace)
  if (options.collection) params.set('collection', options.collection)
  if (options.limit != null) params.set('limit', String(options.limit))
  if (options.offset != null) params.set('offset', String(options.offset))
  const response = await fetch(`${BASE}/api/v1/assets?${params}`, {
    cache: 'no-store', signal: options.signal,
  })
  if (!response.ok) throw new Error('Failed to fetch assets')
  return response.json()
}

export async function fetchAsset(assetId: string, signal?: AbortSignal): Promise<AssetCatalogItem> {
  const response = await fetch(`${BASE}/api/v1/assets/${encodeURIComponent(assetId)}`, {
    cache: 'no-store', signal,
  })
  if (!response.ok) throw new Error(response.status === 404 ? 'Asset not found' : 'Failed to fetch asset')
  return response.json()
}
