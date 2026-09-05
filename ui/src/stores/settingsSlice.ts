import type { GenerationMode, SettingsTab } from '../types'
import type { SliceCreator } from './storeApi'

export type SettingsSlice = {
  settingsOpen: boolean
  toggleSettings: () => void
  setSettingsOpen: (open: boolean) => void
  settingsTab: SettingsTab
  setSettingsTab: (tab: SettingsTab) => void
  modelVisibilityFocus: GenerationMode | null
  openModelVisibility: (mode: GenerationMode) => void
  clearModelVisibilityFocus: () => void
}

export const createSettingsSlice: SliceCreator<SettingsSlice> = (set, get) => ({
  settingsOpen: false,
  toggleSettings: () => set({ settingsOpen: !get().settingsOpen }),
  setSettingsOpen: open => set({ settingsOpen: open }),
  settingsTab: 'performance',
  setSettingsTab: tab => set({ settingsTab: tab }),
  modelVisibilityFocus: null,
  openModelVisibility: mode => set({
    settingsOpen: true,
    settingsTab: 'performance',
    modelVisibilityFocus: mode,
  }),
  clearModelVisibilityFocus: () => set({ modelVisibilityFocus: null }),
})
