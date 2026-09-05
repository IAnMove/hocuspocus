import { BASE } from './http'

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
