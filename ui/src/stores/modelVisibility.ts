import * as api from '../api/client'
import type { ModelDef } from '../types'

export const ENABLED_MODELS_KEY = 'maestro_enabled_models'
export const HUNYUAN3D_VISIBILITY_MIGRATION_KEY = 'maestro_hunyuan3d_visibility_v2'
export const MINIMAX_H3_VISIBILITY_MIGRATION_KEY = 'maestro_minimax_h3_visibility_v1'
export let _initializedMatureModels = new Set<string>()
export let _modelVisibilityHydrated = false
export let _modelVisibilityDefaultsVersion = 1
let _modelVisibilitySaveTask: Promise<void> = Promise.resolve()

export function _saveEnabledModels(models: Set<string>) {
  try {
    localStorage.setItem(ENABLED_MODELS_KEY, JSON.stringify([...models]))
  } catch { /* quota exceeded */ }
  const payload = {
    enabled_models: [...models],
    initialized_mature_models: [..._initializedMatureModels],
    defaults_version: _modelVisibilityDefaultsVersion,
  }
  _modelVisibilitySaveTask = _modelVisibilitySaveTask
    .catch(() => { /* a later save should still run */ })
    .then(async () => {
      try {
        await api.updateModelVisibility(payload)
      } catch (error) {
        console.warn('Failed to persist model visibility:', error)
      }
    })
}

export function _enableUninitializedMatureModels(
  models: ModelDef[],
  enabledModels: Set<string>,
): Set<string> | null {
  const next = new Set(enabledModels)
  let changed = false
  for (const model of models) {
    if (
      model.nsfw_only
      && !_initializedMatureModels.has(model.model_type)
    ) {
      _initializedMatureModels.add(model.model_type)
      next.add(model.model_type)
      changed = true
    }
  }
  return changed ? next : null
}

export function replaceInitializedMatureModels(models: Set<string>) {
  _initializedMatureModels = models
}

export function setModelVisibilityDefaultsVersion(version: number) {
  _modelVisibilityDefaultsVersion = version
}

export function markModelVisibilityHydrated() {
  _modelVisibilityHydrated = true
}
