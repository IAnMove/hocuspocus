import { BASE } from './http'

// --- Style sheet library ---

export interface StyleAttribution {
  id: string
  type: string
  author: string
  name: string
  url: string
  repoId: string
  modelFamily: string
  collection: string
  license: string | null
  licenseNotice?: string
  description: string
  expectedStyles: number
  expectedBytes: number
  revision?: string | null
  lastModified?: string | null
}

export interface StyleSource extends StyleAttribution {
  installed: boolean
  styleCount: number
  downloadedFiles: number
  downloadedBytes: number
  activeJob?: StyleImportJob | null
  latestJob?: StyleImportJob | null
  storagePath?: string
  storageNotice?: string | null
}

export interface StyleLibraryItem {
  id: string
  modelFamily: string
  title: string
  prompt: string
  collection: string
  group: string
  tags: string[]
  sourceOrder: number
  sourceFilename: string
  videoFilename: string
  source: StyleAttribution
  importedAt: number
  previewUrl: string
  videoUrl: string
}

export interface StyleImportJob {
  jobId: string
  status: 'queued' | 'running' | 'cancelling' | 'cancelled' | 'completed' | 'failed' | 'interrupted'
  stage: 'queued' | 'downloading' | 'indexing' | 'previews' | 'cancelling' | 'cancelled' | 'completed' | 'failed' | 'interrupted'
  current: number
  total: number
  message: string
  downloadedBytes: number
  expectedBytes: number
  error?: string | null
  storagePath?: string
  preflight?: StyleImportPreflight
  cancelRequestedAt?: number | null
  resumeAvailable?: boolean
  resumed?: boolean
  resumeCount?: number
  source: StyleAttribution
}

export interface StyleImportPreflight {
  storagePath: string
  probePath: string
  downloadedFiles: number
  downloadedBytes: number
  expectedBytes: number
  remainingBytes: number
  marginBytes: number
  requiredBytes: number
  freeBytes: number
  sufficient: boolean
}

export interface StyleLibraryPage {
  styles: StyleLibraryItem[]
  total: number
  offset: number
  limit: number
  facets: { sources: string[]; collections: string[]; groups: string[] }
}

export async function fetchStyleSources(): Promise<StyleSource[]> {
  const res = await fetch(`${BASE}/api/v1/style-library/sources`, { cache: 'no-store' })
  if (!res.ok) throw new Error('Could not load style sources')
  const data = await res.json()
  return data.sources || []
}

export async function fetchStyleLibrary(params: {
  modelFamily?: string
  sourceId?: string
  collection?: string
  group?: string
  query?: string
  sort?: string
  offset?: number
  limit?: number
} = {}): Promise<StyleLibraryPage> {
  const query = new URLSearchParams()
  if (params.modelFamily) query.set('model_family', params.modelFamily)
  if (params.sourceId) query.set('source_id', params.sourceId)
  if (params.collection) query.set('collection', params.collection)
  if (params.group) query.set('group', params.group)
  if (params.query) query.set('q', params.query)
  if (params.sort) query.set('sort', params.sort)
  if (params.offset) query.set('offset', String(params.offset))
  if (params.limit) query.set('limit', String(params.limit))
  const res = await fetch(`${BASE}/api/v1/style-library/styles?${query.toString()}`, { cache: 'no-store' })
  if (!res.ok) throw new Error('Could not load styles')
  return res.json()
}

export async function startMiniMaxStyleImport(): Promise<StyleImportJob> {
  const res = await fetch(`${BASE}/api/v1/style-library/imports/minimax-h3-1k`, { method: 'POST' })
  if (!res.ok) {
    const payload = await res.json().catch(() => null)
    const detail = payload?.detail
    throw new Error(
      (typeof detail === 'object' && detail?.message)
      || (typeof detail === 'string' && detail)
      || 'Could not start the MiniMax style download',
    )
  }
  return res.json()
}

export async function fetchStyleImport(jobId: string): Promise<StyleImportJob> {
  const res = await fetch(`${BASE}/api/v1/style-library/imports/${encodeURIComponent(jobId)}`, { cache: 'no-store' })
  if (!res.ok) throw new Error('Could not load style import progress')
  return res.json()
}

export async function cancelStyleImport(jobId: string): Promise<StyleImportJob> {
  const res = await fetch(`${BASE}/api/v1/style-library/imports/${encodeURIComponent(jobId)}/cancel`, {
    method: 'POST',
  })
  if (!res.ok) throw new Error('Could not cancel the style import')
  return res.json()
}

export async function deleteStyle(styleId: string): Promise<{ id: string; deleted: boolean }> {
  const res = await fetch(`${BASE}/api/v1/style-library/styles/${encodeURIComponent(styleId)}?confirm=true`, {
    method: 'DELETE',
  })
  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: 'Could not delete style' }))
    throw new Error(detail.detail || 'Could not delete style')
  }
  return res.json()
}
