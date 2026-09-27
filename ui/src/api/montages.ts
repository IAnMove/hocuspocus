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
  fit: 'fit' | 'fill' | 'blur'
  focusX?: number
  focusY?: number
  blurAmount?: number
  backgroundDim?: number
  transition: string
  transitionDuration: number
  transitionText: string
  transitionTextSize: number
  origin?: MontageOrigin
  takes?: MontageTake[]
  lyric?: string
}

export interface MontageOrigin {
  kind: 'scene2d' | 'scene3d' | 'generation' | 'upload' | 'render' | 'production'
  scene?: string
  note?: string
  meta?: string
  derivedFrom?: string
  productionId?: string
  shotId?: string
  takeId?: string
}

export interface MontageTake {
  id: string
  source?: string
  pending?: { jobId: string; intentId?: string }
  origin?: MontageOrigin
  createdAt?: string
  note?: string
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
  derivedFrom?: { file: string; revision: number }
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

export async function deriveMontage(workspace: string, file: string, input: {
  format: '9:16' | '1:1' | '4:5'
  fit: 'blur' | 'fill'
  outputFile?: string
  expectedRevision?: number
}): Promise<{ file: string; revision: number; url: string }> {
  const res = await fetch(`${BASE}/api/v1/montages/${encodeURIComponent(file)}/derive`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      workspace,
      format: input.format,
      fit: input.fit,
      ...(input.outputFile ? { output_file: input.outputFile } : {}),
      ...(input.expectedRevision !== undefined ? { expected_revision: input.expectedRevision } : {}),
    }),
  })
  return readJson(res, 'Could not derive montage')
}

export async function exportMontage(workspace: string, file: string): Promise<{ file: string; job: VideoEditorExportJob }> {
  const res = await fetch(`${BASE}/api/v1/montages/${encodeURIComponent(file)}/export?workspace=${encodeURIComponent(workspace)}`, { method: 'POST' })
  return readJson(res, 'Could not export montage')
}

export interface ShotProvenance {
  kind: string
  scene?: string
  note?: string
  sidecar?: string
  generatedFrom?: string
  model?: string
  prompt?: string
  seed?: number
  resolution?: string
  frames?: number
  startImage?: { name: string; url: string }
  canRegenerate: boolean
}

export interface ShotTake extends MontageTake {
  status: string
  url?: string
  duration?: number
  error?: string
  provenance?: ShotProvenance
}

export interface MontageShot {
  index: number
  id: string
  name: string
  start: number
  end: number
  source: string
  url: string
  lyric: string
  provenance: ShotProvenance
  takes: ShotTake[]
}

export interface MontageShotBoard {
  file: string
  name: string
  revision: number
  duration: number
  shots: MontageShot[]
}

export async function getMontageShots(workspace: string, file: string): Promise<MontageShotBoard> {
  const res = await fetch(`${BASE}/api/v1/montages/${encodeURIComponent(file)}/shots?workspace=${encodeURIComponent(workspace)}`)
  return readJson(res, 'Could not read the shots')
}

async function postShot<T>(file: string, clipId: string, action: 'regenerate' | 'select', payload: object, fallback: string): Promise<T> {
  const res = await fetch(`${BASE}/api/v1/montages/${encodeURIComponent(file)}/shots/${encodeURIComponent(clipId)}/${action}`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  })
  return readJson(res, fallback)
}

export function regenerateShot(workspace: string, file: string, clipId: string, input: {
  intentId: string; expectedRevision: number; prompt?: string; seed?: number
}): Promise<{ jobId: string; revision: number }> {
  return postShot(file, clipId, 'regenerate', {
    workspace, intent_id: input.intentId, expected_revision: input.expectedRevision,
    ...(input.prompt ? { prompt: input.prompt } : {}), ...(input.seed !== undefined ? { seed: input.seed } : {}),
  }, 'Could not regenerate the shot')
}

export function selectShotTake(workspace: string, file: string, clipId: string, takeId: string, expectedRevision: number): Promise<{ revision: number }> {
  return postShot(file, clipId, 'select', { workspace, take_id: takeId, expected_revision: expectedRevision }, 'Could not use this take')
}
