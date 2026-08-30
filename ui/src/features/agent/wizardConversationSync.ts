export const WIZARD_WELCOME_TEXT = 'Saludos, creador. Soy el mago de HocusPocus: puedo consultar la cola, explicarte el estudio, llevarte a la sección adecuada y preparar o lanzar un vídeo cuando me lo pidas. Dime qué quieres conjurar. 🪄'

export interface WizardSyncMessage {
  id: string
  role: 'user' | 'assistant'
  text: string
  createdAt: number
  cards?: unknown[]
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
      cards: Array.isArray(message.cards) && message.cards.length ? message.cards : undefined,
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
    const localById = new Map(localMessages.map(message => [message.id, message]))
    const merged = remoteMessages.map(message => localById.get(message.id) || message)
    for (const message of localMessages) {
      if (!remoteIds.has(message.id)) merged.push(message)
    }
    return { source: 'local', messages: merged.slice(-40), revision: Math.max(localRevision, remoteRevision) }
  }
  if (localRevision > remoteRevision) {
    return { source: 'local', messages: localMessages, revision: localRevision }
  }
  return { source: 'remote', messages: remoteMessages, revision: remoteRevision }
}
