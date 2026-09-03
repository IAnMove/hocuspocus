import { isDirectorV2PlanFailureDetail, isDirectorV2PlanResponse } from '../types'
import type { DirectorV2PlanFailureDetail, DirectorV2PlanJob, DirectorV2PlanProgress, DirectorV2PlanRequest, DirectorV2PlanResponse, GenerationDetails } from '../types'
import { BASE } from './http'

export interface AudioAnalysisJobStatus {
  job_id: string
  task_id?: string
  root_task_id?: string
  status: 'queued' | 'waiting_resource' | 'running' | 'cancelling' | 'completed' | 'failed' | 'cancelled'
  progress: number
  step: number
  total_steps: number
  phase: string
  message: string
  error: string | null
  result: import('../types').AudioAnalysisResult | null
}

// Director Music Video: generate a music track (writes the song first if only
// a description is given) and return the ABSOLUTE audio path so it can flow
// straight into the existing analyze → plan-structure → pipeline chain.
export async function generateMusic(params: {
  description?: string
  style?: string
  lyrics?: string
  instrumental?: boolean
  duration_seconds?: number
  reference_image_path?: string
  model_type?: string
  seed?: number
  /** Physical output folder used by the Director run, not a collection ID. */
  workspace?: string
  initiator?: string
  /** Browser-owned attribution; runtime IDs are added by the backend. */
  provenance?: {
    actor?: 'user' | 'wizard' | 'system' | 'unknown'
    capability?: string
    /** Optional explicit Workspace collection ID; never pass `workspace` here. */
    workspace_id?: string
    project_id?: string
    production_id?: string
    cue_id?: string
    candidate_id?: string
    command?: Record<string, string>
  }
}): Promise<{
  audio_path: string
  filename: string
  style: string
  lyrics: string
  job_id?: string
  task_id?: string
  root_task_id?: string
}> {
  const res = await fetch(`${BASE}/api/v1/director/generate-music`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Music generation failed' }))
    throw new Error(err.detail || 'Music generation failed')
  }
  return res.json()
}

// --- Director Pipeline ---

export interface PipelinePreviewClip {
  index: number
  page_number: number | null
  panel_number: number | null
  label: string
  image_filename: string
  end_image_filename: string
  source_resolution: string
  input_resolution: string
  output_resolution: string
  video_model: string
  prompt: string
  base_prompt?: string
  prompt_overridden?: boolean
  negative_prompt: string
  num_inference_steps: number
  stage2_steps: number
  guidance_scale: number
  runtime_recipe?: string
  requested_num_inference_steps?: number
  requested_stage2_steps?: number
  requested_guidance_scale?: number
  guidance_note?: string
  input_video_strength: number
  seed: number
  fps: number
  frames: number
  output_frames?: number
  duration_seconds: number
  image_prompt_type: 'S' | 'SE'
  fit_mode: string
  motion_mode: string
  camera_locked: boolean
  fidelity: string
  self_refiner: number
  spatial_upsampling: string
  film_grain_intensity: number
  film_grain_saturation: number
  single_stage_pipeline: number
  progressive_pipeline: number
  activated_loras: string[]
  lora_multipliers: string
  panel_id?: string
  shot_id?: string
  source_panel_ids?: string[]
  source_image_filename?: string
  renderer?: 'hold' | 'parallax' | 'cinemagraph' | 'ltx'
  effective_renderer?: 'hold' | 'parallax' | 'cinemagraph' | 'ltx'
  motion_level?: number
  dialogue?: string
  included?: boolean
  order?: number
  test_selected?: boolean
  camera_move?: string
  needs_reframe?: boolean
  reframe_approved?: boolean
  used_prepared_keyframe?: boolean
  effective_fit_mode?: string
  retained_fraction?: number
  risk_tags?: string[]
}

export interface PipelineQualityGate {
  status: 'pending' | 'failed' | 'review_required' | 'passed' | 'waived'
  fingerprint: string
  tested_indices: number[]
  required_test_indices?: number[]
  failures: string[]
  results?: Record<string, {
    passed?: boolean
    status?: string
    failures?: string[]
    warnings?: string[]
    renderer?: string
    video_filename?: string
    error?: string
    pipeline_id?: string
    output_files?: string[]
  }>
  waiver_reason?: string
}

export interface PipelineResourceSchedule {
  mode: string
  images_ready?: number
  images_total?: number
  lanes: Record<string, { key: string; label: string; location: string }>
}

export interface PipelineStatus {
  id: string
  status: 'running' | 'paused' | 'preview_ready' | 'completed' | 'failed' | 'cancelled'
  phase: 'planning' | 'polishing_prompts' | 'preparing_direct_video' | 'generating_images' | 'preview_ready' | 'preparing_video' | 'generating_video' | 'post_processing' | 'completed' | 'failed' | 'cancelled'
  generation_mode?: 'image_guided' | 'direct_video'
  auto_mode: boolean
  progress: { current: number; total: number; message: string; step: number; total_steps: number }
  clip_plans: Array<{ video_prompt: string; image_prompt: string }>
  clip_images: string[]
  preview_clips?: PipelinePreviewClip[]
  /** Hash of the exact frozen source images, shot plan and render settings.
   *  PATCH and generation calls echo this value so stale browser tabs cannot
   *  mutate or launch a different PRE accidentally. */
  preview_fingerprint?: string
  preview_approved?: boolean
  quality_gate?: PipelineQualityGate
  output_files: string[]
  error: string | null
  /** Present only on failed pipelines that look like CUDA OOMs.
   *  See `OomInfo` in types/index.ts. */
  oom_info?: import('../types').OomInfo | null
  pause_reason: string | null
  llm_streaming: boolean
  recovered_from_disk?: boolean
  /** Non-fatal warnings raised during the run — currently used for
   *  architecture-mismatch advisories when image LoRAs are dropped
   *  because they were trained for a different Flux variant than the
   *  active model (e.g. Flux 2 Dev LoRA on Klein 9B). The chat renders
   *  these inline so users see why some selected LoRAs weren't applied. */
  lora_warnings?: string[]
  resource_schedule?: PipelineResourceSchedule
  created_at?: number
  updated_at?: number
  phase_started_at?: number
  generation_details?: GenerationDetails
}

export interface ActiveDirectorPipeline {
  id: string
  status: 'running' | 'queued' | 'paused'
  phase: string
  auto_mode?: boolean
  progress: { current: number; total: number; message: string; step: number; total_steps: number }
  output_files?: string[]
  error?: string | null
  pipeline_type?: string
  workspace?: string
  created_at?: number
  updated_at?: number
  phase_started_at?: number
  resource_schedule?: PipelineResourceSchedule
  generation_details?: GenerationDetails
}

export async function startPipeline(params: Record<string, unknown>): Promise<{ pipeline_id: string }> {
  const res = await fetch(`${BASE}/api/v1/director/pipeline/start`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Failed to start pipeline' }))
    throw new Error(err.detail || err.error || 'Failed to start pipeline')
  }
  return res.json()
}

export async function fetchPipelineStatus(pid: string): Promise<PipelineStatus> {
  const res = await fetch(`${BASE}/api/v1/director/pipeline/${encodeURIComponent(pid)}`)
  if (!res.ok) throw new Error('Failed to fetch pipeline status')
  return res.json()
}

export async function fetchActiveDirectorPipelines(signal?: AbortSignal): Promise<{ pipelines: ActiveDirectorPipeline[] }> {
  const res = await fetch(`${BASE}/api/v1/director/pipelines/active`, { signal })
  if (!res.ok) throw new Error('Failed to fetch active Director pipelines')
  return res.json()
}

export async function continuePipeline(pid: string, updates?: { clip_plans?: Array<{ video_prompt: string; image_prompt: string }> }): Promise<void> {
  const res = await fetch(`${BASE}/api/v1/director/pipeline/${encodeURIComponent(pid)}/continue`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(updates || {}),
  })
  if (!res.ok) throw new Error('Failed to continue pipeline')
}

export async function generatePipelinePreview(
  pid: string,
  options: {
    clipIndex?: number
    clipIndices?: number[]
    expectedFingerprint: string
    runType: 'test' | 'full'
  },
): Promise<{ pipeline_id: string; source_preview_pipeline_id: string; clip_index?: number; reused?: boolean }> {
  const selectedIndices = (options.clipIndices || [])
    .filter(value => Number.isInteger(value) && value >= 0)
    .map(Number)
  const selection = selectedIndices.length
    ? { clip_indices: Array.from(new Set(selectedIndices)) }
    : Number.isInteger(options.clipIndex)
      ? { clip_index: options.clipIndex }
      : {}
  const res = await fetch(
    `${BASE}/api/v1/director/pipeline/${encodeURIComponent(pid)}/generate-preview`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        ...selection,
        expected_fingerprint: options.expectedFingerprint,
        run_type: options.runType,
      }),
    },
  )
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: 'Failed to generate PRE clip' }))
    throw new Error(body.detail || 'Failed to generate PRE clip')
  }
  return res.json()
}

export interface PipelinePreviewClipUpdate {
  index: number
  included: boolean
  order: number
  prompt?: string
  prompt_override?: boolean
  renderer: 'hold' | 'parallax' | 'cinemagraph' | 'ltx'
  motion_level: number
  fit_mode: 'reframe' | 'cover' | 'contain'
  duration_seconds: number
  camera_move: string
  seed: number
  test_selected: boolean
  reframe_approved?: boolean
}

export async function updatePipelinePreview(
  pid: string,
  clips: PipelinePreviewClipUpdate[],
  options: {
    expectedFingerprint: string
    approvePreview?: boolean
    acceptQualityTest?: boolean
    qualityWaiver?: boolean
    waiverReason?: string
  },
): Promise<PipelineStatus | { preview_clips: PipelinePreviewClip[] }> {
  const res = await fetch(
    `${BASE}/api/v1/director/pipeline/${encodeURIComponent(pid)}/preview`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        clips,
        expected_fingerprint: options.expectedFingerprint,
        ...(options.approvePreview ? { approve_preview: true } : {}),
        ...(options.acceptQualityTest ? { accept_quality_test: true } : {}),
        ...(options.qualityWaiver ? {
          quality_waiver: true,
          waiver_reason: options.waiverReason || '',
        } : {}),
      }),
    },
  )
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: 'Failed to update comic PRE' }))
    throw new Error(body.detail || 'Failed to update comic PRE')
  }
  return res.json()
}

export async function stopPipeline(pid: string): Promise<void> {
  const res = await fetch(`${BASE}/api/v1/director/pipeline/${encodeURIComponent(pid)}/stop`, {
    method: 'POST',
  })
  if (!res.ok) throw new Error('Failed to stop pipeline')
}

export async function resumePipeline(pid: string): Promise<void> {
  const res = await fetch(`${BASE}/api/v1/director/pipeline/${encodeURIComponent(pid)}/resume`, {
    method: 'POST',
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: 'Failed to resume pipeline' }))
    throw new Error(body.detail || 'Failed to resume pipeline')
  }
}

// ── Director Pipeline Dashboard ──────────────────────────────────────────

export async function fetchPipelineList(opts?: { limit?: number; offset?: number }): Promise<{
  pipelines: import('../types').PipelineListItem[]
  total: number
}> {
  const params = new URLSearchParams()
  if (opts?.limit && opts.limit > 0) params.set('limit', String(opts.limit))
  if (opts?.offset && opts.offset > 0) params.set('offset', String(opts.offset))
  const qs = params.toString()
  const res = await fetch(`${BASE}/api/v1/director/pipelines${qs ? `?${qs}` : ''}`)
  if (!res.ok) throw new Error('Failed to fetch pipelines')
  const data = await res.json()
  const pipelines = data.pipelines || []
  return { pipelines, total: data.total ?? pipelines.length }
}

export async function fetchSavedPipeline(pid: string): Promise<import('../types').SavedPipelineState> {
  const res = await fetch(`${BASE}/api/v1/director/pipelines/${encodeURIComponent(pid)}`, {
    cache: 'no-store',
  })
  if (!res.ok) {
    throw new Error(res.status === 404 ? 'Pipeline not found' : `Failed to load pipeline (${res.status})`)
  }
  return res.json()
}

export async function updatePipelineClipPrompt(
  pid: string,
  clipIndex: number,
  body: { video_prompt?: string; image_prompt?: string; soundtrack_drive?: boolean },
): Promise<import('../types').SavedPipelineState> {
  const res = await fetch(`${BASE}/api/v1/director/pipelines/${encodeURIComponent(pid)}/clips/${clipIndex}/prompt`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: 'Could not save prompt' }))
    throw new Error(err.error || err.detail || 'Could not save prompt')
  }
  return res.json()
}

export async function tagPipelineClip(pid: string, clipIndex: number, tag: string | null): Promise<void> {
  const res = await fetch(`${BASE}/api/v1/director/pipelines/${encodeURIComponent(pid)}/clips/${clipIndex}/tag`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tag }),
  })
  if (!res.ok) throw new Error('Failed to tag clip')
}

export async function selectPipelineClipVideo(
  pid: string,
  clipIndex: number,
  filename: string,
): Promise<{
  pipeline_id: string
  clip_index: number
  filename: string
  attempt: import('../types').PipelineVideoAttempt
}> {
  const res = await fetch(`${BASE}/api/v1/director/pipelines/${encodeURIComponent(pid)}/clips/${clipIndex}/video-selection`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ filename }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: 'Clip selection failed' }))
    throw new Error(err.error || err.detail || 'Could not select this clip version')
  }
  return res.json()
}

export async function startPipelineRepair(pid: string): Promise<{
  pipeline_id: string
  repair: import('../types').PipelineRepairState
}> {
  const res = await fetch(`${BASE}/api/v1/director/pipelines/${encodeURIComponent(pid)}/repair`, {
    method: 'POST',
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: 'Repair failed to start' }))
    throw new Error(err.error || err.detail || 'Repair failed to start')
  }
  return res.json()
}

export async function cancelPipelineRepair(pid: string): Promise<{
  pipeline_id: string
  repair: import('../types').PipelineRepairState
}> {
  const res = await fetch(`${BASE}/api/v1/director/pipelines/${encodeURIComponent(pid)}/repair/cancel`, {
    method: 'POST',
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: 'Repair cancel failed' }))
    throw new Error(err.error || err.detail || 'Repair cancel failed')
  }
  return res.json()
}

export async function rerunClipImage(pid: string, clipIndex: number, prompt?: string): Promise<{ filename: string; clip_index: number }> {
  const res = await fetch(`${BASE}/api/v1/director/pipelines/${encodeURIComponent(pid)}/clips/${clipIndex}/rerun-image`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ prompt: prompt || undefined }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: 'Re-run failed' }))
    throw new Error(err.error || 'Re-run image failed')
  }
  return res.json()
}

export async function rerunClipVideo(pid: string, clipIndex: number, prompt?: string): Promise<{ filename: string; clip_index: number }> {
  const res = await fetch(`${BASE}/api/v1/director/pipelines/${encodeURIComponent(pid)}/clips/${clipIndex}/rerun-video`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ prompt: prompt || undefined }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: 'Re-run failed' }))
    throw new Error(err.error || 'Re-run video failed')
  }
  return res.json()
}

export async function rerunH3Segment(
  pid: string,
  clipIndex: number,
  segmentIndex: number,
  prompt?: string,
): Promise<{ filename: string; filenames: string[]; clip_index: number; segment_index: number; requires_rejoin: boolean }> {
  const res = await fetch(`${BASE}/api/v1/director/pipelines/${encodeURIComponent(pid)}/clips/${clipIndex}/segments/${segmentIndex}/rerun`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ prompt: prompt || undefined, cascade: true }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: 'Segment regeneration failed' }))
    throw new Error(err.error || 'Segment regeneration failed')
  }
  return res.json()
}

export async function rejoinPipeline(pid: string): Promise<{
  filename: string
  assembly_time_sec: number
  total_time_sec: number | null
}> {
  const res = await fetch(`${BASE}/api/v1/director/pipelines/${encodeURIComponent(pid)}/rejoin`, {
    method: 'POST',
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: 'Rejoin failed' }))
    throw new Error(err.error || 'Rejoin failed')
  }
  return res.json()
}

export async function deletePipeline(pid: string): Promise<{ media_deleted: number; media_deferred: number }> {
  const res = await fetch(`${BASE}/api/v1/director/pipelines/${encodeURIComponent(pid)}`, { method: 'DELETE' })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Delete failed' }))
    throw new Error(err.detail || 'Delete failed')
  }
  return res.json()
}

// --- Director v2 ---

export class DirectorV2PlanError extends Error {
  readonly detail: DirectorV2PlanFailureDetail
  readonly job: DirectorV2PlanJob

  constructor(detail: DirectorV2PlanFailureDetail) {
    super(detail.message)
    this.name = 'DirectorV2PlanError'
    this.detail = detail
    this.job = detail.job
  }
}

async function throwDirectorV2PlanError(res: Response, fallback: string): Promise<never> {
  const payload: unknown = await res.json().catch(() => null)
  if (payload && typeof payload === 'object') {
    const detail = (payload as Record<string, unknown>).detail
    if (isDirectorV2PlanFailureDetail(detail)) {
      throw new DirectorV2PlanError(detail)
    }
    if (typeof detail === 'string' && detail.trim()) throw new Error(detail)
  }
  throw new Error(fallback)
}

export async function directorV2Plan(params: DirectorV2PlanRequest): Promise<DirectorV2PlanResponse> {
  const res = await fetch(`${BASE}/api/v1/director/v2/plan`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  if (!res.ok) {
    return throwDirectorV2PlanError(res, 'Director v2 plan failed')
  }
  const payload: unknown = await res.json()
  if (!isDirectorV2PlanResponse(payload)) {
    throw new Error('Director v2 returned an invalid plan contract')
  }
  return payload
}

export async function getDirectorV2PlanProgress(activityId: string): Promise<DirectorV2PlanProgress | null> {
  const res = await fetch(`${BASE}/api/v1/director/v2/plan/progress/${encodeURIComponent(activityId)}`)
  if (res.status === 404) return null
  if (!res.ok) throw new Error('Could not read Director planning progress')
  return res.json()
}

export async function listDirectorV2PlanJobs(workspace = 'default'): Promise<DirectorV2PlanJob[]> {
  const res = await fetch(`${BASE}/api/v1/director/v2/plan/jobs?workspace=${encodeURIComponent(workspace)}`)
  if (!res.ok) throw new Error('Failed to list Director plan jobs')
  const payload = await res.json()
  return Array.isArray(payload?.jobs) ? payload.jobs : []
}

export async function getDirectorV2PlanJob(jobId: string, workspace = 'default'): Promise<DirectorV2PlanJob> {
  const res = await fetch(`${BASE}/api/v1/director/v2/plan/jobs/${encodeURIComponent(jobId)}?workspace=${encodeURIComponent(workspace)}`)
  if (!res.ok) throw new Error('Director plan job not found')
  return res.json()
}

export async function resumeDirectorV2PlanJob(
  jobId: string,
  workspace = 'default',
  activityId?: string,
): Promise<DirectorV2PlanResponse> {
  const res = await fetch(`${BASE}/api/v1/director/v2/plan/jobs/${encodeURIComponent(jobId)}/resume?workspace=${encodeURIComponent(workspace)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(activityId ? { activity_id: activityId } : {}),
  })
  if (!res.ok) {
    return throwDirectorV2PlanError(res, 'Director plan resume failed')
  }
  const payload: unknown = await res.json()
  if (!isDirectorV2PlanResponse(payload)) {
    throw new Error('Director v2 returned an invalid resumed plan contract')
  }
  return payload
}

// --- Audio Mix ---

export async function mixAudio(tracks: { path: string; start_time: number; volume: number }[], workspace?: string): Promise<{ filename: string; path: string }> {
  const res = await fetch(`${BASE}/api/v1/audio/mix`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tracks, workspace }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Mix failed' }))
    throw new Error(err.detail || 'Mix failed')
  }
  return res.json()
}

// --- Audio Analysis ---

export async function uploadAudio(file: File): Promise<{
  filename: string
  path: string
  url: string
  duration_seconds?: number | null
}> {
  const form = new FormData()
  form.append('file', file)
  const res = await fetch(`${BASE}/api/v1/upload-audio`, {
    method: 'POST',
    body: form,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Upload failed' }))
    throw new Error(err.detail || 'Audio upload failed')
  }
  return res.json()
}

/** Adopt audio the server already holds — a workspace output or an earlier
 *  upload — as the current audio source, by name. The counterpart to
 *  uploadAudio for a file that never left the machine: same response, without
 *  pulling the track through the browser and posting it straight back. */
export async function adoptAudio(params: { audio_path: string; workspace?: string }): Promise<{
  filename: string
  path: string
  url: string
  duration_seconds?: number | null
}> {
  const res = await fetch(`${BASE}/api/v1/audio/adopt`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Could not load the audio' }))
    throw new Error(err.detail || 'Could not load the audio')
  }
  return res.json()
}

// The workspace travels with the path: an adopted song lives in its workspace
// folder, and the server confines every media path to uploads plus one
// workspace root, so trimming it without saying which one would be rejected.
export async function trimAudio(params: { audio_path: string; start: number; end: number; workspace?: string }): Promise<{
  filename: string; path: string; url: string; start: number; end: number; duration: number
}> {
  const res = await fetch(`${BASE}/api/v1/audio/trim`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Audio trim failed' }))
    throw new Error(err.detail || 'Audio trim failed')
  }
  return res.json()
}

export async function analyzeAudio(params: {
  audio_path: string
  transcribe?: boolean
  extract_vocals?: boolean
  /** Known written lyrics (generated tracks) — seeds Whisper so the
   *  transcription snaps to the real words instead of mishearing
   *  sung vocals. Omit for uploads/unknown tracks. */
  lyrics_hint?: string
}): Promise<import('../types').AudioAnalysisResult> {
  const res = await fetch(`${BASE}/api/v1/audio/analyze`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Analysis failed' }))
    throw new Error(err.detail || 'Audio analysis failed')
  }
  return res.json()
}

export async function startAudioAnalysisJob(params: {
  audio_path: string
  transcribe?: boolean
  extract_vocals?: boolean
  lyrics_hint?: string
  workspace?: string
}): Promise<{ job_id: string; task_id: string; root_task_id: string }> {
  const res = await fetch(`${BASE}/api/v1/audio/analyze/jobs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Analysis queue failed' }))
    throw new Error(err.detail || 'Audio analysis could not be queued')
  }
  return res.json()
}

export async function fetchAudioAnalysisJob(jobId: string): Promise<AudioAnalysisJobStatus> {
  const res = await fetch(`${BASE}/api/v1/audio/analyze/jobs/${encodeURIComponent(jobId)}`)
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Analysis job unavailable' }))
    throw new Error(err.detail || 'Audio analysis job unavailable')
  }
  return res.json()
}

/** Read live progress of the in-flight audio analyze call. Backed by
 *  audio_analysis._PROGRESS — updated at each phase boundary in the
 *  synchronous analyze() call. Polled by the Director sidebar to
 *  show "Loading transcription model (first use downloads ~300MB)..."
 *  vs "Transcribing audio..." instead of a single "Analyzing audio..."
 *  message for the entire 1-5 minute first-run wait. Returns empty
 *  step/detail when no analyze is in flight. */

export async function fetchAudioAnalyzeStatus(): Promise<{ step: string; detail: string }> {
  const res = await fetch(`${BASE}/api/v1/audio/analyze/status`)
  if (!res.ok) return { step: '', detail: '' }
  return res.json()
}

export async function suggestAudioClips(params: {
  analysis: import('../types').AudioAnalysisResult
  clip_duration: number
  total_duration?: number
}): Promise<{ clips: import('../types').SuggestedClip[] }> {
  const res = await fetch(`${BASE}/api/v1/audio/suggest-clips`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Clip suggestion failed' }))
    throw new Error(err.detail || 'Clip suggestion failed')
  }
  return res.json()
}

// --- Director ---

export async function planAnglePrompts(params: {
  style_prompt: string
  num_angles?: number
}): Promise<{ prompts: string[] }> {
  const res = await fetch(`${BASE}/api/v1/director/plan-angle-prompts`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Angle prompt planning failed' }))
    throw new Error(err.detail || 'Angle prompt planning failed')
  }
  return res.json()
}

export async function planClipPrompts(params: {
  clips: import('../types').SuggestedClip[]
  style_prompt: string
  lyrics?: import('../types').LyricSegment[]
  bpm: number
}): Promise<{ prompts: string[] }> {
  const res = await fetch(`${BASE}/api/v1/director/plan-prompts`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Prompt planning failed' }))
    throw new Error(err.detail || 'Prompt planning failed')
  }
  return res.json()
}

export async function planClipStructure(params: {
  analysis: import('../types').AudioAnalysisResult
  energy_bias?: number
  pacing_profile?: 'cinematic' | 'balanced' | 'rhythmic'
  fps?: number
  frames_steps?: number
  frames_minimum?: number
  total_duration?: number
  /** The Director's VIDEO model — the backend resolves fps/frame params
   *  from its model def. The fps/frames_* fields above reflect the
   *  Studio-selected model (possibly a music model) and are only a
   *  fallback when this is absent. */
  video_model?: string
}): Promise<{ clips: import('../types').PlannedClip[] }> {
  const res = await fetch(`${BASE}/api/v1/audio/plan-structure`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Structure planning failed' }))
    throw new Error(err.detail || 'Structure planning failed')
  }
  return res.json()
}

export async function classifySections(params: {
  analysis: import('../types').AudioAnalysisResult
  lyrics_hint?: string
}): Promise<{
  sections: import('../types').AudioSection[]
  song_structure: { label: string; display_label: string; start: number }[]
  method: 'lyrics_hint' | 'llm' | 'heuristic'
}> {
  const res = await fetch(`${BASE}/api/v1/director/classify-sections`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Classification failed' }))
    throw new Error(err.detail || 'Section classification failed')
  }
  return res.json()
}

export async function planClipPromptsAndImages(params: {
  clips: import('../types').PlannedClip[]
  scene_description: string
  lyrics?: import('../types').LyricSegment[]
  bpm: number
  reference_image_path?: string | null
  character_ref_paths?: string[]
  character_ref_labels?: string[]
  location_ref_paths?: string[]
  location_ref_labels?: string[]
  speaker_mappings?: Record<string, { name: string; role: string }>
  prompt_type?: 'image' | 'video' | 'both'
  existing_image_prompts?: string[]
  video_model?: string
  h3_reference_mode?: 'first_frame' | 'references'
  h3_audio_prompt?: string
  music_video_treatment?: import('../types').MusicVideoTreatment
}): Promise<{ clip_plans: import('../types').ClipPlan[] }> {
  const res = await fetch(`${BASE}/api/v1/director/plan-prompts-and-images`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Prompt and image planning failed' }))
    throw new Error(err.detail || 'Prompt and image planning failed')
  }
  return res.json()
}

// --- Short Film Director ---

export async function planDialogueScenes(params: {
  analysis: import('../types').AudioAnalysisResult
  pacing_bias?: number
  fps?: number
  frames_steps?: number
  frames_minimum?: number
}): Promise<{ clips: import('../types').PlannedClip[] }> {
  const res = await fetch(`${BASE}/api/v1/director/plan-dialogue-scenes`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Dialogue scene planning failed' }))
    throw new Error(err.detail || 'Dialogue scene planning failed')
  }
  return res.json()
}

export async function planShortFilmPrompts(params: {
  clips: import('../types').PlannedClip[]
  scene_description: string
  lyrics?: import('../types').LyricSegment[]
  reference_image_path?: string | null
  character_ref_paths?: string[]
  character_ref_labels?: string[]
  location_ref_paths?: string[]
  location_ref_labels?: string[]
  speaker_mappings?: Record<string, { name: string; role: string }>
  characters?: { name: string; description: string }[]
  prompt_type?: 'image' | 'video' | 'both'
  existing_image_prompts?: string[]
  video_model?: string
  h3_reference_mode?: 'first_frame' | 'references'
  h3_audio_prompt?: string
}): Promise<{ clip_plans: import('../types').ClipPlan[] }> {
  const res = await fetch(`${BASE}/api/v1/director/plan-short-film-prompts`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Short film prompt planning failed' }))
    throw new Error(err.detail || 'Short film prompt planning failed')
  }
  return res.json()
}

export async function planShortFilmScript(params: {
  story_description: string
  characters?: { name: string; description: string }[]
  reference_image_path?: string | null
  character_ref_paths?: string[]
  character_ref_labels?: string[]
  location_ref_paths?: string[]
  location_ref_labels?: string[]
  target_duration?: number
  target_scenes?: number
  narrative_mode?: boolean
  fps?: number
  frames_steps?: number
  frames_minimum?: number
  visual_style?: string
  preserve_visual_style?: boolean
  character_visual_style?: string
  allow_clip_text?: boolean
}): Promise<{ clips: import('../types').PlannedClip[]; clip_plans: import('../types').ClipPlan[] }> {
  const res = await fetch(`${BASE}/api/v1/director/plan-short-film-script`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Story planning failed' }))
    throw new Error(err.detail || 'Story planning failed')
  }
  return res.json()
}
