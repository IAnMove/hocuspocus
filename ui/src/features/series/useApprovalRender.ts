import { useCallback, useEffect, useRef, useState } from 'react'
import {
  controlSeriesServerRender, fetchSeriesServerRender, fetchSeriesServerRenders, startSeriesServerRender, type SeriesServerRenderJob,
} from '../../api/series'

const LIVE = new Set(['queued', 'running', 'cancelling'])
type RenderState = { scope: string; job?: SeriesServerRenderJob; error: string; busy: boolean }

/** The episode's server render from the review: start (all that needs a pass, or some shots), follow, stop. */
export function useApprovalRender(workspace: string, seriesId: string, episodeId: string, reload: () => Promise<void>) {
  const scope = JSON.stringify([workspace, seriesId, episodeId])
  const epoch = useRef(0), acting = useRef<string | null>(null)
  const invalidate = useCallback(() => ++epoch.current, [])
  const [state, setState] = useState<RenderState>({ scope, error: '', busy: false })
  const { job, error, busy } = state.scope === scope ? state : { job: undefined, error: '', busy: false }
  useEffect(() => {
    const version = invalidate()
    acting.current = null
    fetchSeriesServerRenders(workspace).then(jobs => {
      const latest = jobs.filter(item => item.seriesId === seriesId && item.episodeId === episodeId && item.original !== false)
        .sort((a, b) => (b.createdAt ?? 0) - (a.createdAt ?? 0))[0]
      if (version === epoch.current) setState({ scope, job: latest, error: '', busy: false })
    }).catch(cause => {
      if (version === epoch.current) setState({ scope, error: (cause as Error).message, busy: false })
    })
    return () => { invalidate() }
  }, [scope, workspace, seriesId, episodeId, invalidate])
  const live = Boolean(job && LIVE.has(job.status))
  useEffect(() => {
    if (!job || !LIVE.has(job.status) || busy) return
    let alive = true, polling = false
    const timer = window.setInterval(() => {
      if (polling) return
      polling = true
      const version = epoch.current
      fetchSeriesServerRender(workspace, job.jobId).then(next => {
        if (!alive || version !== epoch.current) return
        setState({ scope, job: next, error: '', busy: false })
        if (!LIVE.has(next.status)) void reload().catch(() => {})
      }).catch(cause => {
        if (alive && version === epoch.current) setState(current => ({ ...current, error: (cause as Error).message }))
      }).finally(() => { polling = false })
    }, 3000)
    return () => { alive = false; window.clearInterval(timer) }
  }, [scope, workspace, job, busy, reload])
  const act = useCallback(async (task: () => Promise<SeriesServerRenderJob>) => {
    if (acting.current === scope) return
    acting.current = scope
    const version = invalidate()
    setState(current => ({ scope, job: current.scope === scope ? current.job : undefined, busy: true, error: '' }))
    try {
      const next = await task()
      if (version === epoch.current) setState({ scope, job: next, error: '', busy: false })
    } catch (cause) {
      if (version === epoch.current) setState(current => ({ ...current, error: (cause as Error).message, busy: false }))
    } finally { if (version === epoch.current) acting.current = null }
  }, [scope, invalidate])
  /** Some shots by id (a new pass even when one waits for review), else every shot that needs a render. */
  const start = useCallback((shotIds?: string[]) => act(() => startSeriesServerRender(workspace, seriesId, episodeId, false, undefined,
    shotIds, !shotIds?.length)), [act, workspace, seriesId, episodeId])
  const stop = useCallback(() => { if (job) void act(() => controlSeriesServerRender(workspace, job.jobId, 'cancel')) }, [act, job, workspace])
  return { job, live, busy, error, start, stop }
}

export type ApprovalRender = ReturnType<typeof useApprovalRender>
