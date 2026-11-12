import type { ProductionProfile } from '../../types'

const DISMISSED_KEY = 'hocuspocus-production-profile-notice'
const closedVisit = new Set<string>()
let revision = 0
const listeners = new Set<() => void>()

function emit() {
  revision += 1
  for (const listener of listeners) listener()
}

export function subscribeProfileNotice(listener: () => void) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function profileNoticeRevision() {
  return revision
}

export function profileNoticeSignature(invalidReason: string, profile: ProductionProfile): string {
  return invalidReason
    ? `invalid:${invalidReason}`
    : `defaults:${profile.text.provider}:${profile.image.provider}`
}

function dismissedFor(signature: string): boolean {
  try {
    return localStorage.getItem(DISMISSED_KEY) === signature
  } catch {
    return false
  }
}

function remember(signature: string) {
  try {
    localStorage.setItem(DISMISSED_KEY, signature)
  } catch {
    // Storage can be unavailable; the visit set still hides it until reload.
  }
}

export function isProfileNoticeVisible(loaded: boolean, configured: boolean, signature: string): boolean {
  if (!loaded || configured) return false
  if (closedVisit.has(signature)) return false
  return !dismissedFor(signature)
}

export function dismissProfileNotice(signature: string) {
  closedVisit.add(signature)
  remember(signature)
  emit()
}

export function resetProfileNoticeForTests() {
  closedVisit.clear()
  emit()
}
