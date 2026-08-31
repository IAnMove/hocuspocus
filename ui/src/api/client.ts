import { rememberPrompt } from '../lib/promptHistory'
import { openCanonicalTaskEventStream } from '../lib/canonicalTaskEvents'
import type { CanonicalTaskEvent, CanonicalTaskStreamState } from '../lib/canonicalTaskEvents'
import type { SeriesAssemblyActionRequest, SeriesAssemblyDiscardResponse, SeriesAssemblyJob, SeriesAssemblyRecoveryResponse, SeriesAssemblyStartRequest } from '../features/series/assemblyContract'
import { isDirectorV2PlanFailureDetail, isDirectorV2PlanResponse } from '../types'
import type { DirectorModelCompatibility, DirectorV2PlanFailureDetail, DirectorV2PlanJob, DirectorV2PlanProgress, DirectorV2PlanRequest, DirectorV2PlanResponse, GenerationDetails, H3WindowPlan, ScailResolutionProfile } from '../types'

const BASE = ''  // same origin in production; Vite proxy handles /api in dev

export interface ApiModel {
  model_type: string
  name: string
  description?: string
  selector_help?: string
  lora_compatibility_note?: string
  family: string
  architecture: string
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

export interface ApiOutput {
  name: string
  type: 'video' | 'image' | 'audio' | 'model3d' | 'scene' | 'comic'
  mode: string | null
  favorite?: boolean
  size: number
  created_at: number
  /** Time the generated asset was fully published. Older/imported assets
   *  fall back to the media file's modification time. */
  completed_at?: number
  completion_time_source?: 'metadata' | 'file'
  url: string
  /** Small static preview for image/video cards and saved 3D/scene assets. */
  thumbnail_url?: string | null
  /** Edit-mode sub-classification (retake / inpaint / outpaint / restyle /
   *  edit_anything). Field added as a recovery stub after a git
   *  filter-repo reset wiped the original Stream C/D work that
   *  introduced it. Optional so the type compiles even when the
   *  backend hasn't been updated to emit this yet. */
  edit_sub_mode?: string | null
  result_kind?: 'music_video' | 'trailer' | 'series_episode' | 'chapter' | null
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

export type CanonicalTaskStatus =
  | 'created' | 'queued' | 'waiting_resource' | 'running'
  | 'completed' | 'failed' | 'cancelled' | 'interrupted'

export interface CanonicalTask {
  id: string
  root_id: string
  parent_id?: string | null
  kind: string
  title: string
  workflow: string
  status: CanonicalTaskStatus
  phase: string
  message: string
  detail?: string
  current: number
  total: number
  progress: number
  detail_current: number
  detail_total: number
  created_at: number
  queued_at?: number | null
  started_at?: number | null
  updated_at: number
  completed_at?: number | null
  provider?: string
  model?: string
  server_origin?: string
  resource_requirements?: string[]
  acquired_resources?: string[]
  attempt: number
  max_attempts: number
  token_usage?: { prompt?: number; completion?: number; total?: number; calls?: number }
  backend_job_id?: string
  pipeline_id?: string
  cancelable: boolean
  resumable: boolean
  recoverable: boolean
  error?: { message?: string; retryable?: boolean } | null
  result_refs?: string[]
  metadata?: Record<string, unknown>
}

export async function fetchCanonicalTasks(
  workspace: string,
  status: 'active' | 'all' = 'all',
): Promise<{ workspace: string; tasks: CanonicalTask[]; latest_event_id: number }> {
  const query = new URLSearchParams({ workspace, status, limit: '300' })
  const res = await fetch(`${BASE}/api/v1/tasks?${query}`)
  if (!res.ok) throw new Error('Failed to fetch HocusPocus tasks')
  return res.json()
}

export function subscribeCanonicalTaskEvents(
  workspace: string,
  onEvent: (event: CanonicalTaskEvent) => void,
  onError?: () => void,
  onStateChange?: (state: CanonicalTaskStreamState) => void,
  initialEventId = 0,
): () => void {
  return openCanonicalTaskEventStream(BASE, workspace, onEvent, onError, onStateChange, {
    initialEventId,
  })
}

export async function upsertCanonicalClientTask(task: Record<string, unknown>): Promise<CanonicalTask> {
  const clientTaskId = canonicalClientTaskId(task.id)
  const canonicalTask: Record<string, unknown> = { ...task, id: clientTaskId }
  delete canonicalTask.root_id
  delete canonicalTask.rootId
  const res = await fetch(`${BASE}/api/v1/tasks/upsert`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ task: canonicalTask }),
  })
  if (!res.ok) throw new Error('Failed to publish HocusPocus activity')
  return res.json()
}

/** Keep frontend activity ids inside the namespace reserved for client tasks. */
export function canonicalClientTaskId(value: unknown): string {
  let normalized = String(value ?? '').replace(/[^A-Za-z0-9_-]+/g, '-').replace(/^-+|-+$/g, '')
  while (normalized.startsWith('task-client-')) {
    normalized = normalized.slice('task-client-'.length).replace(/^-+/, '')
  }
  if (!normalized) {
    const uniquePart = globalThis.crypto?.randomUUID?.()
      || `${Date.now()}-${Math.random().toString(36).slice(2)}`
    normalized = `activity-${uniquePart}`
  }
  return `task-client-${normalized.slice(0, 160)}`
}

export async function cancelCanonicalTask(taskId: string, workspace: string): Promise<CanonicalTask> {
  const res = await fetch(`${BASE}/api/v1/tasks/${encodeURIComponent(taskId)}/cancel?workspace=${encodeURIComponent(workspace)}`, { method: 'POST' })
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: 'Task cancellation failed' }))
    throw new Error(error.detail || 'Task cancellation failed')
  }
  const payload = await res.json()
  return payload.task
}

export async function resumeCanonicalTask(taskId: string, workspace: string): Promise<CanonicalTask> {
  const res = await fetch(`${BASE}/api/v1/tasks/${encodeURIComponent(taskId)}/resume?workspace=${encodeURIComponent(workspace)}`, { method: 'POST' })
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: 'Task resume failed' }))
    throw new Error(error.detail || 'Task resume failed')
  }
  const payload = await res.json()
  return payload.task
}

export async function retryCanonicalTask(taskId: string, workspace: string): Promise<CanonicalTask> {
  const res = await fetch(`${BASE}/api/v1/tasks/${encodeURIComponent(taskId)}/retry?workspace=${encodeURIComponent(workspace)}`, { method: 'POST' })
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: 'Task retry failed' }))
    throw new Error(error.detail || 'Task retry failed')
  }
  const payload = await res.json()
  return payload.task
}

export async function dismissCanonicalTask(taskId: string, workspace: string): Promise<void> {
  const res = await fetch(`${BASE}/api/v1/tasks/${encodeURIComponent(taskId)}?workspace=${encodeURIComponent(workspace)}`, { method: 'DELETE' })
  if (!res.ok) throw new Error('Failed to dismiss HocusPocus task')
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

export async function planH3Windows(params: {
  prompt: string
  model_type: string
  resolution: string
  total_frames: number
  window_frames: number
  overlap_frames: number
  discard_frames: number
  sliding_window_memory_override?: boolean
  has_start_image?: boolean
  has_end_image?: boolean
  image_paths?: string[]
}): Promise<H3WindowPlan> {
  const res = await fetch(`${BASE}/api/v1/llm/plan-h3-windows`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'H3 window planning failed' }))
    throw new Error(err.detail || 'H3 window planning failed')
  }
  return res.json()
}

export async function fetchJobStatus(jobId: string): Promise<ApiJobStatus> {
  const res = await fetch(`${BASE}/api/v1/status/${encodeURIComponent(jobId)}`)
  if (!res.ok) throw new Error('Failed to fetch job status')
  return res.json()
}

// --- Music: LLM song writer (Music mode Simple) ---

export async function writeSong(params: {
  description: string
  instrumental?: boolean
  target?: 'ace-step' | 'minimax'
  model?: 'music-3.0' | 'music-2.6' | 'music-cover' | 'ace_step_v1_5_xl_sft_lm_4b'
  reference_song?: string
  style_direction?: string
  lyrics_direction?: string
  story_context?: string
  language?: string
  duration_seconds?: number
  seed?: number
  reference_image_path?: string
  include_lyria?: boolean
  max_new_tokens?: number
  writingProvider?: import('../features/stories/types').StoryWritingProvider
  writingModel?: string
  writingBaseUrl?: string
}): Promise<{ style: string; lyrics: string; lyria_prompt: string; warnings?: string[]; raw: string }> {
  const res = await fetch(`${BASE}/api/v1/llm/write-song`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Song writing failed' }))
    throw new Error(err.detail || 'Song writing failed')
  }
  return res.json()
}

export interface MiniMaxMusicCandidate {
  filename: string
  audio_path: string
  source: string
  duration_seconds: number
  provider: 'minimax'
  model: string
  task_id?: string
  root_task_id?: string
  taskId?: string
  rootTaskId?: string
}

export interface MiniMaxMusicJob {
  jobId: string
  taskId: string
  rootTaskId: string
  workspace: string
  status: 'queued' | 'waiting_resource' | 'running' | 'cancelling' | 'completed' | 'failed' | 'cancelled' | 'interrupted'
  phase: string
  message: string
  current: number
  total: number
  progress: number
  provider: 'minimax'
  model: string
  candidates: MiniMaxMusicCandidate[]
  error?: string | null
  statusCode?: number
}

export interface StoryMusicCandidateRequest {
  prompt: string
  lyrics: string
  count: 1 | 2 | 3
  model?: 'music-3.0' | 'music-2.6' | 'music-cover' | 'ace_step_v1_5_xl_sft_lm_4b'
  reference_audio_filename?: string
  instrumental?: boolean
  workspace?: string
}

export async function startStoryMusicCandidatesJob(
  params: StoryMusicCandidateRequest,
): Promise<MiniMaxMusicJob> {
  const res = await fetch(`${BASE}/api/v1/stories/music-candidates/jobs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: 'MiniMax Music generation failed' }))
    throw new Error(error.detail || 'MiniMax Music generation failed')
  }
  return res.json()
}

export async function fetchStoryMusicCandidatesJob(jobId: string): Promise<MiniMaxMusicJob> {
  const res = await fetch(
    `${BASE}/api/v1/stories/music-candidates/jobs/${encodeURIComponent(jobId)}`,
  )
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: 'MiniMax Music job not found' }))
    throw new Error(error.detail || 'MiniMax Music job not found')
  }
  return res.json()
}

export async function cancelStoryMusicCandidatesJob(jobId: string): Promise<MiniMaxMusicJob> {
  const res = await fetch(
    `${BASE}/api/v1/stories/music-candidates/jobs/${encodeURIComponent(jobId)}/cancel`,
    { method: 'POST' },
  )
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: 'MiniMax Music cancellation failed' }))
    throw new Error(error.detail || 'MiniMax Music cancellation failed')
  }
  return res.json()
}

export async function generateStoryMusicCandidates(
  params: StoryMusicCandidateRequest,
  options: {
    onJobSubmitted?: (job: MiniMaxMusicJob) => void
    onProgress?: (job: MiniMaxMusicJob) => void
  } = {},
): Promise<{
  candidates: MiniMaxMusicCandidate[]
  status: 'completed' | 'cancelled' | 'failed' | 'interrupted'
  jobId: string
  taskId: string
  message: string
}> {
  let job = await startStoryMusicCandidatesJob(params)
  options.onJobSubmitted?.(job)
  let pollFailures = 0
  while (!['completed', 'failed', 'cancelled', 'interrupted'].includes(job.status)) {
    await new Promise(resolve => window.setTimeout(resolve, pollFailures ? Math.min(10_000, pollFailures * 1_500) : 1_000))
    try {
      job = await fetchStoryMusicCandidatesJob(job.jobId)
      pollFailures = 0
      options.onProgress?.(job)
    } catch (error) {
      pollFailures += 1
      if (pollFailures >= 20) {
        throw new Error(
          `Could not reconnect to MiniMax Music job ${job.jobId}; its ID was preserved: ${(error as Error).message}`,
        )
      }
    }
  }
  if (job.status === 'completed' || job.candidates.length > 0) {
    return {
      candidates: job.candidates,
      status: job.status as 'completed' | 'cancelled' | 'failed' | 'interrupted',
      jobId: job.jobId,
      taskId: job.taskId,
      message: job.message,
    }
  }
  throw new Error(
    `${job.statusCode ? `HTTP ${job.statusCode}: ` : ''}`
    + (job.error || job.message || `MiniMax Music job ${job.status}`),
  )
}

export async function translateStoryLyrics(params: {
  lyrics: string
  targetLanguage: string
  writingProvider: import('../features/stories/types').StoryWritingProvider
  writingModel?: string
  writingBaseUrl?: string
}): Promise<{ lyrics: string; targetLanguage: string }> {
  const res = await fetch(`${BASE}/api/v1/stories/translate-lyrics`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: 'Lyric translation failed' }))
    throw new Error(error.detail || 'Lyric translation failed')
  }
  return res.json()
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
  workspace?: string
}): Promise<{ audio_path: string; filename: string; style: string; lyrics: string }> {
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

// --- Tools: standalone post-processing on an existing clip ---

export async function submitToolUpscale(params: {
  video_path: string
  method?: string
  seed?: number
  workspace?: string
}): Promise<{ job_id: string }> {
  const res = await fetch(`${BASE}/api/v1/tools/upscale`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
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

// --- Workspaces ---

export interface Workspace {
  name: string
  path: string
  file_count?: number
}

export async function fetchWorkspaces(): Promise<{ workspaces: Workspace[]; active: string }> {
  const res = await fetch(`${BASE}/api/v1/workspaces`)
  if (!res.ok) throw new Error('Failed to fetch workspaces')
  return res.json()
}

export async function setActiveWorkspace(name: string): Promise<void> {
  const res = await fetch(`${BASE}/api/v1/workspaces/active`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  })
  if (!res.ok) throw new Error('Failed to switch workspace')
}

export async function createWorkspace(name: string): Promise<void> {
  const res = await fetch(`${BASE}/api/v1/workspaces`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Failed to create workspace' }))
    throw new Error(err.detail || 'Failed to create workspace')
  }
}

export async function deleteWorkspace(name: string): Promise<{ switched_to_default: boolean; files_deleted: number }> {
  const res = await fetch(`${BASE}/api/v1/workspaces/${encodeURIComponent(name)}`, { method: 'DELETE' })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Failed to delete workspace' }))
    throw new Error(err.detail || 'Failed to delete workspace')
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

// --- Move to Workspace ---

export async function moveOutput(name: string, workspace: string): Promise<void> {
  const res = await fetch(`${BASE}/api/v1/outputs/${encodeURIComponent(name)}/move`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ workspace }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Move failed' }))
    throw new Error(err.detail || 'Move failed')
  }
}

// --- Favorites ---

export async function toggleFavorite(name: string): Promise<{ name: string; favorite: boolean }> {
  const res = await fetch(`${BASE}/api/v1/favorites/${encodeURIComponent(name)}`, { method: 'POST' })
  if (!res.ok) throw new Error('Failed to toggle favorite')
  return res.json()
}

// --- Outputs ---

export async function fetchOutputs(limit = 0, offset = 0, opts?: { favoritesOnly?: boolean; multiclipOnly?: boolean; editsOnly?: boolean; search?: string; workspace?: string; mediaType?: ApiOutput['type']; resultKind?: ApiOutput['result_kind']; signal?: AbortSignal }): Promise<{ outputs: ApiOutput[]; total: number }> {
  const params = new URLSearchParams()
  if (limit > 0) params.set('limit', String(limit))
  if (offset > 0) params.set('offset', String(offset))
  if (opts?.favoritesOnly) params.set('favorites_only', 'true')
  if (opts?.multiclipOnly) params.set('multiclip_only', 'true')
  if (opts?.editsOnly) params.set('edits_only', 'true')
  if (opts?.resultKind) params.set('result_kind', opts.resultKind)
  if (opts?.search) params.set('search', opts.search)
  // "__uploads__" browses the uploads folder (virtual Uploads view)
  if (opts?.workspace) params.set('workspace', opts.workspace)
  if (opts?.mediaType) params.set('media_type', opts.mediaType)
  const qs = params.toString()
  const res = await fetch(`${BASE}/api/v1/outputs${qs ? '?' + qs : ''}`, { cache: 'no-store', signal: opts?.signal })
  if (!res.ok) throw new Error('Failed to fetch outputs')
  const data = await res.json()
  return { outputs: data.outputs, total: data.total ?? data.outputs.length }
}

export async function saveScene(scene: import('../types').Scene, preview: string, workspace?: string): Promise<{ name: string; type: 'scene'; url: string; thumbnail_url: string }> {
  const res = await fetch(`${BASE}/api/v1/scenes`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ scene, preview, workspace }),
  })
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: 'Failed to save scene' }))
    throw new Error(error.detail || 'Failed to save scene')
  }
  return res.json()
}

export async function fetchCharacterKitLibrary(workspace: string): Promise<import('../lib/characterKit').CharacterKitLibrary> {
  const response = await fetch(`${BASE}/api/v1/character-kits/library?workspace=${encodeURIComponent(workspace)}`)
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Could not load Character Kits' }))
    throw new Error(typeof error.detail === 'string' ? error.detail : 'Could not load Character Kits')
  }
  return response.json()
}

export async function saveCharacterKit(
  workspace: string,
  library: import('../lib/characterKit').CharacterKitLibrary,
  kit: import('../lib/characterKit').CharacterKit,
): Promise<import('../lib/characterKit').CharacterKitLibrary> {
  const response = await fetch(`${BASE}/api/v1/character-kits/library/kits/${encodeURIComponent(kit.id)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ workspace, baseRevision: library.revision, kit, makeActive: true }),
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Could not save Character Kit' }))
    const detail = error.detail
    throw new Error(typeof detail === 'string' ? detail : typeof detail?.message === 'string' ? detail.message : 'Could not save Character Kit')
  }
  return response.json()
}

export async function deleteCharacterKit(
  workspace: string,
  library: import('../lib/characterKit').CharacterKitLibrary,
  kitId: string,
): Promise<import('../lib/characterKit').CharacterKitLibrary> {
  const response = await fetch(`${BASE}/api/v1/character-kits/library/kits/${encodeURIComponent(kitId)}`, {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ workspace, baseRevision: library.revision }),
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Could not delete Character Kit' }))
    const detail = error.detail
    throw new Error(typeof detail === 'string' ? detail : typeof detail?.message === 'string' ? detail.message : 'Could not delete Character Kit')
  }
  return response.json()
}

export async function cleanCharacterKitFaceOverlay(details: {
  workspace: string
  source: string
  padding?: number
}): Promise<import('../lib/characterKitFaceRig').FaceRigCleanupResult> {
  const response = await fetch(`${BASE}/api/v1/character-kits/face-rig/cleanup`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      workspace: details.workspace,
      source: details.source,
      padding: details.padding ?? 8,
    }),
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Could not clean Face Rig overlay' }))
    const detail = error.detail
    throw new Error(typeof detail === 'string' ? detail : 'Could not clean Face Rig overlay')
  }
  return response.json()
}

export async function saveSceneRecording(
  recording: Blob,
  details: {
    scene: import('../types').Scene
    prompt: string
    recipe: Record<string, unknown> | null
  workspace?: string
  },
): Promise<ApiOutput> {
  const form = new FormData()
  const extension = recording.type.includes('mp4') ? 'mp4' : 'webm'
  form.append('file', recording, `${details.scene.name || '3d-scene'}.${extension}`)
  form.append('metadata', JSON.stringify(details))
  const res = await fetch(`${BASE}/api/v1/scenes/recordings`, {
    method: 'POST',
    body: form,
  })
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: 'Failed to save MP4 recording' }))
    throw new Error(error.detail || 'Failed to save MP4 recording')
  }
  return res.json()
}

export function getFileUrl(filename: string, workspace?: string): string {
  const query = workspace ? `?workspace=${encodeURIComponent(workspace)}` : ''
  return `${BASE}/api/v1/file/${encodeURIComponent(filename)}${query}`
}

export function getOutputThumbnailUrl(filename: string, workspace?: string): string {
  const query = workspace ? `?workspace=${encodeURIComponent(workspace)}` : ''
  return `${BASE}/api/v1/outputs/thumbnail/${encodeURIComponent(filename)}${query}`
}

export function getUploadUrl(filename: string): string {
  return `${BASE}/api/v1/uploads/${encodeURIComponent(filename)}`
}

function storedAssetFilename(pathOrFilename: string): string {
  const normalized = String(pathOrFilename || '').replace(/\\/g, '/')
  const withoutQuery = normalized.split(/[?#]/, 1)[0]
  const encodedName = withoutQuery.split('/').pop() || ''
  try {
    return decodeURIComponent(encodedName)
  } catch {
    return encodedName
  }
}

/**
 * Resolve a persisted sidecar path to the endpoint that actually owns it.
 *
 * Director-generated conditioning frames live in outputs, while files the
 * user selected live in uploads. Older restore code discarded the directory
 * and sent every basename to /uploads, which made generated comic frames 404.
 */
export function getStoredAssetUrl(pathOrFilename: string): string {
  const normalized = String(pathOrFilename || '').replace(/\\/g, '/')
  const filename = storedAssetFilename(normalized)
  const isUpload = normalized.startsWith('/api/v1/uploads/')
    || /(^|\/)uploads\//i.test(normalized)
  return isUpload ? getUploadUrl(filename) : getFileUrl(filename)
}

/**
 * Fetch a stored asset with a compatibility fallback for old sidecars that
 * persisted only a basename and therefore lost whether it came from uploads
 * or outputs.
 */
export async function fetchStoredAsset(pathOrFilename: string): Promise<Response> {
  const filename = storedAssetFilename(pathOrFilename)
  const primary = getStoredAssetUrl(pathOrFilename)
  const fallback = primary === getFileUrl(filename)
    ? getUploadUrl(filename)
    : getFileUrl(filename)
  const first = await fetch(primary)
  if (first.ok || primary === fallback) return first
  return fetch(fallback)
}

export async function fetchOutputMetadata(
  name: string,
  workspace?: string,
  signal?: AbortSignal,
): Promise<import('../types').OutputMetadata> {
  // Retry with a per-attempt timeout. On a slow/high-latency link (e.g. the user
  // is remote over VPN) the request can stall long enough that a single attempt
  // hangs or is dropped by an intermediary; the old single-shot fetch then left
  // the caller with no metadata and the "Load Settings" button a silent no-op.
  const workspaceQuery = workspace
    ? `?workspace=${encodeURIComponent(workspace)}`
    : ''
  const url = `${BASE}/api/v1/outputs/${encodeURIComponent(name)}/metadata${workspaceQuery}`
  const ATTEMPTS = 3
  const PER_ATTEMPT_MS = 30000  // generous: the server may read embedded video metadata to recover a seed
  let lastErr: unknown = null
  for (let attempt = 0; attempt < ATTEMPTS; attempt++) {
    if (signal?.aborted) throw new DOMException('Metadata request aborted', 'AbortError')
    const controller = new AbortController()
    const abortFromCaller = () => controller.abort()
    signal?.addEventListener('abort', abortFromCaller, { once: true })
    const timer = setTimeout(() => controller.abort(), PER_ATTEMPT_MS)
    try {
      const res = await fetch(url, { signal: controller.signal })
      if (!res.ok) return { source: 'none', params: null }
      return await res.json()
    } catch (e) {
      lastErr = e
      if (signal?.aborted) throw e
      // Diagnostic: AbortError = our per-attempt timeout fired (link too slow);
      // TypeError = network failure / dropped connection. Helps pinpoint a
      // "Load Settings does nothing over VPN" report.
      console.warn(`[LoadSettings] fetchOutputMetadata attempt ${attempt + 1}/${ATTEMPTS} failed:`,
                   (e as { name?: string })?.name || e)
      if (attempt < ATTEMPTS - 1) {
        await new Promise(r => setTimeout(r, 400 * (attempt + 1)))  // brief backoff before retry
      }
    } finally {
      clearTimeout(timer)
      signal?.removeEventListener('abort', abortFromCaller)
    }
  }
  throw lastErr  // all attempts failed — loadOutputMetadata's catch sets meta null
}

// --- Style sheet library ---

export interface StyleAttribution {
  id: string
  type: string
  author: string
  name: string
  url: string
  repoId: string
  modelFamily: string
  collection: string
  license: string | null
  licenseNotice?: string
  description: string
  expectedStyles: number
  expectedBytes: number
  revision?: string | null
  lastModified?: string | null
}

export interface StyleSource extends StyleAttribution {
  installed: boolean
  styleCount: number
  downloadedFiles: number
  downloadedBytes: number
  activeJob?: StyleImportJob | null
  latestJob?: StyleImportJob | null
  storagePath?: string
  storageNotice?: string | null
}

export interface StyleLibraryItem {
  id: string
  modelFamily: string
  title: string
  prompt: string
  collection: string
  group: string
  tags: string[]
  sourceOrder: number
  sourceFilename: string
  videoFilename: string
  source: StyleAttribution
  importedAt: number
  previewUrl: string
  videoUrl: string
}

export interface StyleImportJob {
  jobId: string
  status: 'queued' | 'running' | 'cancelling' | 'cancelled' | 'completed' | 'failed' | 'interrupted'
  stage: 'queued' | 'downloading' | 'indexing' | 'previews' | 'cancelling' | 'cancelled' | 'completed' | 'failed' | 'interrupted'
  current: number
  total: number
  message: string
  downloadedBytes: number
  expectedBytes: number
  error?: string | null
  storagePath?: string
  preflight?: StyleImportPreflight
  cancelRequestedAt?: number | null
  resumeAvailable?: boolean
  resumed?: boolean
  resumeCount?: number
  source: StyleAttribution
}

export interface StyleImportPreflight {
  storagePath: string
  probePath: string
  downloadedFiles: number
  downloadedBytes: number
  expectedBytes: number
  remainingBytes: number
  marginBytes: number
  requiredBytes: number
  freeBytes: number
  sufficient: boolean
}

export interface StyleLibraryPage {
  styles: StyleLibraryItem[]
  total: number
  offset: number
  limit: number
  facets: { sources: string[]; collections: string[]; groups: string[] }
}

export async function fetchStyleSources(): Promise<StyleSource[]> {
  const res = await fetch(`${BASE}/api/v1/style-library/sources`, { cache: 'no-store' })
  if (!res.ok) throw new Error('Could not load style sources')
  const data = await res.json()
  return data.sources || []
}

export async function fetchStyleLibrary(params: {
  modelFamily?: string
  sourceId?: string
  collection?: string
  group?: string
  query?: string
  sort?: string
  offset?: number
  limit?: number
} = {}): Promise<StyleLibraryPage> {
  const query = new URLSearchParams()
  if (params.modelFamily) query.set('model_family', params.modelFamily)
  if (params.sourceId) query.set('source_id', params.sourceId)
  if (params.collection) query.set('collection', params.collection)
  if (params.group) query.set('group', params.group)
  if (params.query) query.set('q', params.query)
  if (params.sort) query.set('sort', params.sort)
  if (params.offset) query.set('offset', String(params.offset))
  if (params.limit) query.set('limit', String(params.limit))
  const res = await fetch(`${BASE}/api/v1/style-library/styles?${query.toString()}`, { cache: 'no-store' })
  if (!res.ok) throw new Error('Could not load styles')
  return res.json()
}

export async function startMiniMaxStyleImport(): Promise<StyleImportJob> {
  const res = await fetch(`${BASE}/api/v1/style-library/imports/minimax-h3-1k`, { method: 'POST' })
  if (!res.ok) {
    const payload = await res.json().catch(() => null)
    const detail = payload?.detail
    throw new Error(
      (typeof detail === 'object' && detail?.message)
      || (typeof detail === 'string' && detail)
      || 'Could not start the MiniMax style download',
    )
  }
  return res.json()
}

export async function fetchStyleImport(jobId: string): Promise<StyleImportJob> {
  const res = await fetch(`${BASE}/api/v1/style-library/imports/${encodeURIComponent(jobId)}`, { cache: 'no-store' })
  if (!res.ok) throw new Error('Could not load style import progress')
  return res.json()
}

export async function cancelStyleImport(jobId: string): Promise<StyleImportJob> {
  const res = await fetch(`${BASE}/api/v1/style-library/imports/${encodeURIComponent(jobId)}/cancel`, {
    method: 'POST',
  })
  if (!res.ok) throw new Error('Could not cancel the style import')
  return res.json()
}

export async function deleteStyle(styleId: string): Promise<{ id: string; deleted: boolean }> {
  const res = await fetch(`${BASE}/api/v1/style-library/styles/${encodeURIComponent(styleId)}?confirm=true`, {
    method: 'DELETE',
  })
  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: 'Could not delete style' }))
    throw new Error(detail.detail || 'Could not delete style')
  }
  return res.json()
}

export async function fetchVideoExtraInfo(
  name: string,
  language: string,
): Promise<import('../types').VideoExtraInfoStatus> {
  const res = await fetch(
    `${BASE}/api/v1/outputs/${encodeURIComponent(name)}/extra-info?language=${encodeURIComponent(language)}`,
    { cache: 'no-store' },
  )
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: 'Failed to load extra info' }))
    throw new Error(error.detail || 'Failed to load extra info')
  }
  return res.json()
}

export async function generateVideoExtraInfo(
  name: string,
  language: string,
  regenerate = false,
): Promise<{ cached: boolean; data: import('../types').VideoExtraInfo }> {
  const res = await fetch(`${BASE}/api/v1/outputs/${encodeURIComponent(name)}/extra-info`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ language, regenerate }),
  })
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: 'Failed to generate extra info' }))
    throw new Error(error.detail || 'Failed to generate extra info')
  }
  return res.json()
}

export async function deleteOutput(name: string): Promise<void> {
  const res = await fetch(`${BASE}/api/v1/outputs/${encodeURIComponent(name)}`, { method: 'DELETE' })
  if (!res.ok) throw new Error('Failed to delete output')
}

export async function rejoinClips(groupId: string, audioFile?: string): Promise<{ filename: string; clip_count: number }> {
  const res = await fetch(`${BASE}/api/v1/outputs/rejoin`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ group_id: groupId, audio_file: audioFile }),
  })
  if (!res.ok) throw new Error('Failed to rejoin clips')
  return res.json()
}

export interface VideoEditorProbe {
  duration: number
  width: number
  height: number
  fps: number
  has_audio: boolean
  pixel_format: string
  has_alpha: boolean
}

export interface VideoEditorExportJob {
  job_id: string
  task_id?: string | null
  root_task_id?: string | null
  workspace?: string
  status: 'queued' | 'waiting_resource' | 'running' | 'cancelling' | 'completed' | 'failed' | 'cancelled'
  phase?: string
  progress: number
  message: string
  filename: string | null
  url: string | null
  error: string | null
  acquired_resources?: string[]
  cancel_mode?: 'immediate' | 'deferred' | string
  safe_boundary?: string
  result?: { duration: number; clip_count: number }
}

export async function probeVideoEditorClip(source: string, workspace?: string): Promise<VideoEditorProbe> {
  const res = await fetch(`${BASE}/api/v1/video-editor/probe`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ source, workspace: workspace || undefined }),
  })
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: 'Could not inspect video' }))
    throw new Error(error.detail || 'Could not inspect video')
  }
  return res.json()
}

export async function probeVideoEditorAudio(source: string, workspace?: string): Promise<{ duration: number; has_audio: boolean }> {
  const res = await fetch(`${BASE}/api/v1/video-editor/probe-audio`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ source, workspace }),
  })
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: 'Could not inspect audio' }))
    throw new Error(error.detail || 'Could not inspect audio')
  }
  return res.json()
}

export function getVideoEditorThumbnailUrl(source: string): string {
  const params = new URLSearchParams({ source })
  return `${BASE}/api/v1/video-editor/thumbnail?${params.toString()}`
}

export interface VideoEditorScreenshot {
  filename: string
  url: string
  time: number
  width: number
  height: number
}

export async function captureVideoEditorFrame(payload: {
  source: string
  time: number
  name: string
  workspace?: string
}): Promise<VideoEditorScreenshot> {
  const res = await fetch(`${BASE}/api/v1/video-editor/screenshot`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: 'Could not capture video frame' }))
    throw new Error(error.detail || 'Could not capture video frame')
  }
  return res.json()
}

export async function startVideoEditorExport(payload: {
  name: string
  width: number
  height: number
  fps: number
  workspace?: string
  soundtrack?: {
    name: string
    source: string
    trim_start: number
    trim_end: number
    volume: number
    loop: boolean
  } | null
  clips: Array<{
    name: string
    source: string
    trim_start: number
    trim_end: number
    volume: number
    muted: boolean
    fit: 'fit' | 'fill'
    transition:
      | 'none'
      | 'crossfade'
      | 'fade-black'
      | 'wipe-left'
      | 'slide-left'
      | 'slide-right'
      | 'circle-open'
      | 'dissolve'
      | 'pixelize'
      | 'blur'
      | 'zoom-in'
      | 'later-clock'
      | 'later-tropical'
      | 'later-cinematic'
    transition_duration: number
    transition_text: string
    transition_text_size: number
  }>
}): Promise<VideoEditorExportJob> {
  const res = await fetch(`${BASE}/api/v1/video-editor/export`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: 'Could not start export' }))
    throw new Error(error.detail || 'Could not start export')
  }
  return res.json()
}

export async function fetchVideoEditorExport(jobId: string): Promise<VideoEditorExportJob> {
  const res = await fetch(`${BASE}/api/v1/video-editor/export/${encodeURIComponent(jobId)}`)
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: 'Could not read export status' }))
    throw new Error(error.detail || 'Could not read export status')
  }
  return res.json()
}

export async function cancelVideoEditorExport(jobId: string): Promise<VideoEditorExportJob> {
  const res = await fetch(`${BASE}/api/v1/video-editor/export/${encodeURIComponent(jobId)}/cancel`, {
    method: 'POST',
  })
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: 'Could not cancel export' }))
    throw new Error(error.detail || 'Could not cancel export')
  }
  return res.json()
}

export async function startComicAnimatic(payload: {
  comic_id: string
  comic_title: string
  width: number
  height: number
  fps: number
  transition: string
  transition_duration: number
  workspace?: string
  panels: Array<{
    source: string
    page_number: number
    panel_number: number
    duration: number
    motion: string
    script: string
  }>
}): Promise<VideoEditorExportJob> {
  const res = await fetch(`${BASE}/api/v1/comics/animatic`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: 'Could not start comic animatic' }))
    throw new Error(error.detail || 'Could not start comic animatic')
  }
  return res.json()
}

export async function fetchGroupClips(groupId: string): Promise<{ group_id: string; clips: Array<{ filename: string; index: number; total: number; prompt: string }> }> {
  const res = await fetch(`${BASE}/api/v1/outputs/group/${encodeURIComponent(groupId)}`)
  if (!res.ok) throw new Error('Failed to fetch group clips')
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

// ── Recipes ──────────────────────────────────────────────────────────────

export interface RecipeLora {
  filename: string
  multiplier: string | number
  source_url?: string
  size_mb?: number
}

export interface RecipeCard {
  id: string
  name: string
  description: string
  mode: string
  model_type: string
  lora_count: number
  prompt_example: string
  nsfw: boolean
  source: 'bundled' | 'user'
  thumbnail_url: string | null
}

export interface Recipe extends RecipeCard {
  loras: RecipeLora[]
  params: Record<string, unknown>
}

export async function fetchRecipes(): Promise<{ recipes: RecipeCard[] }> {
  const res = await fetch(`${BASE}/api/v1/recipes`)
  if (!res.ok) throw new Error('Failed to load recipes')
  return res.json()
}

export async function fetchRecipe(id: string): Promise<Recipe> {
  const res = await fetch(`${BASE}/api/v1/recipes/${encodeURIComponent(id)}`)
  if (!res.ok) throw new Error('Recipe not found')
  return res.json()
}

export async function saveRecipeFromOutput(body: {
  output_name: string; name: string; description?: string; nsfw?: boolean
}): Promise<RecipeCard> {
  const res = await fetch(`${BASE}/api/v1/recipes/save-from-output`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Save failed' }))
    throw new Error(err.detail || 'Save failed')
  }
  return res.json()
}

export async function importRecipe(recipe: Record<string, unknown>): Promise<RecipeCard> {
  const res = await fetch(`${BASE}/api/v1/recipes/import`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(recipe),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Import failed' }))
    throw new Error(err.detail || 'Import failed')
  }
  return res.json()
}

export async function deleteRecipe(id: string): Promise<void> {
  const res = await fetch(`${BASE}/api/v1/recipes/${encodeURIComponent(id)}`, { method: 'DELETE' })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Delete failed' }))
    throw new Error(err.detail || 'Delete failed')
  }
}

// ── System preflight ─────────────────────────────────────────────────────

export interface PreflightCheck {
  id: string
  level: 'error' | 'warn'
  message: string
}

export async function fetchPreflight(): Promise<{ ok: boolean; checks: PreflightCheck[] }> {
  const res = await fetch(`${BASE}/api/v1/system/preflight`)
  if (!res.ok) throw new Error('preflight failed')
  return res.json()
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

// --- LoRAs ---

export async function fetchLoras(modelType: string): Promise<{ loras: string[]; guidance_max_phases: number }> {
  const res = await fetch(`${BASE}/api/v1/loras/${encodeURIComponent(modelType)}`)
  if (!res.ok) throw new Error('Failed to fetch loras')
  return res.json()
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

export interface StoryAssetSuggestion {
  index: number
  kind: import('../features/stories/types').StoryAssetKind
  targetId: string
  name: string
  nameOriginal: string
  description: string
  visualPrompt: string
  confidence: number
  reason: string
  source: string
}

export async function analyzeStoryAssets(params: {
  assets: Array<{ name: string; path: string; url: string }>
  description: string
  project: import('../features/stories/types').StoryProject
  writingProvider: import('../features/stories/types').StoryWritingProvider
  writingModel: string
  writingBaseUrl: string
  activity_id: string
}): Promise<{ assets: StoryAssetSuggestion[] }> {
  const response = await fetch(`${BASE}/api/v1/stories/assets/analyze`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Smart asset analysis failed' }))
    throw new Error(error.detail || 'Smart asset analysis failed')
  }
  return response.json()
}

// --- Comics ---

export async function saveComicProject(
  project: import('../features/comics/types').ComicProject,
  preview?: string,
  existingName?: string | null,
): Promise<{ name: string; type: 'comic'; url: string; thumbnail_url: string }> {
  const method = existingName ? 'PUT' : 'POST'
  const url = existingName
    ? `${BASE}/api/v1/comics/${encodeURIComponent(existingName)}`
    : `${BASE}/api/v1/comics`
  const res = await fetch(url, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project, preview }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Failed to save comic' }))
    throw new Error(err.detail || 'Failed to save comic')
  }
  return res.json()
}

export async function loadComicProject(name: string): Promise<import('../features/comics/types').ComicProject> {
  const res = await fetch(`${BASE}/api/v1/comics/${encodeURIComponent(name)}`)
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Failed to load comic' }))
    throw new Error(err.detail || 'Failed to load comic')
  }
  const data = await res.json()
  return data.project
}

export interface ComicHistoryEntry {
  id: string
  comicId: string
  title: string
  createdAt: string
  reason: string
  persistedName: string | null
  pageCount: number
  assetCount: number
}

export async function createComicHistory(
  project: import('../features/comics/types').ComicProject,
  reason = 'Automatic checkpoint',
  persistedName?: string | null,
): Promise<ComicHistoryEntry> {
  const res = await fetch(`${BASE}/api/v1/comics/history`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project, reason, persisted_name: persistedName || null }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Failed to back up comic' }))
    throw new Error(err.detail || 'Failed to back up comic')
  }
  return res.json()
}

export async function listComicHistory(comicId?: string): Promise<ComicHistoryEntry[]> {
  const query = comicId ? `?comic_id=${encodeURIComponent(comicId)}` : ''
  const res = await fetch(`${BASE}/api/v1/comics/history${query}`)
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Failed to load comic history' }))
    throw new Error(err.detail || 'Failed to load comic history')
  }
  const data = await res.json()
  return data.history || []
}

export async function loadComicHistory(id: string): Promise<{
  project: import('../features/comics/types').ComicProject
  entry: ComicHistoryEntry
}> {
  const res = await fetch(`${BASE}/api/v1/comics/history/${encodeURIComponent(id)}`)
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Failed to restore comic backup' }))
    throw new Error(err.detail || 'Failed to restore comic backup')
  }
  return res.json()
}

export async function generateComicWithMiniMax(params: {
  prompt: string
  aspect_ratio: string
  subject_reference?: string
}): Promise<{ asset: import('../features/comics/types').ComicAsset }> {
  const res = await fetch(`${BASE}/api/v1/comics/generate/minimax`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'MiniMax generation failed' }))
    throw new Error(`HTTP ${res.status}: ${err.detail || 'MiniMax generation failed'}`)
  }
  return res.json()
}

export interface MiniMaxImageJob {
  jobId: string
  workspace: string
  status: 'queued' | 'waiting_resource' | 'running' | 'cancelling' | 'completed' | 'failed' | 'cancelled'
  phase: string
  message: string
  current: number
  total: number
  progress: number
  taskId?: string | null
  rootTaskId?: string | null
  statusCode?: number
  error?: string | null
  result?: { asset: import('../features/comics/types').ComicAsset } | null
}

export async function startMiniMaxImageJob(params: {
  prompt: string
  aspect_ratio: string
  subject_reference?: string
  workspace: string
}): Promise<MiniMaxImageJob> {
  const res = await fetch(`${BASE}/api/v1/comics/generate/minimax/jobs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'MiniMax generation failed' }))
    throw new Error(`HTTP ${res.status}: ${err.detail || 'MiniMax generation failed'}`)
  }
  return res.json()
}

export async function fetchMiniMaxImageJob(jobId: string): Promise<MiniMaxImageJob> {
  const res = await fetch(`${BASE}/api/v1/comics/generate/minimax/jobs/${encodeURIComponent(jobId)}`)
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'MiniMax image job not found' }))
    throw new Error(`HTTP ${res.status}: ${err.detail || 'MiniMax image job not found'}`)
  }
  return res.json()
}

export async function generateStorySection(params: {
  scope: import('../features/stories/types').StoryGenerationScope
  premise: string
  language: string
  genre: string
  tone: string
  audience: string
  instruction?: string
  project: import('../features/stories/types').StoryProject
  writingProvider: import('../features/stories/types').StoryWritingProvider
  writingModel?: string
  writingBaseUrl?: string
  workspace?: string
}, onProgress?: (progress: {
  jobId: string
  status: string
  message: string
  stage: string
  current: number
  total: number
}) => void, signal?: AbortSignal): Promise<{ result: Record<string, unknown> }> {
  const res = await fetch(`${BASE}/api/v1/stories/generate/start`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
    signal,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Story generation failed' }))
    throw new Error(err.detail || 'Story generation failed')
  }
  const accepted = await res.json()
  rememberPrompt({
    prompt: params.premise,
    mode: `story-${params.scope}`,
    model: params.writingModel || params.writingProvider,
    workspace: params.workspace,
    source: 'generation',
  })
  window.localStorage.setItem('maestro-last-story-plan-job', accepted.jobId)
  onProgress?.(accepted)
  const cancelRemote = () => {
    void fetch(
      `${BASE}/api/v1/stories/generate/cancel/${encodeURIComponent(accepted.jobId)}`,
      { method: 'POST', keepalive: true },
    )
  }
  signal?.addEventListener('abort', cancelRemote, { once: true })
  try {
    for (;;) {
      await new Promise<void>((resolve, reject) => {
        const onAbort = () => {
          window.clearTimeout(timer)
          reject(new DOMException('Story generation cancelled', 'AbortError'))
        }
        const timer = window.setTimeout(() => {
          signal?.removeEventListener('abort', onAbort)
          resolve()
        }, 1000)
        signal?.addEventListener('abort', onAbort, { once: true })
      })
      const status = await getStoryGenerationStatusResilient(
        accepted.jobId,
        signal,
        (attempt, delayMs) => onProgress?.({
          ...accepted,
          status: 'running',
          stage: 'reconnecting',
          message: `Mobile connection interrupted; retrying in ${Math.round(delayMs / 1000)}s (attempt ${attempt})…`,
          current: 0,
          total: 0,
        }),
      )
      onProgress?.(status)
      if (status.status === 'failed' || status.status === 'cancelled') {
        throw new Error(`${status.error || status.message} Resume job: ${accepted.jobId}`)
      }
      if (status.status === 'completed') {
        const result = status.result?.result
        if (!result) throw new Error('Story Lab job completed without a draft')
        window.localStorage.setItem('maestro-last-story-plan-result', JSON.stringify({
          jobId: accepted.jobId,
          projectId: params.project.id,
          scope: params.scope,
          result,
        }))
        return { result }
      }
    }
  } finally {
    signal?.removeEventListener('abort', cancelRemote)
  }
}

export interface StoryLibraryPayload {
  version: 2
  revision: number
  activeId: string
  projects: Record<string, import('../features/stories/types').StoryProject>
}

export interface WizardConversationPayload {
  version: 1
  revision: number
  messages: unknown[]
  executions: unknown[]
  requestedActions?: unknown[]
  executedActions?: unknown[]
  confirmations?: unknown[]
}

export interface WizardWorkflowCollectionPayload {
  version: 1
  revision: number
  workflows: unknown[]
}

export async function fetchWizardConversation(workspace: string): Promise<WizardConversationPayload> {
  const response = await fetch(
    `${BASE}/api/v1/wizard/conversations?workspace=${encodeURIComponent(workspace)}`,
  )
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Could not load Wizard conversation' }))
    throw new Error(error.detail || 'Could not load Wizard conversation')
  }
  return response.json()
}

export async function saveWizardConversation(
  workspace: string,
  conversation: WizardConversationPayload,
): Promise<WizardConversationPayload> {
  const response = await fetch(`${BASE}/api/v1/wizard/conversations`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ workspace, baseRevision: conversation.revision, conversation }),
  })
  if (!response.ok) {
    const error: unknown = await response.json().catch(() => null)
    if (error && typeof error === 'object') {
      const detail = (error as Record<string, unknown>).detail
      if (typeof detail === 'string') throw new Error(detail)
    }
    throw new Error('Could not save Wizard conversation')
  }
  return response.json()
}

export async function fetchWizardWorkflows(workspace: string): Promise<WizardWorkflowCollectionPayload> {
  const response = await fetch(
    `${BASE}/api/v1/wizard/workflows?workspace=${encodeURIComponent(workspace)}`,
  )
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Could not load Wizard workflows' }))
    throw new Error(error.detail || 'Could not load Wizard workflows')
  }
  return response.json()
}

export async function saveWizardWorkflows(
  workspace: string,
  collection: WizardWorkflowCollectionPayload,
): Promise<WizardWorkflowCollectionPayload> {
  const response = await fetch(`${BASE}/api/v1/wizard/workflows`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ workspace, baseRevision: collection.revision, collection }),
  })
  if (!response.ok) {
    const error: unknown = await response.json().catch(() => null)
    if (error && typeof error === 'object') {
      const detail = (error as Record<string, unknown>).detail
      if (typeof detail === 'string') throw new Error(detail)
      if (detail && typeof detail === 'object') {
        const message = (detail as Record<string, unknown>).message
        if (typeof message === 'string') throw new Error(message)
      }
    }
    throw new Error('Could not save Wizard workflows')
  }
  return response.json()
}

export async function fetchStoryLibrary(workspace: string): Promise<StoryLibraryPayload> {
  const response = await fetch(
    `${BASE}/api/v1/stories/library?workspace=${encodeURIComponent(workspace)}`,
  )
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Could not load Story Lab library' }))
    throw new Error(error.detail || 'Could not load Story Lab library')
  }
  return response.json()
}

export async function saveStoryLibrary(
  workspace: string,
  library: StoryLibraryPayload,
): Promise<StoryLibraryPayload> {
  const response = await fetch(`${BASE}/api/v1/stories/library`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ workspace, baseRevision: library.revision, library }),
  })
  if (!response.ok) {
    const error: unknown = await response.json().catch(() => null)
    if (error && typeof error === 'object') {
      const detail = (error as Record<string, unknown>).detail
      if (detail && typeof detail === 'object') {
        const conflict = detail as Record<string, unknown>
        if (
          conflict.code === 'story_library_revision_conflict'
          && typeof conflict.currentRevision === 'number'
        ) {
          throw new StoryLibraryRevisionError(
            typeof conflict.message === 'string' ? conflict.message : 'Story library changed in another tab',
            conflict.currentRevision,
          )
        }
      }
      if (typeof detail === 'string') throw new Error(detail)
    }
    throw new Error('Could not save Story Lab library')
  }
  return response.json()
}

export class StoryLibraryRevisionError extends Error {
  readonly currentRevision: number

  constructor(message: string, currentRevision: number) {
    super(message)
    this.name = 'StoryLibraryRevisionError'
    this.currentRevision = currentRevision
  }
}

async function seriesResponse<T>(responsePromise: Response | Promise<Response>, fallback: string): Promise<T> {
  const response = await responsePromise
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: fallback }))
    const detailMessage = typeof error.detail === 'object' && error.detail
      ? error.detail.message
      : error.detail
    throw new Error(detailMessage || error.error || fallback)
  }
  return response.json() as Promise<T>
}

export class SeriesEpisodeRevisionError extends Error {
  readonly currentSeriesRevision: number
  readonly currentEpisodeUpdatedAt: string

  constructor(message: string, currentSeriesRevision: number, currentEpisodeUpdatedAt: string) {
    super(message)
    this.name = 'SeriesEpisodeRevisionError'
    this.currentSeriesRevision = currentSeriesRevision
    this.currentEpisodeUpdatedAt = currentEpisodeUpdatedAt
  }
}

export async function fetchSeriesLibrary(workspace: string): Promise<import('../features/series/types').SeriesLibrary> {
  return seriesResponse(fetch(
    `${BASE}/api/v1/series/library?workspace=${encodeURIComponent(workspace)}`,
  ), 'Could not load Series Lab library')
}

export async function fetchSeriesProject(
  workspace: string,
  seriesId: string,
): Promise<import('../features/series/types').SeriesProject> {
  return seriesResponse(fetch(
    `${BASE}/api/v1/series/${encodeURIComponent(seriesId)}?workspace=${encodeURIComponent(workspace)}`,
  ), 'Could not load Series Lab project')
}

export async function createSeriesProject(
  workspace: string,
  title = 'Untitled series',
): Promise<import('../features/series/types').SeriesProject> {
  return seriesResponse(fetch(`${BASE}/api/v1/series`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ workspace, title }),
  }), 'Could not create Series Lab project')
}

export async function saveSeriesProject(
  workspace: string,
  project: import('../features/series/types').SeriesProject,
  baseRevision: number,
): Promise<import('../features/series/types').SeriesProject> {
  return seriesResponse(fetch(`${BASE}/api/v1/series/${encodeURIComponent(project.id)}`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ workspace, series: project, baseRevision }),
  }), 'Could not save Series Lab project')
}

export async function deleteSeriesProject(workspace: string, seriesId: string): Promise<void> {
  await seriesResponse(fetch(
    `${BASE}/api/v1/series/${encodeURIComponent(seriesId)}?workspace=${encodeURIComponent(workspace)}`,
    { method: 'DELETE' },
  ), 'Could not delete Series Lab project')
}

export async function duplicateSeriesProject(
  workspace: string,
  seriesId: string,
): Promise<import('../features/series/types').SeriesProject> {
  return seriesResponse(fetch(`${BASE}/api/v1/series/${encodeURIComponent(seriesId)}/duplicate`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ workspace }),
  }), 'Could not duplicate Series Lab project')
}

export async function importStoryAsSeries(
  workspace: string,
  storyId: string,
): Promise<import('../features/series/types').SeriesProject> {
  return seriesResponse(fetch(`${BASE}/api/v1/series/import-story`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ workspace, storyId }),
  }), 'Could not import Story Lab project')
}

export async function createSeriesEpisode(
  workspace: string,
  seriesId: string,
  seasonId?: string,
  episode?: Partial<Pick<import('../features/series/types').SeriesEpisode,
    'title' | 'premise' | 'logline' | 'targetDurationSeconds' | 'status' | 'outline'>>,
): Promise<import('../features/series/types').SeriesEpisode> {
  return seriesResponse(fetch(`${BASE}/api/v1/series/${encodeURIComponent(seriesId)}/episodes`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ workspace, seasonId, episode }),
  }), 'Could not create Series episode')
}

export async function fetchSeriesEpisodes(
  workspace: string, seriesId: string,
): Promise<{ episodes: import('../features/series/types').SeriesEpisode[] }> {
  return seriesResponse(fetch(
    `${BASE}/api/v1/series/${encodeURIComponent(seriesId)}/episodes?workspace=${encodeURIComponent(workspace)}`,
  ), 'Could not list Series episodes')
}

export async function fetchSeriesEpisode(
  workspace: string, seriesId: string, episodeId: string,
): Promise<import('../features/series/types').SeriesEpisode> {
  return seriesResponse(fetch(
    `${BASE}/api/v1/series/${encodeURIComponent(seriesId)}/episodes/${encodeURIComponent(episodeId)}?workspace=${encodeURIComponent(workspace)}`,
  ), 'Could not load Series episode')
}

export async function deleteSeriesEpisode(
  workspace: string, seriesId: string, episodeId: string,
): Promise<void> {
  await seriesResponse(fetch(
    `${BASE}/api/v1/series/${encodeURIComponent(seriesId)}/episodes/${encodeURIComponent(episodeId)}?workspace=${encodeURIComponent(workspace)}`,
    { method: 'DELETE' },
  ), 'Could not delete Series episode')
}

export async function importSeriesAsset(
  workspace: string,
  seriesId: string,
  input: {
    uploadPath: string
    name: string
    ownerType: 'series' | 'character' | 'location' | 'prop' | 'episode' | 'shot'
    ownerId: string
    kind?: import('../features/series/types').SeriesAsset['kind']
    referenceRole?: string
    metadata?: Record<string, unknown>
  },
): Promise<{
  asset: import('../features/series/types').SeriesAsset
  series: import('../features/series/types').SeriesProject
}> {
  return seriesResponse(fetch(
    `${BASE}/api/v1/series/${encodeURIComponent(seriesId)}/assets/import`,
    {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ workspace, ...input }),
    },
  ), 'Could not import Series reference')
}

export async function saveSeriesEpisode(
  workspace: string,
  seriesId: string,
  episode: import('../features/series/types').SeriesEpisode,
  concurrency: { baseSeriesRevision?: number; baseEpisodeUpdatedAt?: string },
): Promise<import('../features/series/types').SeriesEpisode> {
  const response = await fetch(
    `${BASE}/api/v1/series/${encodeURIComponent(seriesId)}/episodes/${encodeURIComponent(episode.id)}`,
    {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ workspace, episode, ...concurrency }),
    },
  )
  if (response.status === 409) {
    const payload = await response.json().catch(() => null)
    const detail = payload?.detail
    throw new SeriesEpisodeRevisionError(
      (typeof detail === 'object' && detail?.message) || 'Episode changed; reload before saving',
      Number(detail?.currentSeriesRevision || 0),
      String(detail?.currentEpisodeUpdatedAt || ''),
    )
  }
  return seriesResponse(response, 'Could not save Series episode')
}

export async function startSeriesPlan(
  workspace: string,
  seriesId: string,
  episodeId: string,
  options: {
    scope: 'outline' | 'script' | 'shots' | 'complete'
    instruction?: string
    writingProvider?: string
    writingModel?: string
    writingBaseUrl?: string
  },
): Promise<import('../features/series/types').SeriesJobStatus> {
  return seriesResponse(fetch(
    `${BASE}/api/v1/series/${encodeURIComponent(seriesId)}/episodes/${encodeURIComponent(episodeId)}/plan/start`,
    {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ workspace, ...options }),
    },
  ), 'Could not start Series episode planning')
}

export async function startSeriesCanonPreparation(
  workspace: string,
  seriesId: string,
  options: {
    instruction?: string
    writingProvider?: string
    writingModel?: string
    writingBaseUrl?: string
    generateImages?: boolean
    bootstrapKnownSeries?: boolean
    autoApply?: boolean
  },
): Promise<import('../features/series/types').SeriesJobStatus> {
  return seriesResponse(fetch(
    `${BASE}/api/v1/series/${encodeURIComponent(seriesId)}/canon/prepare/start`,
    {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ workspace, ...options }),
    },
  ), 'Could not prepare Series canon')
}

export async function fetchSeriesPlanJob(
  jobId: string,
  signal?: AbortSignal,
): Promise<import('../features/series/types').SeriesJobStatus> {
  return seriesResponse(fetch(
    `${BASE}/api/v1/series/plan/jobs/${encodeURIComponent(jobId)}`,
    signal ? { signal } : undefined,
  ), 'Could not read Series planning job')
}

export async function cancelSeriesPlanJob(jobId: string): Promise<import('../features/series/types').SeriesJobStatus> {
  return seriesResponse(fetch(
    `${BASE}/api/v1/series/plan/jobs/${encodeURIComponent(jobId)}/cancel`, { method: 'POST' },
  ), 'Could not cancel Series planning job')
}

export async function resumeSeriesPlanJob(jobId: string): Promise<import('../features/series/types').SeriesJobStatus> {
  return seriesResponse(fetch(
    `${BASE}/api/v1/series/plan/jobs/${encodeURIComponent(jobId)}/resume`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
    },
  ), 'Could not resume Series planning job')
}

export async function applySeriesPlanJob(
  jobId: string,
  episodeResult?: import('../features/series/types').SeriesEpisode,
): Promise<import('../features/series/types').SeriesEpisode> {
  return seriesResponse(fetch(
    `${BASE}/api/v1/series/plan/jobs/${encodeURIComponent(jobId)}/apply`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(episodeResult ? { episodeResult } : {}),
    },
  ), 'Could not apply Series planning proposal')
}

export async function applySeriesCanonPlanJob(jobId: string): Promise<import('../features/series/types').SeriesProject> {
  return seriesResponse(fetch(
    `${BASE}/api/v1/series/plan/jobs/${encodeURIComponent(jobId)}/apply-canon`, { method: 'POST' },
  ), 'Could not apply Series canon proposal')
}

export async function approveSeriesCanon(
  workspace: string, seriesId: string, baseRevision: number,
): Promise<import('../features/series/types').SeriesProject> {
  return seriesResponse(fetch(
    `${BASE}/api/v1/series/${encodeURIComponent(seriesId)}/canon/approve`,
    {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ workspace, baseRevision }),
    },
  ), 'Could not approve Series canon')
}

export async function fetchSeriesPlanRecovery(workspace: string): Promise<{ jobs: import('../features/series/types').SeriesJobStatus[] }> {
  return seriesResponse(fetch(
    `${BASE}/api/v1/series/plan/recovery?workspace=${encodeURIComponent(workspace)}`,
  ), 'Could not read Series planning recovery')
}

export async function discardSeriesPlanJob(jobId: string): Promise<void> {
  await seriesResponse(fetch(
    `${BASE}/api/v1/series/plan/jobs/${encodeURIComponent(jobId)}`, { method: 'DELETE' },
  ), 'Could not discard Series planning job')
}

export async function routeSeriesReferences(
  workspace: string,
  seriesId: string,
  episodeId: string,
  shotId?: string,
): Promise<{ shotId?: string; manifest?: import('../features/series/types').SeriesReferenceManifest; manifests?: Record<string, import('../features/series/types').SeriesReferenceManifest> }> {
  return seriesResponse(fetch(
    `${BASE}/api/v1/series/${encodeURIComponent(seriesId)}/episodes/${encodeURIComponent(episodeId)}/references/route`,
    {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ workspace, shotId }),
    },
  ), 'Could not route Series references')
}

export async function previewSeriesShotDuration(
  workspace: string,
  seriesId: string,
  shot: import('../features/series/types').SeriesShot,
  signal?: AbortSignal,
): Promise<import('../features/series/types').SeriesShot> {
  return seriesResponse(fetch(
    `${BASE}/api/v1/series/${encodeURIComponent(seriesId)}/shots/duration/preview`,
    {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, signal,
      body: JSON.stringify({ workspace, shot }),
    },
  ), 'Could not calculate Series dialogue duration')
}

export async function startSeriesRender(
  workspace: string,
  seriesId: string,
  episodeId: string,
  options: {
    mode: 'selected' | 'failed' | 'missing' | 'all'
    shotIds?: string[]
    seed?: number
    settings?: Record<string, unknown>
  },
): Promise<import('../features/series/types').SeriesJobStatus> {
  return seriesResponse(fetch(
    `${BASE}/api/v1/series/${encodeURIComponent(seriesId)}/episodes/${encodeURIComponent(episodeId)}/render/start`,
    {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ workspace, ...options }),
    },
  ), 'Could not start Series render')
}

export async function fetchSeriesRenderJob(jobId: string): Promise<import('../features/series/types').SeriesJobStatus> {
  return seriesResponse(fetch(
    `${BASE}/api/v1/series/render/jobs/${encodeURIComponent(jobId)}`,
  ), 'Could not read Series render job')
}

export async function cancelSeriesRenderJob(jobId: string): Promise<import('../features/series/types').SeriesJobStatus> {
  return seriesResponse(fetch(
    `${BASE}/api/v1/series/render/jobs/${encodeURIComponent(jobId)}/cancel`, { method: 'POST' },
  ), 'Could not cancel Series render job')
}

export async function resumeSeriesRenderJob(jobId: string): Promise<import('../features/series/types').SeriesJobStatus> {
  return seriesResponse(fetch(
    `${BASE}/api/v1/series/render/jobs/${encodeURIComponent(jobId)}/resume`, { method: 'POST' },
  ), 'Could not resume Series render job')
}

export async function fetchSeriesRenderRecovery(workspace: string): Promise<{ jobs: import('../features/series/types').SeriesJobStatus[] }> {
  return seriesResponse(fetch(
    `${BASE}/api/v1/series/render/recovery?workspace=${encodeURIComponent(workspace)}`,
  ), 'Could not read Series render recovery')
}

export async function discardSeriesRenderJob(jobId: string): Promise<void> {
  await seriesResponse(fetch(
    `${BASE}/api/v1/series/render/jobs/${encodeURIComponent(jobId)}`, { method: 'DELETE' },
  ), 'Could not discard Series render job')
}

export async function approveSeriesAttempt(
  workspace: string, seriesId: string, episodeId: string, shotId: string, attemptId: string,
): Promise<import('../features/series/types').SeriesShot> {
  return seriesResponse(fetch(
    `${BASE}/api/v1/series/${encodeURIComponent(seriesId)}/episodes/${encodeURIComponent(episodeId)}/shots/${encodeURIComponent(shotId)}/attempts/${encodeURIComponent(attemptId)}/approve`,
    {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ workspace }),
    },
  ), 'Could not approve Series shot attempt')
}

export async function approveSeriesAttemptsBulk(
  workspace: string,
  seriesId: string,
  episodeId: string,
  selections: Array<{ shotId: string; attemptId: string }>,
): Promise<{ seriesId: string; episodeId: string; revision: number; episode: import('../features/series/types').SeriesEpisode }> {
  return seriesResponse(fetch(
    `${BASE}/api/v1/series/${encodeURIComponent(seriesId)}/episodes/${encodeURIComponent(episodeId)}/attempts/approve-bulk`,
    {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ workspace, selections }),
    },
  ), 'Could not approve Series shot attempts')
}

export async function startSeriesEpisodeAssembly(
  workspace: string, seriesId: string, episodeId: string,
): Promise<SeriesAssemblyJob> {
  const payload: SeriesAssemblyStartRequest = { workspace }
  return seriesResponse(fetch(
    `${BASE}/api/v1/series/${encodeURIComponent(seriesId)}/episodes/${encodeURIComponent(episodeId)}/assembly/start`,
    {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  ), 'Could not start Series episode assembly')
}

export async function fetchSeriesEpisodeAssembly(
  jobId: string, workspace?: string,
): Promise<SeriesAssemblyJob> {
  const query = workspace ? `?workspace=${encodeURIComponent(workspace)}` : ''
  return seriesResponse(fetch(
    `${BASE}/api/v1/series/assembly/jobs/${encodeURIComponent(jobId)}${query}`,
  ), 'Could not read Series episode assembly')
}

export async function cancelSeriesEpisodeAssembly(
  jobId: string, workspace: string,
): Promise<SeriesAssemblyJob> {
  const payload: SeriesAssemblyActionRequest = { workspace }
  return seriesResponse(fetch(
    `${BASE}/api/v1/series/assembly/jobs/${encodeURIComponent(jobId)}/cancel`,
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) },
  ), 'Could not cancel Series episode assembly')
}

export async function resumeSeriesEpisodeAssembly(
  jobId: string, workspace: string,
): Promise<SeriesAssemblyJob> {
  const payload: SeriesAssemblyActionRequest = { workspace }
  return seriesResponse(fetch(
    `${BASE}/api/v1/series/assembly/jobs/${encodeURIComponent(jobId)}/resume`,
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) },
  ), 'Could not resume Series episode assembly')
}

export async function discardSeriesEpisodeAssembly(
  jobId: string, workspace: string,
): Promise<SeriesAssemblyDiscardResponse> {
  return seriesResponse(fetch(
    `${BASE}/api/v1/series/assembly/jobs/${encodeURIComponent(jobId)}?workspace=${encodeURIComponent(workspace)}`,
    { method: 'DELETE' },
  ), 'Could not discard Series episode assembly')
}

export async function fetchSeriesAssemblyRecovery(workspace: string): Promise<SeriesAssemblyRecoveryResponse> {
  return seriesResponse(fetch(
    `${BASE}/api/v1/series/assembly/recovery?workspace=${encodeURIComponent(workspace)}`,
  ), 'Could not read Series assembly recovery')
}

export async function rejectSeriesAttempt(
  workspace: string, seriesId: string, episodeId: string, shotId: string, attemptId: string,
): Promise<import('../features/series/types').SeriesShot> {
  return seriesResponse(fetch(
    `${BASE}/api/v1/series/${encodeURIComponent(seriesId)}/episodes/${encodeURIComponent(episodeId)}/shots/${encodeURIComponent(shotId)}/attempts/${encodeURIComponent(attemptId)}/reject`,
    {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ workspace }),
    },
  ), 'Could not reject Series shot attempt')
}

export async function commitSeriesCanon(
  workspace: string,
  seriesId: string,
  episodeId: string,
  baseRevision: number,
  decisions: Record<string, 'pending' | 'accepted' | 'rejected'>,
): Promise<import('../features/series/types').SeriesProject> {
  return seriesResponse(fetch(
    `${BASE}/api/v1/series/${encodeURIComponent(seriesId)}/episodes/${encodeURIComponent(episodeId)}/canon/commit`,
    {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ workspace, baseRevision, decisions }),
    },
  ), 'Could not commit Series canon')
}

export async function cancelStoryGeneration(jobId: string): Promise<void> {
  const response = await fetch(
    `${BASE}/api/v1/stories/generate/cancel/${encodeURIComponent(jobId)}`,
    { method: 'POST' },
  )
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Could not cancel Story Lab job' }))
    throw new Error(error.detail || 'Could not cancel Story Lab job')
  }
}

export interface StoryGenerationStatus {
  jobId: string
  taskId?: string | null
  rootTaskId?: string | null
  status: string
  message: string
  stage: string
  current: number
  total: number
  error?: string | null
  result?: { result?: Record<string, unknown> } | null
}

export interface QuickVideoBatchItem {
  index: number
  idea: string
  status: 'queued' | 'planning' | 'running' | 'completed' | 'failed' | 'cancelled' | 'interrupted' | 'skipped'
  stage: string
  message: string
  pipelineId?: string | null
  outputFiles: string[]
  finalOutput?: string | null
  error?: string | null
  createdAt: number
  startedAt?: number | null
  finishedAt?: number | null
  progressCurrent: number
  progressTotal: number
}

export interface QuickVideoBatchJob {
  jobId: string
  taskId: string
  workspace: string
  title: string
  status: 'queued' | 'running' | 'cancelling' | 'completed' | 'failed' | 'cancelled' | 'interrupted'
  stage: string
  current: number
  total: number
  message: string
  error?: string | null
  continueOnError: boolean
  settings: Record<string, unknown>
  items: QuickVideoBatchItem[]
  createdAt: number
  updatedAt: number
  finishedAt?: number | null
}

export interface QuickVideoBatchStart {
  workspace: string
  title: string
  ideas: string[]
  continueOnError: boolean
  settings: {
    durationSeconds: number
    generationMode: 'direct_video' | 'image_guided' | 'direct_references'
    videoModel: string
    imageModel: string
    resolution: string
    aspectRatio: string
    spokenLanguage: string
    visualStyle: string
    characterVisualStyle: string
    directVideoMasterPrompt: string
    allowClipText: boolean
    writingProvider: string
    writingModel: string
    writingBaseUrl: string
    characters: Array<Record<string, unknown>>
    references: Array<{ source: string; label: string; kind: string }>
  }
}

async function quickVideoBatchResponse(response: Promise<Response>, fallback: string) {
  const resolved = await response
  if (!resolved.ok) {
    const error = await resolved.json().catch(() => ({ detail: fallback }))
    throw new Error(error.detail || fallback)
  }
  return resolved.json()
}

export async function startQuickVideoBatch(payload: QuickVideoBatchStart): Promise<QuickVideoBatchJob> {
  return quickVideoBatchResponse(fetch(`${BASE}/api/v1/stories/quick-video-batches/start`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  }), 'Could not start Quick Video batch')
}

export async function listQuickVideoBatches(workspace: string): Promise<{ jobs: QuickVideoBatchJob[] }> {
  return quickVideoBatchResponse(fetch(
    `${BASE}/api/v1/stories/quick-video-batches?workspace=${encodeURIComponent(workspace)}`,
  ), 'Could not load Quick Video batches')
}

export async function getQuickVideoBatch(jobId: string, workspace: string): Promise<QuickVideoBatchJob> {
  return quickVideoBatchResponse(fetch(
    `${BASE}/api/v1/stories/quick-video-batches/${encodeURIComponent(jobId)}?workspace=${encodeURIComponent(workspace)}`,
  ), 'Could not load Quick Video batch')
}

export async function controlQuickVideoBatch(
  jobId: string,
  action: 'cancel' | 'resume' | 'retry-item' | 'skip-item' | 'discard',
  workspace: string,
  itemIndex?: number,
): Promise<QuickVideoBatchJob | { jobId: string; discarded: boolean; outputsPreserved: boolean }> {
  return quickVideoBatchResponse(fetch(
    `${BASE}/api/v1/stories/quick-video-batches/${encodeURIComponent(jobId)}/${action}`,
    {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ workspace, itemIndex }),
    },
  ), `Could not ${action} Quick Video batch`)
}

const STORY_STATUS_RETRY_DELAYS_MS = [1_000, 2_000, 4_000, 8_000, 15_000, 15_000, 15_000, 15_000]

function isStoryStatusNetworkError(error: unknown): boolean {
  return error instanceof TypeError || (error instanceof Error && error.name === 'TypeError')
}

function waitForStoryStatusRetry(delayMs: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException('Story generation cancelled', 'AbortError'))
      return
    }
    const onAbort = () => {
      window.clearTimeout(timer)
      reject(new DOMException('Story generation cancelled', 'AbortError'))
    }
    const timer = window.setTimeout(() => {
      signal?.removeEventListener('abort', onAbort)
      resolve()
    }, delayMs)
    signal?.addEventListener('abort', onAbort, { once: true })
  })
}

export async function getStoryGenerationStatus(
  jobId: string,
  signal?: AbortSignal,
): Promise<StoryGenerationStatus> {
  const response = await fetch(
    `${BASE}/api/v1/stories/generate/status/${encodeURIComponent(jobId)}`,
    { signal },
  )
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Could not read Story Lab job' }))
    throw new Error(error.detail || 'Could not read Story Lab job')
  }
  return response.json()
}

async function getStoryGenerationStatusResilient(
  jobId: string,
  signal?: AbortSignal,
  onRetry?: (attempt: number, delayMs: number) => void,
): Promise<StoryGenerationStatus> {
  for (let attempt = 0; ; attempt += 1) {
    try {
      return await getStoryGenerationStatus(jobId, signal)
    } catch (error) {
      if (signal?.aborted) throw new DOMException('Story generation cancelled', 'AbortError')
      if (!isStoryStatusNetworkError(error)) throw error
      if (attempt >= STORY_STATUS_RETRY_DELAYS_MS.length) {
        throw new Error(`Connection to HocusPocus is still unavailable. The job remains saved. Resume job: ${jobId}`)
      }
      const delayMs = STORY_STATUS_RETRY_DELAYS_MS[attempt]
      onRetry?.(attempt + 1, delayMs)
      await waitForStoryStatusRetry(delayMs, signal)
    }
  }
}

export async function resumeStoryGeneration(
  jobId: string,
  onProgress?: (progress: {
    jobId: string
    status: string
    message: string
    stage: string
    current: number
    total: number
  }) => void,
  writing?: {
    writingProvider: import('../features/stories/types').StoryWritingProvider
    writingModel?: string
    writingBaseUrl?: string
  },
): Promise<{ result: Record<string, unknown> }> {
  const resumed = await fetch(
    `${BASE}/api/v1/stories/generate/resume/${encodeURIComponent(jobId)}`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(writing || {}),
    },
  )
  if (!resumed.ok) {
    const err = await resumed.json().catch(() => ({ detail: 'Could not resume Story Lab job' }))
    throw new Error(err.detail || 'Could not resume Story Lab job')
  }
  for (;;) {
    await new Promise(resolve => window.setTimeout(resolve, 1000))
    const status = await getStoryGenerationStatusResilient(
      jobId,
      undefined,
      (attempt, delayMs) => onProgress?.({
        jobId,
        status: 'running',
        stage: 'reconnecting',
        message: `Mobile connection interrupted; retrying in ${Math.round(delayMs / 1000)}s (attempt ${attempt})…`,
        current: 0,
        total: 0,
      }),
    )
    onProgress?.(status)
    if (status.status === 'failed' || status.status === 'cancelled') {
      throw new Error(status.error || status.message)
    }
    if (status.status === 'completed') {
      if (!status.result?.result) throw new Error('Story Lab job completed without a draft')
      window.localStorage.setItem('maestro-last-story-plan-result', JSON.stringify({
        jobId,
        result: status.result.result,
      }))
      return { result: status.result.result }
    }
  }
}

export type ComicPlanProgress = {
  jobId?: string
  taskId?: string | null
  rootTaskId?: string | null
  status: 'queued' | 'loading_llm' | 'planning' | 'planning_bible' | 'planning_page' | 'completed' | 'failed'
  message: string
  provider?: string
  model?: string
  createdAt?: number
  current?: number
  total?: number
  stage?: 'bible' | 'page'
  page?: number
}

export async function planComic(
  params: import('../features/comics/types').ComicDirectorRequest & { workspace?: string },
  onProgress?: (progress: ComicPlanProgress) => void,
  signal?: AbortSignal,
): Promise<{ plan: import('../features/comics/types').ComicPlan }> {
  const start = await fetch(`${BASE}/api/v1/director/comic/plan/start`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
    signal,
  })
  if (!start.ok) {
    const err = await start.json().catch(() => ({ detail: 'Comic planning failed to start' }))
    throw new Error(err.detail || 'Comic planning failed')
  }
  const accepted = await start.json() as ComicPlanProgress & { jobId: string }
  try {
    window.localStorage.setItem('maestro-last-comic-plan-job', accepted.jobId)
  } catch {
    // Recovery still works by manually entering the job ID.
  }
  onProgress?.(accepted)
  for (;;) {
    await new Promise<void>((resolve, reject) => {
      const onAbort = () => {
        window.clearTimeout(timer)
        reject(new DOMException('Comic planning cancelled', 'AbortError'))
      }
      const timer = window.setTimeout(() => {
        signal?.removeEventListener('abort', onAbort)
        resolve()
      }, 1000)
      signal?.addEventListener('abort', onAbort, { once: true })
    })
    const response = await fetch(
      `${BASE}/api/v1/director/comic/plan/status/${encodeURIComponent(accepted.jobId)}`,
      { signal },
    )
    if (!response.ok) {
      const err = await response.json().catch(() => ({ detail: 'Could not read comic planning status' }))
      throw new Error(err.detail || 'Could not read comic planning status')
    }
    const status = await response.json() as ComicPlanProgress & {
      error?: string
      result?: { plan: import('../features/comics/types').ComicPlan }
    }
    onProgress?.(status)
    if (status.status === 'failed') throw new Error(status.error || status.message)
    if (status.status === 'completed') {
      if (!status.result?.plan) throw new Error('Comic Director completed without a plan')
      try {
        window.localStorage.setItem('maestro-last-comic-plan-result', JSON.stringify({
          jobId: accepted.jobId,
          plan: status.result.plan,
        }))
      } catch {
        // The server job remains recoverable while Maestro is running.
      }
      return status.result
    }
  }
}

export async function fetchComicPlanJob(jobId: string): Promise<{
  jobId: string
  status: ComicPlanProgress['status']
  message: string
  error?: string
  request?: import('../features/comics/types').ComicDirectorRequest
  result?: { plan: import('../features/comics/types').ComicPlan }
}> {
  const response = await fetch(
    `${BASE}/api/v1/director/comic/plan/status/${encodeURIComponent(jobId)}`,
  )
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Comic planning job not found' }))
    throw new Error(error.detail || 'Comic planning job not found')
  }
  return response.json()
}

export async function resumeComicPlanJob(jobId: string): Promise<{
  jobId: string
  status: ComicPlanProgress['status']
  message: string
}> {
  const response = await fetch(
    `${BASE}/api/v1/director/comic/plan/resume/${encodeURIComponent(jobId)}`,
    { method: 'POST' },
  )
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Could not resume comic planning' }))
    throw new Error(error.detail || 'Could not resume comic planning')
  }
  return response.json()
}

export async function waitForComicPlanJob(
  jobId: string,
  onProgress?: (progress: ComicPlanProgress) => void,
): Promise<{ plan: import('../features/comics/types').ComicPlan }> {
  for (;;) {
    await new Promise(resolve => window.setTimeout(resolve, 1000))
    const job = await fetchComicPlanJob(jobId)
    onProgress?.(job)
    if (job.status === 'failed') throw new Error(job.error || job.message)
    if (job.status === 'completed') {
      if (!job.result?.plan) throw new Error('Comic Director completed without a plan')
      try {
        window.localStorage.setItem('maestro-last-comic-plan-result', JSON.stringify({
          jobId,
          plan: job.result.plan,
        }))
      } catch {
        // The durable server checkpoint remains available.
      }
      return job.result
    }
  }
}

export async function fetchLatestCompletedComicPlan(): Promise<{
  jobId: string
  request?: import('../features/comics/types').ComicDirectorRequest
  result: { plan: import('../features/comics/types').ComicPlan }
  finishedAt?: number
}> {
  const response = await fetch(`${BASE}/api/v1/director/comic/plan/recent/completed`)
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'No completed comic plan is available' }))
    throw new Error(error.detail || 'No completed comic plan is available')
  }
  return response.json()
}

export async function rewriteComicTextPage(params: {
  plan: import('../features/comics/types').ComicPlan
  pageIndex: number
  mode: 'rewrite' | 'translate'
  instruction?: string
  targetLanguage?: string
  dialogueDensity: import('../features/comics/types').ComicDirectorRequest['dialogueDensity']
  glossary?: import('../features/comics/types').ComicGlossaryEntry[]
  writingProvider?: import('../features/comics/types').ComicDirectorRequest['writingProvider']
  writingModel?: string
  writingBaseUrl?: string
}): Promise<{ page: import('../features/comics/types').ComicPlanPage }> {
  const response = await fetch(`${BASE}/api/v1/director/comic/text/page`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Comic text operation failed' }))
    throw new Error(error.detail || 'Comic text operation failed')
  }
  return response.json()
}

export async function reviseComicStory(params: {
  plan: import('../features/comics/types').ComicPlan
  instruction?: string
  dialogueDensity: import('../features/comics/types').ComicDirectorRequest['dialogueDensity']
  productionMode?: import('../features/comics/types').ComicDirectorRequest['productionMode']
  writingProvider?: import('../features/comics/types').ComicDirectorRequest['writingProvider']
  writingModel?: string
  writingBaseUrl?: string
}): Promise<{ plan: import('../features/comics/types').ComicPlan }> {
  const response = await fetch(`${BASE}/api/v1/director/comic/story/revise`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Comic story revision failed' }))
    throw new Error(error.detail || 'Comic story revision failed')
  }
  return response.json()
}

// --- System Config ---

export async function fetchSystemConfig(): Promise<import('../types').SystemConfig> {
  const res = await fetch(`${BASE}/api/v1/system-config`)
  if (!res.ok) throw new Error('Failed to fetch system config')
  return res.json()
}

export async function scanModelFolders(): Promise<{ candidates: import('../types').ModelFolderCandidate[] }> {
  const res = await fetch(`${BASE}/api/v1/model-folders/scan`)
  if (!res.ok) throw new Error('Failed to scan for model folders')
  return res.json()
}

export async function updateSystemConfig(
  partial: Partial<import('../types').SystemConfig>
): Promise<{ status: string; updated: Record<string, unknown> }> {
  const res = await fetch(`${BASE}/api/v1/system-config`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(partial),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Update failed' }))
    throw new Error(err.detail || 'Update failed')
  }
  return res.json()
}

// --- Performance Auto-Tune ---

/** Read the user's current hardware + the auto-tune recommendation
 *  for it. Backs the AutoPerformanceCard readout. Always succeeds —
 *  on systems without CUDA, the response includes a "no GPU detected"
 *  recommendation rather than a 500. */
export async function fetchSystemDetect(): Promise<import('../types').SystemDetectResponse> {
  const res = await fetch(`${BASE}/api/v1/system-detect`)
  if (!res.ok) throw new Error('Failed to fetch hardware detection')
  return res.json()
}

/** Live CPU / RAM / GPU + loaded-model telemetry for the hardware
 *  status indicators. Cheap enough to poll every ~2s. */
export async function fetchSystemStats(signal?: AbortSignal): Promise<import('../types').SystemStats> {
  const res = await fetch(`${BASE}/api/v1/system-stats`, { signal })
  if (!res.ok) throw new Error('Failed to fetch system stats')
  return res.json()
}

/** Manually unload the resident generation model (and LLM) to free
 *  VRAM/RAM. Models stay loaded between generations by design; this is
 *  the explicit opt-out. 409s when a generation or Director run is
 *  active. Returns which models were released. */
export async function releaseModels(): Promise<{ released: string[] }> {
  const res = await fetch(`${BASE}/api/v1/system/release-model`, { method: 'POST' })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Unload failed' }))
    throw new Error(err.detail || 'Unload failed')
  }
  return res.json()
}

/** Apply the recommended settings to wgp_config.json. Used by both
 *  the "Re-detect" button (refreshes after hardware change) and the
 *  auto-tune toggle going from off → on. Server-side this is a single
 *  call: re-runs detection, writes recommendation, sets
 *  services.auto_performance=true, applies runtime side effects. */
export async function applySystemDetect(): Promise<import('../types').SystemDetectApplyResponse> {
  const res = await fetch(`${BASE}/api/v1/system-detect/apply`, {
    method: 'POST',
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Apply failed' }))
    throw new Error(err.detail || 'Apply failed')
  }
  return res.json()
}

// --- Services Config ---

export async function fetchServicesConfig(): Promise<import('../types').ServicesConfig> {
  const res = await fetch(`${BASE}/api/v1/services-config`)
  if (!res.ok) throw new Error('Failed to fetch services config')
  return res.json()
}

export async function updateServicesConfig(
  partial: Partial<import('../types').ServicesConfig>
): Promise<{ status: string; updated: Record<string, unknown> }> {
  const res = await fetch(`${BASE}/api/v1/services-config`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(partial),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Update failed' }))
    throw new Error(err.detail || 'Update failed')
  }
  return res.json()
}

// --- Native Hunyuan3D ---

export interface Hunyuan3DModel {
  id: string
  label: string
  engine: 'v2' | 'v21'
  repo: string
  subfolder: string
  parameters: string
  multiview: boolean
  turbo: boolean
  supports_text: boolean
  recommended_vram_gb: number
  description: string
}

export interface Hunyuan3DPreset {
  id: string
  label: string
  description: string
  model_id: string
  num_inference_steps: number
  guidance_scale: number
  octree_resolution: number
  num_chunks: number
  texture_mode: string
  cpu_offload: boolean
  flashvdm: boolean
}

export interface Hunyuan3DCapabilities {
  runtime: { installed: boolean; isolated_runtime: boolean; releases_vram_after_job: boolean; install_hint: string | null }
  models: Hunyuan3DModel[]
  presets: Hunyuan3DPreset[]
  texture_modes: { id: string; label: string; recommended_vram_gb: number }[]
  input_views: string[]
  output_formats: string[]
  active_jobs: number
}

export interface Hunyuan3DJob {
  job_id: string
  operation?: 'generate' | 'retexture'
  status: 'queued' | 'waiting' | 'waiting_resource' | 'running' | 'cancelling' | 'completed' | 'failed' | 'cancelled'
  progress: number
  phase: string
  message: string
  error: string | null
  filename: string | null
  url: string | null
  model_id: string
  size?: number
}

export async function describeCharacterRefs(params: {
  kind: 'character' | 'object'
  image_paths: string[]
  roles?: string[]
  workspace?: string
}): Promise<{ a_prompt: string; kind: string }> {
  const res = await fetch(`${BASE}/api/v1/characters/describe-refs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Could not describe the reference images' }))
    throw new Error(err.detail || 'Could not describe the reference images')
  }
  return res.json()
}

export async function fetchHunyuan3DCapabilities(): Promise<Hunyuan3DCapabilities> {
  const res = await fetch(`${BASE}/api/v1/model3d/capabilities`)
  if (!res.ok) throw new Error('Failed to fetch Hunyuan3D capabilities')
  return res.json()
}

export async function startHunyuan3DJob(params: {
  operation?: 'generate' | 'retexture'
  source_model?: string
  preset?: string
  provider?: string
  model_id?: string
  prompt?: string
  workspace?: string
  images?: Partial<Record<'front' | 'left' | 'right' | 'back', string>>
  output_format?: string
  texture_mode?: string
  seed?: number
  num_inference_steps?: number
  guidance_scale?: number
  octree_resolution?: number
  num_chunks?: number
  texture_resolution?: number
  cpu_offload?: boolean
  flashvdm?: boolean
  remove_background?: boolean
  compile?: boolean
  reduce_face?: boolean
  target_face_num?: number
  mc_algo?: string
}): Promise<Hunyuan3DJob> {
  const res = await fetch(`${BASE}/api/v1/model3d/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: '3D generation failed' }))
    throw new Error(err.detail || '3D generation failed')
  }
  return res.json()
}

export async function fetchHunyuan3DJob(jobId: string): Promise<Hunyuan3DJob> {
  const res = await fetch(`${BASE}/api/v1/model3d/status/${encodeURIComponent(jobId)}`)
  if (!res.ok) {
    // A 404 means the job registry no longer knows this id (the backend
    // restarted mid-generation); callers use the status to stop polling.
    const error = new Error(res.status === 404 ? 'Hunyuan3D job not found' : 'Failed to fetch Hunyuan3D job')
    ;(error as Error & { status?: number }).status = res.status
    throw error
  }
  return res.json()
}

export async function cancelHunyuan3DJob(jobId: string): Promise<Hunyuan3DJob> {
  const res = await fetch(`${BASE}/api/v1/model3d/jobs/${encodeURIComponent(jobId)}/cancel`, { method: 'POST' })
  if (!res.ok) throw new Error('Failed to cancel Hunyuan3D job')
  return res.json()
}

// --- Rig & Animate (procedural skeletons for 3D outputs) ---

export interface RigEngine {
  id: string
  label: string
  description: string
  installed: boolean
  install_hint: string | null
}

export interface RigAnimation {
  id: string
  label: string
  description: string
  category?: string
}

export type RigProfileId = 'prop' | 'vehicle' | 'humanoid' | 'quadruped' | 'flying' | 'serpentine'

export interface RigProfile {
  id: RigProfileId
  label: string
  description: string
  default_spine_joints: number
  default_axis_mode: 'auto' | 'x' | 'y' | 'z'
  default_weight_falloff: number
  recommended_animations: string[]
  allowed_animations: string[]
}

export interface RigCapabilities {
  engines: RigEngine[]
  animations: RigAnimation[]
  /** Optional during rolling upgrades from backends predating rig profiles. */
  rig_profiles?: RigProfile[]
  default_rig_profile?: RigProfileId
  default_spine_joints: number
  active_jobs: number
}

export interface RigJob {
  job_id: string
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled'
  progress: number
  phase: string
  message: string
  error: string | null
  filename: string | null
  url: string | null
  engine: string
  rig_profile?: RigProfileId
  source_file: string
  animations?: string[]
  created_at: number
  updated_at: number
}

export async function fetchRigCapabilities(): Promise<RigCapabilities> {
  const res = await fetch(`${BASE}/api/v1/rig/capabilities`)
  if (!res.ok) throw new Error('Failed to fetch rig capabilities')
  return res.json()
}

export async function startRigJob(params: {
  source: string
  engine?: string
  rig_profile?: RigProfileId
  animations?: string[]
  spine_joints?: number
  axis_mode?: 'auto' | 'x' | 'y' | 'z'
  weight_falloff?: number
}): Promise<RigJob> {
  const res = await fetch(`${BASE}/api/v1/rig/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Rig job failed to start' }))
    throw new Error(err.detail || 'Rig job failed to start')
  }
  return res.json()
}

export async function fetchRigJob(jobId: string): Promise<RigJob> {
  const res = await fetch(`${BASE}/api/v1/rig/status/${encodeURIComponent(jobId)}`)
  if (!res.ok) {
    // 404 → the registry lost the job (backend restart); callers stop polling.
    const error = new Error(res.status === 404 ? 'Rig job not found' : 'Failed to fetch rig job')
    ;(error as Error & { status?: number }).status = res.status
    throw error
  }
  return res.json()
}

export async function cancelRigJob(jobId: string): Promise<RigJob> {
  const res = await fetch(`${BASE}/api/v1/rig/jobs/${encodeURIComponent(jobId)}/cancel`, { method: 'POST' })
  if (!res.ok) throw new Error('Failed to cancel rig job')
  return res.json()
}

// --- LLM Service ---

export async function generateLlmText(params: {
  prompt: string
  system_prompt?: string
  max_new_tokens?: number
  temperature?: number
  top_p?: number
  frequency_penalty?: number
  presence_penalty?: number
  json_schema?: Record<string, unknown>
}): Promise<string> {
  const res = await fetch(`${BASE}/api/v1/llm/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      prompt: params.prompt,
      system_prompt: params.system_prompt || '',
      max_new_tokens: params.max_new_tokens ?? 1536,
      temperature: params.temperature ?? 0.3,
      top_p: params.top_p ?? 0.9,
      frequency_penalty: params.frequency_penalty ?? 0,
      presence_penalty: params.presence_penalty ?? 0,
      json_schema: params.json_schema,
    }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'LLM generate failed' }))
    throw new Error(err.detail || err.error || 'LLM generate failed')
  }
  const body = await res.json()
  return String(body.text || '')
}

export async function fetchLlmStatus(): Promise<import('../types').LlmStatus> {
  const res = await fetch(`${BASE}/api/v1/llm/status`)
  if (!res.ok) throw new Error('Failed to fetch LLM status')
  return res.json()
}

export async function loadLlm(
  params?: { model_id?: string; device?: string }
): Promise<import('../types').LlmStatus & { status: string }> {
  const res = await fetch(`${BASE}/api/v1/llm/load`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params || {}),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Load failed' }))
    throw new Error(err.detail || 'Load failed')
  }
  return res.json()
}

export async function unloadLlm(): Promise<void> {
  const res = await fetch(`${BASE}/api/v1/llm/unload`, { method: 'POST' })
  if (!res.ok) throw new Error('Failed to unload LLM')
}

export async function fetchLlmModels(provider?: string): Promise<{ models: import('../types').LlmModelOption[] }> {
  const query = provider ? `?provider=${encodeURIComponent(provider)}` : ''
  const res = await fetch(`${BASE}/api/v1/llm/models${query}`)
  if (!res.ok) throw new Error('Failed to fetch LLM models')
  return res.json()
}

export async function testLlmConnection(): Promise<{ ok: boolean; response: string; status: import('../types').LlmStatus }> {
  let res: Response
  try {
    res = await fetch(`${BASE}/api/v1/llm/test`, { method: 'POST' })
  } catch {
    throw new Error('HocusPocus backend is unreachable. Reopen the current WebUI from Pinokio and try again')
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'LLM test failed' }))
    throw new Error(err.detail || 'LLM test failed')
  }
  return res.json()
}

export async function llmEnhancePrompt(params: {
  prompt: string
  mode?: string
  model_type?: string
  temperature?: number
  image_path?: string
  image_paths?: string[]
  duration_seconds?: number
  window_count?: number
  window_size_seconds?: number
  activated_loras?: string[]
  tts_enhance_mode?: string
  tts_voice_count?: number
  max_new_tokens?: number
  reference_context?: string
}): Promise<{ original: string; enhanced: string }> {
  const res = await fetch(`${BASE}/api/v1/llm/enhance-prompt`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Enhancement failed' }))
    throw new Error(err.detail || 'Enhancement failed')
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

export async function trimAudio(params: { audio_path: string; start: number; end: number }): Promise<{
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

export async function getLlmStreamStatus(): Promise<{ text: string; done: boolean }> {
  const res = await fetch(`${BASE}/api/v1/llm/stream-status`)
  if (!res.ok) return { text: '', done: true }
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

// --- CivitAI Browser ---

export async function fetchLoraDirectories(): Promise<{ directories: string[] }> {
  const res = await fetch(`${BASE}/api/v1/loras/directories`)
  if (!res.ok) throw new Error('Failed to fetch LoRA directories')
  return res.json()
}

export interface CivitAIModelFilter {
  label: string
  civitai_base: string
  search_query?: string
  default_dir?: string
}

export async function fetchCivitAIModelFilters(): Promise<{ filters: CivitAIModelFilter[] }> {
  const res = await fetch(`${BASE}/api/v1/civitai/base-models`)
  if (!res.ok) throw new Error('Failed to fetch model filters')
  return res.json()
}

export interface CheckpointArchitecture {
  architecture: string
  name: string
  family: string
  template_model_type: string
}

// List the architectures a full checkpoint can be imported as (video/image
// models we already support) + a best-guess default for the given CivitAI
// baseModel so the picker can pre-select it.
export async function fetchCheckpointArchitectures(
  baseModel?: string
): Promise<{ architectures: CheckpointArchitecture[]; suggested_architecture: string | null }> {
  const qs = baseModel ? `?base_model=${encodeURIComponent(baseModel)}` : ''
  const res = await fetch(`${BASE}/api/v1/civitai/checkpoint-architectures${qs}`)
  if (!res.ok) throw new Error('Failed to fetch checkpoint architectures')
  return res.json()
}

export interface InstalledCheckpoint {
  model_type: string
  name: string
  architecture: string
  civitai_model_id: number | null
  current_version_id: number | null
  base_model: string
  filename: string
  auto_quantize: boolean
  update_status: 'current' | 'available' | 'unknown' | 'removed'
  latest_version_id: number | null
  latest_published_at: string | null
  latest_changelog: string | null
  preview_url: string | null
}

// List CivitAI-imported checkpoints (registered finetunes) with update status.
export async function fetchInstalledCheckpoints(): Promise<{ checkpoints: InstalledCheckpoint[]; manifest_last_check_at: string | null }> {
  const res = await fetch(`${BASE}/api/v1/checkpoints/installed`)
  if (!res.ok) throw new Error('Failed to fetch installed checkpoints')
  return res.json()
}

// Query CivitAI for newer versions of every imported checkpoint.
export async function checkCheckpointUpdates(force = false): Promise<{ checked: number; updates_available: number; errors: number; skipped: boolean }> {
  const res = await fetch(`${BASE}/api/v1/checkpoints/check-updates?force=${force}`, { method: 'POST' })
  if (!res.ok) throw new Error('Failed to check checkpoint updates')
  return res.json()
}

export async function searchCivitAI(params: {
  query?: string; sort?: string; period?: string
  nsfw?: boolean; types?: string; baseModels?: string
  limit?: number; cursor?: string
}): Promise<import('../types').CivitAISearchResult> {
  const qs = new URLSearchParams()
  if (params.query) qs.set('query', params.query)
  if (params.sort) qs.set('sort', params.sort)
  if (params.period) qs.set('period', params.period)
  if (params.nsfw != null) qs.set('nsfw', String(params.nsfw))
  if (params.types) qs.set('types', params.types)
  if (params.baseModels) qs.set('baseModels', params.baseModels)
  if (params.limit) qs.set('limit', String(params.limit))
  if (params.cursor) qs.set('cursor', params.cursor)
  const res = await fetch(`${BASE}/api/v1/civitai/search?${qs}`)
  if (!res.ok) {
    // Pull the backend's `detail` if available — it carries the
    // human-readable reason (e.g. "CivitAI is currently in scheduled
    // maintenance") that the proxy synthesises for known states.
    let detail = ''
    try {
      const body = await res.json()
      detail = body?.detail || ''
    } catch { /* non-JSON body */ }
    const err = new Error(detail || `CivitAI search failed (HTTP ${res.status})`)
    ;(err as Error & { status?: number }).status = res.status
    throw err
  }
  return res.json()
}

export async function fetchCivitAIModel(modelId: number): Promise<import('../types').CivitAIModel> {
  const res = await fetch(`${BASE}/api/v1/civitai/model/${modelId}`)
  if (!res.ok) throw new Error('Failed to fetch model details')
  return res.json()
}

export async function startCivitAIDownload(params: {
  download_url: string; filename: string; target_arch: string
  model_id: number; version_id: number; trained_words: string[]
  model_name: string; images: { url: string }[]
  description?: string; version_description?: string; base_model?: string
  example_prompts?: string[]; tags?: string[]
  nsfw?: boolean; target_dir_name?: string; published_at?: string
  // Checkpoint imports: kind='checkpoint' routes the file into ckpts/ and
  // registers a finetune for target_architecture instead of saving a LoRA.
  // auto_quantize=true sets the finetune to load-time int8 (mmgp).
  kind?: string; target_architecture?: string; auto_quantize?: boolean
}): Promise<{ download_id: string }> {
  const res = await fetch(`${BASE}/api/v1/civitai/download`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Download failed' }))
    throw new Error(err.detail || 'Download failed')
  }
  return res.json()
}

export async function fetchCivitAIDownloads(): Promise<{ downloads: import('../types').CivitAIDownload[] }> {
  const res = await fetch(`${BASE}/api/v1/civitai/downloads`)
  if (!res.ok) throw new Error('Failed to fetch downloads')
  return res.json()
}

export async function generateLoraGuide(modelType: string, filename: string): Promise<{ guide: string }> {
  const res = await fetch(`${BASE}/api/v1/loras/generate-guide`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model_type: modelType, filename }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Guide generation failed' }))
    throw new Error(err.detail || 'Guide generation failed')
  }
  return res.json()
}

export async function fetchLoraGuide(modelType: string, filename: string): Promise<{ guide: string | null }> {
  const res = await fetch(`${BASE}/api/v1/loras/${encodeURIComponent(modelType)}/${encodeURIComponent(filename)}/guide`)
  if (!res.ok) return { guide: null }
  return res.json()
}

export async function importHuggingFaceLora(url: string, targetDir?: string, filename?: string): Promise<{
  status: string; download_id: string; filename: string; target_dir: string; repo_id?: string; base_model: string
}> {
  const res = await fetch(`${BASE}/api/v1/huggingface/import-lora`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url, target_dir: targetDir || '', filename: filename || '' }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: 'Import failed' }))
    throw new Error(err.error || 'Import failed')
  }
  return res.json()
}

export async function startLoraScan(options?: { modelType?: string; force?: boolean }): Promise<{ scan_id: string; total: number }> {
  const body: Record<string, unknown> = {}
  if (options?.modelType) body.model_type = options.modelType
  if (options?.force) body.force = true
  const res = await fetch(`${BASE}/api/v1/loras/scan-and-generate-guides`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Scan failed' }))
    throw new Error(err.detail || 'Scan failed')
  }
  return res.json()
}

export async function fetchLoraScanStatus(scanId: string): Promise<{
  status: string; current: number; total: number; message: string
  results: { filename: string; metadata?: string; guide?: string; error?: string }[]
}> {
  const res = await fetch(`${BASE}/api/v1/loras/scan-status/${scanId}`)
  if (!res.ok) throw new Error('Failed to fetch scan status')
  return res.json()
}

/** Per-LoRA update status. Mirrored from types/index.ts for use in
 *  the API layer without forcing a circular import. */
export type LoraUpdateStatus = 'current' | 'available' | 'unknown' | 'local' | 'removed'

export interface InstalledLora {
  filename: string
  directory: string
  /** File lives in a linked install's loras folder (read-only), not
   *  Maestro's own. Sidecars/guides for it live in Maestro's mirror. */
  linked?: boolean
  trained_words: string[]
  preview_url: string | null
  civitai_model_id: number | null
  hf_repo_id?: string | null
  has_guide: boolean
  name: string | null
  base_model: string | null
  nsfw: boolean
  /** True when the user manually overrode CivitAI's NSFW classification
   *  via /api/v1/loras/nsfw-override. */
  nsfw_overridden?: boolean
  /** Stable identifier that survives version updates. Format:
   *  `civitai:{modelId}` when the sidecar exposes a CivitAI modelId,
   *  otherwise `local:{filename}`. Used as the persistence key for
   *  per-LoRA settings (weight overrides, activations) so updating a
   *  LoRA from v1.2 → v1.5 carries those settings forward. */
  lora_id: string
  /** Update status from the cached LoRA-update manifest, populated by
   *  the backend on every /api/v1/loras/installed and
   *  /api/v1/loras/{model_type}/details call. The UI uses this to
   *  render badges. */
  update_status?: LoraUpdateStatus
  latest_version_id?: number | null
  current_version_id?: number | null
  latest_published_at?: string | null
  latest_changelog?: string | null
  /** On-disk size of the .safetensors file (null when unreadable). */
  size_bytes?: number | null
  /** When the file arrived: sidecar downloadedAt (CivitAI downloads) or
   *  the weight file's mtime (HF/hand-installed). ISO string. */
  downloaded_at?: string | null
  /** The version's CivitAI release date (publishedAt) — captured at
   *  download time, backfilled for older files by Check Updates. */
  released_at?: string | null
}

export async function fetchInstalledLoras(): Promise<{
  loras: InstalledLora[]
  /** ISO timestamp of the last full CivitAI check that populated the
   *  cached update manifest. UI shows "last checked X minutes ago". */
  manifest_last_check_at?: string | null
}> {
  const res = await fetch(`${BASE}/api/v1/loras/installed`)
  if (!res.ok) throw new Error('Failed to fetch installed LoRAs')
  return res.json()
}

// --- Storage (duplicates + usage analytics) ---

export interface StorageDuplicate {
  kind: 'checkpoint' | 'lora'
  filename: string
  rel_path: string
  primary_path: string
  size_bytes: number
  linked_path: string
  linked_size_bytes: number
  linked_install: string
}

export interface StorageUsageModel {
  model_type: string
  name: string
  size_bytes: number
  /** Bytes living in the primary (deletable) roots — what deleting frees. */
  primary_bytes: number
  /** Display name of the base model whose weights this entry aliases
   *  (finetunes with "URLs": "<base>") — deleting this row frees nothing. */
  alias_of?: string | null
  use_count: number
  last_used: number | null
}

export interface StorageUsageLora {
  filename: string
  directory: string
  linked: boolean
  size_bytes: number
  use_count: number
  last_used: number | null
}

export interface StorageUsage {
  models: StorageUsageModel[]
  /** Globally deduped — per-model sizes overlap on shared weights
   *  (base transformers, text encoders), so summing rows over-counts. */
  models_total_bytes: number
  loras: StorageUsageLora[]
  workspaces: { name: string; file_count: number; size_bytes: number }[]
  scanned_sidecars: number
}

export async function fetchStorageUsage(): Promise<StorageUsage> {
  const res = await fetch(`${BASE}/api/v1/storage/usage`)
  if (!res.ok) throw new Error('Failed to fetch storage usage')
  return res.json()
}

export async function fetchStorageDuplicates(): Promise<{ duplicates: StorageDuplicate[]; conflicts: StorageDuplicate[]; total_reclaimable_bytes: number }> {
  const res = await fetch(`${BASE}/api/v1/storage/duplicates`)
  if (!res.ok) throw new Error('Failed to scan for duplicates')
  return res.json()
}

export async function reclaimDuplicate(path: string): Promise<{ freed_bytes: number }> {
  const res = await fetch(`${BASE}/api/v1/storage/duplicates/reclaim`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Reclaim failed' }))
    throw new Error(err.detail || 'Reclaim failed')
  }
  return res.json()
}

export async function removeLinkedDuplicate(path: string): Promise<{ freed_bytes: number; recycled: boolean }> {
  const res = await fetch(`${BASE}/api/v1/storage/duplicates/remove-linked`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Remove failed' }))
    throw new Error(err.detail || 'Remove failed')
  }
  return res.json()
}

export async function deleteLoraFile(directory: string, filename: string): Promise<{ deleted: string; deferred: boolean }> {
  const params = new URLSearchParams({ directory: directory || '.', filename })
  const res = await fetch(`${BASE}/api/v1/loras/file?${params.toString()}`, { method: 'DELETE' })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Failed to delete LoRA' }))
    throw new Error(err.detail || 'Failed to delete LoRA')
  }
  return res.json()
}

/** Single entry in the cached LoRA-update manifest (one per
 *  civitai-sourced LoRA). The manifest itself is keyed by `lora_id`
 *  (e.g. `civitai:12345`) — see LoraUpdateManifest. */
export interface LoraManifestEntry {
  model_id: number
  current_version_id: number | null
  latest_version_id: number | null
  latest_published_at: string | null
  latest_changelog: string | null
  status: 'current' | 'available' | 'removed' | 'unknown'
  last_checked_at: string
}

export interface LoraUpdateManifest {
  _version: number
  last_full_check_at: string | null
  entries: Record<string, LoraManifestEntry>
}

export interface LoraUpdateCheckResult {
  /** Number of LoRAs with a `civitai:`-style lora_id that the backend
   *  considered for refresh during this call. */
  checked: number
  /** How many of the checked LoRAs have a newer version on CivitAI. */
  updates_available: number
  /** Per-LoRA error messages (network failures, deleted models, etc.).
   *  Empty array on success. */
  errors: string[]
  /** True when the backend skipped the refresh because the cached
   *  manifest is fresh (within the 24h window) and `force` was false.
   *  In that case `checked` and `updates_available` come from cache. */
  skipped: boolean
  /** Why the refresh was skipped, when `skipped: true`. Currently the
   *  only value is "fresh" but kept open for future cases. */
  reason?: string
  /** ISO timestamp of the most recent full check (the one whose data
   *  is reflected in `checked` / `updates_available`). */
  last_full_check_at?: string | null
}

/** Trigger a fresh CivitAI version check across every installed LoRA
 *  with a sidecar `modelId`. Updates the cached manifest the backend
 *  uses to populate per-LoRA `update_status` fields on subsequent
 *  /installed and /{model_type}/details calls.
 *
 *  Honours a 24h staleness window unless `force` is true:
 *    - `checkLoraUpdates(false)` — opportunistic; if the manifest is
 *      <24h old the backend short-circuits and returns the cached
 *      summary with `skipped: true`. Cheap to call on app startup.
 *    - `checkLoraUpdates(true)`  — bypass the window. Use for explicit
 *      "Check now" buttons in the UI; pulls from CivitAI even if a
 *      check happened minutes ago.
 *
 *  Returns the summary the UI shows in a toast. Throws on network/HTTP
 *  failure (call sites typically `.catch()` to keep UI responsive). */
export async function checkLoraUpdates(force = false): Promise<LoraUpdateCheckResult> {
  const url = `${BASE}/api/v1/loras/check-updates${force ? '?force=true' : ''}`
  const res = await fetch(url, { method: 'POST' })
  if (!res.ok) throw new Error(`Failed to check LoRA updates (${res.status})`)
  return res.json()
}

/** Read the cached LoRA-update manifest WITHOUT hitting CivitAI.
 *  Use this on app startup to populate badges immediately, then
 *  optionally call checkLoraUpdates() if the cache is stale. The
 *  manifest schema is documented in launch.py near the constant
 *  LORA_MANIFEST_VERSION. */
export async function fetchLoraUpdateManifest(): Promise<LoraUpdateManifest> {
  const res = await fetch(`${BASE}/api/v1/loras/update-manifest`)
  if (!res.ok) throw new Error('Failed to fetch LoRA update manifest')
  return res.json()
}

export async function fetchLoraDetails(modelType: string): Promise<{
  loras: import('../types').LoraInfo[]
  guidance_max_phases: number
  /** ISO timestamp of the last full CivitAI check that populated the
   *  cached update manifest. UI uses this to render "last checked X
   *  minutes ago" alongside the manual "Check updates" button. */
  manifest_last_check_at?: string | null
}> {
  const res = await fetch(`${BASE}/api/v1/loras/${encodeURIComponent(modelType)}/details`)
  if (!res.ok) throw new Error('Failed to fetch LoRA details')
  return res.json()
}

// --- Active model file downloads (HuggingFace etc.) ---

export interface ActiveDownload {
  file_id: string
  filename: string
  started_at: number
  last_active_at: number
  downloaded_bytes: number
  total_bytes: number | null
  status: 'downloading' | 'stalled' | 'retrying' | 'done' | 'incomplete'
  /** Seconds since the byte counter last advanced. UI uses this to
   *  flag stalled downloads (e.g. `> 15` → show "slow / retrying"). */
  seconds_since_progress: number
}

export async function fetchActiveDownloads(signal?: AbortSignal): Promise<{ downloads: ActiveDownload[] }> {
  const res = await fetch(`${BASE}/api/v1/downloads/active`, { signal })
  if (!res.ok) throw new Error(`Failed to fetch active downloads (${res.status})`)
  return res.json()
}
