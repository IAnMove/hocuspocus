import { loadDeveloperMode, saveDeveloperMode } from '../lib/developerMode'
import type { MediaFilter } from '../types'

export type DeveloperModeSlice = {
  developerMode: boolean
  setDeveloperMode: (enabled: boolean) => void
}

// Runtime get() is the full AppState. The setter may also write mediaFilter
// when leaving auditdev; that field stays owned by the gallery store.
type DeveloperModeWriteState = DeveloperModeSlice & {
  mediaFilter?: MediaFilter
}

type SetDeveloperModeState = (
  partial: Partial<DeveloperModeWriteState> | ((state: DeveloperModeWriteState) => Partial<DeveloperModeWriteState>),
) => void

type GetDeveloperModeState = () => DeveloperModeWriteState

export function createDeveloperModeSlice(set: SetDeveloperModeState, get: GetDeveloperModeState): DeveloperModeSlice {
  return {
    developerMode: loadDeveloperMode(),
    setDeveloperMode: enabled => {
      saveDeveloperMode(enabled)
      const { mediaFilter } = get()
      set({
        developerMode: enabled,
        mediaFilter: !enabled && mediaFilter === 'auditdev' ? 'all' : mediaFilter,
      })
    },
  }
}
