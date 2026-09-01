import { BASE } from './http'

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
