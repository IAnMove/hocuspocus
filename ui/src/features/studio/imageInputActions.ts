import { useStore } from '../../stores/useStore'
import { fetchOutputMetadata } from '../../api/outputs'
import { outputImageUrl, restoreImageFile } from '../../lib/storedImageFiles'
import { forgetLocalImage, localEditPreview } from '../../lib/localEditImages'
import { referenceImageResolution, snapImageResolution } from '../../lib/imageResolution'
import { mergeVideoPromptLetters } from '../../lib/studioImageEdit'
import { beginImageSettingsChange, restoreStudioImageSettings } from './imageSettingsRestore'
import i18n from '../../i18n'
import type { AppState } from '../../stores/useStore'
import type { ImageStudioIntent } from './imageStudioIntent'

function requireReferenceCapacity(state: AppState, intent: Exclude<ImageStudioIntent, 'chooser'>) {
  const target = state.imageStudioIntent === intent ? state : state.imageStudioDrafts[intent]
  const limit = state.modelOptions?.max_image_refs
  if (limit != null && (target?.imageRefs.length || 0) + (target?.params.image_guide ? 1 : 0) >= limit) {
    throw new Error(i18n.t('studio:imageEdit.referenceLimit', { count: limit }))
  }
}

function defaultReferenceType(state: AppState): string {
  const choices = state.modelOptions?.image_ref_choices?.choices || []
  return choices.find(([, value]) => value.includes('K'))?.[1] || choices.find(([, value]) => value)?.[1] || 'I'
}

export function setStudioImageSource(source?: string): void {
  const previous = useStore.getState()
  previous.setImageStudioIntent('edit')
  const state = useStore.getState()
  if (source !== state.params.image_guide) forgetLocalImage(String(state.params.image_guide || ''))
  forgetLocalImage(String(state.params.image_mask || ''))
  useStore.setState({ imageSourceSize: null })
  state.setParams({ image_guide: source, image_mask: undefined, video_guide_outpainting: undefined,
    video_prompt_type: mergeVideoPromptLetters(String(state.params.video_prompt_type || ''), source ? 'V' : '', 'VAG'),
  })
  if (!source || typeof Image === 'undefined') return
  const preview = new Image(), workspace = state.activeWorkspace
  preview.onload = () => {
    const current = useStore.getState()
    if (current.params.image_guide !== source || current.imageStudioIntent !== 'edit'
      || current.generationMode !== 'image' || current.activeWorkspace !== workspace) return
    useStore.setState({ imageSourceSize: { source, width: preview.width, height: preview.height } })
    if (current.aspectRatio === 'auto') current.setParam('resolution', String(current.params.model_type).startsWith('qwen_image_21')
      ? referenceImageResolution(preview.width, preview.height, current.resolutionPreset, current.params.model_type)
      : snapImageResolution(preview.width, preview.height, 2048, current.params.model_type))
  }
  preview.src = localEditPreview(source)
}

export function setStudioImageMask(mask?: string): void {
  const state = useStore.getState()
  if (!state.params.image_guide) throw new Error(i18n.t('studio:generate.needSource'))
  if (mask !== state.params.image_mask) forgetLocalImage(String(state.params.image_mask || ''))
  const modes = state.modelOptions?.image_edit_modes
  const method = modes?.choices.some(([, value]) => value === state.params.model_mode)
    ? state.params.model_mode : modes?.default ?? 0
  state.setParams({ image_mask: mask, model_mode: method,
    video_prompt_type: mergeVideoPromptLetters(String(state.params.video_prompt_type || ''), mask ? 'VAG' : 'V', 'AG'),
  })
}

export async function addOutputImageReference(name: string, workspace: string): Promise<boolean> {
  const state = useStore.getState(), change = beginImageSettingsChange(useStore.getState)
  if (!state.modelOptions?.image_ref_choices) throw new Error(i18n.t('studio:imageIntent.incompatible'))
  const item = await restoreImageFile(outputImageUrl(name, workspace), workspace, change.signal)
  if (!change.current()) return false
  const intent = state.imageStudioIntent === 'edit' && state.modelOptions.image_ref_inpaint ? 'edit' : 'character'
  requireReferenceCapacity(state, intent)
  state.setImageStudioIntent(intent)
  const active = useStore.getState()
  active.addImageRef(item.file)
  if (!active.imageRefType) active.setImageRefType(defaultReferenceType(state))
  return true
}

/** Edit the selected result; source inputs used to make that result are not required. */
export async function editOutputImage(name: string, workspace: string): Promise<boolean> {
  const state = useStore.getState(), change = beginImageSettingsChange(useStore.getState)
  const metadata = workspace === '__uploads__' ? null : await fetchOutputMetadata(name, workspace)
  if (!change.current()) return false
  const saved = metadata?.params || (state.generationMode === 'image' ? state.params : {
    model_type: state.selectedModelPerMode.image, prompt: '',
  })
  return restoreStudioImageSettings({ ...saved, image_mode: 1,
    image_guide: outputImageUrl(name, workspace), image_mask: undefined, image_refs: [],
    image_start: undefined, image_end: undefined, video_guide: undefined, video_mask: undefined,
    video_prompt_type: 'V', image_prompt_type: 'T', video_guide_outpainting: undefined,
  }, workspace, useStore.getState, useStore.setState)
}
