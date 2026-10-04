import { useCallback, useState, type RefObject } from 'react'
import { animateHumanoid } from '../../api/model3d'
import { patchScene3DSlot } from './templates'
import { motionPathPoints, walkKey } from './walkPath'
import type { Scene3DStageHandle } from './Scene3DStage'
import type { Scene3DDocument, Scene3DSlot } from './types'

export type WalkBakeState = { slotId: string; status: 'baking' | 'error'; message?: string } | null

/** Bake the selected humanoid's path into a walk clip with planted feet, then let the clip move it. */
export function useWalkBake(
  stageRef: RefObject<Scene3DStageHandle | null>,
  document: Scene3DDocument,
  applyScene: (updater: (current: Scene3DDocument) => Scene3DDocument) => void,
  messages: { needsSaved: string; failed: string },
) {
  const [state, setState] = useState<WalkBakeState>(null)
  const bake = useCallback(async (slot: Scene3DSlot) => {
    const ref = slot.sourceRef
    const points = stageRef.current?.modelSpacePath?.(slot.id, motionPathPoints(slot))
    if (!ref || !points || points.length < 2) { setState({ slotId: slot.id, status: 'error', message: messages.needsSaved }); return }
    setState({ slotId: slot.id, status: 'baking' })
    try {
      const duration = document.duration
      const result = await animateHumanoid({ workspace: ref.workspaceId, source: ref.filename, clips: [], bpm: 120, path: { points, duration } })
      const made = result.clips[result.clips.length - 1]
      if (!made) throw new Error(messages.failed)
      const clip = { index: made.index, name: made.name }
      applyScene(current => {
        const live = current.slots.find(item => item.id === slot.id)
        if (!live?.motion) return current
        return patchScene3DSlot(current, slot.id, {
          sourceUrl: result.url, sourceRef: { ...ref, filename: result.file, url: result.url }, clip,
          clipPlayback: { speed: 1, start: 0, loop: false },
          clips: undefined,
          motion: { ...live.motion, walk: { sourceUrl: result.url, clip, key: walkKey(live, duration) } },
        })
      })
      setState(null)
    } catch (error) {
      setState({ slotId: slot.id, status: 'error', message: error instanceof Error ? error.message : messages.failed })
    }
  }, [stageRef, document.duration, applyScene, messages.needsSaved, messages.failed])
  /** The Travel panel's walk control for one slot. */
  const control = useCallback((slot: Scene3DSlot) => {
    const mine = state?.slotId === slot.id ? state : null
    return { sceneDuration: document.duration, baking: mine?.status === 'baking', error: mine?.message, onBake: () => void bake(slot) }
  }, [state, document.duration, bake])
  return { state, bake, control }
}
