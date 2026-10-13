import { create } from 'zustand'
import { createDeveloperModeSlice, type DeveloperModeSlice } from './developerModeSlice'
import { createDirectorSlice, type DirectorSlice } from './directorSlice'
import { createDirectorDashboardSlice, disposeDirectorRepairPolls, type DirectorDashboardSlice } from '../features/director/store/directorDashboardSlice'
import { createShortFilmSlice, type ShortFilmSlice } from '../features/director/store/shortFilmSlice'
import { createDirectorPipelineSlice, type DirectorPipelineSlice } from '../features/director/store/directorPipelineSlice'
import { createDirectorMusicSourceSlice, type DirectorMusicSourceSlice } from '../features/director/store/directorMusicSourceSlice'
import { createDirectorMusicVideoSlice, type DirectorMusicVideoSlice } from '../features/director/store/directorMusicVideoSlice'
import { createStudioEditSlice, type StudioEditSlice } from '../features/studio/store/studioEditSlice'
import { createOutputRestoreSlice, type OutputRestoreSlice } from '../features/studio/store/outputRestoreSlice'
import { createStudioFormSlice, type StudioFormSlice } from '../features/studio/store/studioFormSlice'
import { createGenerationSlice, type GenerationSlice } from './generationSlice'
import { createJobsSlice, type JobsSlice } from './jobsSlice'
import { createRetakeDialogSlice, type RetakeDialogSlice } from './retakeDialogSlice'
import { createSettingsSlice, type SettingsSlice } from './settingsSlice'
import { createSidebarSlice, type SidebarSlice } from './sidebarSlice'
import { createSystemSlice, type SystemSlice } from './systemSlice'
import { createCivitaiSlice, disposeCivitaiDownloadPoll, type CivitaiSlice } from './civitaiSlice'
import { createPresetsSlice, type PresetsSlice } from '../features/studio/store/presetsSlice'
import { createToolsSlice, type ToolsSlice } from '../features/studio/store/toolsSlice'
import { createRecipesSlice, type RecipesSlice } from './recipesSlice'
import {
  alignFrameCount,
  createModelOptionsSlice,
  invalidateModelOptionsLoad,
  type ModelOptionsSlice,
} from './modelOptionsSlice'
export { alignFrameCount, invalidateModelOptionsLoad }
import { createServicesSlice, type ServicesSlice } from './servicesSlice'
import { createLorasSlice, type LorasSlice } from './lorasSlice'
import { createModelsSlice, type ModelsSlice } from './modelsSlice'
import {
  createActivitySlice,
  type ActivitySlice,
  type ForegroundActivity,
} from '../features/activity/store'
export type { ForegroundActivity }
import { bindSlice } from './storeApi'
import { createThemeSlice, type ThemeSlice } from './themeSlice'
import { createGallerySlice, type GallerySlice } from './gallerySlice'
import { createLlmSlice, type LlmSlice } from './llmSlice'
import { createStudioConfigurationSlice, type StudioConfigurationSlice } from './studioConfigurationSlice'
import {
  createStudioMusicSlice,
  type StudioMusicSlice,
} from './studioMusicSlice'
import {
  getDisplayFamily,
  getFamiliesForMode,
  getFamilyMode,
  getModelMode,
  getModelsForFamily,
} from './modelCatalog'
export {
  getDisplayFamily,
  getFamiliesForMode,
  getFamilyMode,
  getModelMode,
  getModelsForFamily,
}
import { findResolutionSelection, resolveResolution } from './resolution'
export { findResolutionSelection, resolveResolution }

// Vite can replace this module without a full page unload. Abort the old
// async loop so HMR never leaves an orphaned polling timer behind.
if (import.meta.hot) {
  import.meta.hot.dispose(() => {
    disposeCivitaiDownloadPoll()
    disposeDirectorRepairPolls()
  })
}

export interface AppState extends LlmSlice, StudioConfigurationSlice, StudioMusicSlice, DirectorSlice, ThemeSlice, SettingsSlice, SidebarSlice, RetakeDialogSlice, GallerySlice, DeveloperModeSlice, SystemSlice, PresetsSlice, ActivitySlice, CivitaiSlice, ToolsSlice, RecipesSlice, ServicesSlice, LorasSlice, ModelOptionsSlice, ModelsSlice, DirectorDashboardSlice, ShortFilmSlice, DirectorPipelineSlice, StudioEditSlice, DirectorMusicSourceSlice, DirectorMusicVideoSlice, OutputRestoreSlice, StudioFormSlice, JobsSlice, GenerationSlice {
  wangpRestoreError: string
  /** Snapshot of lora_id → filename loaded from localStorage at boot.
   *  Used by `refreshLoraIdMap` reconciliation to rewrite filenames that
   *  changed since save (LoRA version updates). Internal-only; not part
   *  of the persisted runtime state. */
  _loraFilenameSnapshotAtLoad?: Record<string, string>

  // Director-mode post-processing (separate image/video)
  directorImageSpatialUpsampling: string
  setDirectorImageSpatialUpsampling: (v: string) => void
  directorImageFilmGrainIntensity: number
  setDirectorImageFilmGrainIntensity: (v: number) => void
  directorImageFilmGrainSaturation: number
  setDirectorImageFilmGrainSaturation: (v: number) => void
  directorVideoSpatialUpsampling: string
  setDirectorVideoSpatialUpsampling: (v: string) => void
  directorVideoFilmGrainIntensity: number
  setDirectorVideoFilmGrainIntensity: (v: number) => void
  directorVideoFilmGrainSaturation: number
  setDirectorVideoFilmGrainSaturation: (v: number) => void
  directorVideoSelfRefiner: number
  setDirectorVideoSelfRefiner: (v: number) => void
  directorAudioScale: number
  setDirectorAudioScale: (v: number) => void

  // Storage Manager overlay
  storageDashboardOpen: boolean
  setStorageDashboardOpen: (open: boolean) => void

  // LoRA picker sort order — store-backed (not per-component state) so
  // simultaneously mounted pickers (e.g. Director's Image + Video
  // accordions) stay in sync; persisted to localStorage.
  loraPickerSort: 'name' | 'newest'
  setLoraPickerSort: (sort: 'name' | 'newest') => void

  // LLM streaming
  llmStreamText: string
  llmStreamDone: boolean

}

export const useStore = create<AppState>((set, get) => {
  const developerMode = bindSlice(set, get, createDeveloperModeSlice)
  return {
  ...bindSlice(set, get, createDirectorSlice),
  ...bindSlice(set, get, createThemeSlice),
  ...bindSlice(set, get, createSettingsSlice),
  ...bindSlice(set, get, createSidebarSlice),
  ...bindSlice(set, get, createRetakeDialogSlice),
  ...bindSlice(set, get, createGallerySlice),
  ...bindSlice(set, get, createLlmSlice),
  ...bindSlice(set, get, createStudioConfigurationSlice({ alignFrameCount, resolveResolution })),
  ...bindSlice(set, get, createStudioMusicSlice),
  ...bindSlice(set, get, createSystemSlice),
  ...bindSlice(set, get, createPresetsSlice),
  ...bindSlice(set, get, createActivitySlice),
  ...bindSlice(set, get, createCivitaiSlice),
  ...bindSlice(set, get, createToolsSlice),
  ...bindSlice(set, get, createRecipesSlice),
  ...bindSlice(set, get, createServicesSlice),
  ...bindSlice(set, get, createLorasSlice),
  ...bindSlice(set, get, createModelOptionsSlice),
  ...bindSlice(set, get, createModelsSlice),
  ...bindSlice(set, get, createDirectorDashboardSlice),
  ...bindSlice(set, get, createShortFilmSlice),
  ...bindSlice(set, get, createDirectorPipelineSlice),
  ...bindSlice(set, get, createStudioEditSlice),
  ...bindSlice(set, get, createDirectorMusicSourceSlice),
  ...bindSlice(set, get, createDirectorMusicVideoSlice),
  ...bindSlice(set, get, createOutputRestoreSlice),
  ...bindSlice(set, get, createStudioFormSlice),
  ...bindSlice(set, get, createJobsSlice),
  ...bindSlice(set, get, createGenerationSlice),
  ...developerMode,
  setDeveloperMode: (enabled: boolean) => {
    developerMode.setDeveloperMode(enabled)
    if (!enabled && get().mediaFilter === 'auditdev') {
      get().setMediaFilter('all')
    }
  },

  // Director-mode post-processing (separate image/video)
  directorImageSpatialUpsampling: '',
  setDirectorImageSpatialUpsampling: (v) => set({ directorImageSpatialUpsampling: v }),
  directorImageFilmGrainIntensity: 0,
  setDirectorImageFilmGrainIntensity: (v) => set({ directorImageFilmGrainIntensity: v }),
  directorImageFilmGrainSaturation: 0.5,
  setDirectorImageFilmGrainSaturation: (v) => set({ directorImageFilmGrainSaturation: v }),
  directorVideoSpatialUpsampling: '',
  setDirectorVideoSpatialUpsampling: (v) => set({ directorVideoSpatialUpsampling: v }),
  directorVideoFilmGrainIntensity: 0,
  setDirectorVideoFilmGrainIntensity: (v) => set({ directorVideoFilmGrainIntensity: v }),
  directorVideoFilmGrainSaturation: 0.5,
  setDirectorVideoFilmGrainSaturation: (v) => set({ directorVideoFilmGrainSaturation: v }),
  directorVideoSelfRefiner: 0,
  setDirectorVideoSelfRefiner: (v) => set({ directorVideoSelfRefiner: v }),
  directorAudioScale: 1.0,
  setDirectorAudioScale: (v) => set({ directorAudioScale: v }),

  llmStreamText: '',
  llmStreamDone: true,

  wangpRestoreError: '',
  storageDashboardOpen: false,
  setStorageDashboardOpen: (open) => set({ storageDashboardOpen: open }),

  loraPickerSort: (() => {
    try { return localStorage.getItem('maestro_lora_picker_sort') === 'newest' ? 'newest' as const : 'name' as const } catch { return 'name' as const }
  })(),
  setLoraPickerSort: (sort) => {
    try { localStorage.setItem('maestro_lora_picker_sort', sort) } catch { /* private mode */ }
    set({ loraPickerSort: sort })
  },

  }
})
