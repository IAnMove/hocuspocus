export const WIZARD_WELCOME_TEXT = 'Saludos, creador. Soy el mago de HocusPocus: puedo consultar la cola, explicarte el estudio, llevarte a la sección adecuada y preparar o lanzar un vídeo cuando me lo pidas. Dime qué quieres conjurar. 🪄'

export interface WizardSyncMessage {
  id: string
  role: 'user' | 'assistant'
  text: string
  createdAt: number
  language?: string
  cards?: unknown[]
  executionKey?: string
  jobLinks?: unknown[]
  lastState?: string
  error?: string
}

export interface WizardConversationChoice {
  source: 'local' | 'remote'
  messages: WizardSyncMessage[]
  revision: number
}

function isMessageRole(value: unknown): value is 'user' | 'assistant' {
  return value === 'user' || value === 'assistant'
}

export function normalizeRemoteWizardMessages(
  remoteMessages: unknown[],
  remoteExecutions?: unknown[],
): WizardSyncMessage[] {
  const restored = (Array.isArray(remoteMessages) ? remoteMessages : []).flatMap((value): WizardSyncMessage[] => {
    if (!value || typeof value !== 'object') return []
    const message = value as Record<string, unknown>
    if (typeof message.id !== 'string' || !isMessageRole(message.role) || typeof message.text !== 'string') {
      return []
    }
    return [{
      id: message.id,
      role: message.role,
      text: message.text,
      createdAt: typeof message.createdAt === 'number' ? message.createdAt : 0,
      ...(typeof message.language === 'string' && message.language ? { language: message.language } : {}),
      cards: Array.isArray(message.cards) && message.cards.length ? message.cards : undefined,
      ...(typeof message.executionKey === 'string' && message.executionKey ? { executionKey: message.executionKey } : {}),
      jobLinks: Array.isArray(message.jobLinks) && message.jobLinks.length ? message.jobLinks : undefined,
      ...(typeof message.lastState === 'string' && message.lastState ? { lastState: message.lastState } : {}),
      ...(typeof message.error === 'string' && message.error ? { error: message.error } : {}),
    }]
  })
  if (!restored.length && Array.isArray(remoteExecutions) && remoteExecutions.length) {
    restored.push({
      id: 'wizard-restored-cards',
      role: 'assistant',
      text: WIZARD_WELCOME_TEXT,
      createdAt: 0,
      cards: remoteExecutions,
    })
  }
  return restored.slice(-40)
}

/**
 * Merge two snapshots without duplicating a message id.
 *
 * Remote order is canonical, but a local value wins for a shared id. Callers
 * use this fallback only when no common ancestor is available, so preserving
 * an in-browser card/workflow update is safer than silently reverting it.
 * Local-only messages are appended in their existing order.
 */
export function mergeWizardMessages(
  localMessages: WizardSyncMessage[],
  remoteMessages: WizardSyncMessage[],
): WizardSyncMessage[] {
  const localById = new Map(localMessages.map(message => [message.id, message]))
  const merged: WizardSyncMessage[] = []
  const seen = new Set<string>()
  for (const message of remoteMessages) {
    if (!message.id || seen.has(message.id)) continue
    seen.add(message.id)
    merged.push(localById.get(message.id) ?? message)
  }
  for (const message of localMessages) {
    if (!message.id || seen.has(message.id)) continue
    seen.add(message.id)
    merged.push(message)
  }
  return merged.slice(-40)
}

/** True when the visible client state still contains a turn absent from a saved snapshot. */
export function hasExclusiveWizardMessages(
  visibleMessages: WizardSyncMessage[],
  savedMessages: WizardSyncMessage[],
): boolean {
  const savedIds = new Set(savedMessages.map(message => message.id))
  return visibleMessages.some(message => Boolean(message.id) && !savedIds.has(message.id))
}

export function isTransientWizardChat(messages: WizardSyncMessage[]): boolean {
  if (!messages.length) return true
  return !messages.some(message => (
    message.role === 'user'
    || (Array.isArray(message.cards) && message.cards.length > 0)
  ))
}

export function applyRemoteWizardConversation(input: {
  localMessages: WizardSyncMessage[]
  localRevision: number
  remoteMessages: unknown[]
  remoteRevision?: number
  remoteExecutions?: unknown[]
}): WizardConversationChoice {
  const localMessages = Array.isArray(input.localMessages) ? input.localMessages : []
  const localRevision = Number.isFinite(input.localRevision) ? input.localRevision : 0
  const remoteRevision = Number.isFinite(input.remoteRevision) ? Number(input.remoteRevision) : 0
  const remoteMessages = normalizeRemoteWizardMessages(input.remoteMessages, input.remoteExecutions)

  if (!remoteMessages.length) {
    return { source: 'local', messages: localMessages, revision: Math.max(localRevision, remoteRevision) }
  }

  const remoteIds = new Set(remoteMessages.map(message => message.id))
  const localHasExclusiveTurn = localMessages.some(message => !remoteIds.has(message.id))
    && !isTransientWizardChat(localMessages)
  if (localHasExclusiveTurn) {
    return {
      source: 'local',
      messages: mergeWizardMessages(localMessages, remoteMessages),
      revision: Math.max(localRevision, remoteRevision),
    }
  }
  if (localRevision > remoteRevision) {
    return { source: 'local', messages: localMessages, revision: localRevision }
  }
  return { source: 'remote', messages: remoteMessages, revision: remoteRevision }
}

/** Follow the footer workspace only after the in-flight turn finishes. */
export function shouldFollowWizardWorkspace(input: {
  activeWorkspace: string
  conversationWorkspace: string
  busy: boolean
}): boolean {
  return input.activeWorkspace !== input.conversationWorkspace && !input.busy
}

/** Drop async conversation writes that finished after the owner changed. */
export function isWizardConversationWriteCurrent(owner: string, current: string): boolean {
  return Boolean(owner) && owner === current
}
