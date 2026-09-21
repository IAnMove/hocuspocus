import { useEffect, useState } from 'react'
import { fetchSystemCapabilities, type SystemCapabilities } from '../api/system'

let cached: SystemCapabilities | null = null
let pending: Promise<SystemCapabilities> | null = null

function load(): Promise<SystemCapabilities> {
  if (cached) return Promise.resolve(cached)
  if (!pending) {
    pending = fetchSystemCapabilities().then(value => {
      cached = value
      return value
    }).finally(() => { pending = null })
  }
  return pending
}

export function usePlatformCapabilities(): SystemCapabilities | null {
  const [snapshot, setSnapshot] = useState<SystemCapabilities | null>(cached)
  useEffect(() => {
    let cancelled = false
    load().then(value => { if (!cancelled) setSnapshot(value) }).catch(() => {})
    return () => { cancelled = true }
  }, [])
  return snapshot
}

export function showsCudaControls(snapshot: SystemCapabilities | null): boolean {
  return snapshot?.ui.show_cuda_controls !== false
}
