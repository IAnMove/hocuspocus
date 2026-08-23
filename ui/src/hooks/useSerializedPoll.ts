import { useEffect, useRef } from 'react'

export type SerializedPollOptions<T> = {
  enabled?: boolean
  intervalMs: number
  ownerKey?: string | number | null
  immediate?: boolean
  poll: (signal: AbortSignal) => Promise<T>
  onValue: (value: T) => void
  onError?: (reason: unknown) => void
}

function isAbortError(reason: unknown): boolean {
  return reason instanceof DOMException && reason.name === 'AbortError'
}

/** Run one poll at a time, cancelling and invalidating work when ownership changes. */
export function useSerializedPoll<T>({
  enabled = true,
  intervalMs,
  ownerKey = null,
  immediate = true,
  poll,
  onValue,
  onError,
}: SerializedPollOptions<T>): void {
  const pollRef = useRef(poll)
  const onValueRef = useRef(onValue)
  const onErrorRef = useRef(onError)
  pollRef.current = poll
  onValueRef.current = onValue
  onErrorRef.current = onError

  useEffect(() => {
    if (!enabled) return

    let disposed = false
    let epoch = 0
    let timer: number | undefined
    let controller: AbortController | null = null

    const schedule = () => {
      if (disposed) return
      timer = window.setTimeout(() => {
        timer = undefined
        void run()
      }, intervalMs)
    }

    const run = async () => {
      if (disposed || controller) return
      const runEpoch = ++epoch
      const runController = new AbortController()
      controller = runController
      try {
        const value = await pollRef.current(runController.signal)
        if (
          !disposed
          && runEpoch === epoch
          && controller === runController
          && !runController.signal.aborted
        ) onValueRef.current(value)
      } catch (reason) {
        if (
          !disposed
          && runEpoch === epoch
          && controller === runController
          && !runController.signal.aborted
          && !isAbortError(reason)
        ) onErrorRef.current?.(reason)
      } finally {
        if (controller === runController) controller = null
        if (!disposed && runEpoch === epoch) schedule()
      }
    }

    if (immediate) void run()
    else schedule()

    return () => {
      disposed = true
      epoch += 1
      if (timer !== undefined) window.clearTimeout(timer)
      controller?.abort()
      controller = null
    }
  }, [enabled, intervalMs, immediate, ownerKey])
}
