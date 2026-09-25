import { useEffect, useMemo } from 'react'
import { fetchOutputFacts } from '../../api/outputs'
import { useStore } from '../../stores/useStore'
import type { OutputFile } from '../../types'

const POLL_MS = 3000
/** Consecutive polls with nothing new before giving up on the rest. */
const IDLE_POLLS = 5
const BATCH = 200

/** Outputs whose size or placeholder colour the server may still work out. */
export function missingFactNames(outputs: OutputFile[]): string[] {
  return outputs
    .filter(file => (file.type === 'image' || file.type === 'video') && (!file.color || !file.width || !file.height))
    .map(file => file.name)
}

/** While listed images and videos lack a size or colour, ask the server for
 *  the ones its background worker has finished, so they settle into place
 *  without reloading the list. Stops when the page is hidden, when nothing is
 *  missing, or after a few polls that bring nothing new (some outputs never
 *  get a colour, such as fully transparent cut-outs). */
export function useLiveMediaFacts(outputs: OutputFile[], workspace: string, enabled: boolean) {
  const missing = useMemo(() => missingFactNames(outputs), [outputs])
  const key = missing.join('\n')

  useEffect(() => {
    if (!enabled || !key) return
    const names = key.split('\n').slice(0, BATCH)
    const controller = new AbortController()
    let idle = 0
    let timer = 0
    const poll = async () => {
      if (document.visibilityState === 'visible') {
        try {
          const facts = await fetchOutputFacts(names, workspace, controller.signal)
          if (controller.signal.aborted) return
          // Progress (even a size without its colour yet) keeps polling.
          idle = useStore.getState().mergeOutputFacts(facts) ? 0 : idle + 1
        } catch {
          if (controller.signal.aborted) return
          idle += 1
        }
      }
      if (idle < IDLE_POLLS) timer = window.setTimeout(() => void poll(), POLL_MS)
    }
    timer = window.setTimeout(() => void poll(), POLL_MS)
    return () => {
      controller.abort()
      window.clearTimeout(timer)
    }
  }, [enabled, key, workspace])
}
