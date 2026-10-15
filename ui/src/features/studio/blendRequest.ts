import type { submitBlend } from '../../api/generation'
import type { AppState } from '../../stores/useStore'

export type BlendRequestState = Pick<AppState,
  'blendClipAPath' | 'blendClipBPath' | 'blendMode' | 'blendOverlapSec' | 'blendTransitionSec'
  | 'blendMotionPrefixSec' | 'blendMotionSuffixSec' | 'blendAnchorStrength' | 'params' | 'activeWorkspace'>

/**
 * The POST /api/v1/blend body for the Blend sidebar. Each mode reads its own slider: Overlap sends
 * "Overlap Duration" as `overlap_sec`; Insert sends "Transition Duration" as `transition_sec` (the length of
 * the footage added between A and B). Both are always sent, the server takes the one its mode needs.
 * Callers have checked that both clips are chosen.
 */
export function buildBlendRequest(state: BlendRequestState, prompt: string): Parameters<typeof submitBlend>[0] {
  return {
    clip_a_path: state.blendClipAPath as string,
    clip_b_path: state.blendClipBPath as string,
    prompt: prompt || 'smooth natural transition between the two clips',
    model_type: state.params.model_type as string,
    blend_mode: state.blendMode,
    overlap_sec: state.blendOverlapSec,
    transition_sec: state.blendTransitionSec,
    // Blend-specific tuning knobs (exposed in BlendControls sliders)
    motion_prefix_sec: state.blendMotionPrefixSec,
    motion_suffix_sec: state.blendMotionSuffixSec,
    input_video_strength: state.blendAnchorStrength,
    seed: (state.params.seed as number) ?? -1,
    activated_loras: (state.params.activated_loras as string[]) || [],
    loras_multipliers: (state.params.loras_multipliers as string) || '',
    workspace: state.activeWorkspace,
    // Pass the full Studio params so the backend can inherit the user's
    // progressive_pipeline / num_inference_steps / guidance_scale /
    // negative_prompt settings, matching what a manual SE generation
    // would have used. Blend-specific fields (image_start/end, video_length,
    // resolution, image_prompt_type) are overridden server-side.
    base_params: state.params as unknown as Record<string, unknown>,
  }
}
