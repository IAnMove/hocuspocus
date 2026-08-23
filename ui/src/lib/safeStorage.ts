export type SafeStorageArea = 'local' | 'session'

const memoryFallbacks: Record<SafeStorageArea, Map<string, string>> = {
  local: new Map(),
  session: new Map(),
}

// A key belongs here only when its latest write could not reach browser
// storage. This lets a successful external removal win without losing values
// that exist solely in memory after a quota or security failure.
const fallbackOnlyKeys: Record<SafeStorageArea, Set<string>> = {
  local: new Set(),
  session: new Set(),
}

function getStorage(area: SafeStorageArea): Storage | null {
  try {
    if (typeof window === 'undefined') return null
    return area === 'local' ? window.localStorage : window.sessionStorage
  } catch {
    return null
  }
}

export function safeStorageGet(area: SafeStorageArea, key: string): string | null {
  const fallback = memoryFallbacks[area]
  const fallbackOnly = fallbackOnlyKeys[area]
  const storage = getStorage(area)
  if (!storage) return fallback.get(key) ?? null

  try {
    const value = storage.getItem(key)
    if (value !== null) {
      fallback.set(key, value)
      fallbackOnly.delete(key)
      return value
    }

    if (fallbackOnly.has(key)) return fallback.get(key) ?? null

    // Browser storage was reachable and authoritatively reports the key as
    // absent, including removals performed by another tab.
    fallback.delete(key)
    return null
  } catch {
    // Private browsing, disabled storage, and quota/security policies are
    // expected browser states; use the session-local fallback below.
    return fallback.get(key) ?? null
  }
}

export function safeStorageSet(area: SafeStorageArea, key: string, value: string): void {
  memoryFallbacks[area].set(key, value)
  const fallbackOnly = fallbackOnlyKeys[area]
  const storage = getStorage(area)
  if (!storage) {
    fallbackOnly.add(key)
    return
  }

  try {
    storage.setItem(key, value)
    fallbackOnly.delete(key)
  } catch {
    // The in-memory value keeps the current tab functional when persistence
    // is unavailable or the browser reports a quota/security error.
    fallbackOnly.add(key)
  }
}

export function safeStorageRemove(area: SafeStorageArea, key: string): void {
  memoryFallbacks[area].delete(key)
  fallbackOnlyKeys[area].delete(key)
  try {
    getStorage(area)?.removeItem(key)
  } catch {
    // Removal is best-effort; the fallback was cleared above regardless.
  }
}
