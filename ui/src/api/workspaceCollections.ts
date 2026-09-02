import { BASE } from './http'

export interface WorkspaceCollection {
  schema: 'hocuspocus.workspace-record'
  schema_version: 1
  id: string
  revision: number
  name: string
  description: string
  project_ids: string[]
  asset_ids: string[]
  production_ids: string[]
  created_at: string | null
  updated_at: string | null
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${url}`, init)
  if (!response.ok) {
    const payload = await response.json().catch(() => ({})) as { detail?: string }
    throw new Error(payload.detail || 'No se pudo actualizar el Workspace')
  }
  if (response.status === 204) return undefined as T
  return response.json()
}

export async function fetchWorkspaceCollections(signal?: AbortSignal) {
  return request<{ workspaces: WorkspaceCollection[]; total: number }>('/api/v1/workspace-collections', {
    cache: 'no-store', signal,
  })
}

export async function createWorkspaceCollection(value: {
  name: string
  description?: string
  project_ids?: string[]
  asset_ids?: string[]
  production_ids?: string[]
}) {
  return request<WorkspaceCollection>('/api/v1/workspace-collections', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(value),
  })
}

export async function updateWorkspaceCollection(value: WorkspaceCollection) {
  return request<WorkspaceCollection>(`/api/v1/workspace-collections/${encodeURIComponent(value.id)}`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({
      expected_revision: value.revision,
      name: value.name,
      description: value.description,
      project_ids: value.project_ids,
      asset_ids: value.asset_ids,
      production_ids: value.production_ids,
    }),
  })
}

export async function deleteWorkspaceCollection(workspaceId: string) {
  return request<void>(`/api/v1/workspace-collections/${encodeURIComponent(workspaceId)}`, { method: 'DELETE' })
}
