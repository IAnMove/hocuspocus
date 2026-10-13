import * as api from '../api/client'
import { installedPreferredModel } from '../lib/preferredModels'
import type { AspectRatio, GenerationMode, ModelDef, ModelFamily, ResolutionPreset } from '../types'
import { getFamiliesForMode, getModelsForFamily, sfxModelTypes } from './modelCatalog'
import { _loadSettings, _persistModelSelections } from './modeSettingsPersistence'
import {
  DEFAULT_ENABLED_MODELS,
  DEFAULTS_ADDED_IN,
  DEFAULTS_VERSION,
  DEFAULTS_VERSION_KEY,
  _enableUninitializedMatureModels,
  _loadEnabledModels,
  _markMatureModelsInitialized,
  _modelVisibilityDefaultsVersion,
  _modelVisibilityHydrated,
  _saveEnabledModels,
  markModelVisibilityHydrated,
  replaceInitializedMatureModels,
  setModelVisibilityDefaultsVersion,
} from './modelVisibility'
import { _applyModelDefaults } from './modelOptionsSlice'
import { _globalModelSelectionModes, _syncGlobalProductionVideoFormat } from './servicesSlice'
import type { SliceCreator } from './storeApi'
import type { AppState } from './useStore'

// Virtual MMAudio model entries (injected into model list alongside backend models)
const SFX_VIRTUAL_MODELS: ModelDef[] = [
  { model_type: 'mmaudio_v2', name: 'MMAudio v2', family: 'tts', architecture: 'mmaudio', is_i2v: false, is_t2v: false, guidance_max_phases: 1, fps: 0, is_downloaded: true },
  { model_type: 'mmaudio_nsfw', name: 'MMAudio NSFW', family: 'tts', architecture: 'mmaudio', is_i2v: false, is_t2v: false, guidance_max_phases: 1, fps: 0, is_downloaded: false },
]

/* The music default changed in v1.2.0 (Turbo LM_4B -> SFT LM_4B).
 * A saved selection equal to the OLD default means the user was riding
 * the default rather than expressing a preference — follow them to the
 * new one, once, at the same version transition. Users who picked any
 * other model keep their choice. */
const OLD_MUSIC_DEFAULT = 'ace_step_v1_5_xl_turbo_lm_4b'
const NEW_MUSIC_DEFAULT = 'ace_step_v1_5_xl_sft_lm_4b'

let _modelSelectionsHydrated = false

// Default model_type per generation mode
const modeDefaultModel: Record<GenerationMode, string> = {
  image: 'flux2_klein_9b',
  video: 'ltx2_22B_distilled_1_1',
  audio: 'kugelaudio_0_open',
  model3d: 'hunyuan3d-2-turbo',
  avatar: '',  // will fallback to first available
  tools: '',   // Tools is non-generative post-processing — owns no model
}

export function getDefaultModelForMode(mode: GenerationMode, families: ModelFamily[], models: ModelDef[]): string {
  const installedFirst = installedPreferredModel(mode, models)
  if (installedFirst) return installedFirst
  // Try the preferred default first
  const preferred = modeDefaultModel[mode]
  if (preferred && models.some(m => m.model_type === preferred)) {
    return preferred
  }
  // Fallback: first model in first family of this mode
  const modeFamilies = getFamiliesForMode(mode, families)
  if (modeFamilies.length > 0) {
    const firstModel = getModelsForFamily(modeFamilies[0].id, models, mode).filter(m => !m.tool_only)[0]
    if (firstModel) return firstModel.model_type
  }
  return ''
}

export type ModelsSlice = {
  // Models & families (from API)
  families: ModelFamily[]
  models: ModelDef[]
  loadModels: () => Promise<void>
  modelsLoaded: boolean

  // Model visibility (favorites)
  enabledModels: Set<string>
  toggleModelEnabled: (modelType: string) => void
  resetEnabledModels: () => void
  setAllModelsEnabled: (enabled: boolean) => void
  /** Bulk-toggle a list of models (family-level enable/disable, issue #14). */
  setModelsEnabled: (modelTypes: string[], enabled: boolean) => void
}

/** loadModels passes get and set into _syncGlobalProductionVideoFormat, which is typed as AppState. */
export type ModelsSliceHost = AppState

export const createModelsSlice: SliceCreator<ModelsSlice, ModelsSliceHost> = (set, get) => ({
  // Models & families
  families: [],
  models: [],
  modelsLoaded: false,
  enabledModels: _loadEnabledModels() ?? new Set(DEFAULT_ENABLED_MODELS),
  toggleModelEnabled: (modelType) => {
    _markMatureModelsInitialized(get().models, [modelType])
    set(s => {
      const next = new Set(s.enabledModels)
      if (next.has(modelType)) next.delete(modelType)
      else next.add(modelType)
      _saveEnabledModels(next)
      return { enabledModels: next }
    })
  },
  resetEnabledModels: () => {
    _markMatureModelsInitialized(get().models)
    const next = new Set(DEFAULT_ENABLED_MODELS)
    _saveEnabledModels(next)
    set({ enabledModels: next })
  },
  setAllModelsEnabled: (enabled) => {
    _markMatureModelsInitialized(get().models)
    if (enabled) {
      const all = new Set(get().models.map(m => m.model_type))
      _saveEnabledModels(all)
      set({ enabledModels: all })
    } else {
      const empty = new Set<string>()
      _saveEnabledModels(empty)
      set({ enabledModels: empty })
    }
  },
  setModelsEnabled: (modelTypes, enabled) => {
    _markMatureModelsInitialized(get().models, modelTypes)
    set(s => {
      const next = new Set(s.enabledModels)
      for (const mt of modelTypes) {
        if (enabled) next.add(mt)
        else next.delete(mt)
      }
      _saveEnabledModels(next)
      return { enabledModels: next }
    })
  },
  loadModels: async () => {
    try {
      // A download/catalog refresh is not a new Studio session. Keep the
      // live draft, selected model and options, even for a now-hidden model.
      if (get().modelsLoaded) {
        const catalog = await api.fetchModels()
        set({ families: catalog.families, models: [...catalog.models, ...SFX_VIRTUAL_MODELS] })
        return
      }
      // The backend catalog is the single source for Hunyuan3D models too:
      // /api/v1/models already lists them (family included) with real
      // download state, so re-adding them from the capabilities endpoint
      // would duplicate every variant in the selectors.
      const shouldHydrateVisibility = !_modelVisibilityHydrated
      const shouldHydrateSelections = !_modelSelectionsHydrated
      const [data, visibility, durableSelections] = await Promise.all([
        api.fetchModels(),
        shouldHydrateVisibility
          ? api.fetchModelVisibility().catch(error => {
              console.warn('Failed to load model visibility:', error)
              return null
            })
          : Promise.resolve(null),
        shouldHydrateSelections
          ? api.fetchModelSelections().catch(error => {
              console.warn('Failed to load model selections:', error)
              return null
            })
          : Promise.resolve(null),
      ])
      const families = data.families
      // Keep the complete backend capability record. Director publishes a
      // stricter per-workflow contract than Studio; rebuilding model objects
      // field-by-field used to discard that metadata and leave both Director
      // selectors empty even though compatible models were enabled.
      const backendModels: ModelDef[] = data.models.map(m => ({
        ...m,
        guidance_max_phases: m.guidance_max_phases ?? 1,
        fps: m.fps ?? 16,
        is_downloaded: m.is_downloaded ?? false,
        nsfw_only: m.nsfw_only ?? false,
        shared_cache_group: m.shared_cache_group,
        tool_only: m.tool_only ?? false,
      }))
      // Inject models maintained by Maestro services alongside backend models.
      const models = [...backendModels, ...SFX_VIRTUAL_MODELS]

      // Pinokio can assign a different web-server port on every launch.
      // Browser localStorage is origin-bound, so hydrate durable visibility
      // once from the server config and keep localStorage only as a
      // migration/cache layer.
      if (shouldHydrateVisibility && visibility) {
        let restoredModels: Set<string>
        if (visibility.configured) {
          restoredModels = new Set(visibility.enabled_models)
          replaceInitializedMatureModels(new Set(
            visibility.initialized_mature_models,
          ))
          setModelVisibilityDefaultsVersion(
            visibility.defaults_version || 1
          )
        } else {
          const legacyModels = _loadEnabledModels()
          restoredModels = legacyModels ?? new Set(DEFAULT_ENABLED_MODELS)
          const legacyDefaultsVersion = parseInt(
            localStorage.getItem(DEFAULTS_VERSION_KEY) || '',
            10,
          )
          setModelVisibilityDefaultsVersion(legacyModels
            ? (legacyDefaultsVersion || 1)
            : DEFAULTS_VERSION)
          // An existing browser whitelist is an explicit snapshot. Mark the
          // current Mature entries initialized so migration cannot re-enable
          // one the user deliberately disabled.
          replaceInitializedMatureModels(legacyModels
            ? new Set(
                models
                  .filter(model => model.nsfw_only)
                  .map(model => model.model_type),
              )
            : new Set())
        }
        markModelVisibilityHydrated()
        set({ enabledModels: restoredModels })
        if (!visibility.configured) _saveEnabledModels(restoredModels)
      }

      // One-time curated-defaults upgrade for existing installs (see
      // DEFAULTS_VERSION). Fresh installs already start from the full
      // DEFAULT_ENABLED_MODELS list; for them this only stamps the
      // version key.
      let migrateMusicDefault = false
      try {
        const storedVer = _modelVisibilityHydrated
          ? _modelVisibilityDefaultsVersion
          : (
              parseInt(
                localStorage.getItem(DEFAULTS_VERSION_KEY) || '1',
                10,
              ) || 1
            )
        if (storedVer < DEFAULTS_VERSION) {
          const additions: string[] = []
          for (let v = storedVer + 1; v <= DEFAULTS_VERSION; v++) {
            additions.push(...(DEFAULTS_ADDED_IN[v] || []))
          }
          const present = additions.filter(id => models.some(m => m.model_type === id))
          if (present.length > 0) {
            set(s => {
              const next = new Set(s.enabledModels)
              present.forEach(id => next.add(id))
              _saveEnabledModels(next)
              return { enabledModels: next }
            })
          }
          migrateMusicDefault = storedVer < 2
          setModelVisibilityDefaultsVersion(DEFAULTS_VERSION)
          localStorage.setItem(DEFAULTS_VERSION_KEY, String(DEFAULTS_VERSION))
          _saveEnabledModels(get().enabledModels)
        }
      } catch { /* localStorage blocked — defaults only apply this session */ }

      // Hydrate persisted per-mode settings from localStorage.
      //
      // Deliberately PARTIAL: only the last generation mode and the
      // per-mode model selections survive a page refresh. The working
      // state — prompt text and Advanced settings (seed, steps, LoRA
      // selection, …) — starts fresh from the model's defaults on every
      // load. The per-mode snapshots (savedParamsPerMode /
      // savedLoraPerMode / savedPromptPerMode) still carry edits across
      // MODE SWITCHES within a session, in-memory only. v1.2.0 restored
      // them here on refresh; stale text/seeds/LoRAs re-appearing after
      // a reload felt wrong, so a refresh is a clean slate again.
      const saved = _loadSettings()
      const persistedSelections: Partial<Record<GenerationMode, string>> = {
        ...(saved?.selectedModelPerMode || {}),
        ...((durableSelections?.selected_models || {}) as Partial<Record<GenerationMode, string>>),
      }
      if (durableSelections?.sources) {
        Object.entries(durableSelections.sources).forEach(([mode, source]) => {
          if (source === 'global') _globalModelSelectionModes.add(mode as GenerationMode)
          else _globalModelSelectionModes.delete(mode as GenerationMode)
        })
      }
      if (shouldHydrateSelections) _modelSelectionsHydrated = true
      // v2 migration: users whose saved audio model IS the old music
      // default follow it to the new default (see NEW_MUSIC_DEFAULT).
      // (The old-model-params concern the migration used to handle is
      // gone: saved params no longer rehydrate, and the defaults
      // hydration below runs on every boot.)
      if (migrateMusicDefault && saved?.selectedModelPerMode?.audio === OLD_MUSIC_DEFAULT
          && models.some(m => m.model_type === NEW_MUSIC_DEFAULT)) {
        saved.selectedModelPerMode = { ...saved.selectedModelPerMode, audio: NEW_MUSIC_DEFAULT }
        persistedSelections.audio = NEW_MUSIC_DEFAULT
      }
      let mode = get().generationMode
      let initialModelType: string

      if (saved) {
        // Restore saved generation mode
        mode = saved.generationMode || mode
        // Validate saved model for this mode still exists
        const savedModel = persistedSelections[mode]
        initialModelType = savedModel && models.some(m => m.model_type === savedModel)
          ? savedModel
          : getDefaultModelForMode(mode, families, models)
        const bootedIntoRecast = mode === 'avatar'
          && (initialModelType === 'scail2_14B_recast_fast' || initialModelType === 'scail2_14B')
        const bootedIntoRepaint = mode === 'avatar'
          && initialModelType === 'scail2_14B_fast'

        set(s => ({
          families,
          models,
          modelsLoaded: true,
          generationMode: mode,
          ...(bootedIntoRecast
            ? { editSubMode: 'recast' as const }
            : bootedIntoRepaint
              ? { editSubMode: 'restyle' as const }
              : {}),
          // Seed the VALIDATED boot model into the map (the saved entry
          // may point at a removed model) — _applyModelDefaults' race
          // guard compares against selectedModelPerMode[mode].
          selectedModelPerMode: { ...persistedSelections, [mode]: initialModelType },
          // Mode-shaping mirrored from setGenerationMode: booting into
          // image mode needs image_mode 1 + Auto resolution. These used
          // to arrive via the restored params snapshot.
          ...(mode === 'image' ? { resolutionPreset: 'auto' as ResolutionPreset, aspectRatio: 'auto' as AspectRatio } : {}),
          params: {
            ...s.params,
            model_type: initialModelType || s.params.model_type,
            ...(mode === 'image' ? { image_mode: 1 } : {}),
          },
        }))
      } else {
        const durableModel = persistedSelections[mode]
        initialModelType = durableModel && models.some(m => m.model_type === durableModel)
          ? durableModel
          : getDefaultModelForMode(mode, families, models)
        set(s => ({
          families,
          models,
          modelsLoaded: true,
          selectedModelPerMode: { ...persistedSelections, [mode]: initialModelType },
          ...(mode === 'image' ? { resolutionPreset: 'auto' as ResolutionPreset, aspectRatio: 'auto' as AspectRatio } : {}),
          params: {
            ...s.params,
            model_type: initialModelType || s.params.model_type,
            ...(mode === 'image' ? { image_mode: 1 } : {}),
          },
        }))
      }

      // Load LoRAs, model options, and tuned defaults for the initial
      // model. The defaults hydration (steps, guidance, LM sampling…)
      // must run on every boot now that saved params don't rehydrate —
      // without it the sliders would show INITIAL_PARAMS' generic values
      // instead of the model's.
      const mt = initialModelType || get().params.model_type
      _persistModelSelections(get().selectedModelPerMode)
      // Profile and model-selection hydration are intentionally parallel.
      // Whichever request settles second re-applies the inherited Story /
      // Director canvas, without touching an explicit video override.
      void _syncGlobalProductionVideoFormat(
        get().productionProfile,
        get,
        partial => set(partial),
      )
      if (mt) {
        // Restore saved LoRA state for this mode if the model matches
        const savedLora = saved?.savedLoraPerMode?.[mode]
        const savedModelForMode = persistedSelections[mode]
        if (savedLora && savedModelForMode === mt) {
          set(s => ({
            params: {
              ...s.params,
              activated_loras: savedLora.activated_loras || [],
              loras_multipliers: savedLora.loras_multipliers || '',
            },
            loraWeights: savedLora.loraWeights || {},
            availableLoras: savedLora.availableLoras || [],
          }))
        }
        if (mode !== 'model3d') get().loadModelOptions(mt)
        if (!sfxModelTypes.has(mt) && mode !== 'model3d') {
          get().loadLoras(mt)
          _applyModelDefaults(get, set, mt)
        }
      }
      // Refresh the lora_id ↔ filename map from /installed and reconcile
      // any filename renames since save (LoRA version updates land here
      // transparently — saved weights/activations carry over to the new
      // filename without user intervention).
      get().refreshLoraIdMap()

      // Auto-enable each Mature model once, then preserve an explicit
      // disable. The initialized IDs live in the same server-side visibility
      // record, so a changing Pinokio port cannot reset this decision.
      const cfg = get().servicesConfig
      if (cfg?.nsfw_mode && _modelVisibilityHydrated) {
        set(s => {
          const next = _enableUninitializedMatureModels(
            models,
            s.enabledModels,
          )
          if (!next) return s
          _saveEnabledModels(next)
          return { enabledModels: next }
        })
      }
    } catch (e) {
      console.error('Failed to load models:', e)
    }
  },
})
