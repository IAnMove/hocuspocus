import { BASE } from './http'

export type PublishPreset = 'x' | 'youtube' | 'shorts' | 'apple' | 'broadcast' | 'archive'

export interface PublishLoudness {
  lufs: number | null
  true_peak: number | null
  target_lufs?: number
  target_true_peak?: number
}

export function formatPublishNumber(value: number | null | undefined): string {
  return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(1) : '—'
}

export interface PublishWarning {
  code: 'duration' | 'aspect' | 'safe_area' | 'loudness'
  limit?: number
  duration?: number
  expected?: string
  ids?: string[]
  lufs?: number
  true_peak?: number
  target_lufs?: number
}

export async function checkPublishPreset(payload: {
  preset: PublishPreset
  premium?: boolean
  width: number
  height: number
  duration: number
  overlays?: Array<{ id: string; y: number; width: number }>
}): Promise<PublishWarning[]> {
  const res = await fetch(`${BASE}/api/v1/video-editor/publish-check`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: 'Could not check the publish preset' }))
    const detail = typeof error.detail === 'string' ? error.detail : error.detail?.message
    throw new Error(detail || 'Could not check the publish preset')
  }
  const body = await res.json()
  return body.warnings || []
}

/** Export jobs return `/api/v1/file/name` without a workspace. The resolver rejects that. */
export function publishMediaSource(source: string, workspace: string): string {
  if (!source.startsWith('/api/v1/file/')) return source
  const cut = source.indexOf('?')
  const path = cut < 0 ? source : source.slice(0, cut)
  const query = cut < 0 ? '' : source.slice(cut + 1)
  if (query.split('&').some(part => part.split('=')[0] === 'workspace')) return source
  return `${path}?${query ? `${query}&` : ''}workspace=${encodeURIComponent(workspace)}`
}

export async function publishVideo(payload: {
  workspace: string
  source: string
  preset: PublishPreset
  premium?: boolean
  width: number
  height: number
  duration: number
  overlays?: Array<{ id: string; y: number; width: number }>
  loudnorm?: boolean
}): Promise<{ file: string; url: string; thumbnail: string; sidecar: string; warnings: PublishWarning[]; loudness?: PublishLoudness | null }> {
  const res = await fetch(`${BASE}/api/v1/video-editor/publish`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      ...payload,
      source: publishMediaSource(payload.source, payload.workspace),
      loudnorm: payload.loudnorm !== false,
    }),
  })
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: 'Could not publish the video' }))
    const detail = typeof error.detail === 'string' ? error.detail : error.detail?.message
    throw new Error(detail || 'Could not publish the video')
  }
  return res.json()
}
