import { BASE } from './http'

export interface WizardConversationPayload {
  version: 1
  revision: number
  messages: unknown[]
  executions: unknown[]
  requestedActions?: unknown[]
  executedActions?: unknown[]
  confirmations?: unknown[]
}

export interface WizardConversationErrorDetail {
  code?: string
  message?: string
  expectedRevision?: number
  currentRevision?: number
  [key: string]: unknown
}

/**
 * Error from the durable Wizard conversation endpoint.
 *
 * Keeping the HTTP status and structured detail at this boundary prevents
 * callers from treating validation/auth/server errors as revision conflicts.
 */
export class WizardConversationRequestError extends Error {
  readonly status: number
  readonly detail: unknown
  readonly code?: string

  constructor(message: string, status: number, detail: unknown = null) {
    super(message)
    this.name = 'WizardConversationRequestError'
    this.status = status
    this.detail = detail
    const structured = detail && typeof detail === 'object' && 'detail' in detail
      ? (detail as { detail?: unknown }).detail
      : detail
    this.code = structured && typeof structured === 'object' && typeof (structured as WizardConversationErrorDetail).code === 'string'
      ? (structured as WizardConversationErrorDetail).code
      : undefined
  }
}

async function readWizardError(response: Response, fallback: string): Promise<WizardConversationRequestError> {
  const body = await response.json().catch(() => null)
  const detail = body && typeof body === 'object' && 'detail' in body
    ? (body as { detail?: unknown }).detail
    : body
  const message = typeof detail === 'string'
    ? detail
    : detail && typeof detail === 'object' && typeof (detail as WizardConversationErrorDetail).message === 'string'
      ? (detail as WizardConversationErrorDetail).message as string
      : fallback
  return new WizardConversationRequestError(message, response.status, body)
}

export interface WizardWorkflowCollectionPayload {
  version: 1
  revision: number
  workflows: unknown[]
}

export async function fetchWizardConversation(workspace: string): Promise<WizardConversationPayload> {
  const response = await fetch(
    `${BASE}/api/v1/wizard/conversations?workspace=${encodeURIComponent(workspace)}`,
  )
  if (!response.ok) {
    throw await readWizardError(response, 'Could not load Wizard conversation')
  }
  return response.json()
}

export async function saveWizardConversation(
  workspace: string,
  conversation: WizardConversationPayload,
): Promise<WizardConversationPayload> {
  const response = await fetch(`${BASE}/api/v1/wizard/conversations`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ workspace, baseRevision: conversation.revision, conversation }),
  })
  if (!response.ok) {
    throw await readWizardError(response, 'Could not save Wizard conversation')
  }
  return response.json()
}

export async function fetchWizardWorkflows(workspace: string): Promise<WizardWorkflowCollectionPayload> {
  const response = await fetch(
    `${BASE}/api/v1/wizard/workflows?workspace=${encodeURIComponent(workspace)}`,
  )
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Could not load Wizard workflows' }))
    throw new Error(error.detail || 'Could not load Wizard workflows')
  }
  return response.json()
}

export async function saveWizardWorkflows(
  workspace: string,
  collection: WizardWorkflowCollectionPayload,
): Promise<WizardWorkflowCollectionPayload> {
  const response = await fetch(`${BASE}/api/v1/wizard/workflows`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ workspace, baseRevision: collection.revision, collection }),
  })
  if (!response.ok) {
    const error: unknown = await response.json().catch(() => null)
    if (error && typeof error === 'object') {
      const detail = (error as Record<string, unknown>).detail
      if (typeof detail === 'string') throw new Error(detail)
      if (detail && typeof detail === 'object') {
        const message = (detail as Record<string, unknown>).message
        if (typeof message === 'string') throw new Error(message)
      }
    }
    throw new Error('Could not save Wizard workflows')
  }
  return response.json()
}
