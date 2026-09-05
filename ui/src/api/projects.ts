import { BASE } from './http'

export type ProjectKind = 'story' | 'series' | 'episode' | 'comic' | 'scene3d' | 'character_kit' | 'video_editor'

export interface ProjectSource {
  workspace_id: string
  adapter: string
  key: string
}

export interface ProjectCatalogItem {
  schema: 'hocuspocus.project-record'
  schema_version: 1
  id: string
  kind: ProjectKind
  subtype?: string | null
  title: string
  revision?: number | null
  created_at?: string | null
  updated_at?: string | null
  parent?: { id: string; kind: ProjectKind } | null
  workspace_ids: string[]
  sources: ProjectSource[]
  metadata: Record<string, unknown>
}

export interface ProjectCatalogWarning {
  workspace_id: string
  source: string
  error: string
}

export async function fetchProjects(options: {
  search?: string
  kind?: ProjectKind
  workspace?: string
  limit?: number
  offset?: number
  signal?: AbortSignal
} = {}): Promise<{
  projects: ProjectCatalogItem[]
  total: number
  warnings: ProjectCatalogWarning[]
}> {
  const params = new URLSearchParams()
  if (options.search) params.set('search', options.search)
  if (options.kind) params.set('kind', options.kind)
  if (options.workspace) params.set('workspace', options.workspace)
  if (options.limit != null) params.set('limit', String(options.limit))
  if (options.offset != null) params.set('offset', String(options.offset))
  const response = await fetch(`${BASE}/api/v1/projects?${params}`, {
    cache: 'no-store', signal: options.signal,
  })
  if (!response.ok) throw new Error('Failed to fetch projects')
  return response.json()
}

export async function fetchProject(projectId: string, signal?: AbortSignal): Promise<ProjectCatalogItem> {
  const response = await fetch(`${BASE}/api/v1/projects/${encodeURIComponent(projectId)}`, {
    cache: 'no-store', signal,
  })
  if (!response.ok) throw new Error(response.status === 404 ? 'Project not found' : 'Failed to fetch project')
  return response.json()
}
