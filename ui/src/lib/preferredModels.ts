import type { ModelDef } from '../types'

/** Newer models that become the default for a mode as soon as their weights are installed.
 *  Without them the mode keeps its existing default, so a small install is never pointed at a model it cannot run. */
export const INSTALLED_FIRST_DEFAULTS: Readonly<Record<string, string>> = {
  image: 'qwen_image_21',
}

export function installedPreferredModel(
  mode: string,
  models: ReadonlyArray<Pick<ModelDef, 'model_type' | 'is_downloaded'>>,
): string | null {
  const preferred = INSTALLED_FIRST_DEFAULTS[mode]
  if (!preferred) return null
  return models.some(model => model.model_type === preferred && model.is_downloaded === true) ? preferred : null
}
