import { rememberPrompt } from '../lib/promptHistory'
import type { DirectorModelCompatibility, GenerationDetails, H3WindowPlan, ModelResourceRequirements, ScailResolutionProfile } from '../types'
import { BASE } from './http'

export interface ApiModel {
  model_type: string
  name: string
  description?: string
  selector_help?: string
  lora_compatibility_note?: string
  family: string
  architecture: string
  resource_requirements?: ModelResourceRequirements
  is_i2v: boolean
  is_t2v: boolean
  guidance_max_phases: number
  fps: number
  supports_end_frame?: boolean
  /** Legacy broad flag: accepts input audio OR generates output audio. */
  supports_audio?: boolean
  supports_audio_input?: boolean
  generates_audio?: boolean
  supports_ref_images?: boolean
  /** Per-workflow eligibility computed by the Director backend. */
  director?: DirectorModelCompatibility
  is_downloaded?: boolean
  // True when the model JSON declares `"nsfw_only": true` in its
  // model block. The UI hides it from selectors and the visibility
  // settings unless servicesConfig.nsfw_mode is enabled.
  nsfw_only?: boolean
  // Hunyuan3D variants stored in one shared HF repo: deleting this
  // model's cache also removes the weights of every listed sibling.
  shared_cache_group?: string[]
  // Weight-managed tool models (e.g. UniRig): shown in the settings
  // catalog for download/delete, but never selectable for generation.
  tool_only?: boolean
}

export interface ApiFamily {
  id: string
  label: string
  order: number
}

export interface ApiResolution {
  label: string
  value: string
}

export interface ApiJobStatus {
  job_id: string
  task_id?: string | null
  root_task_id?: string | null
  status: 'queued' | 'waiting_resource' | 'running' | 'cancelling' | 'completed' | 'failed' | 'cancelled'
  progress: number
  step: number
  total_steps: number
  phase: string
  message: string
  output_files: string[]
  error: string | null
  created_at?: number | null
  started_at?: number | null
  finished_at?: number | null
  processing_time_sec?: number | null
  queue_position?: number | null
  task_timings?: ApiTaskTiming[]
  /** Present only on failed jobs that look like CUDA OOMs.
   *  See `OomInfo` in types/index.ts. */
  oom_info?: import('../types').OomInfo | null
  generation_details?: GenerationDetails
  h3_window_plan?: H3WindowPlan | null
}

export interface ApiTaskTiming {
  panel_no: number
  panel_total: number
  prompt_preview: string
  status: 'running' | 'completed' | 'failed' | 'skipped'
  total_seconds?: number
  phase_timings: Array<{ phase: string; seconds: number }>
}

// --- Models & Families ---

export async function fetchModels(): Promise<{ families: ApiFamily[]; models: ApiModel[] }> {
  const res = await fetch(`${BASE}/api/v1/models`)
  if (!res.ok) throw new Error('Failed to fetch models')
  return res.json()
}

export interface ModelVisibilitySettings {
  configured: boolean
  enabled_models: string[]
  initialized_mature_models: string[]
  defaults_version: number
}

export async function fetchModelVisibility(): Promise<ModelVisibilitySettings> {
  const res = await fetch(`${BASE}/api/v1/model-visibility`)
  if (!res.ok) throw new Error('Failed to fetch model visibility')
  return res.json()
}

export async function updateModelVisibility(params: {
  enabled_models: string[]
  initialized_mature_models: string[]
  defaults_version: number
}): Promise<ModelVisibilitySettings> {
  const res = await fetch(`${BASE}/api/v1/model-visibility`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  if (!res.ok) throw new Error('Failed to save model visibility')
  return res.json()
}

export interface ModelSelectionSettings {
  configured: boolean
  selected_models: Record<string, string>
  sources?: Record<string, 'global' | 'override'>
}

export async function fetchModelSelections(): Promise<ModelSelectionSettings> {
  const res = await fetch(`${BASE}/api/v1/model-selections`)
  if (!res.ok) throw new Error('Failed to fetch model selections')
  return res.json()
}

export async function updateModelSelections(
  selectedModels: Record<string, string>,
): Promise<ModelSelectionSettings> {
  const res = await fetch(`${BASE}/api/v1/model-selections`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ selected_models: selectedModels }),
  })
  if (!res.ok) throw new Error('Failed to save model selections')
  return res.json()
}

export interface ProductionProfileSettings {
  configured: boolean
  profile: import('../types').ProductionProfile
}

export async function fetchProductionProfile(): Promise<ProductionProfileSettings> {
  const res = await fetch(`${BASE}/api/v1/production-profile`)
  if (!res.ok) throw new Error('Failed to fetch the production profile')
  return res.json()
}

export async function updateProductionProfile(
  profile: import('../types').ProductionProfile,
): Promise<ProductionProfileSettings> {
  const res = await fetch(`${BASE}/api/v1/production-profile`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ profile }),
  })
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: 'Failed to save the production profile' }))
    throw new Error(error.detail || 'Failed to save the production profile')
  }
  return res.json()
}

// Re-scan defaults/ + finetunes/ on the server so a newly-imported checkpoint
// appears in the model list without a restart. Returns model_types that appeared.
export async function reloadModels(): Promise<{ status: string; model_count: number; added: string[] }> {
  const res = await fetch(`${BASE}/api/v1/models/reload`, { method: 'POST' })
  if (!res.ok) throw new Error('Failed to reload models')
  return res.json()
}

export async function deleteModel(modelType: string): Promise<{ deleted: string[]; model_type: string; affected_models?: string[] }> {
  const res = await fetch(`${BASE}/api/v1/models/${encodeURIComponent(modelType)}`, { method: 'DELETE' })
  if (!res.ok) throw new Error('Failed to delete model')
  return res.json()
}

export type ModelDownloadStatus = 'downloading' | 'completed' | 'failed'

export async function downloadModel(modelType: string): Promise<{ status: ModelDownloadStatus; model_type: string }> {
  const res = await fetch(`${BASE}/api/v1/models/${encodeURIComponent(modelType)}/download`, { method: 'POST' })
  if (!res.ok) throw new Error('Failed to start model download')
  return res.json()
}

export async function fetchModelDownloads(): Promise<{ downloads: Record<string, { status: ModelDownloadStatus; error: string | null }> }> {
  const res = await fetch(`${BASE}/api/v1/models/downloads/status`)
  if (!res.ok) throw new Error('Failed to fetch model download status')
  return res.json()
}

// --- Resolutions ---

export async function fetchResolutions(): Promise<ApiResolution[]> {
  const res = await fetch(`${BASE}/api/v1/resolutions`)
  if (!res.ok) throw new Error('Failed to fetch resolutions')
  const data = await res.json()
  return data.resolutions
}

// --- Model Defaults ---

export async function fetchDefaults(modelType: string): Promise<Record<string, unknown>> {
  const res = await fetch(`${BASE}/api/v1/defaults/${encodeURIComponent(modelType)}`)
  if (!res.ok) throw new Error(`Failed to fetch defaults for ${modelType}`)
  return res.json()
}

// --- Generation ---

export async function submitGeneration(params: Record<string, unknown>): Promise<{
  job_id: string
  task_id?: string | null
  root_task_id?: string | null
  status: string
  h3_window_plan?: H3WindowPlan
}> {
  const res = await fetch(`${BASE}/api/v1/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Generation failed' }))
    throw new Error(err.detail || 'Generation failed')
  }
  const result = await res.json()
  rememberPrompt({
    prompt: params.prompt,
    negativePrompt: params.negative_prompt,
    mode: params.generation_mode,
    model: params.model_type,
    workspace: params.workspace,
    source: 'generation',
  })
  return result
}

export async function fetchJobStatus(jobId: string): Promise<ApiJobStatus> {
  const res = await fetch(`${BASE}/api/v1/status/${encodeURIComponent(jobId)}`)
  if (!res.ok) throw new Error('Failed to fetch job status')
  return res.json()
}

// --- Tools: standalone post-processing on existing media ---

export async function submitToolUpscale(params: {
  source?: string
  // Kept for callers that submit the legacy video contract.
  video_path?: string
  source_kind?: 'image' | 'video'
  asset_id?: string
  source_workspace?: string
  method?: string
  seed?: number
  workspace?: string
  provenance?: {
    actor?: 'user' | 'wizard' | 'system' | 'unknown'
    capability?: string
    workspace_id?: string
    command?: { command_id?: string; workflow_id?: string; run_id?: string }
  }
}): Promise<{ job_id: string }> {
  const { source, video_path, source_kind, ...rest } = params
  const selectedSource = source ?? video_path
  const body = {
    ...rest,
    ...(source_kind === 'image'
      ? { source: selectedSource, source_kind }
      : { video_path: selectedSource, ...(source_kind ? { source_kind } : {}) }),
  }
  const res = await fetch(`${BASE}/api/v1/tools/upscale`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Upscale failed' }))
    throw new Error(err.detail || 'Upscale failed')
  }
  return res.json()
}

export async function submitToolRevoice(params: {
  video_path: string
  voice_ref_paths: string[]
  mode?: 'single' | 'two'
  diffusion_steps?: number
  cfg_rate?: number
  workspace?: string
}): Promise<{ job_id: string }> {
  const res = await fetch(`${BASE}/api/v1/tools/revoice`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Revoice failed' }))
    throw new Error(err.detail || 'Revoice failed')
  }
  return res.json()
}

export async function submitToolRemoveBackground(params: {
  asset_id?: string
  source?: string
  source_workspace?: string
  workspace?: string
  instruction?: string
  provenance?: {
    actor?: 'user' | 'wizard' | 'system' | 'unknown'
    capability?: string
    workspace_id?: string
    command?: { command_id?: string; workflow_id?: string; run_id?: string }
  }
}): Promise<{ job_id: string; task_id?: string | null; root_task_id?: string | null }> {
  const res = await fetch(`${BASE}/api/v1/tools/remove-background`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Background removal failed' }))
    throw new Error(err.detail || 'Background removal failed')
  }
  return res.json()
}

// --- Job Management ---

export async function cancelJob(jobId: string): Promise<void> {
  const res = await fetch(`${BASE}/api/v1/cancel/${encodeURIComponent(jobId)}`, { method: 'POST' })
  if (!res.ok) throw new Error('Failed to cancel job')
}

export async function fetchActiveJobs(): Promise<{ jobs: Array<{
  job_id: string; status: string; progress: number; step: number;
  total_steps: number; phase: string; message: string; output_files: string[];
  error: string | null; created_at: number; started_at?: number | null;
  finished_at?: number | null; queue_position?: number | null;
  task_timings?: ApiTaskTiming[];
  h3_window_plan?: H3WindowPlan | null;
  generation_details?: GenerationDetails;
}> }> {
  const res = await fetch(`${BASE}/api/v1/jobs`)
  if (!res.ok) throw new Error('Failed to fetch jobs')
  return res.json()
}

export interface RecoverableGenerationJob {
  job_id: string
  previous_status: 'queued' | 'running' | string
  created_at: number
  workspace: string
  model_type: string
  generation_mode: string
  prompt_preview: string
}

export async function fetchGenerationQueueRecovery(): Promise<{ jobs: RecoverableGenerationJob[] }> {
  const res = await fetch(`${BASE}/api/v1/jobs/recovery`)
  if (!res.ok) throw new Error('Could not inspect the saved generation queue')
  return res.json()
}

export async function resumeGenerationQueue(): Promise<{ resumed: RecoverableGenerationJob[]; count: number }> {
  const res = await fetch(`${BASE}/api/v1/jobs/recovery/resume`, { method: 'POST' })
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: 'Could not resume the saved queue' }))
    throw new Error(error.detail || 'Could not resume the saved queue')
  }
  return res.json()
}

export async function discardGenerationQueue(): Promise<{ discarded: number }> {
  const res = await fetch(`${BASE}/api/v1/jobs/recovery/discard`, { method: 'POST' })
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: 'Could not discard the saved queue' }))
    throw new Error(error.detail || 'Could not discard the saved queue')
  }
  return res.json()
}

// --- Presets ---

export interface GenerationPreset {
  id: string
  name: string
  mode: string
  model_type: string
  prompt: string
  activated_loras: string[]
  loras_multipliers: string
  lora_weights: Record<string, number[]>
  params: Record<string, unknown>
  created_at: number
}

export async function fetchPresets(): Promise<{ presets: GenerationPreset[] }> {
  const res = await fetch(`${BASE}/api/v1/presets`)
  if (!res.ok) throw new Error('Failed to fetch presets')
  return res.json()
}

export async function createPreset(preset: Omit<GenerationPreset, 'id' | 'created_at'>): Promise<GenerationPreset> {
  const res = await fetch(`${BASE}/api/v1/presets`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(preset),
  })
  if (!res.ok) throw new Error('Failed to create preset')
  return res.json()
}

export async function deletePreset(id: string): Promise<void> {
  const res = await fetch(`${BASE}/api/v1/presets/${encodeURIComponent(id)}`, { method: 'DELETE' })
  if (!res.ok) throw new Error('Failed to delete preset')
}

// --- Model Options ---

export async function fetchModelOptions(modelType: string): Promise<import('../types').ModelOptions> {
  const res = await fetch(`${BASE}/api/v1/model-options/${encodeURIComponent(modelType)}`)
  if (!res.ok) throw new Error('Failed to fetch model options')
  return res.json()
}

// --- Retake ---

export async function submitRetake(params: {
  video_path: string; start_time: number; end_time: number;
  prompt: string; model_type: string;
  negative_prompt?: string; seed?: number; guidance_scale?: number;
  num_inference_steps?: number; retake_strength?: number; workspace?: string;
  retake_engine?: string; regenerate_audio?: boolean; resolution?: string;
  activated_loras?: string[]; loras_multipliers?: string;
}): Promise<{ job_id: string; status: string; retake_frames: string }> {
  const res = await fetch(`${BASE}/api/v1/retake`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Retake failed' }))
    throw new Error(err.detail || 'Retake failed')
  }
  return res.json()
}

// --- Inpaint ---

export async function segmentPreview(params: {
  video_path: string; text: string; frame_index?: number;
  start_time?: number; end_time?: number;
  full_video?: boolean; invert_mask?: boolean;
}): Promise<{ mask_preview: string; target: string; frame_index: number; masks_path?: string; prompt?: string; negative_prompt?: string }> {
  const res = await fetch(`${BASE}/api/v1/segment/preview`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Segmentation failed' }))
    throw new Error(err.detail || 'Segmentation failed')
  }
  return res.json()
}

export async function submitInpaint(params: {
  video_path: string; description: string;
  sam_target?: string; invert_mask?: boolean;
  start_time?: number; end_time?: number;
  model_type: string; retake_strength?: number; resolution?: string;
  activated_loras?: string[]; loras_multipliers?: string;
  seed?: number; guidance_scale?: number;
  num_inference_steps?: number; negative_prompt?: string;
  mask_padding?: number; workspace?: string;
  masks_path?: string; stage2_steps?: number;
}): Promise<{ job_id: string; status: string }> {
  const res = await fetch(`${BASE}/api/v1/inpaint`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Inpaint failed' }))
    throw new Error(err.detail || 'Inpaint failed')
  }
  return res.json()
}

// --- Edit Anything ---
//
// Prompt-driven video edit using the Alissonerdx Edit Anything LoRA
// (https://huggingface.co/Alissonerdx/LTX-LoRAs). No mask required —
// the LoRA interprets Add/Remove/Replace/Style prompts directly.

export async function submitEditAnything(params: {
  video_path: string;
  prompt: string;
  model_type: string;
  start_time?: number;
  end_time?: number;
  /** LoRA strength (default 1.0, try 1.2 if edit is too weak). */
  lora_strength?: number;
  /** Retake strength — how much of the source latent structure is kept.
   *  Default 1.0 (full regen). Lower (0.5-0.8) preserves more of the
   *  original composition. */
  retake_strength?: number;
  negative_prompt?: string;
  seed?: number;
  guidance_scale?: number;
  num_inference_steps?: number;
  activated_loras?: string[];
  loras_multipliers?: string;
  workspace?: string;
}): Promise<{
  job_id: string;
  status: string;
  edit_range?: string;
  lora_filename?: string;
}> {
  const res = await fetch(`${BASE}/api/v1/edit-anything`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Edit Anything failed' }))
    throw new Error(err.detail || 'Edit Anything failed')
  }
  return res.json()
}

// --- Repaint (SCAIL-2 Animate: edited first frame + source motion) ---

export interface RepaintRegionRequest {
  id?: string;
  /** Person/object phrase to track through the source video. */
  source: string;
  /** Corresponding person/object phrase in the edited first frame. */
  target: string;
}

export async function submitRepaint(params: {
  video_path: string;
  target_frame_path: string;
  region_mappings?: RepaintRegionRequest[];
  prompt?: string;
  start_time?: number;
  end_time?: number;
  model_type?: string;
  negative_prompt?: string;
  seed?: number;
  num_inference_steps?: number;
  /** SCAIL-2 HQ only. Fast is CFG-distilled and stays at 1. */
  guidance_scale?: number;
  resolution_profile?: ScailResolutionProfile;
  activated_loras?: string[];
  loras_multipliers?: string;
  workspace?: string;
}): Promise<{
  job_id: string;
  status: string;
  frames?: number;
  region_count?: number;
  resolution_profile?: ScailResolutionProfile;
  resolution?: string;
  sliding_window_size?: number;
  num_inference_steps?: number;
  guidance_scale?: number;
}> {
  const res = await fetch(`${BASE}/api/v1/repaint`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Repaint failed' }))
    throw new Error(err.detail || 'Repaint failed')
  }
  return res.json()
}

export async function repaintPreview(params: {
  video_path: string;
  target_frame_path: string;
  region_mappings: RepaintRegionRequest[];
  time?: number;
  workspace?: string;
}): Promise<{
  found: boolean;
  frame_index: number;
  source_preview: string;
  target_preview: string;
  mapping_results: Array<{
    mapping_index: number;
    source: string;
    target: string;
    source_found: boolean;
    target_found: boolean;
    color: number[];
  }>;
}> {
  const res = await fetch(`${BASE}/api/v1/repaint/preview`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Repaint preview failed' }))
    throw new Error(err.detail || 'Repaint preview failed')
  }
  return res.json()
}

// --- Recast (SCAIL-2 Replace: swap a person for a reference character) ---

export async function submitRecast(params: {
  video_path: string;
  ref_image_path?: string;
  /** Same-character views for the legacy single-mapping request. */
  additional_ref_image_paths?: string[];
  /** Deterministic source-person → replacement-reference assignments. */
  character_mappings?: Array<{
    id?: string;
    target: string;
    ref_image_path: string;
    additional_ref_image_paths?: string[];
    reference_aligned_to_source?: boolean;
  }>;
  /** Who to replace, as a SAM3 keyword ("woman", "man in red"). */
  target?: string;
  /** Number of matching people to track and replace (1-5). */
  person_count?: number;
  /** The reference is an edited copy of the selected source first frame. */
  reference_aligned_to_source?: boolean;
  /** Preserve original subject identity while neutralizing reference scenery. */
  isolate_reference?: boolean;
  /** Derive a tighter same-character identity view when none is supplied. */
  auto_face_detail?: boolean;
  /** Rewrite and append Maestro's identity/scene continuity guidance. */
  enhance_prompt?: boolean;
  /** Strict post-composite fallback; may create visible lighting/color seams. */
  protect_bystanders?: boolean;
  /** Experimental: preserve other visible identities with native SCAIL-2 color correspondence. */
  preserve_bystanders?: boolean;
  /** Apply the official SCAIL-2 replacement Relighting LoRA. */
  use_relighting?: boolean;
  /** Spatial quality only; does not select a model or change its step schedule. */
  resolution_profile?: ScailResolutionProfile;
  /** Optional scene/character description — a good one helps identity. */
  prompt?: string;
  start_time?: number;
  end_time?: number;
  model_type?: string;
  negative_prompt?: string;
  seed?: number;
  num_inference_steps?: number;
  guidance_scale?: number;
  activated_loras?: string[];
  loras_multipliers?: string;
  workspace?: string;
}): Promise<{
  job_id: string;
  status: string;
  frames?: number;
  target?: string;
  person_count?: number;
  resolution_profile?: ScailResolutionProfile;
  resolution?: string;
  sliding_window_size?: number;
  num_inference_steps?: number;
  guidance_scale?: number;
}> {
  const res = await fetch(`${BASE}/api/v1/recast`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Recast failed' }))
    throw new Error(err.detail || 'Recast failed')
  }
  return res.json()
}

export async function recastPreview(params: {
  video_path: string;
  target?: string;
  person_count?: number;
  ref_image_path?: string;
  additional_ref_image_paths?: string[];
  character_mappings?: Array<{
    id?: string;
    target: string;
    ref_image_path?: string;
    additional_ref_image_paths?: string[];
    reference_aligned_to_source?: boolean;
  }>;
  isolate_reference?: boolean;
  auto_face_detail?: boolean;
  resolution_profile?: ScailResolutionProfile;
  time?: number;
  end_time?: number;
  workspace?: string;
}): Promise<{
  found: boolean;
  matched_people: number;
  requested_people: number;
  frame_index: number;
  time_seconds?: number;
  timeline_start_seconds?: number;
  timeline_end_seconds?: number;
  sampled_frame_count?: number;
  preview: string;
  resolution_profile?: ScailResolutionProfile;
  output_resolution?: number[];
  mapping_results?: Array<{
    mapping_index: number;
    target: string;
    found: boolean;
    color: number[];
    overlap_fraction: number;
    first_frame_index?: number | null;
    first_time_seconds?: number | null;
    anchor_frame_index?: number | null;
    anchor_time_seconds?: number | null;
  }>;
  reference_previews?: Array<{
    mapping_index: number;
    view_index: number;
    kind: 'primary' | 'additional' | 'auto_face_detail';
    mask_source: string;
    source_size: number[];
    prepared_size: number[];
    crop_box?: number[];
    detail_size?: number[];
    detail_source?: string;
    prepared_image: string;
    clip_identity_image?: string;
    semantic_mask: string;
  }>;
}> {
  const res = await fetch(`${BASE}/api/v1/recast/preview`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Preview failed' }))
    throw new Error(err.detail || 'Preview failed')
  }
  return res.json()
}

// --- Outpaint ---

export async function submitOutpaint(params: {
  video_path: string; prompt: string; model_type: string;
  pad_top?: number; pad_bottom?: number; pad_left?: number; pad_right?: number;
  outpaint_aspect?: 'source' | '16:9' | '9:16' | '1:1' | '4:3' | '3:4';
  resolution_preset?: 'auto' | '480p' | '540p' | '720p' | '1080p';
  source_preservation?: number;
  outpaint_lora_strength?: number;
  mask_preserving_outpaint?: boolean;
  num_inference_steps?: number;
  guidance_scale?: number;
  negative_prompt?: string;
  seed?: number;
  activated_loras?: string[]; loras_multipliers?: string;
  workspace?: string;
  // Recovery stubs — these fields were added by the Stream C/D outpaint
  // refinement work that got wiped by the git filter-repo reset. The
  // backend should already accept them (handler is server-side); these
  // signature additions just stop the TS build from complaining.
  preserve_source_audio?: boolean;
  lock_source_pixels?: boolean;
  trim_window_smear?: boolean;
  sliding_window_size?: number;
  sliding_window_overlap?: number;
  start_time?: number;
  end_time?: number;
}): Promise<{ job_id: string; status: string }> {
  const res = await fetch(`${BASE}/api/v1/outpaint`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Outpaint failed' }))
    throw new Error(err.detail || 'Outpaint failed')
  }
  return res.json()
}

// --- Blend ---

export async function submitBlend(params: {
  clip_a_path: string; clip_b_path: string;
  prompt?: string;
  model_type: string;
  blend_mode?: 'insert' | 'overlap'; overlap_sec?: number;
  seed?: number; activated_loras?: string[]; loras_multipliers?: string;
  workspace?: string;
  // Studio params inherited by the blend (progressive_pipeline,
  // num_inference_steps, guidance_scale, negative_prompt, etc.). Blend-
  // specific fields are overridden server-side.
  base_params?: Record<string, unknown>;
  // Blend-specific tuning overrides (take precedence over base_params)
  /** Seconds of A's overlap-zone start used as video_source for motion
   *  continuity (VE mode). 0 = pure SE. Default 1.0. */
  motion_prefix_sec?: number;
  /** Seconds of B's overlap-zone end used as video_end for motion continuity
   *  on the B side (via _append_suffix_entries in ltx2.py). 0 = single
   *  image_end anchor. Default 1.0. */
  motion_suffix_sec?: number;
  /** Strength of the VE anchor locks (video_source + image_end).
   *  1.0 = hard lock → averaging → crossfade. 0.5-0.8 = model invents
   *  motion between anchors. Default 1.0 server-side. */
  input_video_strength?: number;
  anchor_frames?: number;
  injection_strength?: number;
  num_inference_steps?: number;
  guidance_scale?: number;
  negative_prompt?: string;
  /** @deprecated no longer used; kept for back-compat with existing call sites */
  transition_sec?: number;
  /** @deprecated bell-curve weighting is applied automatically */
  strength_a?: number;
  /** @deprecated bell-curve weighting is applied automatically */
  strength_b?: number;
  /** @deprecated superseded by anchor_frames; kept for back-compat */
  denoise_strength?: number;
}): Promise<{ job_id: string; status: string; overlap_sec?: number; frames?: number }> {
  const res = await fetch(`${BASE}/api/v1/blend`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Blend failed' }))
    throw new Error(err.detail || 'Blend failed')
  }
  return res.json()
}

/** SAM (Inpaint) service status. Status values:
 *   ready / available — service running, model loaded or loading
 *   installed         — env installed but service not started; will
 *                        auto-start on demand
 *   not_installed     — SAM env doesn't exist; user must run
 *                        "Install Inpaint Support (SAM 3.1)" from the
 *                        Pinokio menu before Inpaint will work
 *   unavailable       — generic failure (service unhealthy, network)
 */

export async function samServiceStatus(): Promise<{
  status: string
  model_loaded: boolean
  error?: string
}> {
  const res = await fetch(`${BASE}/api/v1/sam/status`)
  if (!res.ok) return { status: 'unavailable', model_loaded: false }
  return res.json()
}

// --- Upload ---

export async function uploadImage(file: File): Promise<{
  filename: string
  path: string
  url: string
  fps?: number
  frame_count?: number
  duration_seconds?: number
  has_audio?: boolean
}> {
  const form = new FormData()
  form.append('file', file)
  const res = await fetch(`${BASE}/api/v1/upload`, {
    method: 'POST',
    body: form,
  })
  if (!res.ok) throw new Error('Upload failed')
  return res.json()
}
