import { randomUuid } from '../lib/uuid'
import { BASE, httpError } from './http'

// --- Native Hunyuan3D ---

export interface Hunyuan3DModel {
  id: string
  label: string
  engine: 'v2' | 'v21' | 'trellis2' | 'pixal3d'
  repo: string
  subfolder: string
  parameters: string
  multiview: boolean
  turbo: boolean
  supports_text: boolean
  recommended_vram_gb: number | null
  description: string
  runtime?: { installed: boolean; install_hint: string | null; validation?: string; compatible?: boolean; weights_downloaded?: boolean; compatibility_reason?: string | null }
  resolutions?: number[]
  supports_low_vram?: boolean
  supports_camera_fov?: boolean
  multiview_reason?: 'single_image' | 'camera_contract'
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
  task_id?: string
  root_task_id?: string
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
  provenance?: Record<string, unknown>
  resolution?: number
  low_vram?: boolean
  camera_fov?: number
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
  // A 404 means the job registry no longer knows this id (the backend
  // restarted mid-generation); callers use the status to stop polling.
  if (!res.ok) throw await httpError(res, res.status === 404 ? 'Hunyuan3D job not found' : 'Failed to fetch Hunyuan3D job')
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
  /** Humanoid clips: loop length in beats at the chosen BPM. */
  beats?: number
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
  /** Standard Mixamo-named clips. Present when the humanoid engine is installed. */
  humanoid_animations?: RigAnimation[]
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
  /** Set when the worker refused the mesh, e.g. ``not_humanoid`` with reason ``hands_stuck``. */
  error_code?: string
  error_reason?: string
  /** Humanoid engine: what was detected and which clips the GLB holds. */
  humanoid?: HumanoidRigSummary
  created_at: number
  updated_at: number
}

export interface HumanoidClip {
  index: number
  name: string
  duration: number
}

export interface HumanoidRigSummary {
  pose?: 't' | 'a'
  arm_drop?: number
  confidence?: number
  warnings?: string[]
  clips?: HumanoidClip[]
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
  animation_bpm?: number
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

// --- Humanoid clips on an already rigged model ---

export interface HumanoidRig {
  name: string
  clips: string[]
  modified: number
}

export interface HumanoidAnimateResult {
  file: string
  workspace: string
  url: string
  clips: HumanoidClip[]
  warnings: string[]
  bytes: number
}

async function commandError(res: Response, fallback: string): Promise<Error> {
  const body = await res.json().catch(() => null) as { detail?: string | { message?: string } } | null
  const detail = body?.detail
  return new Error(typeof detail === 'string' ? detail : detail?.message || fallback)
}

/** GLBs in a workspace that carry the standard humanoid skeleton. */
export async function fetchHumanoidRigs(workspace: string): Promise<HumanoidRig[]> {
  const res = await fetch(`${BASE}/api/v1/model3d/humanoid-rigs?workspace=${encodeURIComponent(workspace)}`, { cache: 'no-store' })
  if (!res.ok) throw await commandError(res, 'Could not list rigged characters')
  return (await res.json()).rigs
}

/** Stores a .bvh/.glb/.gltf in the workspace (out of the gallery) and returns its workspace path. */
export async function uploadAnimationFile(workspace: string, file: File): Promise<string> {
  const query = new URLSearchParams({ workspace, filename: file.name })
  const res = await fetch(`${BASE}/api/v1/model3d/animation-files?${query}`, { method: 'POST', body: file })
  if (!res.ok) throw await commandError(res, 'Could not upload the animation file')
  return (await res.json()).file
}

export async function animateHumanoid(params: {
  workspace: string
  source: string
  clips: string[]
  bpm: number
  importFile?: string | null
  /** A walk along these model-space ground points with the feet planted. */
  path?: { points: [number, number][]; duration: number; name?: string }
}): Promise<HumanoidAnimateResult> {
  const input: Record<string, unknown> = { workspace: params.workspace, source: params.source, bpm: params.bpm }
  if (params.clips.length) input.clips = params.clips
  if (params.importFile) input.import = { file: params.importFile }
  if (params.path) input.path = params.path
  const res = await fetch(`${BASE}/api/v1/model3d/animate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ version: 1, intent_id: `ui-animate-${randomUuid()}`, input }),
  })
  if (!res.ok) throw await commandError(res, 'Could not add the animations')
  return (await res.json()).result
}
