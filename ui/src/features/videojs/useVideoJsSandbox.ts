import { useCallback, useEffect, useMemo, useState } from 'react'
import { VideoJsSandbox, VideoJsSandboxError, mergeSceneErrors, videoJsRenderSpec, type VideoJsRenderSpec } from './sandbox.ts'
import { hostSource, videoJsSandboxSources } from './sources.ts'
import type { VideoJsDocument, VideoJsSceneError } from './types.ts'

export type VideoJsSandboxStatus = 'loading' | 'ready' | 'crashed'

export function videoJsExportBlocker(errorCount: number, status: VideoJsSandboxStatus): 'blockedErrors' | 'blockedLoading' | null {
  if (errorCount > 0) return 'blockedErrors'
  return status === 'ready' ? null : 'blockedLoading'
}

/** Owns one sandbox per panel. It reloads only when something that affects
 *  pixels changes (not on title edits). */
export function useVideoJsSandbox(document: VideoJsDocument) {
  const [sandbox, setSandbox] = useState<VideoJsSandbox | null>(null)
  const [status, setStatus] = useState<VideoJsSandboxStatus>('loading')
  const [errors, setErrors] = useState<VideoJsSceneError[]>([])
  const [revision, setRevision] = useState(0)
  const [retry, setRetry] = useState(0)
  const specKey = JSON.stringify(videoJsRenderSpec(document))
  const spec = useMemo(() => JSON.parse(specKey) as VideoJsRenderSpec, [specKey])

  // A ref callback (not an effect) creates the sandbox when its host mounts.
  const attachHost = useCallback((node: HTMLDivElement | null) => {
    if (!node) return
    const instance = new VideoJsSandbox(node, hostSource)
    setSandbox(instance)
    return () => {
      instance.dispose()
      setSandbox(current => (current === instance ? null : current))
    }
  }, [])

  const fail = useCallback((error: unknown) => {
    const sceneError = error instanceof VideoJsSandboxError
      ? error.sceneError
      : { sceneId: '', phase: 'runtime' as const, message: error instanceof Error ? error.message : String(error) }
    setErrors(current => mergeSceneErrors(current, [sceneError]))
    setStatus('crashed')
  }, [])

  useEffect(() => {
    if (!sandbox) return
    let cancelled = false
    const timer = window.setTimeout(() => {
      setStatus('loading')
      void (async () => {
        try {
          const loadErrors = await sandbox.load(spec, await videoJsSandboxSources(spec))
          if (cancelled) return
          setErrors(loadErrors)
          setStatus('ready')
          setRevision(value => value + 1)
        } catch (error) {
          if (!cancelled) fail(error)
        }
      })()
    }, 250)
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [sandbox, spec, retry, fail])

  const reportFrameErrors = useCallback((next: VideoJsSceneError[]) => {
    setErrors(current => mergeSceneErrors(current, next))
  }, [])

  const reload = useCallback(() => setRetry(value => value + 1), [])

  return { attachHost, sandbox, status, errors, revision, reportFrameErrors, fail, reload }
}
