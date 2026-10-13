import { useCallback, useEffect, useRef, useState } from 'react'
import { cancelJob } from '../../api/client'
import { fetchCharacterKitLibrary, saveCharacterKit } from '../../api/characters'
import { canAddAnimation, reviewKitAnimation, withKitAnimation, withoutKitAnimation, type AnimationDef } from '../../lib/characterAnimations'
import type { CharacterKit, CharacterKitReviewState } from '../../lib/characterKit'
import { keptPoses, makeAnimation, type MakeStage, type MakerDependencies, type PoseTake } from './characterAnimationMaker'

export type AnimationRun = { kitId: string; animationId: string; stage: MakeStage; takes: PoseTake[] }

/** Make, review and delete the animations of a saved kit. One run at a time (one GPU); every change is read from the library
 * again just before it is saved, so another tab's edits to the kit are not overwritten. A run that failed stays on screen
 * with the poses it did make, and the next try keeps them. */
export function useCharacterAnimations(workspace: string, reload: () => void, dependencies?: Partial<MakerDependencies>) {
  const [run, setRun] = useState<AnimationRun>()
  const [working, setWorking] = useState(false)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState('')
  const operation = useRef<AbortController | null>(null)
  const job = useRef<string | null>(null)
  const previous = useRef<AnimationRun | undefined>(undefined)
  useEffect(() => () => {
    operation.current?.abort()
    if (job.current) void cancelJob(job.current).catch(() => {})
  }, [])

  const commit = useCallback(async (kitId: string, change: (kit: CharacterKit) => CharacterKit) => {
    const library = await fetchCharacterKitLibrary(workspace)
    const kit = library.kits[kitId]
    if (!kit) throw new Error('The character is no longer in the library.')
    await saveCharacterKit(workspace, library, change(kit))
    reload()
  }, [workspace, reload])

  const start = useCallback(async (kit: CharacterKit, def: AnimationDef, model: string, remake?: string) => {
    if (operation.current) return
    // A new id at the cap would run Qwen and then fail the kit save. Remaking one that is already on the kit is fine.
    if (!kit.animations?.[def.id] && !canAddAnimation(kit)) {
      setError('This character already has the most animations.')
      return
    }
    const controller = new AbortController()
    operation.current = controller
    setWorking(true); setError(''); setSaved('')
    // Remaking one pose keeps the others as they are; a retry after a failure keeps what was made.
    const frames = kit.animations?.[def.id]?.frames ?? []
    const again = previous.current?.kitId === kit.id && previous.current.animationId === def.id
    const reuse = remake ? Object.fromEntries(frames.filter(frame => frame.id !== remake).map(frame => [frame.id, frame.source]))
      : again ? keptPoses(previous.current!.takes) : {}
    try {
      const made = await makeAnimation({
        workspace, kit, def, model, signal: controller.signal, reuse,
        onUpdate: (takes, stage) => { previous.current = { kitId: kit.id, animationId: def.id, stage, takes }; setRun(previous.current) },
        onJobSubmitted: id => { if (controller.signal.aborted) void cancelJob(id).catch(() => {}); else job.current = id },
      }, dependencies)
      controller.signal.throwIfAborted()
      await commit(kit.id, fresh => withKitAnimation(fresh, def.id, made))
      previous.current = undefined; setRun(undefined); setSaved(def.id)
    } catch (cause) {
      if (!controller.signal.aborted) setError((cause as Error).message)
    } finally {
      if (operation.current === controller) { operation.current = null; job.current = null; setWorking(false) }
    }
  }, [workspace, commit, dependencies])

  const cancel = useCallback(() => {
    operation.current?.abort(); operation.current = null
    if (job.current) void cancelJob(job.current).catch(() => {})
    job.current = null; previous.current = undefined; setRun(undefined); setWorking(false)
  }, [])

  const change = useCallback(async (kitId: string, edit: (kit: CharacterKit) => CharacterKit) => {
    setError(''); setSaved('')
    try { await commit(kitId, edit) } catch (cause) { setError((cause as Error).message) }
  }, [commit])

  const review = useCallback((kitId: string, id: string, state: CharacterKitReviewState) => change(kitId, kit => reviewKitAnimation(kit, id, state)), [change])
  const remove = useCallback((kitId: string, id: string) => change(kitId, kit => withoutKitAnimation(kit, id)), [change])
  return { run, error, saved, busy: working, start, cancel, review, remove }
}
