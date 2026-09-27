import { BASE } from './http'
import { newCollectionIntentId, submitCollectionCommand } from './workspaceCommands'

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
    throw new Error(payload.detail || 'The Workspace could not be updated')
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
  const receipt = await submitCollectionCommand({ version: 1, operation: 'collections.create', intent_id: newCollectionIntentId(), input: value })
  return receipt.result
}

export async function updateWorkspaceCollection(value: WorkspaceCollection) {
  const receipt = await submitCollectionCommand({ version: 1, operation: 'collections.update', intent_id: newCollectionIntentId(), input: {
      workspace_id: value.id,
      expected_revision: value.revision,
      name: value.name,
      description: value.description,
      project_ids: value.project_ids,
      asset_ids: value.asset_ids,
      production_ids: value.production_ids,
    },
  })
  return receipt.result
}

export async function deleteWorkspaceCollection(workspaceId: string) {
  return request<void>(`/api/v1/workspace-collections/${encodeURIComponent(workspaceId)}`, { method: 'DELETE' })
}
