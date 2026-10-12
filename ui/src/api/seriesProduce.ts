import { BASE } from './http'

/** One step of ``series.episode.produce``: the render or the cut of one language. */
export interface SeriesProduceStep {
  kind: 'render' | 'assemble'
  language: string
  status: string
  jobId?: string | null
  progress?: string | null
  error?: string | null
  retries?: number
  shots?: number
}

/** A chapter a production cut: the video, its burned-subtitle copy and the subtitle file. */
export interface SeriesProduceChapter {
  assetId?: string | null
  file?: string | null
  subtitledFile?: string | null
  srt?: string | null
  loudness?: number | null
}

/** An episode production (``series.episode.produce``) as the server keeps it (services/series_produce.py). */
export interface SeriesProduceJob {
  jobId: string
  seriesId: string
  episodeId: string
  original?: string
  languages?: string[]
  status: string
  message?: string
  error?: string | null
  steps: SeriesProduceStep[]
  chapters?: Record<string, SeriesProduceChapter>
  createdAt?: number
  finishedAt?: number
  rerender?: boolean
  burnSubtitles?: boolean
  /** A staged review holds the cut for these shots (status ``waiting``). */
  waiting?: Array<{ shotId?: string; reason?: string }>
}

async function produceResponse<T>(response: Response, fallback: string): Promise<T> {
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { detail?: { message?: string } | string }
    const detail = body.detail
    throw new Error(typeof detail === 'string' ? detail : detail?.message || fallback)
  }
  return response.json() as Promise<T>
}

/** The productions of an episode (or of the workspace), newest first. */
export async function listSeriesProductions(workspace: string, options: { seriesId?: string; episodeId?: string; limit?: number } = {},
  signal?: AbortSignal): Promise<SeriesProduceJob[]> {
  const query = new URLSearchParams({ workspace })
  if (options.seriesId) query.set('series_id', options.seriesId)
  if (options.episodeId) query.set('episode_id', options.episodeId)
  if (options.limit) query.set('limit', String(options.limit))
  const body = await produceResponse<{ jobs?: SeriesProduceJob[] }>(
    await fetch(`${BASE}/api/v1/series/produce/jobs?${query}`, { cache: 'no-store', signal }), 'Could not list the productions')
  return Array.isArray(body.jobs) ? body.jobs : []
}

export async function controlSeriesProduction(workspace: string, jobId: string, action: 'cancel' | 'resume'): Promise<SeriesProduceJob> {
  return produceResponse(await fetch(`${BASE}/api/v1/series/produce/jobs/${encodeURIComponent(jobId)}/${action}`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ workspace }),
  }), 'Could not update the production')
}
