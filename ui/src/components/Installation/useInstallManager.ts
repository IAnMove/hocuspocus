import { useCallback, useEffect, useRef, useState } from 'react'
import {
  fetchInstallStatus, startComponentInstall, startComponentUninstall,
  type InstallStatus,
} from '../../api/installManager'

const POLL_WHILE_BUSY_MS = 2000
const POLL_IDLE_MS = 10000

export type InstallAction = 'install' | 'uninstall'

/** Status of every optional component, refreshed while `active`: quickly during a change
 *  (also so a change started in another tab shows up), slowly otherwise. */
export function useInstallManager(active: boolean) {
  const [status, setStatus] = useState<InstallStatus | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [actingId, setActingId] = useState<string | null>(null)
  const busy = useRef<string | null>(null)
  const reload = useRef<() => Promise<void>>(async () => {})

  useEffect(() => {
    if (!active) return undefined
    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | undefined
    const load = async () => {
      try {
        const next = await fetchInstallStatus()
        if (cancelled) return
        busy.current = next.busy
        setStatus(next)
        setError(null)
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e))
      }
    }
    const tick = async () => {
      await load()
      if (!cancelled) timer = setTimeout(tick, busy.current ? POLL_WHILE_BUSY_MS : POLL_IDLE_MS)
    }
    reload.current = load
    void tick()
    return () => {
      cancelled = true
      if (timer) clearTimeout(timer)
    }
  }, [active])

  const act = useCallback(async (id: string, action: InstallAction) => {
    setActingId(id)
    setError(null)
    try {
      await (action === 'install' ? startComponentInstall(id) : startComponentUninstall(id))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setActingId(null)
      await reload.current()
    }
  }, [])

  return { status, error, actingId, act }
}
