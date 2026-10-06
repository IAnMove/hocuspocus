import { useCallback, useEffect, useState } from 'react'
import {
  controlSeriesServerRender, fetchSeriesServerRender, fetchSeriesServerRenders, startSeriesServerRender, type SeriesServerRenderJob,
} from '../../api/series'

const LIVE = new Set(['queued', 'running', 'cancelling'])

/** The episode's server render from the review: start (all that needs a pass, or some shots), follow, stop. */
export function useApprovalRender(workspace: string, seriesId: string, episodeId: string, reload: () => Promise<void>) {
  const [job, setJob] = useState<SeriesServerRenderJob>()
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    let alive = true
    fetchSeriesServerRenders(workspace).then(jobs => {
      const latest = jobs.filter(item => item.seriesId === seriesId && item.episodeId === episodeId && item.original !== false)
        .sort((a, b) => (b.createdAt ?? 0) - (a.createdAt ?? 0))[0]
      if (alive && latest) setJob(latest)
    }).catch(() => {})
    return () => { alive = false }
  }, [workspace, seriesId, episodeId])
  const live = Boolean(job && LIVE.has(job.status))
  useEffect(() => {
    if (!job || !LIVE.has(job.status)) return
    const timer = window.setInterval(() => {
      fetchSeriesServerRender(workspace, job.jobId).then(next => {
        setJob(next)
        if (!LIVE.has(next.status)) void reload().catch(() => {})
      }).catch(cause => setError((cause as Error).message))
    }, 3000)
    return () => window.clearInterval(timer)
  }, [workspace, job, reload])
  const act = useCallback(async (task: () => Promise<SeriesServerRenderJob>) => {
    setBusy(true); setError('')
    try { setJob(await task()) } catch (cause) { setError((cause as Error).message) } finally { setBusy(false) }
  }, [])
  /** Some shots by id (a new pass even when one waits for review), else every shot that needs a render. */
  const start = useCallback((shotIds?: string[]) => act(() => startSeriesServerRender(workspace, seriesId, episodeId, false, undefined,
    shotIds, !shotIds?.length)), [act, workspace, seriesId, episodeId])
  const stop = useCallback(() => { if (job) void act(() => controlSeriesServerRender(workspace, job.jobId, 'cancel')) }, [act, job, workspace])
  return { job, live, busy, error, start, stop }
}

export type ApprovalRender = ReturnType<typeof useApprovalRender>
