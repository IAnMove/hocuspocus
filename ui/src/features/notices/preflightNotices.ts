import { fetchPreflight, type PreflightCheck } from '../../api/client'
import { safeStorageGet, safeStorageSet } from '../../lib/safeStorage'

/** Same session key the old top bar used. CUDA is never included in that dismissal. */
const DISMISS_KEY = 'maestro_preflight_dismissed'

let checks: PreflightCheck[] = []
let revision = 0
let request = 0
const listeners = new Set<() => void>()

function emit() {
  revision += 1
  for (const listener of listeners) listener()
}

export function subscribePreflight(listener: () => void) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function preflightRevision() {
  return revision
}

export function preflightDismissed() {
  return safeStorageGet('session', DISMISS_KEY) === '1'
}

/** CUDA stays. Every other check hides together, the way the old bar did. */
export function visiblePreflightChecks(source: PreflightCheck[] = checks): PreflightCheck[] {
  const cuda = source.filter(check => check.id === 'cuda')
  if (preflightDismissed()) return cuda
  return [...cuda, ...source.filter(check => check.id !== 'cuda')]
}

export function dismissPreflight() {
  safeStorageSet('session', DISMISS_KEY, '1')
  emit()
}

export function loadPreflight() {
  const token = ++request
  return fetchPreflight()
    .then(result => {
      if (token !== request) return
      checks = result.checks || []
      emit()
    })
    .catch(() => {
      if (token !== request) return
    })
}

export function resetPreflightForTests() {
  checks = []
  request += 1
  emit()
}
