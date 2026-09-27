import { BASE } from './http'
import type { VideoEditorExportJob } from './video-editor'

export interface MontageClip {
  id: string
  name: string
  source: string
  trimStart: number
  trimEnd: number
  volume: number
  muted: boolean
  fit: 'fit' | 'fill'
  transition: string
  transitionDuration: number
  transitionText: string
  transitionTextSize: number
  origin?: { kind: 'scene2d' | 'scene3d' | 'generation' | 'upload' | 'render'; scene?: string; note?: string }
}

export interface MontageOverlay {
  id: string
  name: string
  source: string
  start: number
  end: number
  x: number
  y: number
  width: number
  opacity: number
  fadeIn: number
  fadeOut: number
}

export interface MontageAudioCue {
  id: string
  name: string
  source: string
  start: number
  volume: number
  trimStart: number
  trimEnd: number
}

export interface MontageDocument {
  version: 1
  kind?: 'montage'
  name: string
  width: number
  height: number
  fps: number
  clips: MontageClip[]
  soundtrack: { name: string; source: string; trimStart: number; trimEnd: number; volume: number; loop: boolean } | null
  audioCues: MontageAudioCue[]
  overlays: MontageOverlay[]
  duck: number
  notes?: string
  revision?: number
  updatedAt?: string
}

export interface MontageSummary {
  file: string
  name: string
  revision: number
  updatedAt?: string
  clips: number
  overlays: number
  audioCues: number
  url: string
}

async function readJson<T>(res: Response, fallback: string): Promise<T> {
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: fallback }))
    const detail = typeof error.detail === 'string' ? error.detail : error.detail?.message
    throw new Error(detail || fallback)
  }
  return res.json() as Promise<T>
}

export async function listMontages(workspace: string): Promise<MontageSummary[]> {
  const res = await fetch(`${BASE}/api/v1/montages?workspace=${encodeURIComponent(workspace)}`)
  return (await readJson<{ montages: MontageSummary[] }>(res, 'Could not list montages')).montages
}

export async function getMontage(workspace: string, file: string): Promise<{ file: string; montage: MontageDocument }> {
  const res = await fetch(`${BASE}/api/v1/montages/${encodeURIComponent(file)}?workspace=${encodeURIComponent(workspace)}`)
  return readJson(res, 'Could not open montage')
}

export async function saveMontage(payload: {
  workspace: string
  montage: MontageDocument
  file?: string
  expected_revision?: number
}): Promise<{ file: string; revision: number; url: string }> {
  const res = await fetch(`${BASE}/api/v1/montages`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return readJson(res, 'Could not save montage')
}

export async function exportMontage(workspace: string, file: string): Promise<{ file: string; job: VideoEditorExportJob }> {
  const res = await fetch(`${BASE}/api/v1/montages/${encodeURIComponent(file)}/export?workspace=${encodeURIComponent(workspace)}`, { method: 'POST' })
  return readJson(res, 'Could not export montage')
}
