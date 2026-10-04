import { BASE } from './http'

export interface SongShortenResult {
  file?: string
  url?: string
  duration?: number
  keep?: Array<[number, number] | number[]>
  time_map?: Array<[number, number, number] | number[]>
  preview?: boolean
  report?: { dropped: Array<{ kind: string; id?: string }>; trimmed: Array<{ kind: string; id?: string }> }
  montage?: {
    clips: Array<{ id: string; name?: string; trimStart: number; trimEnd: number }>
    overlays: Array<{ id: string; start: number; end: number }>
    audioCues: Array<{ id: string; start: number }>
  }
}

export async function shortenSong(payload: {
  workspace: string
  source: string
  keep?: number[][]
  durationMax?: number
  preview?: boolean
  montage?: object
}): Promise<SongShortenResult> {
  const res = await fetch(`${BASE}/api/v1/audio/shorten`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      workspace: payload.workspace,
      source: payload.source,
      duration_max: payload.durationMax ?? 180,
      ...(payload.keep ? { keep: payload.keep } : {}),
      ...(payload.preview ? { preview: true } : {}),
      ...(payload.montage ? { montage: payload.montage } : {}),
    }),
  })
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: 'Could not shorten the song' }))
    const detail = typeof error.detail === 'string' ? error.detail : error.detail?.message
    throw new Error(detail || 'Could not shorten the song')
  }
  return res.json()
}
