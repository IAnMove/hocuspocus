import { useCallback, useState } from 'react'

/**
 * Run a cancel/resume/discard call behind a busy flag and route its failure to
 * the panel's error line instead of an unhandled rejection.
 */
export function useJobAction(onError: (message: string) => void) {
  const [busy, setBusy] = useState(false)
  const run = useCallback(async <T,>(action: () => Promise<T>, apply: (value: T) => void) => {
    setBusy(true)
    try {
      apply(await action())
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setBusy(false)
    }
  }, [onError])
  return { busy, run }
}
