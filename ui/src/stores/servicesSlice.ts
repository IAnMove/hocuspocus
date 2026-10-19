import * as api from '../api/client'
import { DEFAULT_PRODUCTION_PROFILE, resolveSupportedVideoFormat } from '../lib/productionProfile'
import type { GenerationMode, ModelOptions, ProductionProfile, ServicesConfig } from '../types'
import {
  _enableUninitializedMatureModels,
  _modelVisibilityHydrated,
  _saveEnabledModels,
} from './modelVisibility'
import type { SliceCreator } from './storeApi'
import type { AppState } from './useStore'

let _servicesConfigUpdateQueue: Promise<void> = Promise.resolve()

export const _globalModelSelectionModes = new Set<GenerationMode>()

let _productionProfileVideoFormatSeq = 0

/** Keep Director/Story Lab's canvas aligned with a globally inherited model.
 *
 * Model selections and the production profile are hydrated by independent
 * requests at boot.  Resolve the format after either one settles, and reject
 * a late response if the user selected a project/model override meanwhile.
 */
export async function _syncGlobalProductionVideoFormat(
  profile: ProductionProfile,
  get: () => AppState,
  set: (partial: Partial<AppState>) => void,
): Promise<void> {
  const requestSeq = ++_productionProfileVideoFormatSeq
  const modelType = profile.video.model.trim()
  const requestedResolution = profile.video.settings.resolution
  const requestedAspect = profile.video.settings.aspectRatio
  const before = get()
  if (
    !modelType
    || !_globalModelSelectionModes.has('video')
    || before.selectedModelPerMode.video !== modelType
  ) return

  let options: ModelOptions
  try {
    options = before.modelOptions?.model_type === modelType
      ? before.modelOptions
      : await api.fetchModelOptions(modelType)
  } catch {
    // The selector remains usable while the backend/model catalog reconnects.
    return
  }

  const latest = get()
  if (
    requestSeq !== _productionProfileVideoFormatSeq
    || !_globalModelSelectionModes.has('video')
    || latest.selectedModelPerMode.video !== modelType
    || latest.productionProfile.video.model !== modelType
    || latest.productionProfile.video.settings.resolution !== requestedResolution
    || latest.productionProfile.video.settings.aspectRatio !== requestedAspect
  ) return

  const format = resolveSupportedVideoFormat(
    options,
    requestedResolution,
    requestedAspect,
  )
  set({
    directorResolution: format.resolution,
    directorAspectRatio: format.aspectRatio,
  })
}

export type ServicesSlice = {
  // Services config
  servicesConfig: ServicesConfig | null
  servicesConfigLoading: boolean
  loadServicesConfig: () => Promise<void>
  updateServicesConfig: (partial: Partial<ServicesConfig>) => Promise<void>

  // Credential-free defaults shared by Studio and every Lab.
  productionProfile: ProductionProfile
  productionProfileConfigured: boolean
  /** Set when the saved profile could not be read and the defaults stand in. */
  productionProfileInvalidReason: string
  /** True once the profile has been read from the server at least once. */
  productionProfileLoaded: boolean
  productionProfileLoading: boolean
  loadProductionProfile: () => Promise<void>
  updateProductionProfile: (profile: ProductionProfile) => Promise<void>
}

/** loadProductionProfile passes get and set into _syncGlobalProductionVideoFormat, which is typed as AppState. */
export type ServicesSliceHost = AppState

export const createServicesSlice: SliceCreator<ServicesSlice, ServicesSliceHost> = (set, get) => ({
  // Services config
  servicesConfig: null,
  servicesConfigLoading: false,
  productionProfile: DEFAULT_PRODUCTION_PROFILE,
  productionProfileConfigured: false,
  productionProfileInvalidReason: '',
  productionProfileLoaded: false,
  productionProfileLoading: false,
  loadProductionProfile: async () => {
    set({ productionProfileLoading: true })
    try {
      const result = await api.fetchProductionProfile()
      set({
        productionProfile: result.profile,
        productionProfileConfigured: result.configured,
        productionProfileInvalidReason: result.invalid_reason || '',
        productionProfileLoaded: true,
        productionProfileLoading: false,
      })
      await _syncGlobalProductionVideoFormat(
        result.profile,
        get,
        partial => set(partial),
      )
    } catch (e) {
      console.error('Failed to load production profile:', e)
      set({ productionProfileLoading: false })
    }
  },
  updateProductionProfile: async (profile) => {
    const previous = get().productionProfile
    set({ productionProfile: profile, productionProfileLoading: true })
    try {
      const result = await api.updateProductionProfile(profile)
      const imageModel = result.profile.image.provider === 'minimax'
        ? `minimax:${result.profile.image.model}` : result.profile.image.model
      _globalModelSelectionModes.add('image')
      _globalModelSelectionModes.add('video')
      set(state => ({
        productionProfile: result.profile,
        productionProfileConfigured: result.configured,
        productionProfileInvalidReason: result.invalid_reason || '',
        productionProfileLoading: false,
        selectedModelPerMode: {
          ...state.selectedModelPerMode,
          image: imageModel,
          video: result.profile.video.model,
        },
        ...(state.generationMode === 'image' || state.generationMode === 'video' ? {
          params: {
            ...state.params,
            model_type: state.generationMode === 'image'
              ? imageModel : result.profile.video.model,
          },
        } : {}),
      }))
      const activeMode = get().generationMode
      if (activeMode === 'image' || activeMode === 'video') {
        const activeModel = get().selectedModelPerMode[activeMode]
        if (activeModel) await get().loadModelOptions(activeModel)
      }
      await _syncGlobalProductionVideoFormat(
        result.profile,
        get,
        partial => set(partial),
      )
      // The global text profile is also the provider used by generic tools.
      await get().loadServicesConfig()
      await get().loadLlmModels()
    } catch (e) {
      console.error('Failed to update production profile:', e)
      set({ productionProfile: previous, productionProfileLoading: false })
      throw e
    }
  },
  loadServicesConfig: async () => {
    set({ servicesConfigLoading: true })
    try {
      const config = await api.fetchServicesConfig()
      set({ servicesConfig: config, servicesConfigLoading: false })
      if (
        config.nsfw_mode
        && _modelVisibilityHydrated
        && get().models.length > 0
      ) {
        set(s => {
          const next = _enableUninitializedMatureModels(
            s.models,
            s.enabledModels,
          )
          if (!next) return s
          _saveEnabledModels(next)
          return { enabledModels: next }
        })
      }
    } catch (e) {
      console.error('Failed to load services config:', e)
      set({ servicesConfigLoading: false })
    }
  },
  updateServicesConfig: async (partial) => {
    // Keep controlled settings inputs stable immediately. Previously the
    // select stayed bound to the old server value until PUT + refetch
    // completed, so choosing another LLM visibly snapped back to Qwen.
    // Serialize writes as well: remote URLs are edited character-by-character
    // and out-of-order PUT completions must never restore an older value.
    const optimistic = Object.fromEntries(
      Object.entries(partial).filter(([key]) => !key.endsWith('_api_key')),
    ) as Partial<ServicesConfig>
    if (Object.keys(optimistic).length > 0) {
      set(state => ({
        servicesConfig: state.servicesConfig
          ? { ...state.servicesConfig, ...optimistic }
          : state.servicesConfig,
      }))
    }
    const updateTask = _servicesConfigUpdateQueue.then(async () => {
      const result = await api.updateServicesConfig(partial)
      set(state => ({
        servicesConfig: state.servicesConfig
          ? { ...state.servicesConfig, ...(result.updated as Partial<ServicesConfig>) }
          : state.servicesConfig,
      }))
    })
    _servicesConfigUpdateQueue = updateTask.catch(() => undefined)
    try {
      await updateTask
      // When Mature Mode flips ON, auto-add all nsfw_only models to
      // enabledModels so they show up in selectors immediately. Without
      // this the user would have to walk Settings → System → Model
      // Visibility and individually enable each one — defeats the
      // "auto-selected when NSFW is enabled" UX.
      //
      // Flipping nsfw_mode OFF doesn't remove them from enabledModels
      // (they're filtered from view by the nsfw_only + nsfw_mode check
      // in ModelSelector / SystemSettingsPanel anyway). That way if the
      // user toggles mature mode back on later, their selections persist.
      get().loadServicesConfig()
      if (partial.nsfw_mode === true) {
        if (_modelVisibilityHydrated) {
          set(s => {
            const next = _enableUninitializedMatureModels(s.models, s.enabledModels)
            if (!next) return s
            _saveEnabledModels(next)
            return { enabledModels: next }
          })
        } else {
          const nsfwModels = get().models.filter(m => m.nsfw_only).map(m => m.model_type)
          if (nsfwModels.length > 0) {
            set(s => {
              const next = new Set(s.enabledModels)
              nsfwModels.forEach(modelType => next.add(modelType))
              _saveEnabledModels(next)
              return { enabledModels: next }
            })
          }
        }
      }
    } catch (e) {
      console.error('Failed to update services config:', e)
      await get().loadServicesConfig()
    }
  },
})
