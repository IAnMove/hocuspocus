import { rememberPrompt } from '../lib/promptHistory'
import type { ProductionPlan } from '../types'

const BASE = ''  // same origin in production; Vite proxy handles /api in dev

export interface ApiModel {
  model_type: string
  name: string
  family: string
  architecture: string
  is_i2v: boolean
  is_t2v: boolean
  guidance_max_phases: number
  fps: number
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
  url: string
  /** Small static preview for image/video cards and saved 3D/scene assets. */
  thumbnail_url?: string | null
  /** Edit-mode sub-classification (retake / inpaint / outpaint / restyle /
   *  edit_anything). Field added as a recovery stub after a git
   *  filter-repo reset wiped the original Stream C/D work that
   *  introduced it. Optional so the type compiles even when the
   *  backend hasn't been updated to emit this yet. */
  edit_sub_mode?: string | null
}

export interface ApiJobStatus {
  job_id: string
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled'
  progress: number
  step: number
  total_steps: number
  phase: string
  message: string
  output_files: string[]
  error: string | null
  task_timings?: ApiTaskTiming[]
  /** Present only on failed jobs that look like CUDA OOMs.
   *  See `OomInfo` in types/index.ts. */
  oom_info?: import('../types').OomInfo | null
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

export async function submitGeneration(params: Record<string, unknown>): Promise<{ job_id: string }> {
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

// --- Music: LLM song writer (Music mode Simple) ---

export async function writeSong(params: {
  description: string
  instrumental?: boolean
  target?: 'ace-step' | 'minimax'
  model?: 'music-3.0' | 'music-2.6' | 'music-cover'
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
}

export async function generateStoryMusicCandidates(params: {
  prompt: string
  lyrics: string
  count: 1 | 2 | 3
  model?: 'music-3.0' | 'music-2.6' | 'music-cover'
  reference_audio_filename?: string
  instrumental?: boolean
  workspace?: string
}): Promise<{ candidates: MiniMaxMusicCandidate[] }> {
  const res = await fetch(`${BASE}/api/v1/stories/music-candidates`, {
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

// --- Job Management ---

export async function cancelJob(jobId: string): Promise<void> {
  const res = await fetch(`${BASE}/api/v1/cancel/${encodeURIComponent(jobId)}`, { method: 'POST' })
  if (!res.ok) throw new Error('Failed to cancel job')
}

export async function fetchActiveJobs(): Promise<{ jobs: Array<{
  job_id: string; status: string; progress: number; step: number;
  total_steps: number; phase: string; message: string; output_files: string[];
  error: string | null; created_at: number; task_timings?: ApiTaskTiming[];
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

export async function fetchOutputs(limit = 0, offset = 0, opts?: { favoritesOnly?: boolean; multiclipOnly?: boolean; search?: string; mediaType?: ApiOutput['type'] }): Promise<{ outputs: ApiOutput[]; total: number }> {
  const params = new URLSearchParams()
  if (limit > 0) params.set('limit', String(limit))
  if (offset > 0) params.set('offset', String(offset))
  if (opts?.favoritesOnly) params.set('favorites_only', 'true')
  if (opts?.multiclipOnly) params.set('multiclip_only', 'true')
  if (opts?.search) params.set('search', opts.search)
  if (opts?.mediaType) params.set('media_type', opts.mediaType)
  const qs = params.toString()
  const res = await fetch(`${BASE}/api/v1/outputs${qs ? '?' + qs : ''}`, { cache: 'no-store' })
  if (!res.ok) throw new Error('Failed to fetch outputs')
  const data = await res.json()
  return { outputs: data.outputs, total: data.total ?? data.outputs.length }
}

export async function saveScene(scene: import('../types').Scene, preview: string): Promise<{ name: string; type: 'scene'; url: string; thumbnail_url: string }> {
  const res = await fetch(`${BASE}/api/v1/scenes`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ scene, preview }),
  })
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: 'Failed to save scene' }))
    throw new Error(error.detail || 'Failed to save scene')
  }
  return res.json()
}

export function getFileUrl(filename: string): string {
  return `${BASE}/api/v1/file/${encodeURIComponent(filename)}`
}

export function getOutputThumbnailUrl(filename: string): string {
  return `${BASE}/api/v1/outputs/thumbnail/${encodeURIComponent(filename)}`
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

export async function fetchOutputMetadata(name: string): Promise<import('../types').OutputMetadata> {
  // Retry with a per-attempt timeout. On a slow/high-latency link (e.g. the user
  // is remote over VPN) the request can stall long enough that a single attempt
  // hangs or is dropped by an intermediary; the old single-shot fetch then left
  // the caller with no metadata and the "Load Settings" button a silent no-op.
  const url = `${BASE}/api/v1/outputs/${encodeURIComponent(name)}/metadata`
  const ATTEMPTS = 3
  const PER_ATTEMPT_MS = 30000  // generous: the server may read embedded video metadata to recover a seed
  let lastErr: unknown = null
  for (let attempt = 0; attempt < ATTEMPTS; attempt++) {
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), PER_ATTEMPT_MS)
    try {
      const res = await fetch(url, { signal: controller.signal })
      if (!res.ok) return { source: 'none', params: null }
      return await res.json()
    } catch (e) {
      lastErr = e
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
    }
  }
  throw lastErr  // all attempts failed — loadOutputMetadata's catch sets meta null
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
  status: 'queued' | 'running' | 'completed' | 'failed'
  progress: number
  message: string
  filename: string | null
  url: string | null
  error: string | null
  result?: { duration: number; clip_count: number }
}

export async function probeVideoEditorClip(source: string): Promise<VideoEditorProbe> {
  const res = await fetch(`${BASE}/api/v1/video-editor/probe`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ source }),
  })
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: 'Could not inspect video' }))
    throw new Error(error.detail || 'Could not inspect video')
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
}): Promise<{ job_id: string }> {
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

export async function startComicAnimatic(payload: {
  comic_id: string
  comic_title: string
  width: number
  height: number
  fps: number
  transition: string
  transition_duration: number
  panels: Array<{
    source: string
    page_number: number
    panel_number: number
    duration: number
    motion: string
    script: string
  }>
}): Promise<{ job_id: string }> {
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
  phase: 'planning' | 'polishing_prompts' | 'generating_images' | 'preview_ready' | 'generating_video' | 'post_processing' | 'completed'
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
}

export async function startPipeline(params: Record<string, unknown>): Promise<{ pipeline_id: string }> {
  const res = await fetch(`${BASE}/api/v1/director/pipeline/start`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: 'Failed to start pipeline' }))
    throw new Error(body.detail || 'Failed to start pipeline')
  }
  return res.json()
}

export async function fetchPipelineStatus(pid: string): Promise<PipelineStatus> {
  const res = await fetch(`${BASE}/api/v1/director/pipeline/${encodeURIComponent(pid)}`)
  if (!res.ok) throw new Error('Failed to fetch pipeline status')
  return res.json()
}

export async function fetchActiveDirectorPipelines(): Promise<{ pipelines: ActiveDirectorPipeline[] }> {
  const res = await fetch(`${BASE}/api/v1/director/pipelines/active`)
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

export async function fetchPipelineList(): Promise<{ pipelines: import('../types').PipelineListItem[] }> {
  const res = await fetch(`${BASE}/api/v1/director/pipelines`)
  if (!res.ok) throw new Error('Failed to fetch pipelines')
  return res.json()
}

export async function fetchSavedPipeline(pid: string): Promise<import('../types').SavedPipelineState> {
  const res = await fetch(`${BASE}/api/v1/director/pipelines/${encodeURIComponent(pid)}`)
  if (!res.ok) throw new Error('Pipeline not found')
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

// --- Director v2 ---

export interface DirectorV2PlanRequest {
  skill_type: string
  activity_id?: string
  scene_description?: string
  story_description?: string
  clips?: unknown[]
  lyrics?: unknown[]
  bpm?: number
  reference_image_path?: string
  character_ref_paths?: string[]
  character_ref_labels?: string[]
  location_ref_paths?: string[]
  location_ref_labels?: string[]
  speaker_mappings?: Record<string, unknown>
  characters?: Array<{ name: string; description: string }>
  audio_path?: string
  target_duration?: number
  target_scenes?: number
  narrative_mode?: boolean
  fps?: number
  frames_steps?: number
  frames_minimum?: number
  concept?: string
  visual_style?: string
  preserve_visual_style?: boolean
  character_visual_style?: string
  allow_clip_text?: boolean
  platform?: string
  style?: string
  prompt_type?: string
  image_model?: string
  video_model?: string
  h3_reference_mode?: 'first_frame' | 'references'
  h3_audio_prompt?: string
  seamless?: boolean
  multishot_lora_mode?: boolean
  music_video_treatment?: import('../types').MusicVideoTreatment
  director_flags?: Record<string, boolean>
}

export interface DirectorV2PlanProgress {
  id: string
  status: 'running' | 'completed' | 'failed'
  phase: string
  current: number
  total: number
  detail: string
  stream_text?: string
  stream_done?: boolean
  usage?: {
    prompt_tokens?: number
    completion_tokens?: number
    total_tokens?: number
    calls?: number
  }
}

export interface DirectorV2PlanResponse {
  clip_plans: Array<{ video_prompt: string; image_prompt: string }>
  production_plan: ProductionPlan
  skill_type: string
}

export async function directorV2Plan(params: DirectorV2PlanRequest): Promise<DirectorV2PlanResponse> {
  const res = await fetch(`${BASE}/api/v1/director/v2/plan`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Plan failed' }))
    throw new Error(err.detail || 'Director v2 plan failed')
  }
  return res.json()
}

export async function getDirectorV2PlanProgress(activityId: string): Promise<DirectorV2PlanProgress | null> {
  const res = await fetch(`${BASE}/api/v1/director/v2/plan/progress/${encodeURIComponent(activityId)}`)
  if (res.status === 404) return null
  if (!res.ok) throw new Error('Could not read Director planning progress')
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

// --- Outpaint ---

export async function submitOutpaint(params: {
  video_path: string; prompt: string; model_type: string;
  pad_top?: number; pad_bottom?: number; pad_left?: number; pad_right?: number;
  resolution_preset?: 'auto' | '480p' | '540p' | '720p' | '1080p';
  source_preservation?: number;
  outpaint_lora_strength?: number;
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

export async function uploadImage(file: File): Promise<{ filename: string; path: string; url: string }> {
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
      const statusResponse = await fetch(
        `${BASE}/api/v1/stories/generate/status/${encodeURIComponent(accepted.jobId)}`,
        { signal },
      )
      if (!statusResponse.ok) {
        const err = await statusResponse.json().catch(() => ({ detail: 'Could not read Story Lab job' }))
        throw new Error(err.detail || 'Could not read Story Lab job')
      }
      const status = await statusResponse.json()
      onProgress?.(status)
      if (status.status === 'failed' || status.status === 'cancelled') {
        throw new Error(`${status.error || status.message} Resume job: ${accepted.jobId}`)
      }
      if (status.status === 'completed') {
        if (!status.result?.result) throw new Error('Story Lab job completed without a draft')
        window.localStorage.setItem('maestro-last-story-plan-result', JSON.stringify({
          jobId: accepted.jobId,
          projectId: params.project.id,
          scope: params.scope,
          result: status.result.result,
        }))
        return status.result
      }
    }
  } finally {
    signal?.removeEventListener('abort', cancelRemote)
  }
}

export interface StoryLibraryPayload {
  version: 2
  activeId: string
  projects: Record<string, import('../features/stories/types').StoryProject>
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
    body: JSON.stringify({ workspace, library }),
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Could not save Story Lab library' }))
    throw new Error(error.detail || 'Could not save Story Lab library')
  }
  return response.json()
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
): Promise<{ result: Record<string, unknown> }> {
  const resumed = await fetch(
    `${BASE}/api/v1/stories/generate/resume/${encodeURIComponent(jobId)}`,
    { method: 'POST' },
  )
  if (!resumed.ok) {
    const err = await resumed.json().catch(() => ({ detail: 'Could not resume Story Lab job' }))
    throw new Error(err.detail || 'Could not resume Story Lab job')
  }
  for (;;) {
    await new Promise(resolve => window.setTimeout(resolve, 1000))
    const response = await fetch(
      `${BASE}/api/v1/stories/generate/status/${encodeURIComponent(jobId)}`,
    )
    if (!response.ok) throw new Error('Could not read resumed Story Lab job')
    const status = await response.json()
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
      return status.result
    }
  }
}

export type ComicPlanProgress = {
  jobId?: string
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
export async function fetchSystemStats(): Promise<import('../types').SystemStats> {
  const res = await fetch(`${BASE}/api/v1/system-stats`)
  if (!res.ok) throw new Error('Failed to fetch system stats')
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
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled'
  progress: number
  phase: string
  message: string
  error: string | null
  filename: string | null
  url: string | null
  model_id: string
  size?: number
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
  model_id?: string
  prompt?: string
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

export async function fetchLlmModels(): Promise<{ models: import('../types').LlmModelOption[] }> {
  const res = await fetch(`${BASE}/api/v1/llm/models`)
  if (!res.ok) throw new Error('Failed to fetch LLM models')
  return res.json()
}

export async function testLlmConnection(): Promise<{ ok: boolean; response: string; status: import('../types').LlmStatus }> {
  let res: Response
  try {
    res = await fetch(`${BASE}/api/v1/llm/test`, { method: 'POST' })
  } catch {
    throw new Error('Maestro backend is unreachable. Reopen the current WebUI from Pinokio and try again')
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

export async function uploadAudio(file: File): Promise<{ filename: string; path: string; url: string }> {
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
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled'
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
}): Promise<{ job_id: string }> {
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
  nsfw?: boolean; target_dir_name?: string
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
  status: string; download_id: string; filename: string; target_dir: string; repo_id: string; base_model: string
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

export async function fetchActiveDownloads(): Promise<{ downloads: ActiveDownload[] }> {
  const res = await fetch(`${BASE}/api/v1/downloads/active`)
  if (!res.ok) throw new Error(`Failed to fetch active downloads (${res.status})`)
  return res.json()
}
