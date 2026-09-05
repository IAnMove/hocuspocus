import { loadDeveloperMode, saveDeveloperMode } from '../lib/developerMode'
import type { SliceCreator } from './storeApi'

export type DeveloperModeSlice = {
  developerMode: boolean
  setDeveloperMode: (enabled: boolean) => void
}

export const createDeveloperModeSlice: SliceCreator<DeveloperModeSlice> = set => ({
  developerMode: loadDeveloperMode(),
  setDeveloperMode: enabled => {
    saveDeveloperMode(enabled)
    set({ developerMode: enabled })
  },
})
