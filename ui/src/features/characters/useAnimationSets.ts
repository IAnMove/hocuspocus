import { useCallback, useEffect, useState } from 'react'
import { cancelAnimationSet, fetchAnimationSets, isActiveSet, startAnimationSet, type AnimationSetJob } from '../../api/characterAnimationSets'
import type { AnimationSetName } from '../../lib/characterAnimations'

/** The newest set job of each set: what the panel shows while the sheets are made, and why one stopped. */
export function latestSets(jobs: AnimationSetJob[]): Partial<Record<AnimationSetName, AnimationSetJob>> {
  const latest: Partial<Record<AnimationSetName, AnimationSetJob>> = {}
  for (const job of jobs) if (!latest[job.set] || job.createdAt > latest[job.set]!.createdAt) latest[job.set] = job
  return latest
}

/** Start, follow and cancel the set jobs of a saved character. A set is a job on the server (the Wizard and the MCP tools start the same
 * one), so this only starts and follows it: it survives a reload, a tab change and a restart, and a stopped one is resumed by starting the
 * same set again. Quick while one runs, slow otherwise, so a set an agent starts shows up here too. */
export function useAnimationSets(workspace: string, kitId: string | undefined, pollMs = 2000, idleMs = 8000) {
  const scope = `${workspace}\u0000${kitId ?? ''}`
  const [view, setView] = useState<{ scope: string; jobs: AnimationSetJob[] }>({ scope, jobs: [] })
  const jobs = view.scope === scope ? view.jobs : []
  const [error, setError] = useState('')
  const show = useCallback((change: (current: AnimationSetJob[]) => AnimationSetJob[]) => setView(previous => ({ scope, jobs: change(previous.scope === scope ? previous.jobs : []) })), [scope])

  const load = useCallback(async () => {
    if (!kitId) return
    const latest = await fetchAnimationSets(workspace, kitId)
    show(() => latest)
  }, [workspace, kitId, show])

  useEffect(() => {
    if (!kitId) return undefined
    const first = setTimeout(() => { void load().catch(cause => setError((cause as Error).message)) }, 0)
    return () => clearTimeout(first)
  }, [workspace, kitId]) // eslint-disable-line react-hooks/exhaustive-deps

  const active = jobs.some(isActiveSet)
  useEffect(() => {
    if (!kitId) return undefined
    const timer = setInterval(() => { void load().catch(() => undefined) }, active ? pollMs : idleMs)
    return () => clearInterval(timer)
  }, [kitId, active, load, pollMs, idleMs])

  const start = useCallback(async (set: AnimationSetName, model: string) => {
    if (!kitId) return
    setError('')
    try {
      const job = await startAnimationSet({ workspace, kitId, set, model })
      show(current => [job, ...current.filter(item => item.jobId !== job.jobId)])
    } catch (cause) { setError((cause as Error).message) }
  }, [workspace, kitId, show])

  const cancel = useCallback(async (jobId: string) => {
    try { const job = await cancelAnimationSet(workspace, jobId); show(current => current.map(item => item.jobId === jobId ? job : item)) }
    catch (cause) { setError((cause as Error).message) }
  }, [workspace, show])

  return { latest: latestSets(jobs), active, error, start, cancel }
}
