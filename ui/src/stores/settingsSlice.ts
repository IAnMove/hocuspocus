import type { SettingsTab } from '../types'

export type SettingsSlice = {
  settingsOpen: boolean
  toggleSettings: () => void
  setSettingsOpen: (open: boolean) => void
  settingsTab: SettingsTab
  setSettingsTab: (tab: SettingsTab) => void
}

type SetSettingsState = (
  partial: Partial<SettingsSlice> | ((state: SettingsSlice) => Partial<SettingsSlice>),
) => void

type GetSettingsState = () => SettingsSlice

export function createSettingsSlice(set: SetSettingsState, get: GetSettingsState): SettingsSlice {
  return {
    settingsOpen: false,
    toggleSettings: () => set({ settingsOpen: !get().settingsOpen }),
    setSettingsOpen: open => set({ settingsOpen: open }),
    settingsTab: 'performance',
    setSettingsTab: tab => set({ settingsTab: tab }),
  }
}
