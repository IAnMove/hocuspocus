import { inspectAttempt } from './inspect'
import type { InspectedAttempt } from './types'

export const INSPECTOR_STORAGE_PREFIX = 'maestro-generation-inspector-v1'
export const INSPECTOR_EVENT = 'hocuspocus:generation-inspector-changed'
export const OPEN_INSPECTOR_EVENT = 'hocuspocus:open-generation-inspector'

export interface PersistedInspector {
  attemptId: string
  outputFolder: string
  attempt: InspectedAttempt
  open: boolean
}

export interface OpenInspectorRequest {
  workspace: string
  source?: unknown
  attempt?: InspectedAttempt
  compareSource?: unknown
}

function storageKey(workspace: string): string {
  return `${INSPECTOR_STORAGE_PREFIX}:${encodeURIComponent(workspace || 'default')}`
}

function canUseStorage(): boolean {
  return typeof window !== 'undefined' && Boolean(window.localStorage)
}

function emit(name: string, workspace: string): void {
  if (typeof window === 'undefined') return
  try {
    window.dispatchEvent(new CustomEvent(name, { detail: { workspace } }))
  } catch {
    /* jsdom without CustomEvent still keeps localStorage writes */
  }
}

export function persistInspectedAttempt(
  workspace: string,
  attempt: InspectedAttempt,
  open = true,
): PersistedInspector | null {
  if (attempt.outputFolder && attempt.outputFolder !== workspace) return null
  const payload: PersistedInspector = {
    attemptId: attempt.attemptId,
    outputFolder: workspace,
    attempt,
    open,
  }
  if (!canUseStorage()) return payload
  try {
    window.localStorage.setItem(storageKey(workspace), JSON.stringify(payload))
    emit(INSPECTOR_EVENT, workspace)
    return payload
  } catch {
    return payload
  }
}

export function loadInspectedAttempt(workspace: string): PersistedInspector | null {
  if (!canUseStorage()) return null
  try {
    const parsed = JSON.parse(window.localStorage.getItem(storageKey(workspace)) || 'null')
    if (!parsed || typeof parsed !== 'object') return null
    const record = parsed as PersistedInspector
    if (!record.attempt || record.outputFolder !== workspace) return null
    if (record.attempt.outputFolder !== workspace) return null
    return record
  } catch {
    return null
  }
}

export function clearInspectedAttempt(workspace: string): void {
  if (!canUseStorage()) return
  window.localStorage.removeItem(storageKey(workspace))
  emit(INSPECTOR_EVENT, workspace)
}

export function openGenerationInspector(request: OpenInspectorRequest): void {
  if (typeof window === 'undefined') return
  try {
    window.dispatchEvent(new CustomEvent(OPEN_INSPECTOR_EVENT, { detail: request }))
  } catch {
    /* host is optional in unit tests without CustomEvent */
  }
}

export function listenForGenerationInspector(
  listener: (request: OpenInspectorRequest) => void,
): () => void {
  if (typeof window === 'undefined') return () => undefined
  const handler = (event: Event) => {
    const detail = (event as CustomEvent<OpenInspectorRequest>).detail
    if (!detail?.workspace) return
    listener(detail)
  }
  window.addEventListener(OPEN_INSPECTOR_EVENT, handler)
  return () => window.removeEventListener(OPEN_INSPECTOR_EVENT, handler)
}

export function attemptFromOpenRequest(request: OpenInspectorRequest): InspectedAttempt | null {
  if (request.attempt) return request.attempt.outputFolder === request.workspace ? request.attempt : null
  if (request.source == null) return loadInspectedAttempt(request.workspace)?.attempt || null
  const inspected = inspectAttempt(request.source, { workspace: request.workspace })
  if (inspected.outputFolder !== request.workspace) return null
  return inspected
}

/** H02 execution-detail hook: open this workspace's inspector without rewriting ActivityFooter. */
export function inspectFromActivity(workspace: string, source: unknown): void {
  openGenerationInspector({ workspace, source })
}
