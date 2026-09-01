import { openCanonicalTaskEventStream } from '../lib/canonicalTaskEvents'
import type { CanonicalTaskEvent, CanonicalTaskStreamState } from '../lib/canonicalTaskEvents'
import { BASE } from './http'

export type CanonicalTaskStatus =
  | 'created' | 'queued' | 'waiting_resource' | 'running'
  | 'completed' | 'failed' | 'cancelled' | 'interrupted'

export interface CanonicalTask {
  id: string
  root_id: string
  parent_id?: string | null
  kind: string
  title: string
  workflow: string
  status: CanonicalTaskStatus
  phase: string
  message: string
  detail?: string
  current: number
  total: number
  progress: number
  detail_current: number
  detail_total: number
  created_at: number
  queued_at?: number | null
  started_at?: number | null
  updated_at: number
  completed_at?: number | null
  provider?: string
  model?: string
  server_origin?: string
  resource_requirements?: string[]
  acquired_resources?: string[]
  attempt: number
  max_attempts: number
  token_usage?: { prompt?: number; completion?: number; total?: number; calls?: number }
  backend_job_id?: string
  pipeline_id?: string
  cancelable: boolean
  resumable: boolean
  recoverable: boolean
  error?: { message?: string; retryable?: boolean } | null
  result_refs?: string[]
  metadata?: Record<string, unknown>
}

export async function fetchCanonicalTasks(
  workspace: string,
  status: 'active' | 'all' = 'all',
): Promise<{ workspace: string; tasks: CanonicalTask[]; latest_event_id: number }> {
  const query = new URLSearchParams({ workspace, status, limit: '300' })
  const res = await fetch(`${BASE}/api/v1/tasks?${query}`)
  if (!res.ok) throw new Error('Failed to fetch HocusPocus tasks')
  return res.json()
}

export function subscribeCanonicalTaskEvents(
  workspace: string,
  onEvent: (event: CanonicalTaskEvent) => void,
  onError?: () => void,
  onStateChange?: (state: CanonicalTaskStreamState) => void,
  initialEventId = 0,
): () => void {
  return openCanonicalTaskEventStream(BASE, workspace, onEvent, onError, onStateChange, {
    initialEventId,
  })
}

export async function upsertCanonicalClientTask(task: Record<string, unknown>): Promise<CanonicalTask> {
  const clientTaskId = canonicalClientTaskId(task.id)
  const canonicalTask: Record<string, unknown> = { ...task, id: clientTaskId }
  delete canonicalTask.root_id
  delete canonicalTask.rootId
  const res = await fetch(`${BASE}/api/v1/tasks/upsert`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ task: canonicalTask }),
  })
  if (!res.ok) throw new Error('Failed to publish HocusPocus activity')
  return res.json()
}

/** Keep frontend activity ids inside the namespace reserved for client tasks. */

export function canonicalClientTaskId(value: unknown): string {
  let normalized = String(value ?? '').replace(/[^A-Za-z0-9_-]+/g, '-').replace(/^-+|-+$/g, '')
  while (normalized.startsWith('task-client-')) {
    normalized = normalized.slice('task-client-'.length).replace(/^-+/, '')
  }
  if (!normalized) {
    const uniquePart = globalThis.crypto?.randomUUID?.()
      || `${Date.now()}-${Math.random().toString(36).slice(2)}`
    normalized = `activity-${uniquePart}`
  }
  return `task-client-${normalized.slice(0, 160)}`
}

export async function cancelCanonicalTask(taskId: string, workspace: string): Promise<CanonicalTask> {
  const res = await fetch(`${BASE}/api/v1/tasks/${encodeURIComponent(taskId)}/cancel?workspace=${encodeURIComponent(workspace)}`, { method: 'POST' })
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: 'Task cancellation failed' }))
    throw new Error(error.detail || 'Task cancellation failed')
  }
  const payload = await res.json()
  return payload.task
}

export async function resumeCanonicalTask(taskId: string, workspace: string): Promise<CanonicalTask> {
  const res = await fetch(`${BASE}/api/v1/tasks/${encodeURIComponent(taskId)}/resume?workspace=${encodeURIComponent(workspace)}`, { method: 'POST' })
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: 'Task resume failed' }))
    throw new Error(error.detail || 'Task resume failed')
  }
  const payload = await res.json()
  return payload.task
}

export async function retryCanonicalTask(taskId: string, workspace: string): Promise<CanonicalTask> {
  const res = await fetch(`${BASE}/api/v1/tasks/${encodeURIComponent(taskId)}/retry?workspace=${encodeURIComponent(workspace)}`, { method: 'POST' })
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: 'Task retry failed' }))
    throw new Error(error.detail || 'Task retry failed')
  }
  const payload = await res.json()
  return payload.task
}

export async function dismissCanonicalTask(taskId: string, workspace: string): Promise<void> {
  const res = await fetch(`${BASE}/api/v1/tasks/${encodeURIComponent(taskId)}?workspace=${encodeURIComponent(workspace)}`, { method: 'DELETE' })
  if (!res.ok) throw new Error('Failed to dismiss HocusPocus task')
}
