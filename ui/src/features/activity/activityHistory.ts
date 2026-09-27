const HIDDEN_HISTORY_STORAGE_PREFIX = 'maestro-activity-hidden-v1:'

export function hiddenHistoryStorageKey(workspace: string): string {
  return `${HIDDEN_HISTORY_STORAGE_PREFIX}${workspace}`
}

export function readHiddenHistory(workspace: string): Set<string> {
  try {
    const raw = window.localStorage.getItem(hiddenHistoryStorageKey(workspace))
    const parsed = raw ? JSON.parse(raw) : []
    if (!Array.isArray(parsed)) return new Set()
    return new Set(parsed.filter(value => typeof value === 'string'))
  } catch {
    return new Set()
  }
}

export function writeHiddenHistory(workspace: string, ids: Set<string>): void {
  try {
    const key = hiddenHistoryStorageKey(workspace)
    if (ids.size) window.localStorage.setItem(key, JSON.stringify([...ids]))
    else window.localStorage.removeItem(key)
  } catch {
    // Hiding history is still useful for the current session if storage is
    // blocked (private browsing, disabled cookies, or a quota error).
  }
}
