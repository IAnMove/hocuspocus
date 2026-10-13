import { useCallback, useEffect, useRef, useState } from 'react'
import { cancelAnimationJob, fetchAnimationJobs, isActiveJob, startAnimationJob, type AnimationJob } from '../../api/characterAnimationJobs'
import { fetchCharacterKitLibrary, saveCharacterKit } from '../../api/characters'
import { customAnimationDef, reviewKitAnimation, withoutKitAnimation, animationDef, type AnimationDef } from '../../lib/characterAnimations'
import type { CharacterKit, CharacterKitReviewState } from '../../lib/characterKit'

/** The job to show for each animation of the character: its latest one, unless it completed (the made animation is on the kit then). */
export function runsOf(jobs: AnimationJob[]): Record<string, AnimationJob> {
  const latest: Record<string, AnimationJob> = {}
  for (const job of jobs) if (!latest[job.animationId] || job.createdAt > latest[job.animationId].createdAt) latest[job.animationId] = job
  return Object.fromEntries(Object.entries(latest).filter(([, job]) => job.status !== 'completed'))
}

/** The animations the author described whose first run is not on the kit yet (still going, or failed): they stay on screen, whatever
 * happens to the page, because the job keeps the words. */
export function pendingCustomDefs(runs: Record<string, AnimationJob>, kit: CharacterKit): AnimationDef[] {
  return Object.values(runs).filter(job => job.custom && !animationDef(job.animationId) && !kit.animations?.[job.animationId])
    .map(job => customAnimationDef(job.animationId, job.custom!.title, job.custom!.view, job.custom!.poses))
}

/** Make, review and delete the animations of a saved character. Making is a job on the server (the Wizard and the MCP tools start the
 * same one), so this only starts it and follows it: a run survives a reload, a tab change or a restart, and a failed one keeps the poses
 * it made. Review and deletion are edits of the kit, read from the library again just before they are saved. */
export function useCharacterAnimations(workspace: string, kitId: string | undefined, reload: () => void, pollMs = 2000, idleMs = 8000) {
  const [jobs, setJobs] = useState<AnimationJob[]>([])
  const [error, setError] = useState('')
  const [saved, setSaved] = useState('')
  const known = useRef<Record<string, string>>({})
  const openedAt = useRef(Date.now())

  const refresh = useCallback(async () => {
    if (!kitId) return
    const latest = await fetchAnimationJobs(workspace, kitId)
    for (const job of latest) {
      // A job that ended while this was looking (or that started and ended between two looks) put its animation on the character.
      const before = known.current[job.jobId]
      const endedNow = job.status === 'completed' && (before ? before !== 'completed' : job.createdAt * 1000 >= openedAt.current)
      if (endedNow) { reload(); setSaved(job.animationId) }
      known.current[job.jobId] = job.status
    }
    setJobs(latest)
  }, [workspace, kitId, reload])

  useEffect(() => {
    known.current = {}; openedAt.current = Date.now()
    setJobs([]); setSaved('')
    if (kitId) void refresh().catch(cause => setError((cause as Error).message))
  }, [workspace, kitId]) // eslint-disable-line react-hooks/exhaustive-deps

  // Quick while a job runs; slow otherwise, so an animation the Wizard or an MCP tool starts shows up here as well.
  const active = jobs.some(isActiveJob)
  useEffect(() => {
    if (!kitId) return undefined
    const timer = setInterval(() => { void refresh().catch(() => undefined) }, active ? pollMs : idleMs)
    return () => clearInterval(timer)
  }, [kitId, active, refresh, pollMs, idleMs])

  const start = useCallback(async (kit: CharacterKit, def: AnimationDef, model: string, remake?: string) => {
    setError(''); setSaved('')
    try {
      // An animation the kit does not have yet is made from the words the author wrote; one it has is made again from the words it kept.
      const custom = def.custom && !kit.animations?.[def.id]
        ? { title: def.title.es, view: def.view as 'bust' | 'front' | 'side', poses: def.poses.map(pose => pose.prompt) } : undefined
      const job = await startAnimationJob({ workspace, kitId: kit.id, animation: def.id, model, ...(remake ? { pose: remake } : {}), ...(custom ? { custom } : {}) })
      known.current[job.jobId] = job.status
      setJobs(list => [job, ...list.filter(item => item.jobId !== job.jobId)])
    } catch (cause) { setError((cause as Error).message) }
  }, [workspace])

  const cancel = useCallback(async (jobId: string) => {
    try { const job = await cancelAnimationJob(workspace, jobId); setJobs(list => list.map(item => item.jobId === jobId ? job : item)) }
    catch (cause) { setError((cause as Error).message) }
  }, [workspace])

  const commit = useCallback(async (id: string, change: (kit: CharacterKit) => CharacterKit) => {
    const library = await fetchCharacterKitLibrary(workspace)
    const kit = library.kits[id]
    if (!kit) throw new Error('The character is no longer in the library.')
    await saveCharacterKit(workspace, library, change(kit))
    reload()
  }, [workspace, reload])
  const change = useCallback(async (id: string, edit: (kit: CharacterKit) => CharacterKit) => {
    setError(''); setSaved('')
    try { await commit(id, edit) } catch (cause) { setError((cause as Error).message) }
  }, [commit])
  const review = useCallback((id: string, animation: string, state: CharacterKitReviewState) => change(id, kit => reviewKitAnimation(kit, animation, state)), [change])
  const remove = useCallback((id: string, animation: string) => change(id, kit => withoutKitAnimation(kit, animation)), [change])

  return { runs: runsOf(jobs), busy: active, error, saved, start, cancel, review, remove }
}
