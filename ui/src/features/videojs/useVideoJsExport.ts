import { useCallback, useRef, useState } from 'react'
import { useStore } from '../../stores/useStore'
import { publishVideoJsRecording, renderVideoJsMp4 } from './exportVideo.ts'
import type { VideoJsSandbox } from './sandbox.ts'
import type { VideoJsDocument } from './types.ts'

export type VideoJsExportState =
  | { phase: 'idle' }
  | { phase: 'rendering'; current: number; total: number }
  | { phase: 'publishing' }
  | { phase: 'done'; name: string; url: string }
  | { phase: 'error'; message: string }

export function isVideoJsExporting(state: VideoJsExportState): boolean {
  return state.phase === 'rendering' || state.phase === 'publishing'
}

export function useVideoJsExport(sandbox: VideoJsSandbox | null, document: VideoJsDocument, workspace: string) {
  const [state, setState] = useState<VideoJsExportState>({ phase: 'idle' })
  const controller = useRef<AbortController | null>(null)
  const start = useCallback(async () => {
    if (!sandbox?.isLoaded) return
    const abort = new AbortController()
    controller.current = abort
    setState({ phase: 'rendering', current: 0, total: 1 })
    try {
      const blob = await renderVideoJsMp4(sandbox, document, {
        signal: abort.signal,
        onProgress: (current, total) => setState({ phase: 'rendering', current, total }),
      })
      setState({ phase: 'publishing' })
      const saved = await publishVideoJsRecording(blob, document, workspace)
      const url = new URL(saved.url, window.location.origin)
      if (workspace) url.searchParams.set('workspace', workspace)
      setState({ phase: 'done', name: saved.name, url: `${url.pathname}${url.search}` })
      void useStore.getState().maybeRefreshGallery({ force: true })
    } catch (error) {
      if (abort.signal.aborted) setState({ phase: 'idle' })
      else setState({ phase: 'error', message: error instanceof Error ? error.message : String(error) })
    } finally {
      controller.current = null
    }
  }, [sandbox, document, workspace])
  const cancel = useCallback(() => controller.current?.abort(), [])
  return { state, start, cancel }
}
