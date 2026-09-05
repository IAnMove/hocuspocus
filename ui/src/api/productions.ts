import { BASE } from './http'

export interface ProductionCatalogItem {
  schema: 'hocuspocus.production-record'
  schema_version: 1
  id: string
  kind: string
  title: string
  project: { kind: string; id: string } | null
  workspace_ids: string[]
  created_at: string | null
  updated_at: string | null
  plan: Record<string, unknown>
  run_ids: string[]
}

export async function fetchProductions(options: { limit?: number; offset?: number; signal?: AbortSignal } = {}) {
  const params = new URLSearchParams()
  if (options.limit != null) params.set('limit', String(options.limit))
  if (options.offset != null) params.set('offset', String(options.offset))
  const response = await fetch(`${BASE}/api/v1/productions?${params}`, { cache: 'no-store', signal: options.signal })
  if (!response.ok) throw new Error('No se pudieron cargar las Productions')
  return response.json() as Promise<{ productions: ProductionCatalogItem[]; total: number }>
}
