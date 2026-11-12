import { useEffect, useState } from 'react'
import { fetchComponentOutput } from '../../api/installManager'

const POLL_MS = 2000

/** The last lines of a component's installer, followed live while it runs. */
export function InstallOutput({ id, running }: { id: string; running: boolean }) {
  const [lines, setLines] = useState<string[]>([])

  useEffect(() => {
    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | undefined
    const load = async () => {
      try {
        const next = await fetchComponentOutput(id)
        if (!cancelled) setLines(next)
      } catch {
        // The output is a convenience; the status above already says what happened.
      }
      if (!cancelled && running) timer = setTimeout(load, POLL_MS)
    }
    void load()
    return () => {
      cancelled = true
      if (timer) clearTimeout(timer)
    }
  }, [id, running])

  return (
    <pre className="mt-2 max-h-40 overflow-auto rounded border border-border bg-bg-primary p-2 text-[10px] leading-snug text-text-secondary whitespace-pre-wrap break-words">
      {lines.length ? lines.join('\n') : '…'}
    </pre>
  )
}
