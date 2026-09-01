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
    const error = await response.json().catch(() => ({ detail: 'Could not load Wizard conversation' }))
    throw new Error(error.detail || 'Could not load Wizard conversation')
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
    const error: unknown = await response.json().catch(() => null)
    if (error && typeof error === 'object') {
      const detail = (error as Record<string, unknown>).detail
      if (typeof detail === 'string') throw new Error(detail)
    }
    throw new Error('Could not save Wizard conversation')
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
