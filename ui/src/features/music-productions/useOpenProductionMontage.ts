import { useEffect, useRef } from 'react'
import { useStore } from '../../stores/useStore'
import { loadMontageIntoEditor } from '../video-editor/montageLoader'
import type { MontageEditorState } from '../video-editor/MontageControls'
import type { MontageLayers, MontageRef } from '../video-editor/montage'

export const MUSIC_PRODUCTION_MONTAGE_KEY = 'hocuspocus:music-production-montage'
export const MUSIC_PRODUCTION_MONTAGE_EVENT = 'hocuspocus:music-production-montage'

type ApplyMontage = (state: MontageEditorState, layers: MontageLayers, ref: MontageRef) => void

/** Node UI tests mount the editor without a browser storage global. */
function browserStorage(): Storage | null {
  return typeof sessionStorage === 'undefined' ? null : sessionStorage
}

/** Remember the montage, then open the Video Editor. The editor consumes the key on mount if it was not listening yet. */
export function requestOpenMontage(workspace: string, file: string) {
  browserStorage()?.setItem(MUSIC_PRODUCTION_MONTAGE_KEY, JSON.stringify({ workspace, file }))
  const state = useStore.getState()
  state.setSettingsOpen(false)
  state.setDashboardOpen(false)
  state.setSidebarOpen(false)
  state.setMediaFilter('videoeditor')
  window.dispatchEvent(new CustomEvent(MUSIC_PRODUCTION_MONTAGE_EVENT, { detail: { workspace, file } }))
  window.dispatchEvent(new Event('hocuspocus:music-productions-close'))
}

export function useOpenProductionMontage(workspace: string, applyMontage: ApplyMontage) {
  const applyRef = useRef(applyMontage)
  applyRef.current = applyMontage
  const busy = useRef(false)
  useEffect(() => {
    let cancelled = false
    const consume = async () => {
      const storage = browserStorage()
      const raw = storage?.getItem(MUSIC_PRODUCTION_MONTAGE_KEY)
      if (!raw || busy.current) return
      let pending: { workspace?: string; file?: string }
      try {
        pending = JSON.parse(raw) as { workspace?: string; file?: string }
      } catch {
        storage?.removeItem(MUSIC_PRODUCTION_MONTAGE_KEY)
        return
      }
      if ((pending.workspace || 'default') !== (workspace || 'default') || !pending.file) return
      busy.current = true
      try {
        const loaded = await loadMontageIntoEditor(workspace, pending.file)
        if (cancelled) return
        applyRef.current(loaded.state, loaded.layers, loaded.ref)
        storage?.removeItem(MUSIC_PRODUCTION_MONTAGE_KEY)
      } catch {
        // Leave the key so the next mount can try again.
      } finally {
        busy.current = false
      }
    }
    void consume()
    const onEvent = () => { void consume() }
    window.addEventListener(MUSIC_PRODUCTION_MONTAGE_EVENT, onEvent)
    return () => {
      cancelled = true
      window.removeEventListener(MUSIC_PRODUCTION_MONTAGE_EVENT, onEvent)
    }
  }, [workspace])
}
