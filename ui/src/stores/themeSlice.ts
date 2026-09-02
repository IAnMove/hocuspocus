import { applyThemePrefs, getStoredPrefs, type FamilyId, type ThemeMode, type ThemePrefs } from '../lib/theme'

export type ThemeSlice = {
  themePrefs: ThemePrefs
  setThemeMode: (mode: ThemeMode) => void
  setThemeFamily: (family: FamilyId) => void
}

type SetThemeState = (
  partial: Partial<ThemeSlice> | ((state: ThemeSlice) => Partial<ThemeSlice>),
) => void

type GetThemeState = () => ThemeSlice

export function createThemeSlice(set: SetThemeState, get: GetThemeState): ThemeSlice {
  return {
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
  }
}
