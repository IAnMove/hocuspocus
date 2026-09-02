import { applyThemePrefs, getStoredPrefs, type FamilyId, type ThemeMode, type ThemePrefs } from '../lib/theme'
import type { SliceCreator } from './storeApi'

export type ThemeSlice = {
  themePrefs: ThemePrefs
  setThemeMode: (mode: ThemeMode) => void
  setThemeFamily: (family: FamilyId) => void
}

export const createThemeSlice: SliceCreator<ThemeSlice> = (set, get) => ({
  themePrefs: getStoredPrefs(),
  setThemeMode: mode => {
    const prefs = { ...get().themePrefs, mode }
    applyThemePrefs(prefs)
    set({ themePrefs: prefs })
  },
  setThemeFamily: family => {
    const prefs = { ...get().themePrefs, family }
    applyThemePrefs(prefs)
    set({ themePrefs: prefs })
  },
})
