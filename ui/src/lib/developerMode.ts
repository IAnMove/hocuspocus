const KEY = 'hocuspocus-developer-mode-v1'

export function loadDeveloperMode(): boolean {
  try {
    return localStorage.getItem(KEY) === '1'
  } catch {
    return false
  }
}

export function saveDeveloperMode(enabled: boolean) {
  try {
    if (enabled) localStorage.setItem(KEY, '1')
    else localStorage.removeItem(KEY)
  } catch {
    /* private mode or blocked storage */
  }
}
