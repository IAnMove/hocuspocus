export type PromptHistorySource = 'generation' | 'manual'

export interface PromptHistoryEntry {
  id: string
  prompt: string
  negativePrompt: string
  mode: string
  model: string
  workspace: string
  source: PromptHistorySource
  createdAt: string
}

const STORAGE_PREFIX = 'maestro-prompt-history-v1'
const HISTORY_LIMIT = 100
export const PROMPT_HISTORY_EVENT = 'maestro:prompt-history-changed'

const storageKey = (workspace: string) =>
  `${STORAGE_PREFIX}:${encodeURIComponent(workspace || 'default')}`

const makeId = () => globalThis.crypto?.randomUUID?.()
  ?? `prompt-${Date.now()}-${Math.random().toString(36).slice(2)}`

export function getPromptHistory(workspace = 'default'): PromptHistoryEntry[] {
  if (typeof window === 'undefined') return []
  try {
    const parsed = JSON.parse(window.localStorage.getItem(storageKey(workspace)) || '[]')
    if (!Array.isArray(parsed)) return []
    return parsed.filter((entry): entry is PromptHistoryEntry =>
      Boolean(entry && typeof entry.prompt === 'string' && entry.prompt.trim()))
  } catch {
    return []
  }
}

export function rememberPrompt(input: {
  prompt: unknown
  negativePrompt?: unknown
  mode?: unknown
  model?: unknown
  workspace?: unknown
  source?: PromptHistorySource
}): PromptHistoryEntry | null {
  if (typeof window === 'undefined') return null
  const prompt = typeof input.prompt === 'string' ? input.prompt.trim() : ''
  if (!prompt) return null
  const workspace = typeof input.workspace === 'string' && input.workspace.trim()
    ? input.workspace.trim()
    : 'default'
  const negativePrompt = typeof input.negativePrompt === 'string'
    ? input.negativePrompt.trim()
    : ''
  const mode = typeof input.mode === 'string' ? input.mode : ''
  const model = typeof input.model === 'string' ? input.model : ''
  const source = input.source || 'generation'
  const existing = getPromptHistory(workspace)
  const duplicate = existing.find(entry =>
    entry.prompt === prompt
    && entry.negativePrompt === negativePrompt
    && entry.mode === mode
    && entry.model === model)
  const entry: PromptHistoryEntry = {
    id: duplicate?.id || makeId(),
    prompt,
    negativePrompt,
    mode,
    model,
    workspace,
    source,
    createdAt: new Date().toISOString(),
  }
  const next = [
    entry,
    ...existing.filter(item => item.id !== entry.id),
  ].slice(0, HISTORY_LIMIT)
  try {
    window.localStorage.setItem(storageKey(workspace), JSON.stringify(next))
    window.dispatchEvent(new CustomEvent(PROMPT_HISTORY_EVENT, { detail: { workspace } }))
    return entry
  } catch (error) {
    console.warn('[Prompt history] Could not save prompt:', error)
    return null
  }
}

export function removePromptHistoryEntry(workspace: string, id: string): void {
  if (typeof window === 'undefined') return
  try {
    const next = getPromptHistory(workspace).filter(entry => entry.id !== id)
    window.localStorage.setItem(storageKey(workspace), JSON.stringify(next))
    window.dispatchEvent(new CustomEvent(PROMPT_HISTORY_EVENT, { detail: { workspace } }))
  } catch (error) {
    console.warn('[Prompt history] Could not remove prompt:', error)
  }
}
