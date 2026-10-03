import { BASE } from './http'

export type PublishPreset = 'x' | 'youtube' | 'shorts' | 'archive'

export interface PublishWarning {
  code: 'duration' | 'aspect' | 'safe_area'
  limit?: number
  duration?: number
  expected?: string
  ids?: string[]
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
}): Promise<{ file: string; url: string; thumbnail: string; sidecar: string; warnings: PublishWarning[] }> {
  const res = await fetch(`${BASE}/api/v1/video-editor/publish`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...payload, loudnorm: payload.loudnorm !== false }),
  })
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: 'Could not publish the video' }))
    const detail = typeof error.detail === 'string' ? error.detail : error.detail?.message
    throw new Error(detail || 'Could not publish the video')
  }
  return res.json()
}
