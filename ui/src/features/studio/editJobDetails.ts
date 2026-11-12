import type { GenerationDetails } from '../../types'
import type { AppState } from '../../stores/useStore'

/**
 * Details for the "Submitting…" / queued card of an Edit-tab job (Retake, Inpaint, Edit
 * Anything, Outpaint, Recast, Repaint). The Edit tab lists a job when its details say
 * `generation_mode: 'avatar'` or carry an `edit_sub_mode` (`jobFitsGalleryFilter`); a
 * placeholder without details was invisible there until the card disappeared. The server
 * publishes `edit_sub_mode` too, so the card stays on the Edit tab once the first status
 * poll replaces these details.
 */
export function editJobGenerationDetails(
  state: Pick<AppState, 'params' | 'models' | 'editSubMode'>,
): GenerationDetails {
  const modelType = typeof state.params.model_type === 'string' ? state.params.model_type.trim() : ''
  return {
    ...(modelType ? {
      model_type: modelType,
      model_name: state.models.find(model => model.model_type === modelType)?.name || modelType,
    } : {}),
    generation_mode: 'avatar',
    edit_sub_mode: state.editSubMode,
  }
}
