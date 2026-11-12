import { useCallback, useEffect, useRef, useState } from 'react'

export type Notice = { kind: 'ok' | 'error'; text: string } | null

/**
 * One notice at a time. Confirmations hide themselves after `hideAfterMs`;
 * errors stay until the next notice or an explicit `notify(null)`. A newer
 * notice always cancels the previous timer so it cannot wipe the newer text.
 */
export function useTimedNotice(hideAfterMs = 5000): [Notice, (value: Notice) => void] {
  const [notice, setNotice] = useState<Notice>(null)
  const timerRef = useRef<number | null>(null)
  const clearTimer = () => {
    if (timerRef.current === null) return
    window.clearTimeout(timerRef.current)
    timerRef.current = null
  }
  const notify = useCallback((value: Notice) => {
    clearTimer()
    setNotice(value)
    if (value?.kind !== 'ok') return
    timerRef.current = window.setTimeout(() => {
      timerRef.current = null
      setNotice(null)
    }, hideAfterMs)
  }, [hideAfterMs])
  useEffect(() => clearTimer, [])
  return [notice, notify]
}
