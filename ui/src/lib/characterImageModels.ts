import type { ModelDef } from '../types'
import { getModelMode } from '../stores/useStore'

/** These editors need a source image; Qwen Image 2.1 also supports plain text. */
export function characterImageNeedsReference(model: Pick<ModelDef, 'model_type' | 'architecture'>): boolean {
  return [model.model_type, model.architecture].some(id => /^(qwen_image_edit|flux_kontext|flux1_kontext)/.test(id))
}

export function characterImageModels(models: ModelDef[], withReference: boolean): ModelDef[] {
  return models.filter(model => getModelMode(model.model_type, model.family) === 'image'
    && model.is_downloaded !== false
    && (withReference ? model.supports_ref_images : !characterImageNeedsReference(model)))
}

export function preferredCharacterImageModel(models: ModelDef[], withReference: boolean): string {
  const preferred = (withReference && models.find(model => model.model_type.startsWith('qwen_image_edit')))
    || models.find(model => model.model_type === 'qwen_image_21')
    || models.find(model => model.model_type.startsWith('qwen_image'))
    || models[0]
  return preferred?.model_type ?? ''
}
