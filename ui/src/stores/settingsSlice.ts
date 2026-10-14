import type { GenerationMode, SettingsTab } from '../types'
import type { SliceCreator } from './storeApi'

export type SettingsSlice = {
  settingsOpen: boolean
  toggleSettings: () => void
  setSettingsOpen: (open: boolean) => void
  settingsTab: SettingsTab
  setSettingsTab: (tab: SettingsTab) => void
  // ModelSelector "+N more" hint → open Settings and expand Enabled Models.
  modelVisibilityFocus: GenerationMode | null
  openModelVisibility: (mode: GenerationMode) => void
  clearModelVisibilityFocus: () => void

  // Storage Manager overlay
  storageDashboardOpen: boolean
  setStorageDashboardOpen: (open: boolean) => void

  // LoRA picker sort order — store-backed (not per-component state) so
  // simultaneously mounted pickers (e.g. Director's Image + Video
  // accordions) stay in sync; persisted to localStorage.
  loraPickerSort: 'name' | 'newest'
  setLoraPickerSort: (sort: 'name' | 'newest') => void
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

  // Storage Manager overlay
  storageDashboardOpen: false,
  setStorageDashboardOpen: (open) => set({ storageDashboardOpen: open }),

  // LoRA picker sort order — store-backed (not per-component state) so
  // simultaneously mounted pickers (e.g. Director's Image + Video
  // accordions) stay in sync; persisted to localStorage.
  loraPickerSort: (() => {
    try { return localStorage.getItem('maestro_lora_picker_sort') === 'newest' ? 'newest' as const : 'name' as const } catch { return 'name' as const }
  })(),
  setLoraPickerSort: (sort) => {
    try { localStorage.setItem('maestro_lora_picker_sort', sort) } catch { /* private mode */ }
    set({ loraPickerSort: sort })
  },
})
